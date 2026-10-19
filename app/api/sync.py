import json
from fastapi import APIRouter, HTTPException, Request, Response
from sqlalchemy import select
from app.api.deps import AdminUser, CurrentUser
from app.database import SessionLocal
from app.models import ImportArchive
from app.services.google_sheets import SyncError
from app.services.sync_service import get_sync_status, sync_google_sheets

router = APIRouter(prefix="/api/sync", tags=["sync"])


@router.get("/status")
def status(user: AdminUser) -> dict:
    return get_sync_status(user.id)


@router.post("/google")
def sync(request: Request, user: AdminUser) -> dict:
    # Browsers must issue a JSON request; cross-origin requests stop at the security middleware.
    if request.headers.get("content-type", "").split(";")[0] != "application/json":
        raise HTTPException(415, "Content-Type: application/json을 사용해 주세요.")
    try:
        return sync_google_sheets(user.id)
    except SyncError as exc:
        raise HTTPException(exc.code, exc.message) from None


@router.get("/archives")
def archives(user: CurrentUser) -> list[dict]:
    with SessionLocal() as session:
        return [{"id": r.id, "filename": r.filename, "sha256": r.sha256, "report": {k: v for k, v in json.loads(r.report).items() if k != "bindings"}}
                for r in session.scalars(select(ImportArchive).where(ImportArchive.user_id == user.id).order_by(ImportArchive.id.desc()))]


@router.get("/archives/{archive_id}")
def archive(archive_id: int, user: CurrentUser) -> dict:
    with SessionLocal() as session:
        r = session.get(ImportArchive, archive_id)
        if r is None or r.user_id != user.id:
            raise HTTPException(404, "원본 자료를 찾을 수 없습니다.")
        return {"filename": r.filename, "sheets": json.loads(r.payload), "report": {k: v for k, v in json.loads(r.report).items() if k != "bindings"}}


@router.get("/archives/{archive_id}/download")
def download_archive(archive_id: int, user: CurrentUser) -> Response:
    from urllib.parse import quote
    with SessionLocal() as session:
        r = session.get(ImportArchive, archive_id)
        if r is None or r.user_id != user.id:
            raise HTTPException(404, "원본 자료를 찾을 수 없습니다.")
        return Response(r.original, media_type="application/json" if r.filename.endswith(".json") else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": "attachment; filename*=UTF-8''" + quote(r.filename)})
