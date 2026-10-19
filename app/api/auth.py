from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, clear_session_cookie, cookie_name
from app.database import get_session
from app.services.accounts import end_session

router = APIRouter(tags=["auth"])


@router.get("/api/me")
def me(user: CurrentUser) -> dict:
    return {"id": user.id, "email": user.email, "display_name": user.display_name, "role": user.role}


@router.post("/auth/logout")
def logout(request: Request, response: Response, db: Annotated[Session, Depends(get_session)]) -> dict:
    # Idempotent: an expired or unknown cookie still ends with the cookie cleared.
    end_session(db, request.cookies.get(cookie_name()))
    clear_session_cookie(response)
    return {"status": "logged_out"}
