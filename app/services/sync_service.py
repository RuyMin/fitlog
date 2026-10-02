"""Validate first, then apply a whole snapshot in one SQLite transaction."""
import json
from datetime import datetime, timezone
from threading import Lock

from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import Workout, WorkoutSet, Exercise, Meal, BodyMetric, SleepRecord, SyncState, utc_now
from app.sync_schemas import COLUMNS, ROW_TYPES
from app.services.google_sheets import GoogleSettings, GoogleSheetsReader, SheetReader, SyncError

MODELS = {"workouts": Workout, "workout_sets": WorkoutSet, "meals": Meal, "body_metrics": BodyMetric, "sleep": SleepRecord}
RUN_LOCK = Lock()
SOURCE = "google_sheets"


def utc(value: datetime) -> datetime:
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def parse_tables(tables: dict[str, list[list]]) -> dict[str, list]:
    if set(tables) != set(COLUMNS):
        raise SyncError("workouts, workout_sets, meals, body_metrics, sleep 시트가 모두 필요합니다.")
    parsed = {}
    for key, columns in COLUMNS.items():
        rows = tables[key]
        if not rows or len(rows) > 20001:
            raise SyncError(f"{key}: 헤더가 필요하며 시트당 최대 20,000행까지 지원합니다.")
        headers = [str(x).strip() for x in rows[0]]
        if len(set(headers)) != len(headers) or set(headers) != set(columns):
            raise SyncError(f"{key}: 헤더가 템플릿과 다릅니다. 필수 컬럼과 중복·추가 컬럼을 확인해 주세요.")
        seen, result = set(), []
        for number, cells in enumerate(rows[1:], 2):
            if all(x is None or x == "" for x in cells):
                continue
            if len(cells) > len(headers):
                raise SyncError(f"{key} {number}행: 헤더보다 값이 많습니다.")
            data = dict(zip(headers, cells + [None] * (len(headers) - len(cells))))
            # Blank optional cells become null; required blank cells still fail validation.
            data = {name: (None if isinstance(value, str) and not value.strip() else value) for name, value in data.items()}
            try:
                row = ROW_TYPES[key].model_validate(data)
            except ValidationError as exc:
                fields = ", ".join(str(e["loc"][0]) if e["loc"] else "날짜/시간" for e in exc.errors())
                raise SyncError(f"{key} {number}행: {fields} 값을 확인해 주세요. 날짜·시각은 시간대 포함 ISO 형식이어야 합니다.") from None
            if row.external_id in seen:
                raise SyncError(f"{key} {number}행: external_id가 중복되었습니다.")
            seen.add(row.external_id)
            result.append(row)
        parsed[key] = result
    return parsed


def apply_rows(session: Session, rows: dict[str, list]) -> dict:
    """Caller owns the transaction. Used by Google sync and the local archive importer."""
    counts = {key: {"inserted": 0, "updated": 0, "skipped": 0} for key in MODELS}
    for key, model in MODELS.items():
        for number, row in enumerate(rows[key], 2):
            record = session.scalar(select(model).where(model.source == SOURCE, model.external_id == row.external_id))
            stamp = utc(row.updated_at)
            if record is not None and record.source_updated_at is not None and stamp <= record.source_updated_at:
                counts[key]["skipped"] += 1
                continue
            action = "inserted" if record is None else "updated"
            if record is None:
                record = model(source=SOURCE, external_id=row.external_id)
            values = row.model_dump(exclude={"external_id", "updated_at"})
            if key == "workout_sets":
                parent = session.scalar(select(Workout).where(Workout.source == SOURCE, Workout.external_id == values.pop("workout_external_id")))
                if parent is None:
                    raise SyncError(f"workout_sets {number}행: 연결할 workout_external_id가 없습니다.")
                name = values.pop("exercise")
                exercise = session.scalar(select(Exercise).where(Exercise.name == name))
                if exercise is None:
                    exercise = Exercise(name=name)
                    session.add(exercise)
                    session.flush()
                values.update(workout_id=parent.id, exercise_id=exercise.id)
            for name, value in values.items():
                if isinstance(value, datetime):
                    value = utc(value)
                if name == "image_url" and value is not None:
                    value = str(value)
                setattr(record, name, value)
            record.source_updated_at = stamp
            session.add(record)
            session.flush()
            counts[key][action] += 1
    # Validate the final sleep intervals, including local records and all changed rows.
    intervals = session.scalars(select(SleepRecord).order_by(SleepRecord.sleep_start, SleepRecord.id)).all()
    for previous, current in zip(intervals, intervals[1:]):
        if current.sleep_start < previous.sleep_end:
            raise SyncError("수면 시간이 기존 기록 또는 다른 행과 겹칩니다. 전체 동기화를 취소했습니다.")
    return counts


