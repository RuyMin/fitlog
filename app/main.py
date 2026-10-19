from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response

from app import config
from app.api.auth import router as auth_router
from app.api.excel import router as excel_router
from app.api.sync import router as sync_router
from app.api.health import router as health_router
from app.api.workouts import router as workouts_router
from app.api.records import router as records_router
from app.api.statistics import router as statistics_router
from app.services.persistence import RecordConflict, RecordNotFound
from sqlalchemy.exc import OperationalError
from app.database import engine, initialize_database

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    initialize_database()
    try:
        yield
    finally:
        engine.dispose()


app = FastAPI(title="FitLog", version="0.6.0", lifespan=lifespan)
app.include_router(auth_router)
app.include_router(excel_router)
app.include_router(sync_router)
app.include_router(health_router)
app.include_router(workouts_router)
app.include_router(records_router)
app.include_router(statistics_router)


@app.exception_handler(RecordNotFound)
async def not_found(_: Request, error: RecordNotFound) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(error)})


@app.exception_handler(RecordConflict)
async def conflict(_: Request, error: RecordConflict) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": str(error)})


@app.exception_handler(OperationalError)
async def database_unavailable(_: Request, error: OperationalError) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": "DB를 사용할 수 없습니다. 잠시 후 다시 시도해 주세요."})


UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
SECURITY_HEADERS = {
    # Everything is served locally: no CDN, inline script/style or external images.
    "Content-Security-Policy": "default-src 'self'; img-src 'self' data:; object-src 'none'; "
                               "base-uri 'self'; form-action 'self'; frame-ancestors 'none'",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
}


def cross_origin(request: Request) -> bool:
    """CSRF guard for cookie sessions, on top of SameSite=Lax."""
    if request.headers.get("sec-fetch-site") in {"cross-site", "same-site"}:
        return True
    origin = request.headers.get("origin")
    expected = config.PUBLIC_ORIGIN or f"{request.url.scheme}://{request.url.netloc}".lower()
    return origin is not None and origin.lower() != expected


@app.middleware("http")
async def security_policy(request: Request, call_next: RequestResponseEndpoint) -> Response:
    if request.method in UNSAFE_METHODS and cross_origin(request):
        response: Response = JSONResponse(status_code=403, content={"detail": "다른 사이트에서 보낸 요청은 처리할 수 없습니다."})
    else:
        response = await call_next(request)
    if request.url.path.startswith(("/api/", "/auth/")):
        response.headers["Cache-Control"] = "no-store"
    response.headers.update(SECURITY_HEADERS)
    return response


@app.get("/meals", include_in_schema=False)
@app.get("/body-metrics", include_in_schema=False)
@app.get("/sleep", include_in_schema=False)
def records_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "records.html", headers={"Cache-Control": "no-cache"})


@app.get("/settings", include_in_schema=False)
def settings_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "settings.html", headers={"Cache-Control": "no-cache"})


@app.get("/statistics", include_in_schema=False)
def statistics_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "statistics.html", headers={"Cache-Control": "no-cache"})


@app.get("/workouts", include_in_schema=False)
def workouts_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "workouts.html", headers={"Cache-Control": "no-cache"})


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/manifest.json", include_in_schema=False)
def manifest() -> FileResponse:
    return FileResponse(STATIC_DIR / "manifest.json", media_type="application/manifest+json")


@app.get("/service-worker.js", include_in_schema=False)
def service_worker() -> FileResponse:
    return FileResponse(
        STATIC_DIR / "service-worker.js",
        media_type="application/javascript",
        headers={"Cache-Control": "no-cache"},
    )


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
