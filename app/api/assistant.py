from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.api.deps import AdminUser, CurrentUser
from app.assistant_schemas import CommitRequest, DraftRequest, KeyInput, StatusResponse
from app.database import get_session
from app.services import assistant
from app.services.claude_records import AssistantError

router = APIRouter(prefix="/api/assistant", tags=["assistant"])
DB = Annotated[Session, Depends(get_session)]


def fail(error: AssistantError) -> HTTPException:
    # The code is mapped to a message by the page; no upstream detail is echoed.
    return HTTPException(error.status, {"code": error.code})


@router.get("/status", response_model=StatusResponse)
def status(user: CurrentUser, db: DB) -> dict:
    return assistant.status(db, user)


@router.put("/key")
async def save_key(data: KeyInput, user: AdminUser, db: DB) -> dict:
    try:
        hint = await run_in_threadpool(assistant.save_key, db, user.id, data.api_key)
    except AssistantError as error:
        raise fail(error) from None
    return {"key_hint": hint}


@router.delete("/key")
def delete_key(user: AdminUser, db: DB) -> dict:
    assistant.delete_key(db)
    return {"status": "deleted"}


@router.post("/draft")
async def draft(data: DraftRequest, user: CurrentUser, db: DB) -> dict:
    try:
        return await run_in_threadpool(assistant.draft, db, user.id, data.text, data.timezone)
    except AssistantError as error:
        raise fail(error) from None


@router.post("/commit", status_code=201)
def commit(data: CommitRequest, user: CurrentUser, db: DB) -> dict:
    if not (data.meals or data.body_metrics or data.sleep or data.workouts):
        raise HTTPException(422, "저장할 기록을 하나 이상 선택해 주세요.")
    return assistant.save(db, user.id, data)