def state_record(session: Session) -> SyncState:
    state = session.get(SyncState, 1)
    if state is None:
        state = SyncState(id=1)
        session.add(state)
    return state


def get_sync_status() -> dict:
    cfg = GoogleSettings.from_env()
    with SessionLocal() as session:
        state = session.get(SyncState, 1)
        configured = cfg.configured()
        bound = bool(state and state.spreadsheet_id and state.spreadsheet_id != cfg.spreadsheet_id)
        return {"source": SOURCE, "configured": configured, "running": RUN_LOCK.locked(),
                "connection_status": "not_configured" if not configured else "different_spreadsheet" if bound else "connected" if state and state.last_sync_status == "ok" else "not_verified",
                "spreadsheet_id": cfg.spreadsheet_id or None,
                "spreadsheet_title": state.spreadsheet_title if state and not bound else None,
                "last_sync_at": state.last_sync_at.replace(tzinfo=timezone.utc).isoformat() if state and state.last_sync_at else None,
                "last_sync_status": state.last_sync_status if state else None,
                "last_sync_error": state.last_sync_error if state else None,
                "last_result": json.loads(state.last_result) if state and state.last_result else None}


def sync_google_sheets(reader: SheetReader | None = None) -> dict:
    if not RUN_LOCK.acquire(blocking=False):
        raise SyncError("이미 동기화 중입니다. 완료 후 다시 시도해 주세요.", 409)
    try:
        cfg = GoogleSettings.from_env()
        try:
            snapshot = (reader or GoogleSheetsReader(cfg)).read()
            korean_plan = None
            if snapshot.format == "korean":
                from app.services.korean_sheets import prepare_korean
                korean_plan = prepare_korean(snapshot.tables)
                parsed = None
            else:
                parsed = parse_tables(snapshot.tables)
            with SessionLocal() as session:
                session.execute(text("BEGIN IMMEDIATE"))
                try:
                    state = state_record(session)
                    if state.spreadsheet_id and state.spreadsheet_id != cfg.spreadsheet_id:
                        raise SyncError("이미 다른 Spreadsheet에 연결된 데이터입니다. 기존 ID를 복원해 주세요.", 409)
                    if korean_plan is not None:
                        from app.services.korean_sheets import apply_korean
                        counts = apply_korean(session, korean_plan, cfg.spreadsheet_id)
                    else:
                        counts = apply_rows(session, parsed)
                    result = {"status": "ok", "source": SOURCE, **counts}
                    state.spreadsheet_id = cfg.spreadsheet_id or None
                    state.spreadsheet_title = snapshot.title
                    state.last_sync_at, state.last_sync_status, state.last_sync_error = utc_now(), "ok", None
                    state.last_result = json.dumps(result)
                    session.commit()
                    return result
                except Exception:
                    session.rollback()
                    raise
        except IntegrityError:
            error = SyncError("세트 번호 또는 기록 식별자가 기존 데이터와 충돌합니다. 전체 동기화를 취소했습니다.", 409)
        except OperationalError:
            error = SyncError("데이터베이스가 사용 중이거나 쓰기에 실패했습니다. 잠시 후 다시 시도해 주세요.", 503)
        except SyncError as exc:
            error = exc
        except Exception:
            # No raw upstream response, credential, row value or traceback is exposed.
            error = SyncError("동기화 처리에 실패했습니다. 설정과 입력 형식을 확인해 주세요.", 502)
        try:
            with SessionLocal() as session:
                state = state_record(session)
                state.last_sync_at, state.last_sync_status = utc_now(), "error"
                state.last_sync_error, state.last_result = error.message, None
                session.commit()
        except OperationalError:
            pass
        raise error from None
    finally:
        RUN_LOCK.release()
