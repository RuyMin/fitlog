"""Transport-neutral row application: validate first, then apply a whole snapshot in one SQLite transaction.

Shared by the Excel import pipeline and the legacy_xlsx CLI. No network transport lives here.
"""
from datetime import datetime

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Workout, WorkoutSet, Meal, BodyMetric, SleepRecord
from app.services import workouts as workout_service
from app.times import utc_naive
from app.sync_schemas import COLUMNS, OPTIONAL_COLUMNS, ROW_TYPES

MODELS = {"workouts": Workout, "workout_sets": WorkoutSet, "meals": Meal, "body_metrics": BodyMetric, "sleep": SleepRecord}
SOURCE = "google_sheets"


class SyncError(Exception):
    def __init__(self, message: str, code: int = 422):
        self.message, self.code = message, code
        super().__init__(message)


def parse_tables(tables: dict[str, list[list]]) -> dict[str, list]:
    if set(tables) != set(COLUMNS):
        raise SyncError("workouts, workout_sets, meals, body_metrics, sleep 시트가 모두 필요합니다.")
    parsed = {}
    for key, columns in COLUMNS.items():
        rows = tables[key]
        if not rows or len(rows) > 20001:
            raise SyncError(f"{key}: 헤더가 필요하며 시트당 최대 20,000행까지 지원합니다.")
        headers = [str(x).strip() for x in rows[0]]
        required = set(columns) - OPTIONAL_COLUMNS.get(key, set())
        if len(set(headers)) != len(headers) or not required <= set(headers) <= set(columns):
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


def apply_rows(session: Session, user_id: int, rows: dict[str, list]) -> dict:
    """Caller owns the transaction. Used by the legacy_xlsx CLI."""
    counts = {key: {"inserted": 0, "updated": 0, "skipped": 0} for key in MODELS}
    for key, model in MODELS.items():
        for number, row in enumerate(rows[key], 2):
            record = session.scalar(select(model).where(model.user_id == user_id, model.source == SOURCE, model.external_id == row.external_id))
            stamp = utc_naive(row.updated_at)
            if record is not None and record.source_updated_at is not None and stamp <= record.source_updated_at:
                counts[key]["skipped"] += 1
                continue
            action = "inserted" if record is None else "updated"
            if record is None:
                record = model(user_id=user_id, source=SOURCE, external_id=row.external_id)
            values = row.model_dump(exclude={"external_id", "updated_at"})
            if key == "workout_sets":
                parent = session.scalar(select(Workout).where(
                    Workout.user_id == user_id, Workout.source == SOURCE, Workout.external_id == values.pop("workout_external_id")))
                if parent is None:
                    raise SyncError(f"workout_sets {number}행: 연결할 workout_external_id가 없습니다.")
                name = values.pop("exercise")
                exercise = workout_service.exercise_named(session, user_id, name)
                values.update(workout_id=parent.id, exercise_id=exercise.id)
            for name, value in values.items():
                if isinstance(value, datetime):
                    value = utc_naive(value)
                if name == "image_url" and value is not None:
                    value = str(value)
                setattr(record, name, value)
            record.source_updated_at = stamp
            session.add(record)
            session.flush()
            counts[key][action] += 1
    # Validate the final sleep intervals, including local records and all changed rows.
    intervals = session.scalars(select(SleepRecord).where(SleepRecord.user_id == user_id).order_by(SleepRecord.sleep_start, SleepRecord.id)).all()
    for previous, current in zip(intervals, intervals[1:]):
        if current.sleep_start < previous.sleep_end:
            raise SyncError("수면 시간이 기존 기록 또는 다른 행과 겹칩니다. 전체 동기화를 취소했습니다.")
    return counts
