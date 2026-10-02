"""Reviewable Excel import. No record writes happen until a preview is committed."""
import hashlib
import json
import re
import secrets
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import delete, select, text, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import ExcelPreview, ImportArchive, Exercise, Workout, WorkoutSet, utc_now
from app.services.legacy_xlsx import build_plan
from app.services.sync_service import MODELS, parse_tables
from app.services.google_sheets import SyncError

TTL = timedelta(hours=1)
LABELS = {"workouts": "운동", "workout_sets": "세트", "meals": "식단", "body_metrics": "신체", "sleep": "수면"}


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


def fingerprint(session: Session) -> str:
    state = {}
    for model in [*MODELS.values(), Exercise]:
        state[model.__tablename__] = [
            {col.name: wire(getattr(row, col.name)) for col in model.__table__.columns}
            for row in session.scalars(select(model).order_by(model.id))
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


def compare(session: Session, rows: dict) -> list[dict]:
    entries, parents = [], {}
    for kind, model in MODELS.items():
        prepared = []
        for row in rows[kind]:
            values = {k: wire(v) for k,v in row.model_dump().items() if k not in {"external_id", "updated_at", "workout_external_id"}}
            # These fields do not exist in the legacy workbook; absence must not clear app/Google data.
            if kind == "meals": values.pop("image_url", None)
            if kind == "workout_sets": values.pop("rpe", None)
            parent = parents.get(row.workout_external_id) if kind == "workout_sets" else None
            key = identity(kind, values)
            if parent: key = (parent["key"], *key)
            prepared.append((row, values, key, parent))
        duplicates = Counter(item[2] for item in prepared)
        existing = list(session.scalars(select(model).order_by(model.id)))
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


def create_preview(original: bytes, filename: str) -> dict:
    try:
        plan = build_plan(original, filename)
        rows = parse_tables(plan["tables"])
        if sum(len(v) for v in rows.values()) > 5000:
            raise SyncError("한 번에 최대 5,000개 기록만 비교할 수 있습니다.")
    except SyncError:
        raise
    except ValueError as exc:
        raise SyncError(str(exc)) from None
    except Exception:
        raise SyncError("Excel 파일을 읽지 못했습니다. 손상·암호 설정·시트 형식을 확인해 주세요.") from None
    with SessionLocal() as session:
        session.execute(text("BEGIN"))
        digest = fingerprint(session)
        entries = compare(session, rows)
        archived = session.scalar(select(ImportArchive.id).where(ImportArchive.sha256 == plan["sha256"]))
    plan.pop("original")
    payload = {"plan":plan,"fingerprint":digest,"entries":entries}
    with SessionLocal() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        session.execute(delete(ExcelPreview).where(ExcelPreview.result.is_(None), ExcelPreview.created_at < utc_now()-TTL))
        if session.scalar(select(func.count()).select_from(ExcelPreview).where(ExcelPreview.result.is_(None))) >= 20:
            raise SyncError("대기 중인 비교가 많습니다. 기존 비교를 취소하거나 만료 후 다시 시도해 주세요.",429)
        preview = ExcelPreview(token=secrets.token_urlsafe(32),payload=json.dumps(payload,ensure_ascii=False),original=original)
        session.add(preview);session.commit()
        return {"token":preview.token,"filename":filename,"expires_at":wire(preview.created_at+TTL),
                "previous_archive_id":archived,"counts":dict(Counter(e["status"] for e in entries)),
                "entries":entries,"notes":plan["report"]["notes"]}


def commit_preview(token: str, selected: list[str]) -> dict:
    if len(selected) != len(set(selected)):
        raise SyncError("선택 항목이 중복되었습니다.")
    with SessionLocal() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        preview = session.get(ExcelPreview, token)
        if preview is None: raise SyncError("비교 결과가 없습니다. 다시 업로드해 주세요.",404)
        if preview.result:
            result = json.loads(preview.result)
            if sorted(selected) != result["selected"]: raise SyncError("이미 다른 선택으로 저장한 비교입니다.",409)
            return result
        if utc_now() - preview.created_at > TTL: raise SyncError("비교 결과가 만료되었습니다. 다시 업로드해 주세요.",409)
        payload=json.loads(preview.payload)
        if fingerprint(session) != payload["fingerprint"]:
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
                record=session.get(model,e["target_id"]) if e["target_id"] is not None else model(source="excel",external_id="xlsx_"+secrets.token_hex(16))
                values=dict(e["incoming"])
                if e["kind"] == "workout_sets":
                    exercise_name=values.pop("exercise")
                    exercise=session.scalar(select(Exercise).where(Exercise.name==exercise_name))
                    if exercise is None:
                        exercise=Exercise(name=exercise_name);session.add(exercise);session.flush()
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
            archive=session.scalar(select(ImportArchive).where(ImportArchive.sha256==plan["sha256"]))
            if archive is None:
                report={**plan["report"],"summary":f"Excel 비교 저장: {result['inserted']}건 추가 · {result['updated']}건 수정 · {result['skipped']}건 유지. 원본 전체 보존."}
                archive=ImportArchive(sha256=plan["sha256"],filename=plan["filename"],original=preview.original,
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


def discard_preview(token: str) -> dict:
    with SessionLocal() as session:
        session.execute(delete(ExcelPreview).where(ExcelPreview.token==token,ExcelPreview.result.is_(None)))
        session.commit()
    return {"status":"discarded"}


def history() -> list[dict]:
    with SessionLocal() as session:
        return [{"token":r.token,**json.loads(r.payload),"result":json.loads(r.result)}
                for r in session.scalars(select(ExcelPreview).where(ExcelPreview.result.is_not(None)).order_by(ExcelPreview.created_at.desc()).limit(10))]
