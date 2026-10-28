import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response

from app import config
from app.pages import IMMUTABLE, asset_hash, page
from app.services import perf
from starlette.concurrency import run_in_threadpool
from app.api.assistant import router as assistant_router
from app.api.auth import router as auth_router
from app.api.excel import router as excel_router
from app.api.goals import router as goals_router
from app.api.health import router as health_router
from app.api.invites import router as invites_router
from app.api.perf import router as perf_router
from app.api.presets import router as presets_router
from app.api.workouts import router as workouts_router
from app.api.records import router as records_router
from app.api.statistics import router as statistics_router
from app.services.persistence import RecordConflict, RecordInvalid, RecordNotFound
from sqlalchemy.exc import OperationalError
from app.database import SessionLocal, engine, initialize_database
from app.services.accounts import ensure_owner

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    initialize_database()
    with SessionLocal() as session:
        ensure_owner(session, os.environ.get("FITLOG_OWNER_EMAIL", ""))
    try:
        yield
    finally:
        engine.dispose()


app = FastAPI(title="FitLog", version=config.APP_VERSION, lifespan=lifespan)
app.include_router(auth_router)
app.include_router(assistant_router)
app.include_router(excel_router)
app.include_router(goals_router)
app.include_router(health_router)
app.include_router(invites_router)
app.include_router(perf_router)
app.include_router(presets_router)
app.include_router(workouts_router)
app.include_router(records_router)
app.include_router(statistics_router)


@app.exception_handler(RecordNotFound)
async def not_found(_: Request, error: RecordNotFound) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(error)})


@app.exception_handler(RecordConflict)
async def conflict(_: Request, error: RecordConflict) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": str(error)})


@app.exception_handler(RecordInvalid)
async def invalid(_: Request, error: RecordInvalid) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": str(error)})


@app.exception_handler(OperationalError)
async def database_unavailable(_: Request, error: OperationalError) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": "DB를 사용할 수 없습니다. 잠시 후 다시 시도해 주세요."})


UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
SECURITY_HEADERS = {
    # Everything is served locally: no CDN, inline script/style or external images.
    # form-action also governs redirects after a submit: the invite form posts to
    # /auth/google/start, which redirects to Google's sign-in page.
    "Content-Security-Policy": "default-src 'self'; img-src 'self' data:; object-src 'none'; "
                               "base-uri 'self'; form-action 'self' https://accounts.google.com; frame-ancestors 'none'",
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
    started = time.perf_counter()
    if request.method in UNSAFE_METHODS and cross_origin(request):
        response: Response = JSONResponse(status_code=403, content={"detail": "다른 사이트에서 보낸 요청은 처리할 수 없습니다."})
    else:
        response = await call_next(request)
    if request.url.path.startswith(("/api/", "/auth/")) and "cache-control" not in response.headers:
        response.headers["Cache-Control"] = "no-store"
    # /api/health is polled by the container healthcheck and every page; it would drown the rest.
    if request.url.path.startswith("/api/") and request.url.path != "/api/health":
        # Server time for the speed statistics; the phone subtracts it from what it waited.
        server_ms = (time.perf_counter() - started) * 1000
        response.headers["Server-Timing"] = f"app;dur={server_ms:.1f}"
        route = getattr(request.scope.get("route"), "path_format", None) or perf.template(request.url.path)
        size = response.headers.get("content-length")
        try:
            await run_in_threadpool(perf.record_server, getattr(request.state, "user_id", None), request.method, route,
                                    response.status_code, server_ms, int(size) if size else None)
        except Exception:
            pass  # statistics must never break a request
    elif request.url.path.startswith("/static/"):
        # Pages link assets as ?v=<content hash> (app/pages.py): that exact address never changes,
        # so it is cached for good. Anything else is revalidated every time (cheap 304 via ETag);
        # otherwise browsers reuse a stale script heuristically after an update.
        current = request.query_params.get("v")
        fresh = response.status_code == 200 and current is not None and current == asset_hash(request.url.path)
        response.headers["Cache-Control"] = IMMUTABLE if fresh else "no-cache"
    response.headers.update(SECURITY_HEADERS)
    return response


@app.get("/meals", include_in_schema=False)
def meals_page() -> HTMLResponse:
    return page("meals.html")


@app.get("/body", include_in_schema=False)
def body_page() -> HTMLResponse:
    return page("body.html")


@app.get("/body-metrics", include_in_schema=False)
@app.get("/sleep", include_in_schema=False)
def records_page() -> HTMLResponse:
    return page("records.html")


@app.get("/admin", include_in_schema=False)
def admin_page() -> HTMLResponse:
    return page("admin.html")


@app.get("/settings", include_in_schema=False)
def settings_page() -> HTMLResponse:
    return page("settings.html")


@app.get("/statistics", include_in_schema=False)
def statistics_page() -> HTMLResponse:
    return page("statistics.html")


@app.get("/workouts", include_in_schema=False)
def workouts_page() -> HTMLResponse:
    return page("workouts.html")


@app.get("/", include_in_schema=False)
def index() -> HTMLResponse:
    return page("index.html")


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
