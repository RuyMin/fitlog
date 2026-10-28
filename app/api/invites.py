"""Invite links for admins: make one, see recent ones, withdraw one nobody has used.

A link's token is shown once, when it is made; the server keeps only its hash.
"""
from datetime import timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import config
from app.api.deps import AdminUser
from app.database import get_session
from app.models import utc_now
from app.schemas import InputModel, UTCDateTime
from app.services import accounts

router = APIRouter(prefix="/api/admin/invites", tags=["invites"])
DB = Annotated[Session, Depends(get_session)]


class InviteInput(InputModel):
    note: Annotated[str, Field(min_length=1, max_length=100)] | None = None
    days: Annotated[int, Field(ge=1, le=30, strict=True)] = 7


class InviteItem(BaseModel):
    id: int
    note: str | None
    created_at: UTCDateTime
    expires_at: UTCDateTime
    status: Literal["pending", "used", "expired"]
    used_at: UTCDateTime | None
    used_by: str | None


class CreatedInvite(InviteItem):
    url: str


def item(invite, email: str | None) -> dict:
    status = "used" if invite.used_at is not None else "expired" if invite.expires_at <= utc_now() else "pending"
    return {"id": invite.id, "note": invite.note, "created_at": invite.created_at, "expires_at": invite.expires_at,
            "status": status, "used_at": invite.used_at, "used_by": email}


@router.get("", response_model=list[InviteItem])
def recent(db: DB, admin: AdminUser) -> list[dict]:
    return [item(invite, email) for invite, email in accounts.list_invites(db)]


@router.post("", response_model=CreatedInvite, status_code=201)
def create(data: InviteInput, request: Request, db: DB, admin: AdminUser) -> dict:
    token = accounts.create_invite(db, admin.id, data.note, timedelta(days=data.days))
    invite = accounts.usable_invite(db, token)
    origin = config.PUBLIC_ORIGIN or str(request.base_url).rstrip("/")
    return {**item(invite, None), "url": f"{origin}/invite/{token}"}


@router.delete("/{invite_id}", status_code=204)
def revoke(invite_id: int, db: DB, admin: AdminUser) -> None:
    try:
        accounts.revoke_invite(db, invite_id)
    except accounts.AccountError as error:
        if error.code == "invite_not_found":
            raise HTTPException(404, "초대 링크를 찾을 수 없습니다.") from None
        raise HTTPException(409, "이미 사용된 초대 링크는 취소할 수 없습니다.") from None
