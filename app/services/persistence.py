"""Shared errors and transaction boundary for record services."""
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session


class RecordNotFound(Exception):
    pass


class RecordConflict(Exception):
    pass


def commit(session: Session) -> None:
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise RecordConflict("중복된 값 또는 다른 기록에서 사용 중인 데이터를 확인해 주세요.") from error
