"""Accounts, invites, login attempts and sessions; independent of HTTP.

Every token (session, invite, OAuth state) is random and only its hash is stored.
"""
import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from app.auth.google import Identity, new_verifier
from app.models import AuthSession, Consent, Invite, OAuthAttempt, User, utc_now

IDLE = timedelta(days=30)
ABSOLUTE = timedelta(days=90)
# Sliding renewal writes at most once per day per session.
TOUCH = timedelta(days=1)
INVITE_TTL = timedelta(days=7)
ATTEMPT_TTL = timedelta(minutes=10)
# Notice version per consent kind (invite.html, settings.html). Raise one when its
# text changes; only that consent is asked again.
CONSENT_VERSIONS = {"service": "2026-10-19", "ai_transfer": "2026-10-21"}


class AccountError(Exception):
    """`code` is a stable, non-sensitive reason shown to the user on the login page."""
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class Attempt:
    verifier: str
    nonce: str
    invite_id: int | None
    next_path: str | None
    consent_service: bool
    consent_ai: bool


def ensure_owner(session: Session, email: str) -> None:
    """Fresh installs: create the unbound admin row so the owner's first Google login can claim it."""
    email = email.strip().lower()
    if email and session.scalar(select(func.count()).select_from(User).where(User.role == "admin")) == 0:
        session.add(User(email=email, role="admin"))
        session.commit()


def create_invite(session: Session, created_by: int, note: str | None = None, ttl: timedelta = INVITE_TTL) -> str:
    token = secrets.token_urlsafe(32)
    now = utc_now()
    session.add(Invite(token_hash=token_hash(token), created_by=created_by, note=note, created_at=now, expires_at=now + ttl))
    session.commit()
    return token


def usable_invite(session: Session, token: str) -> Invite | None:
    invite = session.scalar(select(Invite).where(Invite.token_hash == token_hash(token)))
    if invite is None or invite.used_at is not None or invite.expires_at <= utc_now():
        return None
    return invite


def start_attempt(session: Session, invite_token: str | None, next_path: str | None,
                  consent_service: bool, consent_ai: bool) -> tuple[str, str, str]:
    """Return (state, PKCE verifier, nonce). An invite requires the service consent."""
    invite_id = None
    if invite_token:
        invite = usable_invite(session, invite_token)
        if invite is None:
            raise AccountError("invalid_invite")
        if not consent_service:
            raise AccountError("consent_required")
        invite_id = invite.id
    now = utc_now()
    session.execute(delete(OAuthAttempt).where(OAuthAttempt.created_at <= now - ATTEMPT_TTL))
    state, verifier, nonce = secrets.token_urlsafe(32), new_verifier(), secrets.token_urlsafe(32)
    session.add(OAuthAttempt(state_hash=token_hash(state), code_verifier=verifier, nonce=nonce, invite_id=invite_id,
                             next_path=next_path, consent_service=bool(invite_id and consent_service),
                             consent_ai=bool(invite_id and consent_ai), created_at=now))
    session.commit()
    return state, verifier, nonce


def take_attempt(session: Session, state: str) -> Attempt:
    """Single use: the row is deleted whether or not the login later succeeds."""
    session.execute(text("BEGIN IMMEDIATE"))
    try:
        record = session.get(OAuthAttempt, token_hash(state))
        if record is None or record.created_at <= utc_now() - ATTEMPT_TTL:
            raise AccountError("state")
        attempt = Attempt(record.code_verifier, record.nonce, record.invite_id, record.next_path,
                          record.consent_service, record.consent_ai)
        session.delete(record)
        session.commit()
        return attempt
    except Exception:
        session.rollback()
        raise


