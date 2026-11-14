"""MEDD Maharashtra 2.0 — FastAPI application entry point.

    uvicorn app.main:app --reload            (from the backend/ folder)

Serves the REST API under /api/v1, interactive API docs at /api/docs, and the existing dashboard frontend at /.
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import OperationalError, ProgrammingError

from app.api.v1 import admin, dashboard
from app.config import get_settings
from app.db.session import db_ping
from app.services.analytics import data_status
from app.services.cache import cache
from app.services.events import hub

settings = get_settings()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("medd")


def _on_event(payload: dict) -> None:
    if payload.get("type") == "data_refreshed":
        cache.clear()
        log.info("data refreshed (version %s) — caches invalidated", payload.get("data_version"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    problems = settings.validate()
    if problems:
        for p in problems:
            log.error("CONFIG: %s", p)
        raise RuntimeError("Invalid configuration: " + " ".join(problems))
    settings.ensure_dirs()
    hub.bind_loop(asyncio.get_running_loop())
    hub.on_event(_on_event)
    hub.start_listener()
    if settings.watcher_enabled:
        from app.ingestion.watcher import watcher
        watcher.start()
    log.info("%s started (auth=%s, watcher=%s)", settings.app_name, settings.auth_enabled, settings.watcher_enabled)
    yield
    hub.stop()
    if settings.watcher_enabled:
        from app.ingestion.watcher import watcher
        watcher.stop()


app = FastAPI(title="MEDD Maharashtra 2.0 API", version="2.0.0", lifespan=lifespan,
              docs_url="/api/docs", redoc_url="/api/redoc", openapi_url="/api/openapi.json",
              description="Medical Equipment Decision Support — PostgreSQL-backed analytics. All endpoints except "
                          "/api/health and /api/v1/auth/login require a Bearer token.")

app.add_middleware(GZipMiddleware, minimum_size=1024)  # skips responses that are already Content-Encoding: gzip
if settings.cors_origins:
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=False,
                       allow_methods=["GET", "POST", "PUT"], allow_headers=["Authorization", "Content-Type"])


@app.middleware("http")
async def security_headers(request: Request, call_next):
    if settings.force_https and request.url.scheme == "http" and request.headers.get("x-forwarded-proto", "http") != "https":
        return RedirectResponse(str(request.url.replace(scheme="https")), status_code=308)
    resp = await call_next(request)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    if not request.url.path.startswith("/api/docs") and not request.url.path.startswith("/api/redoc"):
        resp.headers.setdefault("Content-Security-Policy",
                                "default-src 'self'; script-src 'self' 'unsafe-inline'; "
                                "style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; "
                                "frame-ancestors 'self'")
    if settings.force_https:
        resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    if request.url.path.startswith("/api/"):
        resp.headers.setdefault("Cache-Control", "no-store")
    return resp


@app.exception_handler(OperationalError)
async def db_down(_req, exc):
    log.error("database error: %s", exc)
    return JSONResponse({"detail": "Database unavailable or query timed out. Please retry shortly."}, status_code=503)


@app.exception_handler(ProgrammingError)
async def db_prog(_req, exc):
    log.error("database programming error: %s", exc)
    msg = "Analytics views are not initialised — run scripts/setup_database.py." if "has not been populated" in str(exc) \
        else "Database query failed."
    return JSONResponse({"detail": msg}, status_code=500)


@app.get("/api/health", tags=["health"])
def health():
    db = db_ping()
    try:
        st = data_status()
    except Exception:
        st = {}
    ok = all(v == "ok" for v in db.values())
    return JSONResponse({"status": "ok" if ok else "degraded", "database": db, "data_version": st.get("data_version"),
                         "line_items": st.get("line_items"), "last_refresh": st.get("last_refresh"),
                         "cache": cache.stats()}, status_code=200 if ok else 503)


app.include_router(dashboard.router, prefix="/api/v1")
app.include_router(admin.router, prefix="/api/v1")

# ---- existing dashboard frontend (same origin -> no CORS, no credentials in frontend files)
if settings.frontend_dir.exists():
    app.mount("/static", StaticFiles(directory=settings.frontend_dir), name="static")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(settings.frontend_dir / "index.html", headers={"Cache-Control": "no-cache"})
