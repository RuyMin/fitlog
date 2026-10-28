"""Natural-language record assistant: one shared operator key, per-user daily limits, drafts and the confirmed save.

The model only proposes drafts. Nothing is stored until the person confirms, and the
confirmed records pass the same input validation as manual entries.
"""
import base64
import hashlib
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from cryptography.fernet import Fernet, InvalidToken
from pydantic import ValidationError
from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from app import config
from app.assistant_schemas import CommitRequest, WorkoutDraft
from app.models import AiCredential, AiUsage, BodyMetric, Exercise, Meal, SleepRecord, User, Workout, WorkoutSet, utc_now
from app.schemas import BodyMetricInput, MealInput, SleepInput
from app.services import accounts, claude_records, workouts as workout_service
from app.services.claude_records import AssistantError
from app.services.persistence import RecordConflict, commit
from app.services.records import SLEEP_OVERLAP, sleep_overlaps, utc_naive

MIN_SECRET = 32
DRAFT_TYPES = {"meals": MealInput, "body_metrics": BodyMetricInput, "sleep": SleepInput, "workouts": WorkoutDraft}


def cipher() -> Fernet:
    secret = config.secret_key()
    if len(secret) < MIN_SECRET:
        raise AssistantError("server_not_configured", 503)
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest()))


def server_ready() -> bool:
    return len(config.secret_key()) >= MIN_SECRET


def today() -> date:
    return datetime.now(timezone.utc).date()


def shared_credential(session: Session) -> AiCredential | None:
    """The operator's key, registered by an active admin; every user's drafts use it."""
    return session.scalar(select(AiCredential).join(User, User.id == AiCredential.user_id).where(
        User.role == "admin", User.status == "active").order_by(AiCredential.created_at.desc()).limit(1))


def status(session: Session, user: User) -> dict:
    credential = shared_credential(session)
    usage = session.get(AiUsage, (user.id, today()))
    admin = user.role == "admin"
    return {"server_ready": server_ready(), "consent": accounts.has_ai_consent(session, user.id),
            "key_configured": credential is not None, "key_hint": credential.hint if credential and admin else None,
            "can_manage_key": admin, "model": config.AI_MODEL,
            "daily_limit": config.AI_DAILY_LIMIT, "used_today": usage.count if usage else 0}


def save_key(session: Session, admin_id: int, api_key: str) -> str:
    """Replace the shared key. Callers must be admins (enforced by the route)."""
    sealed = cipher().encrypt(api_key.encode())
    claude_records.verify_key(api_key, config.AI_MODEL)
    hint = f"{api_key[:10]}…{api_key[-4:]}"
    session.execute(delete(AiCredential))
    session.add(AiCredential(user_id=admin_id, ciphertext=sealed, hint=hint, created_at=utc_now()))
    session.commit()
    return hint


def delete_key(session: Session) -> None:
    session.execute(delete(AiCredential))
    session.commit()


def stored_key(session: Session) -> str:
    credential = shared_credential(session)
    if credential is None:
        raise AssistantError("no_key", 400)
    try:
        return cipher().decrypt(credential.ciphertext).decode()
    except InvalidToken:
        # The server secret changed; the admin has to register the key again.
        raise AssistantError("key_unreadable", 400) from None


def take_quota(session: Session, user_id: int) -> None:
    """Counts the attempt before calling out, so failures cannot be retried past the limit."""
    session.execute(text("BEGIN IMMEDIATE"))
    usage = session.get(AiUsage, (user_id, today())) or AiUsage(user_id=user_id, day=today(), count=0)
    if usage.count >= config.AI_DAILY_LIMIT:
        session.rollback()
        raise AssistantError("daily_limit", 429)
    usage.count += 1
    session.add(usage)
    session.commit()


def draft(session: Session, user_id: int, journal: str, zone_name: str, images: list[tuple[str, str]] = ()) -> dict:
    try:
        zone = ZoneInfo(zone_name)
    except (ZoneInfoNotFoundError, ValueError):
        raise AssistantError("bad_timezone", 422) from None
    if not accounts.has_ai_consent(session, user_id):
        raise AssistantError("no_consent", 403)
    api_key = stored_key(session)
    exercises = list(session.scalars(select(Exercise.name).where(Exercise.user_id == user_id).order_by(Exercise.name)))
    take_quota(session, user_id)
    raw = claude_records.extract(api_key, config.AI_MODEL, journal, datetime.now(zone), zone.key, exercises, list(images))
    result = {"unparsed": [str(item)[:500] for item in raw.get("unparsed") or []][:20]}
    for kind, model in DRAFT_TYPES.items():
        items = raw.get(kind) if isinstance(raw.get(kind), list) else []
        result[kind] = [checked(model, item) for item in (marked(kind, i) for i in items[:50] if isinstance(i, dict))]
    return result


ESTIMATE_NOTE = "열량·영양소 AI 추정"


