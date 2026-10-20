from fastapi import APIRouter, HTTPException, Request
from app.api.deps import AdminUser
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

