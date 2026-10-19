"""Request identity shared by every private router: a server-side session cookie."""
from typing import Annotated

from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app import config
from app.database import get_session
from app.models import User
from app.services.accounts import ABSOLUTE, resolve_session


def cookie_name() -> str:
    # __Host- binds the cookie to this exact origin over HTTPS (no Domain, Path=/).
    return "fitlog_session" if config.INSECURE_COOKIES else "__Host-fitlog_session"


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        cookie_name(), token, max_age=int(ABSOLUTE.total_seconds()), path="/",
        secure=not config.INSECURE_COOKIES, httponly=True, samesite="lax",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(cookie_name(), path="/", secure=not config.INSECURE_COOKIES, httponly=True, samesite="lax")


def current_user(request: Request, db: Annotated[Session, Depends(get_session)]) -> User:
    user = resolve_session(db, request.cookies.get(cookie_name()))
    if user is None:
        raise HTTPException(401, "로그인이 필요합니다.")
    return user


CurrentUser = Annotated[User, Depends(current_user)]


def admin_user(user: CurrentUser) -> User:
    if user.role != "admin":
        raise HTTPException(403, "관리자만 사용할 수 있습니다.")
    return user


AdminUser = Annotated[User, Depends(admin_user)]