def marked(kind: str, item: dict) -> dict:
    """Meal nutrition may be estimated; say so in the memo that gets saved, not only on screen."""
    estimated = bool(item.pop("nutrition_estimated", False)) if kind == "meals" else False
    if estimated:
        memo = (item.get("memo") or "").strip()
        item["memo"] = f"{memo} · {ESTIMATE_NOTE}" if memo else ESTIMATE_NOTE
    item["__estimated"] = estimated
    return item


LABELS = {
    "eaten_at": "식사 시각", "meal_type": "구분", "name": "음식", "calories": "열량", "protein": "단백질",
    "carbohydrates": "탄수화물", "fat": "지방", "memo": "메모", "measured_at": "측정 시각", "weight": "중량·체중",
    "body_fat": "체지방률", "skeletal_muscle": "골격근량", "sleep_start": "잠든 시각", "sleep_end": "일어난 시각",
    "sleep_type": "구분", "workout_date": "운동일", "title": "제목", "body_part": "부위", "sets": "세트",
    "duration_seconds": "시간", "distance_m": "거리", "speed_kmh": "속도", "incline_pct": "경사", "level": "레벨",
    "heart_rate": "심박", "max_heart_rate": "최대 심박", "cadence": "케이던스", "max_cadence": "최대 케이던스",
    "steps": "걸음", "elevation_gain_m": "누적 상승", "best_pace_seconds": "최고 페이스",
    "exercise": "종목", "set_number": "세트 번호", "reps": "횟수", "completed": "완료",
}


def number(value) -> str:
    return str(int(value)) if isinstance(value, float) and value.is_integer() else str(value)


def problem(issue: dict) -> str:
    """Korean text for a validation issue, e.g. '세트 2 · 횟수: 0 이상이어야 합니다.'"""
    parts = [f"세트 {part + 1}" if isinstance(part, int) else LABELS.get(str(part), str(part)) for part in issue["loc"] if part != "sets"]
    kind, ctx = issue["type"], issue.get("ctx") or {}
    if kind == "value_error":
        text = str(ctx.get("error", issue["msg"]))
    elif kind == "greater_than_equal":
        text = f"{number(ctx.get('ge'))} 이상이어야 합니다."
    elif kind == "greater_than":
        text = f"{number(ctx.get('gt'))}보다 커야 합니다."
    elif kind in {"less_than_equal", "less_than"}:
        text = f"{number(ctx.get('le', ctx.get('lt')))} 이하여야 합니다."
    elif kind == "missing":
        text = "값이 필요합니다."
    elif kind == "string_too_short":
        text = "비어 있습니다."
    elif kind == "timezone_aware" or kind.startswith(("datetime", "date")):
        text = "날짜·시각 형식을 확인해 주세요."
    else:
        text = "값을 확인해 주세요."
    return (" · ".join(parts) + ": " if parts else "") + text


def checked(model, item: dict) -> dict:
    """Keep the draft as proposed and list what must be fixed before saving."""
    estimated = item.pop("__estimated", False)
    try:
        model.model_validate(item)
        errors = []
    except ValidationError as error:
        errors = [problem(issue) for issue in error.errors()][:10]
    return {"data": item, "errors": errors, "estimated": estimated}


def save(session: Session, user_id: int, data: CommitRequest) -> dict:
    """Store every confirmed record in one transaction, or none of them."""
    session.execute(text("BEGIN IMMEDIATE"))
    try:
        for meal in data.meals:
            session.add(Meal(user_id=user_id, **as_utc(meal.model_dump())))
        for metric in data.body_metrics:
            session.add(BodyMetric(user_id=user_id, **as_utc(metric.model_dump())))
        session.flush()
        for entry in data.sleep:
            start, end = utc_naive(entry.sleep_start), utc_naive(entry.sleep_end)
            if sleep_overlaps(session, user_id, start, end):
                raise RecordConflict(SLEEP_OVERLAP)
            session.add(SleepRecord(user_id=user_id, duration_minutes=int((end - start).total_seconds() // 60),
                                    **as_utc(entry.model_dump())))
            session.flush()
        for workout_draft in data.workouts:
            values = as_utc(workout_draft.model_dump(exclude={"sets"}))
            workout = Workout(user_id=user_id, **values)
            session.add(workout)
            session.flush()
            for item in workout_draft.sets:
                session.add(WorkoutSet(user_id=user_id, workout_id=workout.id, exercise_id=exercise_id(session, user_id, item.exercise),
                                       **item.model_dump(exclude={"exercise"})))
        commit(session)
    except Exception:
        session.rollback()
        raise
    return {"meals": len(data.meals), "body_metrics": len(data.body_metrics), "sleep": len(data.sleep),
            "workouts": len(data.workouts), "sets": sum(len(w.sets) for w in data.workouts)}


def as_utc(values: dict) -> dict:
    return {key: utc_naive(value) if isinstance(value, datetime) else value for key, value in values.items()}


def exercise_id(session: Session, user_id: int, name: str) -> int:
    return workout_service.exercise_named(session, user_id, name).id