def sign_in(session: Session, identity: Identity, attempt: Attempt) -> User:
    """Known Google account, else the owner's first login, else a valid invite; nothing else joins."""
    session.execute(text("BEGIN IMMEDIATE"))
    try:
        now = utc_now()
        user = session.scalar(select(User).where(User.google_sub == identity.sub))
        if user is None:
            # Bound once by verified email; afterwards only `sub` identifies the owner.
            user = session.scalar(select(User).where(User.google_sub.is_(None), User.role == "admin", User.email == identity.email))
            if user is not None:
                user.google_sub = identity.sub
        if user is None:
            invite = session.get(Invite, attempt.invite_id) if attempt.invite_id is not None else None
            if invite is None or invite.used_at is not None or invite.expires_at <= now:
                raise AccountError("invalid_invite" if attempt.invite_id is not None else "not_invited")
            user = User(google_sub=identity.sub, email=identity.email, role="member")
            session.add(user)
            session.flush()
            invite.used_at, invite.used_by = now, user.id
            session.add(Consent(user_id=user.id, kind="service", version=CONSENT_VERSIONS["service"], granted_at=now))
            if attempt.consent_ai:
                session.add(Consent(user_id=user.id, kind="ai_transfer", version=CONSENT_VERSIONS["ai_transfer"], granted_at=now))
        if user.status != "active":
            raise AccountError("disabled")
        user.email, user.last_login_at = identity.email, now
        if identity.name:
            user.display_name = identity.name[:100]
        session.commit()
        return user
    except Exception:
        session.rollback()
        raise


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


def consent_status(session: Session, user_id: int) -> dict:
    """Latest record per kind; `active` only for the current notice version and not withdrawn."""
    result = {}
    for kind in ("service", "ai_transfer"):
        record = session.scalar(select(Consent).where(Consent.user_id == user_id, Consent.kind == kind)
                                .order_by(Consent.granted_at.desc(), Consent.id.desc()).limit(1))
        result[kind] = None if record is None else {
            "version": record.version, "granted_at": record.granted_at, "withdrawn_at": record.withdrawn_at,
            "active": record.withdrawn_at is None and record.version == CONSENT_VERSIONS[kind],
        }
    return result


def has_ai_consent(session: Session, user_id: int) -> bool:
    """Gate for any feature that sends this user's data to an external AI."""
    status = consent_status(session, user_id)["ai_transfer"]
    return bool(status and status["active"])


def grant_ai_consent(session: Session, user_id: int) -> None:
    if not has_ai_consent(session, user_id):
        session.add(Consent(user_id=user_id, kind="ai_transfer", version=CONSENT_VERSIONS["ai_transfer"]))
        session.commit()


def withdraw_ai_consent(session: Session, user_id: int) -> None:
    now = utc_now()
    for record in session.scalars(select(Consent).where(
            Consent.user_id == user_id, Consent.kind == "ai_transfer", Consent.withdrawn_at.is_(None))):
        record.withdrawn_at = now
    session.commit()


def find_user(session: Session, email: str) -> User:
    users = session.scalars(select(User).where(User.email == email.strip().lower())).all()
    if len(users) != 1:
        raise AccountError("user_not_found" if not users else "user_ambiguous")
    return users[0]


def set_status(session: Session, user_id: int, status: str) -> None:
    session.get(User, user_id).status = status
    session.commit()
    if status != "active":
        end_all_sessions(session, user_id)


def delete_user(session: Session, user_id: int) -> dict[str, int]:
    """Every row the user owns, in one transaction. Backups made earlier still hold copies."""
    from app.models import BodyMetric, ExcelPreview, Exercise, GoalProfile, ImportArchive, Meal, PerfEvent, SleepRecord, SyncState, Workout, WorkoutSet
    session.execute(text("BEGIN IMMEDIATE"))
    try:
        user = session.get(User, user_id)
        if user is None:
            raise AccountError("user_not_found")
        if user.role == "admin":
            raise AccountError("admin_protected")
        counts = {}
        for model in (WorkoutSet, Workout, Exercise, Meal, BodyMetric, SleepRecord, SyncState, ImportArchive, ExcelPreview):
            counts[model.__tablename__] = session.execute(delete(model).where(model.user_id == user_id)).rowcount
        session.execute(delete(Invite).where(Invite.used_by == user_id))
        session.execute(delete(Consent).where(Consent.user_id == user_id))
        session.execute(delete(AuthSession).where(AuthSession.user_id == user_id))
        session.execute(delete(PerfEvent).where(PerfEvent.user_id == user_id))
        session.execute(delete(GoalProfile).where(GoalProfile.user_id == user_id))
        session.delete(user)
        session.commit()
        return counts
    except Exception:
        session.rollback()
        raise


def end_session(session: Session, token: str | None) -> None:
    if token:
        session.execute(delete(AuthSession).where(AuthSession.token_hash == token_hash(token)))
        session.commit()


def end_all_sessions(session: Session, user_id: int) -> None:
    session.execute(delete(AuthSession).where(AuthSession.user_id == user_id))
    session.commit()
