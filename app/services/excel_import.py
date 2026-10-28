"""Reviewable Excel import. No record writes happen until a preview is committed."""
import hashlib
import json
import re
import secrets
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import ValidationError
from sqlalchemy import delete, select, text, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import config
from app.assistant_schemas import WorkoutDraft
from app.database import SessionLocal
from app.models import ExcelPreview, ImportArchive, Exercise, Workout, WorkoutSet, utc_now
from app.schemas import BodyMetricInput, MealInput, SleepInput
from app.services import accounts, assistant, claude_import, workouts as workout_service
from app.services.claude_records import AssistantError
from app.services.legacy_xlsx import build_plan, load_cells
from app.services.sync_service import MODELS, parse_tables, SyncError
from app.services.persistence import owned
from app.sync_schemas import COLUMNS

TTL = timedelta(hours=1)
LABELS = {"workouts": "운동", "workout_sets": "세트", "meals": "식단", "body_metrics": "신체", "sleep": "수면"}
AI_ROW_LIMIT = 800
CARDIO_FIELDS = ("duration_seconds", "distance_m", "speed_kmh", "incline_pct", "level", "calories", "heart_rate",
                 "max_heart_rate", "cadence", "max_cadence", "steps", "elevation_gain_m", "best_pace_seconds")
AI_MESSAGES = {
    "no_key": "운영자가 공용 AI 키를 아직 등록하지 않았습니다. 설정에서 등록해 주세요.",
    "key_unreadable": "서버 비밀키가 바뀌어 저장된 AI 키를 읽을 수 없습니다. 운영자가 키를 다시 등록해야 합니다.",
    "server_not_configured": "운영자가 서버의 AI 설정(FITLOG_SECRET_KEY)을 아직 하지 않았습니다.",
    "daily_limit": "오늘 AI 사용 한도를 모두 썼습니다. 내일 다시 시도해 주세요.",
    "invalid_key": "등록된 AI 키가 올바르지 않습니다. 운영자에게 확인을 요청해 주세요.",
    "key_forbidden": "등록된 AI 키에 사용 권한이 없습니다.",
    "model_unavailable": "등록된 키로는 앱이 쓰는 모델을 사용할 수 없습니다.",
    "rate_limited": "AI 요청이 몰려 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.",
    "request_rejected": "AI 요청이 거절되었습니다. 관리자에게 알려 주세요(사유는 서버 로그에 남습니다).",
    "refused": "AI가 이 파일 처리를 거절했습니다.",
    "too_long": "표가 너무 커서 한 번에 분석하지 못했습니다. 시트를 나눠 올려 주세요.",
    "unreadable": "AI 응답을 읽지 못했습니다. 잠시 후 다시 시도해 주세요.",
    "upstream": "AI 서버 오류로 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.",
    "unreachable": "AI 서버에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.",
}


def wire(value):
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


def normalized(values: dict) -> dict:
    result = dict(values)
    if result.get("memo"):
        # Location is provenance, not record identity; sorting must not create changes.
        result["memo"] = re.sub(r"(원본: [^\n]+?) \d+행", r"\1", result["memo"])
    return result


