"""Login sessions; independent of HTTP. Tokens are random and only their hashes are stored."""
import hashlib
import secrets
from datetime import datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import AuthSession, User, utc_now

IDLE = timedelta(days=30)
ABSOLUTE = timedelta(days=90)
# Sliding renewal writes at most once per day per session.
TOUCH = timedelta(days=1)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(session: Session, user_id: int) -> tuple[str, datetime]:
    """Return the cookie token and the absolute expiry (UTC-naive)."""
    now = utc_now()
    session.execute(delete(AuthSession).where(AuthSession.expires_at <= now))
    token = secrets.token_urlsafe(32)
    session.add(AuthSession(token_hash=token_hash(token), user_id=user_id, created_at=now, last_seen_at=now, expires_at=now + IDLE))
    session.commit()
    return token, now + ABSOLUTE


def resolve_session(session: Session, token: str | None) -> User | None:
    """The active user for a cookie token, renewing the idle window; None otherwise."""
    if not token or len(token) > 100:
        return None
    record = session.scalar(select(AuthSession).where(AuthSession.token_hash == token_hash(token)))
    now = utc_now()
    if record is None or record.expires_at <= now:
        return None
    user = session.get(User, record.user_id)
    if user is None or user.status != "active":
        return None
    if now - record.last_seen_at >= TOUCH:
        record.last_seen_at = now
        record.expires_at = min(now + IDLE, record.created_at + ABSOLUTE)
        session.commit()
    return user


def end_session(session: Session, token: str | None) -> None:
    if token:
        session.execute(delete(AuthSession).where(AuthSession.token_hash == token_hash(token)))
        session.commit()


def end_all_sessions(session: Session, user_id: int) -> None:
    session.execute(delete(AuthSession).where(AuthSession.user_id == user_id))
    session.commit()
