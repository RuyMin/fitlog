"""Meal, body measurement and sleep operations; independent of HTTP. Always scoped to one user."""
from datetime import datetime, timezone
from typing import TypeVar

from sqlalchemy import select, text
from sqlalchemy.orm import InstrumentedAttribute, Session

from app.models import BodyMetric, Meal, SleepRecord
from app.schemas import BodyMetricInput, MealInput, SleepInput
from app.services.persistence import RecordConflict, commit, owned

Record = TypeVar("Record", Meal, BodyMetric, SleepRecord)


def utc_naive(value: datetime) -> datetime:
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def get_record(session: Session, user_id: int, model: type[Record], record_id: int) -> Record:
    return owned(session, model, user_id, record_id)


def list_records(
    session: Session, user_id: int, model: type[Record], timestamp: InstrumentedAttribute,
    limit: int, offset: int, from_at: datetime | None, to_at: datetime | None,
) -> list[Record]:
    query = select(model).where(model.user_id == user_id)
    if from_at is not None:
        query = query.where(timestamp >= utc_naive(from_at))
    if to_at is not None:
        query = query.where(timestamp < utc_naive(to_at))
    return list(session.scalars(query.order_by(timestamp.desc(), model.id.desc()).limit(limit).offset(offset)))


def save_record(
    session: Session, record: Record, data: MealInput | BodyMetricInput | SleepInput,
) -> Record:
    for key, value in data.model_dump().items():
        setattr(record, key, utc_naive(value) if isinstance(value, datetime) else value)
    session.add(record)
    commit(session)
    return record


def save_meal(session: Session, user_id: int, data: MealInput, record_id: int | None = None) -> Meal:
    record = get_record(session, user_id, Meal, record_id) if record_id is not None else Meal(user_id=user_id)
    return save_record(session, record, data)


def save_body_metric(session: Session, user_id: int, data: BodyMetricInput, record_id: int | None = None) -> BodyMetric:
    record = get_record(session, user_id, BodyMetric, record_id) if record_id is not None else BodyMetric(user_id=user_id)
    return save_record(session, record, data)


SLEEP_OVERLAP = "기존 수면 기록과 시간이 겹칩니다. 기존 기록을 수정하거나 시간을 확인해 주세요."


def sleep_overlaps(session: Session, user_id: int, start: datetime, end: datetime, exclude_id: int | None = None) -> bool:
    """UTC-naive interval against this user's sleep; caller holds the write lock."""
    overlap = select(SleepRecord.id).where(
        SleepRecord.user_id == user_id, SleepRecord.sleep_start < end, SleepRecord.sleep_end > start
    )
    if exclude_id is not None:
        overlap = overlap.where(SleepRecord.id != exclude_id)
    return session.scalar(overlap.limit(1)) is not None


def save_sleep(session: Session, user_id: int, data: SleepInput, record_id: int | None = None) -> SleepRecord:
    # Reserve the SQLite writer before reading overlaps, so concurrent requests
    # cannot both pass the overlap check. Call with a fresh, dedicated session.
    session.execute(text("BEGIN IMMEDIATE"))
    try:
        record = get_record(session, user_id, SleepRecord, record_id) if record_id is not None else SleepRecord(user_id=user_id)
        start, end = utc_naive(data.sleep_start), utc_naive(data.sleep_end)
        if sleep_overlaps(session, user_id, start, end, record_id):
            raise RecordConflict(SLEEP_OVERLAP)
        record.duration_minutes = int((end - start).total_seconds() // 60)
        return save_record(session, record, data)
    except Exception:
        session.rollback()
        raise


def delete_record(session: Session, user_id: int, model: type[Record], record_id: int) -> None:
    session.delete(get_record(session, user_id, model, record_id))
    commit(session)
