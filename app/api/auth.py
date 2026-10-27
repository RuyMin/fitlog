import hmac
import time
from collections import defaultdict, deque
from datetime import timezone
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.pages import page
from app.api.deps import (
    CurrentUser, clear_oauth_cookie, clear_session_cookie, cookie_name, oauth_cookie_name, set_oauth_cookie,
    set_session_cookie,
)
from app.auth import google
from app.config import APP_VERSION
from app.database import get_session
from app.services import accounts

router = APIRouter(tags=["auth"])
DB = Annotated[Session, Depends(get_session)]
# Per client address, in process: one Uvicorn worker serves the whole app.
RATE_WINDOW, RATE_LIMIT = 60.0, 20
_hits: dict[str, deque[float]] = defaultdict(deque)


def rate_limited(request: Request) -> bool:
    now = time.monotonic()
    hits = _hits[request.client.host if request.client else "unknown"]
    while hits and hits[0] <= now - RATE_WINDOW:
        hits.popleft()
    hits.append(now)
    return len(hits) > RATE_LIMIT


def safe_next(value: str | None) -> str | None:
    """Same-origin absolute paths only; anything else returns to the home page."""
    if not value or len(value) > 200 or not value.startswith("/") or value.startswith(("//", "/\\")):
        return None
    if any(ch in value for ch in "\\\r\n\t") or ":" in value.split("?", 1)[0]:
        return None
    return value


def to_login(error: str) -> RedirectResponse:
    response = RedirectResponse("/login?error=" + error, status_code=303)
    clear_oauth_cookie(response)
    return response


@router.get("/login", include_in_schema=False)
def login_page() -> HTMLResponse:
    return page("login.html", "no-store")


@router.get("/invite/{token}", include_in_schema=False)
def invite_page(token: str) -> HTMLResponse:
    # The token is only checked on submit; the page itself reveals nothing.
    return page("invite.html", "no-store")


@router.get("/auth/google/start", include_in_schema=False)
def google_start(request: Request, db: DB, invite: str | None = None, consent_service: bool = False,
                 consent_ai: bool = False, next: str | None = None) -> Response:
    if rate_limited(request):
        return to_login("rate_limited")
    settings = google.GoogleSettings.from_env()
    if not settings.configured():
        return to_login("not_configured")
    try:
        state, verifier, nonce = accounts.start_attempt(db, invite, safe_next(next), consent_service, consent_ai)
    except accounts.AccountError as error:
        return to_login(error.code)
    response = RedirectResponse(google.authorization_url(settings, state, verifier, nonce), status_code=303)
    set_oauth_cookie(response, state)
    return response


@router.get("/auth/google/callback", include_in_schema=False)
def google_callback(request: Request, db: DB, state: str = "", code: str = "", error: str = "") -> Response:
    if rate_limited(request):
        return to_login("rate_limited")
    bound = request.cookies.get(oauth_cookie_name(), "")
    if not state or not bound or not hmac.compare_digest(state.encode(), bound.encode()):
        return to_login("state")
    try:
        attempt = accounts.take_attempt(db, state)
        if error or not code:
            return to_login("cancelled")
        settings = google.GoogleSettings.from_env()
        if not settings.configured():
            return to_login("not_configured")
        identity = google.fetch_identity(settings, code, attempt.verifier, attempt.nonce)
        user = accounts.sign_in(db, identity, attempt)
    except accounts.AccountError as failure:
        return to_login(failure.code)
    except google.GoogleLoginError:
        return to_login("google")
    token, _ = accounts.create_session(db, user.id)
    response = RedirectResponse(attempt.next_path or "/", status_code=303)
    clear_oauth_cookie(response)
    set_session_cookie(response, token)
    return response


@router.get("/api/me")
def me(user: CurrentUser) -> dict:
    # The version rides along so pages need no separate /api/health call to show it.
    return {"id": user.id, "email": user.email, "display_name": user.display_name, "role": user.role, "version": APP_VERSION}


def utc_iso(value):
    return None if value is None else value.replace(tzinfo=timezone.utc).isoformat()


@router.get("/api/me/consents")
def consents(user: CurrentUser, db: DB) -> dict:
    status = accounts.consent_status(db, user.id)
    return {"current_versions": accounts.CONSENT_VERSIONS, **{
        kind: None if entry is None else {**entry, "granted_at": utc_iso(entry["granted_at"]), "withdrawn_at": utc_iso(entry["withdrawn_at"])}
        for kind, entry in status.items()
    }}


@router.post("/api/me/consents/ai_transfer")
def grant_ai(user: CurrentUser, db: DB) -> dict:
    accounts.grant_ai_consent(db, user.id)
    return consents(user, db)


@router.delete("/api/me/consents/ai_transfer")
def withdraw_ai(user: CurrentUser, db: DB) -> dict:
    accounts.withdraw_ai_consent(db, user.id)
    return consents(user, db)


@router.post("/auth/logout")
def logout(request: Request, response: Response, db: DB) -> dict:
    # Idempotent: an expired or unknown cookie still ends with the cookie cleared.
    accounts.end_session(db, request.cookies.get(cookie_name()))
    clear_session_cookie(response)
    return {"status": "logged_out"}
