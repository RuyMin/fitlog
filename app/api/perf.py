"""Speed statistics: the phone reports what it waited for; the operator reads the summary."""
from typing import Annotated, Literal

from fastapi import APIRouter, Body, Depends, Query
from pydantic import AwareDatetime, Field
from sqlalchemy.orm import Session

from app.api.deps import AdminUser, CurrentUser
from app.database import get_session
from app.schemas import InputModel
from app.services import perf

router = APIRouter(prefix="/api", tags=["speed statistics"])
DB = Annotated[Session, Depends(get_session)]
Short = Annotated[str, Field(max_length=160)]


class ClientEvent(InputModel):
    """`request`: one API call the phone waited for. `page`: one screen opened (html_ms page ready, total_ms data shown)."""
    kind: Literal["client", "page"]
    at: AwareDatetime
    page: Annotated[str, Field(max_length=60)] | None = None
    route: Short
    method: Annotated[str, Field(max_length=8)] | None = None
    status: Annotated[int, Field(ge=0, le=999)] | None = None
    total_ms: Annotated[float, Field(ge=0, le=600_000)]
    server_ms: Annotated[float, Field(ge=0, le=600_000)] | None = None
    html_ms: Annotated[float, Field(ge=0, le=600_000)] | None = None
    cached: bool | None = None


@router.post("/metrics", status_code=202)
def report(events: Annotated[list[ClientEvent], Body(max_length=300)], db: DB, user: CurrentUser) -> dict:
    return {"stored": perf.record_client(db, user.id, events)}


@router.get("/admin/perf")
def stats(db: DB, admin: AdminUser, days: Annotated[int, Query(ge=1, le=14)] = 1) -> dict:
    return perf.summary(db, days)