def fingerprint(session: Session, user_id: int) -> str:
    """Only this user's records; another user's writes never stale this preview."""
    state = {}
    for model in [*MODELS.values(), Exercise]:
        state[model.__tablename__] = [
            {col.name: wire(getattr(row, col.name)) for col in model.__table__.columns}
            for row in session.scalars(select(model).where(model.user_id == user_id).order_by(model.id))
        ]
    return hashlib.sha256(json.dumps(state, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def record_values(record, incoming: dict) -> dict:
    result = {key: wire(getattr(record, key)) for key in incoming if key != "exercise"}
    if "exercise" in incoming:
        result["exercise"] = record.exercise.name
    return result


def identity(kind: str, value: dict) -> tuple:
    if kind == "workouts": return value["workout_date"], value["title"]
    if kind == "meals": return value["eaten_at"], value["name"]
    if kind == "body_metrics": return (value["measured_at"],)
    if kind == "sleep": return value["sleep_start"], value["sleep_end"]
    return value["exercise"], value["set_number"]


def compare(session: Session, user_id: int, rows: dict) -> list[dict]:
    entries, parents = [], {}
    for kind, model in MODELS.items():
        prepared = []
        for row in rows[kind]:
            values = {k: wire(v) for k,v in row.model_dump().items() if k not in {"external_id", "updated_at", "workout_external_id"}}
            # These fields do not exist in the legacy workbook; absence must not clear app/Google data.
            if kind == "meals": values.pop("image_url", None)
            if kind == "workout_sets":
                values.pop("rpe", None)
                # Cardio fields a file does not give must not clear what the app has.
                for name in CARDIO_FIELDS:
                    if values.get(name) is None: values.pop(name, None)
            parent = parents.get(row.workout_external_id) if kind == "workout_sets" else None
            key = identity(kind, values)
            if parent: key = (parent["key"], *key)
            prepared.append((row, values, key, parent))
        duplicates = Counter(item[2] for item in prepared)
        existing = list(session.scalars(select(model).where(model.user_id == user_id).order_by(model.id)))
        lookup = defaultdict(list)
        # Index exact semantic keys, never legacy row-number IDs.
        for record in existing:
            if kind == "workout_sets":
                key = (record.workout_id, record.exercise.name, record.set_number)
            elif kind == "workouts": key = (record.workout_date.isoformat(), record.title)
            elif kind == "meals": key = (wire(record.eaten_at), record.name)
            elif kind == "body_metrics": key = (wire(record.measured_at),)
            else: key = (wire(record.sleep_start), wire(record.sleep_end))
            lookup[key].append(record)
        for row, values, key, parent in prepared:
            entry = {"key": str(len(entries)), "kind": kind, "label": LABELS[kind],
                     "incoming": values, "before": None, "target_id": None,
                     "parent": parent["key"] if parent else None, "status": "new", "reason": "새 기록", "changes": []}
            entry["title"] = " · ".join(str(x) for x in identity(kind, values))
            candidates = lookup.get(key, [])
            if kind == "workout_sets":
                candidates = lookup.get((parent["target_id"], values["exercise"], values["set_number"]), []) if parent and parent["target_id"] else []
                if parent:
                    entry["title"] = parent["title"] + " · " + entry["title"]
                if not parent or parent["status"] == "conflict":
                    entry.update(status="conflict", reason="연결할 운동이 모호합니다. 운동 기록부터 확인해 주세요.")
            if duplicates[key] > 1 or len(candidates) > 1:
                entry.update(status="conflict", reason="같은 식별 조건의 기록이 여러 개입니다. 자동 병합하지 않습니다.")
            if entry["status"] != "conflict" and len(candidates) == 1:
                record = candidates[0]
                before = record_values(record, values)
                entry.update(before=before, target_id=record.id)
                a,b = normalized(before), normalized(values)
                changes = [k for k in values if a.get(k) != b.get(k)]
                entry.update(changes=changes, status="updated" if changes else "identical",
                             reason="선택하면 표시된 기존 값을 덮어씁니다." if changes else "현재 기록과 동일")
            if entry["status"] == "conflict":
                entry["candidates"] = [{"id": r.id, "values": record_values(r,values)} for r in candidates]
            if entry["status"] == "new":
                entry["reason"] = "일치하는 식별 조건이 없습니다. 날짜·시각·이름을 수정한 기록이면 중복 후보를 먼저 확인하세요."
                if kind != "workout_sets":
                    field = {"workouts":"workout_date","meals":"eaten_at","body_metrics":"measured_at","sleep":"sleep_start"}[kind]
                    day = str(values[field])[:10]
                    entry["candidates"] = [{"id":r.id,"values":record_values(r,values)} for r in existing if str(wire(getattr(r,field)))[:10] == day][:20]
            entries.append(entry)
            if kind == "workouts": parents[row.external_id] = entry
    return entries


def _persist_preview(user_id: int, plan: dict, filename: str, original: bytes) -> dict:
    """Shared tail for both import paths: validate, diff against current records, store a reviewable preview."""
    rows = parse_tables(plan["tables"])
    if sum(len(v) for v in rows.values()) > 5000:
        raise SyncError("한 번에 최대 5,000개 기록만 비교할 수 있습니다.")
    with SessionLocal() as session:
        session.execute(text("BEGIN"))
        digest = fingerprint(session, user_id)
        entries = compare(session, user_id, rows)
        archived = session.scalar(select(ImportArchive.id).where(ImportArchive.user_id == user_id, ImportArchive.sha256 == plan["sha256"]))
    plan.pop("original", None)
    payload = {"plan":plan,"fingerprint":digest,"entries":entries}
    with SessionLocal() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        session.execute(delete(ExcelPreview).where(ExcelPreview.result.is_(None), ExcelPreview.created_at < utc_now()-TTL))
        if session.scalar(select(func.count()).select_from(ExcelPreview).where(ExcelPreview.user_id == user_id, ExcelPreview.result.is_(None))) >= 20:
            raise SyncError("대기 중인 비교가 많습니다. 기존 비교를 취소하거나 만료 후 다시 시도해 주세요.",429)
        preview = ExcelPreview(user_id=user_id,token=secrets.token_urlsafe(32),payload=json.dumps(payload,ensure_ascii=False),original=original)
        session.add(preview);session.commit()
        return {"token":preview.token,"filename":filename,"expires_at":wire(preview.created_at+TTL),
                "previous_archive_id":archived,"counts":dict(Counter(e["status"] for e in entries)),
                "entries":entries,"notes":plan["report"]["notes"],"unparsed":plan["report"].get("unparsed", [])}


def create_preview(user_id: int, original: bytes, filename: str) -> dict:
    """Fixed 7-sheet Korean workbook path (CLI/legacy); the browser upload uses create_ai_preview."""
    try:
        plan = build_plan(original, filename)
    except SyncError:
        raise
    except ValueError as exc:
        raise SyncError(str(exc)) from None
    except Exception:
        raise SyncError("Excel 파일을 읽지 못했습니다. 손상·암호 설정·시트 형식을 확인해 주세요.") from None
    return _persist_preview(user_id, plan, filename, original)


def create_ai_preview(user_id: int, original: bytes, filename: str, zone_name: str) -> dict:
    """Map an arbitrary workbook to records with Claude, then reuse the reviewable preview pipeline.

    The model's output is validated like a manual entry and never written until the user commits.
    """
    try:
        zone = ZoneInfo(zone_name)
    except (ZoneInfoNotFoundError, ValueError):
        raise SyncError("시간대를 확인해 주세요.", 422) from None
    try:
        sheets = load_cells(original)
    except ValueError as exc:
        raise SyncError(str(exc)) from None
    except Exception:
        raise SyncError("Excel 파일을 읽지 못했습니다. 손상·암호 설정·시트 형식을 확인해 주세요.") from None
    total = sum(len(rows) for rows in sheets.values())
    if total == 0:
        raise SyncError("표에서 읽을 데이터가 없습니다. 내용이 있는 .xlsx 파일을 올려 주세요.")
    if total > AI_ROW_LIMIT:
        raise SyncError(f"AI 분석은 한 번에 최대 {AI_ROW_LIMIT:,}행까지 지원합니다. 시트를 나눠 올려 주세요.")
    with SessionLocal() as session:
        if not accounts.has_ai_consent(session, user_id):
            raise SyncError("AI 외부 전송에 먼저 동의해 주세요. 설정의 계정 카드에서 동의할 수 있습니다.", 403)
        try:
            api_key = assistant.stored_key(session)
            assistant.take_quota(session, user_id)
        except AssistantError as exc:
            raise _ai_error(exc) from None
    try:
        raw = claude_import.extract(api_key, config.AI_MODEL, sheets, datetime.now(zone), zone.key)
    except AssistantError as exc:
        raise _ai_error(exc) from None
    plan = ai_plan(raw, sheets, original, filename, zone.key)
    return _persist_preview(user_id, plan, filename, original)


def _ai_error(exc: AssistantError) -> SyncError:
    return SyncError(AI_MESSAGES.get(exc.code, "AI 요청을 처리하지 못했습니다."), exc.status)


def _list(raw: dict, key: str) -> list:
    value = raw.get(key)
    return value if isinstance(value, list) else []


def mapped_rows(raw: dict, stamp: str, prefix: str) -> tuple[dict, list]:
    """Validate each AI draft with the same input models as manual entry; drop invalid ones.

    This keeps parse_tables all-or-nothing happy and guarantees the model cannot push a value
    past the app's own validation. Dropped rows are listed back to the user, not silently lost.
    """
    rows = {key: [] for key in COLUMNS}
    dropped = []
    counter = 0
    def ident() -> str:
        nonlocal counter
        counter += 1
        return f"ai_{prefix}_{counter}"
    for item in _list(raw, "meals"):
        if not isinstance(item, dict):
            continue
        item = dict(item)
        if item.pop("nutrition_estimated", False):
            memo = (item.get("memo") or "").strip()
            item["memo"] = f"{memo} · {assistant.ESTIMATE_NOTE}" if memo else assistant.ESTIMATE_NOTE
        try:
            MealInput.model_validate(item)
        except ValidationError:
            dropped.append("식단: " + str(item.get("name") or item.get("eaten_at") or "확인 불가"))
            continue
        rows["meals"].append({"external_id": ident(), "eaten_at": item["eaten_at"], "meal_type": item.get("meal_type", "other"),
                              "name": item["name"], "calories": item.get("calories"), "protein": item.get("protein"),
                              "carbohydrates": item.get("carbohydrates"), "fat": item.get("fat"), "memo": item.get("memo"),
                              "image_url": None, "updated_at": stamp})
    for item in _list(raw, "body_metrics"):
        if not isinstance(item, dict):
            continue
        try:
            BodyMetricInput.model_validate(item)
        except ValidationError:
            dropped.append("신체: " + str(item.get("measured_at") or "확인 불가"))
            continue
        rows["body_metrics"].append({"external_id": ident(), "measured_at": item["measured_at"], "weight": item.get("weight"),
                                     "body_fat": item.get("body_fat"), "skeletal_muscle": item.get("skeletal_muscle"),
                                     "memo": item.get("memo"), "updated_at": stamp})
    for item in _list(raw, "sleep"):
        if not isinstance(item, dict):
            continue
        try:
            SleepInput.model_validate(item)
        except ValidationError:
            dropped.append("수면: " + str(item.get("sleep_start") or "확인 불가"))
            continue
        rows["sleep"].append({"external_id": ident(), "sleep_start": item["sleep_start"], "sleep_end": item["sleep_end"],
                              "duration_minutes": None, "sleep_type": item.get("sleep_type", "main"),
                              "memo": item.get("memo"), "updated_at": stamp})
    for item in _list(raw, "workouts"):
        if not isinstance(item, dict):
            continue
        try:
            WorkoutDraft.model_validate(item)
        except ValidationError:
            dropped.append("운동: " + str(item.get("title") or item.get("workout_date") or "확인 불가"))
            continue
        workout_id = ident()
        rows["workouts"].append({"external_id": workout_id, "workout_date": item["workout_date"], "title": item["title"],
                                 "body_part": item.get("body_part"), "started_at": None, "ended_at": None,
                                 "memo": item.get("memo"), "updated_at": stamp})
        for entry in item.get("sets") or []:
            rows["workout_sets"].append({"external_id": ident(), "workout_external_id": workout_id, "exercise": entry["exercise"],
                                         "set_number": entry["set_number"], "weight": entry.get("weight"), "reps": entry.get("reps"),
                                         "completed": entry.get("completed", True), "rpe": None, "rir": None, "memo": None,
                                         **{name: entry.get(name) for name in CARDIO_FIELDS},
                                         "updated_at": stamp})
    return rows, dropped


def ai_plan(raw: dict, sheets: dict, original: bytes, filename: str, zone_name: str) -> dict:
    stamp = datetime.now(timezone.utc).isoformat()
    rows, dropped = mapped_rows(raw, stamp, secrets.token_hex(4))
    tables = {key: [cols] + [[record.get(c) for c in cols] for record in rows[key]] for key, cols in COLUMNS.items()}
    unparsed = ([str(x)[:500] for x in _list(raw, "unparsed")] + dropped)[:80]
    counts = {key: len(value) for key, value in rows.items()}
    notes = [f"AI가 업로드한 표를 FitLog 기록으로 매핑한 초안입니다({zone_name} 기준). 저장 전에 각 항목을 확인해 주세요."]
    notes.append("값이 분명하지 않은 행은 아래 ‘AI가 변환하지 못한 내용’에 남겨 두고 기록으로 만들지 않았습니다." if unparsed
                 else "모든 행을 기록 초안으로 변환했습니다.")
    report = {"counts": counts, "unparsed": unparsed, "notes": notes,
              "summary": (f"AI 매핑: 운동 {counts['workouts']}회 · 세트 {counts['workout_sets']}개 · "
                          f"식단 {counts['meals']}건 · 신체 {counts['body_metrics']}건 · 수면 {counts['sleep']}건.")}
    archive = {name: [{"row": i, "values": cells} for i, cells in enumerate(rowset, 1)] for name, rowset in sheets.items()}
    return {"sha256": hashlib.sha256(original).hexdigest(), "filename": filename,
            "archive": archive, "tables": tables, "report": report}


def commit_preview(user_id: int, token: str, selected: list[str]) -> dict:
    if len(selected) != len(set(selected)):
        raise SyncError("선택 항목이 중복되었습니다.")
    with SessionLocal() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        preview = session.scalar(select(ExcelPreview).where(ExcelPreview.token==token,ExcelPreview.user_id==user_id))
        if preview is None: raise SyncError("비교 결과가 없습니다. 다시 업로드해 주세요.",404)
        if preview.result:
            result = json.loads(preview.result)
            if sorted(selected) != result["selected"]: raise SyncError("이미 다른 선택으로 저장한 비교입니다.",409)
            return result
        if utc_now() - preview.created_at > TTL: raise SyncError("비교 결과가 만료되었습니다. 다시 업로드해 주세요.",409)
        payload=json.loads(preview.payload)
        if fingerprint(session, user_id) != payload["fingerprint"]:
            raise SyncError("비교 이후 기록이 변경되었습니다. 최신 기록으로 다시 비교해 주세요.",409)
        entries={e["key"]:e for e in payload["entries"]}
        if any(k not in entries or entries[k]["status"] not in {"new","updated"} for k in selected):
            raise SyncError("저장할 수 없는 항목이 선택되었습니다.")
        selected_set=set(selected)
        for key in selected:
            e=entries[key]
            if e["parent"] is not None:
                parent=entries[e["parent"]]
                if parent["target_id"] is None and parent["key"] not in selected_set:
                    raise SyncError("새 세트를 저장하려면 해당 운동도 함께 선택해 주세요.")
        ids={e["key"]:e["target_id"] for e in entries.values()}
        result={"status":"ok","inserted":0,"updated":0,"skipped":len(entries)-len(selected),"selected":sorted(selected)}
        changes=[]
        try:
            for key,e in entries.items():
                if key not in selected_set: continue
                model=MODELS[e["kind"]]
                record=owned(session,model,user_id,e["target_id"]) if e["target_id"] is not None else model(user_id=user_id,source="excel",external_id="xlsx_"+secrets.token_hex(16))
                values=dict(e["incoming"])
                if e["kind"] == "workout_sets":
                    exercise_name=values.pop("exercise")
                    exercise=workout_service.exercise_named(session,user_id,exercise_name)
                    values.update(workout_id=ids[e["parent"]],exercise_id=exercise.id)
                for name,value in values.items():
                    if value is not None and name == "workout_date": value=date.fromisoformat(value)
                    elif value is not None and name in {"started_at","ended_at","eaten_at","measured_at","sleep_start","sleep_end"}:
                        value=datetime.fromisoformat(value).astimezone(timezone.utc).replace(tzinfo=None)
                    setattr(record,name,value)
                record.source_updated_at=utc_now()
                session.add(record);session.flush();ids[key]=record.id
                result["inserted" if e["target_id"] is None else "updated"]+=1
                changes.append({**e,"saved_id":record.id})
            plan=payload["plan"]
            archive=session.scalar(select(ImportArchive).where(ImportArchive.user_id==user_id,ImportArchive.sha256==plan["sha256"]))
            if archive is None:
                report={**plan["report"],"summary":f"Excel 비교 저장: {result['inserted']}건 추가 · {result['updated']}건 수정 · {result['skipped']}건 유지. 원본 전체 보존."}
                archive=ImportArchive(user_id=user_id,sha256=plan["sha256"],filename=plan["filename"],original=preview.original,
                                      payload=json.dumps(plan["archive"],ensure_ascii=False),report=json.dumps(report,ensure_ascii=False))
                session.add(archive);session.flush()
            result["archive_id"]=archive.id
            preview.result=json.dumps(result)
            preview.payload=json.dumps({"filename":plan["filename"],"changes":changes,"saved_at":wire(utc_now())},ensure_ascii=False)
            preview.original=b""
            session.commit()
            return result
        except IntegrityError:
            session.rollback()
            raise SyncError("기존 기록과 세트 번호 등이 충돌하여 저장 전체를 취소했습니다. 다시 비교해 주세요.",409) from None


def discard_preview(user_id: int, token: str) -> dict:
    with SessionLocal() as session:
        session.execute(delete(ExcelPreview).where(ExcelPreview.token==token,ExcelPreview.user_id==user_id,ExcelPreview.result.is_(None)))
        session.commit()
    return {"status":"discarded"}


def history(user_id: int) -> list[dict]:
    with SessionLocal() as session:
        return [{"token":r.token,**json.loads(r.payload),"result":json.loads(r.result)}
                for r in session.scalars(select(ExcelPreview).where(ExcelPreview.user_id==user_id,ExcelPreview.result.is_not(None)).order_by(ExcelPreview.created_at.desc()).limit(10))]
