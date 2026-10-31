"""Shared errors, ownership lookup and transaction boundary for record services."""
from typing import TypeVar

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

T = TypeVar("T")


class RecordNotFound(Exception):
    pass


class RecordInvalid(Exception):
    """A value that passes the schema but not the record's own rules (422)."""


class RecordConflict(Exception):
    pass


def owned(session: Session, model: type[T], user_id: int, record_id: int, message: str = "기록을 찾을 수 없습니다.") -> T:
    """Another owner's row is indistinguishable from a missing one."""
    record = session.scalar(select(model).where(model.id == record_id, model.user_id == user_id))
    if record is None:
        raise RecordNotFound(message)
    return record


CONFLICT = "중복된 값 또는 다른 기록에서 사용 중인 데이터를 확인해 주세요."


def commit(session: Session) -> None:
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise RecordConflict(CONFLICT) from error


def flush(session: Session) -> None:
    """Write pending rows inside the caller's transaction (for new ids); constraint errors read like commit's."""
    try:
        session.flush()
    except IntegrityError as error:
        session.rollback()
        raise RecordConflict(CONFLICT) from error
