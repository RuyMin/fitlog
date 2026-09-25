import json
from fastapi import APIRouter, HTTPException, Request, Response
from sqlalchemy import select
from app.database import SessionLocal
from app.models import ImportArchive
from app.services.google_sheets import SyncError
from app.services.sync_service import get_sync_status, sync_google_sheets

router = APIRouter(prefix="/api/sync", tags=["sync"])


@router.get("/status")
def status() -> dict:
    return get_sync_status()


@router.post("/google")
def sync(request: Request) -> dict:
    # Browsers must issue a JSON request; cross-origin form posts cannot trigger sync.
    if request.headers.get("content-type", "").split(";")[0] != "application/json":
        raise HTTPException(415, "Content-Type: application/json을 사용해 주세요.")
    if request.headers.get("sec-fetch-site") == "cross-site":
        raise HTTPException(403, "다른 사이트에서는 동기화를 실행할 수 없습니다.")
    try:
        return sync_google_sheets()
    except SyncError as exc:
        raise HTTPException(exc.code, exc.message) from None


@router.get("/archives")
def archives() -> list[dict]:
    with SessionLocal() as session:
        return [{"id": r.id, "filename": r.filename, "sha256": r.sha256, "report": json.loads(r.report)}
                for r in session.scalars(select(ImportArchive).order_by(ImportArchive.id.desc()))]


@router.get("/archives/{archive_id}")
def archive(archive_id: int) -> dict:
    with SessionLocal() as session:
        r = session.get(ImportArchive, archive_id)
        if r is None:
            raise HTTPException(404, "원본 자료를 찾을 수 없습니다.")
        return {"filename": r.filename, "sheets": json.loads(r.payload), "report": json.loads(r.report)}


@router.get("/archives/{archive_id}/download")
def download_archive(archive_id: int) -> Response:
    from urllib.parse import quote
    with SessionLocal() as session:
        r = session.get(ImportArchive, archive_id)
        if r is None:
            raise HTTPException(404, "원본 자료를 찾을 수 없습니다.")
        return Response(r.original, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": "attachment; filename*=UTF-8''" + quote(r.filename)})
