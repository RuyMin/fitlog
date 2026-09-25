"""Meal, body measurement and sleep operations; independent of HTTP."""
from datetime import datetime, timezone
from typing import TypeVar

from sqlalchemy import select, text
from sqlalchemy.orm import InstrumentedAttribute, Session

from app.models import BodyMetric, Meal, SleepRecord
from app.schemas import BodyMetricInput, MealInput, SleepInput
from app.services.persistence import RecordConflict, RecordNotFound, commit

Record = TypeVar("Record", Meal, BodyMetric, SleepRecord)


def utc_naive(value: datetime) -> datetime:
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def get_record(session: Session, model: type[Record], record_id: int) -> Record:
    record = session.get(model, record_id)
    if record is None:
        raise RecordNotFound("기록을 찾을 수 없습니다.")
    return record


def list_records(
    session: Session, model: type[Record], timestamp: InstrumentedAttribute,
    limit: int, offset: int, from_at: datetime | None, to_at: datetime | None,
) -> list[Record]:
    query = select(model)
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


def save_meal(session: Session, data: MealInput, record_id: int | None = None) -> Meal:
    record = get_record(session, Meal, record_id) if record_id is not None else Meal()
    return save_record(session, record, data)


def save_body_metric(session: Session, data: BodyMetricInput, record_id: int | None = None) -> BodyMetric:
    record = get_record(session, BodyMetric, record_id) if record_id is not None else BodyMetric()
    return save_record(session, record, data)


def save_sleep(session: Session, data: SleepInput, record_id: int | None = None) -> SleepRecord:
    # Reserve the SQLite writer before reading overlaps, so concurrent requests
    # cannot both pass the overlap check. Call with a fresh, dedicated session.
    session.execute(text("BEGIN IMMEDIATE"))
    try:
        record = get_record(session, SleepRecord, record_id) if record_id is not None else SleepRecord()
        start, end = utc_naive(data.sleep_start), utc_naive(data.sleep_end)
        overlap = select(SleepRecord.id).where(
            SleepRecord.sleep_start < end, SleepRecord.sleep_end > start
        )
        if record_id is not None:
            overlap = overlap.where(SleepRecord.id != record_id)
        if session.scalar(overlap.limit(1)) is not None:
            raise RecordConflict("기존 수면 기록과 시간이 겹칩니다. 기존 기록을 수정하거나 시간을 확인해 주세요.")
        record.duration_minutes = int((end - start).total_seconds() // 60)
        return save_record(session, record, data)
    except Exception:
        session.rollback()
        raise


def delete_record(session: Session, model: type[Record], record_id: int) -> None:
    session.delete(get_record(session, model, record_id))
    commit(session)
