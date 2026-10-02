from typing import Annotated
from fastapi import APIRouter, HTTPException, Request, Query
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool
from app.services import excel_import
from app.services.google_sheets import SyncError
from app.services.legacy_xlsx import MAX_UPLOAD_BYTES

router=APIRouter(prefix="/api/sync/excel",tags=["excel import"])


def same_site(request: Request):
    if request.headers.get("sec-fetch-site") == "cross-site":
        raise HTTPException(403,"다른 사이트에서는 업로드·저장을 실행할 수 없습니다.")


@router.post("/preview")
async def preview(request: Request, filename: Annotated[str,Query(min_length=1,max_length=200)]):
    same_site(request)
    if not filename.lower().endswith(".xlsx") or "/" in filename or "\\" in filename:
        raise HTTPException(422,".xlsx 파일 이름을 지정해 주세요.")
    if request.headers.get("content-type", "").split(";")[0] != "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet":
        raise HTTPException(415,".xlsx 파일을 업로드해 주세요.")
    chunks=[];size=0
    async for chunk in request.stream():
        size+=len(chunk)
        if size>MAX_UPLOAD_BYTES: raise HTTPException(413,"파일은 5MB 이하이어야 합니다.")
        chunks.append(chunk)
    try:
        return await run_in_threadpool(excel_import.create_preview,b"".join(chunks),filename)
    except SyncError as exc:
        raise HTTPException(exc.code,exc.message) from None


class Selection(BaseModel):
    model_config=ConfigDict(extra="forbid")
    selected: list[str]=Field(max_length=5000)


@router.post("/{token}/commit")
def commit(token: str, data: Selection, request: Request):
    same_site(request)
    try: return excel_import.commit_preview(token,data.selected)
    except SyncError as exc: raise HTTPException(exc.code,exc.message) from None


@router.delete("/{token}")
def discard(token: str, request: Request):
    same_site(request)
    return excel_import.discard_preview(token)


@router.get("/history")
def history():
    return excel_import.history()
