"""Auth, ingestion management, chatbot, live events, audit, users and reconciliation endpoints."""
from __future__ import annotations

import asyncio
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Literal, Optional

from fastapi import APIRouter, Body, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, text

from app.config import get_settings
from app.db.models import AppUser
from app.db.session import read_engine, write_tx, WriteSession
from app.ingestion.pipeline import FatalIngestionError, revert_file
from app.ingestion.watcher import watcher
from app.security.auth import (ROLE_PERMISSIONS, CurrentUser, authenticate, create_token, get_current_user,
                               hash_password, require, verify_password, write_audit)
from app.services.analytics import Analytics, Filters, data_status
from app.services.chatbot import ask
from app.services.events import hub

router = APIRouter()
settings = get_settings()


# ============================================================================ auth
class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=200)


@router.post("/auth/login", tags=["auth"], summary="Sign in; returns a JWT bearer token")
def login(body: LoginIn, request: Request):
    ip = request.client.host if request.client else None
    try:
        u = authenticate(body.username.strip(), body.password)
    except HTTPException:
        write_audit(body.username, "LOGIN_FAILED", "user", body.username, {}, ip)
        raise
    token, ttl = create_token(u)
    write_audit(u.username, "LOGIN", "user", u.username, {}, ip)
    return {"access_token": token, "token_type": "bearer", "expires_in": ttl,
            "user": {"username": u.username, "full_name": u.full_name, "role": u.role,
                     "allowed_divisions": u.allowed_divisions, "permissions": sorted(ROLE_PERMISSIONS[u.role])}}


@router.get("/auth/config", tags=["auth"], summary="Public: whether sign-in is required")
def auth_config():
    return {"auth_enabled": settings.auth_enabled, "app": settings.app_name}


@router.get("/auth/me", tags=["auth"])
def me(user: CurrentUser = Depends(get_current_user)):
    return {"username": user.username, "full_name": user.full_name, "role": user.role,
            "allowed_divisions": user.allowed_divisions, "permissions": sorted(user.permissions),
            "auth_enabled": settings.auth_enabled}


class PwIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=10, max_length=200)


@router.post("/auth/change-password", tags=["auth"])
def change_password(body: PwIn, user: CurrentUser = Depends(get_current_user)):
    with write_tx() as db:
        u = db.execute(select(AppUser).where(AppUser.username == user.username)).scalar_one_or_none()
        if not u or not verify_password(body.current_password, u.password_hash):
            raise HTTPException(400, "Current password is incorrect.")
        u.password_hash = hash_password(body.new_password)
    write_audit(user.username, "PASSWORD_CHANGED", "user", user.username)
    return {"ok": True}


# ============================================================================ users (admin)
class UserIn(BaseModel):
    username: str = Field(min_length=3, max_length=60, pattern=r"^[A-Za-z0-9_.@-]+$")
    full_name: Optional[str] = None
    password: Optional[str] = Field(default=None, min_length=10)
    role: Literal["admin", "data_manager", "analyst", "viewer"] = "viewer"
    allowed_divisions: Optional[list[str]] = None
    is_active: bool = True


@router.get("/admin/users", tags=["admin"])
def list_users(user: CurrentUser = Depends(require("users:manage"))):
    with WriteSession() as db:
        return [{"username": u.username, "full_name": u.full_name, "role": u.role, "allowed_divisions": u.allowed_divisions,
                 "is_active": u.is_active, "last_login_at": u.last_login_at}
                for u in db.execute(select(AppUser).order_by(AppUser.username)).scalars()]


@router.put("/admin/users", tags=["admin"], summary="Create or update a user")
def upsert_user(body: UserIn, user: CurrentUser = Depends(require("users:manage"))):
    with write_tx() as db:
        u = db.execute(select(AppUser).where(AppUser.username == body.username)).scalar_one_or_none()
        if u is None:
            if not body.password:
                raise HTTPException(400, "password is required for a new user")
            u = AppUser(username=body.username, password_hash=hash_password(body.password), role=body.role)
            db.add(u)
        if body.password and u.id:
            u.password_hash = hash_password(body.password)
        u.full_name, u.role, u.allowed_divisions, u.is_active = body.full_name, body.role, body.allowed_divisions, body.is_active
    write_audit(user.username, "USER_UPSERT", "user", body.username, body.model_dump(exclude={"password"}))
    return {"ok": True}


# ============================================================================ chatbot
class ChatIn(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    filters: dict = Field(default_factory=dict)


@router.post("/chat", tags=["decision-support-ai"], summary="Ask the database-grounded Decision Support AI")
def chat(body: ChatIn, request: Request, user: CurrentUser = Depends(require("chat:use"))):
    fl = body.filters or {}

    def L(k):
        v = fl.get(k) or []
        return [str(x) for x in v][:200] if isinstance(v, list) else [str(v)]
    f = Filters(division=L("division"), institute=L("institute"), department=L("department"), subcat=L("subcat"),
                equipment=L("equipment"), bedded=[int(b) for b in L("bedded") if b.isdigit()])
    f.apply_user_scope(user)
    res = ask(user, body.question, f)
    write_audit(user.username, "CHAT_QUERY", "chat", None, {"q": body.question[:200], "intent": res.get("intent")},
                request.client.host if request.client else None)
    return res


# ============================================================================ live events (SSE)
@router.get("/events", tags=["realtime"], summary="Server-Sent Events: data_refreshed / ingestion_failed")
async def events(request: Request, user: CurrentUser = Depends(require("dashboard:read"))):
    q = hub.subscribe()

    async def gen():
        try:
            yield f"event: hello\ndata: {json.dumps(data_status(), default=str)}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=20)
                    yield f"event: {msg.get('type', 'message')}\ndata: {json.dumps(msg, default=str)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            hub.unsubscribe(q)
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ============================================================================ ingestion
def _rows(sql: str, p: dict | None = None) -> list[dict]:
    with read_engine.connect() as c:
        return [dict(r._mapping) for r in c.execute(text(sql), p or {})]


@router.get("/ingestion/files", tags=["ingestion"], summary="Ingestion history")
def ingestion_files(limit: int = Query(50, ge=1, le=500), user: CurrentUser = Depends(require("ingestion:read"))):
    return _rows("""SELECT id, original_name, status, sha256, size_bytes, dataset_types, sync_mode, rows_read, rows_valid,
                    rows_rejected, rows_inserted, rows_updated, rows_unchanged, rows_deactivated, warnings, errors,
                    error_message, triggered_by, received_at, finished_at FROM metadata.ingestion_file
                    ORDER BY id DESC LIMIT :l""", {"l": limit})


@router.get("/ingestion/files/{file_id}", tags=["ingestion"], summary="One ingestion with issue summary + issues page")
def ingestion_file(file_id: int, severity: Optional[Literal["ERROR", "WARNING", "INFO"]] = None,
                   page: int = Query(0, ge=0), per: int = Query(100, ge=1, le=1000),
                   user: CurrentUser = Depends(require("ingestion:read"))):
    f = _rows("SELECT * FROM metadata.ingestion_file WHERE id=:i", {"i": file_id})
    if not f:
        raise HTTPException(404, "not found")
    sheets = _rows("SELECT sheet_name, dataset_type, header_row, column_map, unmapped_columns, rows_read "
                   "FROM metadata.ingestion_sheet WHERE file_id=:i", {"i": file_id})
    summary = _rows("SELECT severity, code, count(*) n FROM metadata.validation_issue WHERE file_id=:i "
                    "GROUP BY severity, code ORDER BY severity, n DESC", {"i": file_id})
    issues = _rows("""SELECT severity, code, sheet_name, row_no, field, value, message FROM metadata.validation_issue
                      WHERE file_id=:i AND (CAST(:s AS text) IS NULL OR severity=:s) ORDER BY id LIMIT :l OFFSET :o""",
                   {"i": file_id, "s": severity, "l": per, "o": page * per})
    return {"file": f[0], "sheets": sheets, "issue_summary": summary, "issues": issues, "page": page, "per": per}


@router.get("/ingestion/files/{file_id}/report", tags=["ingestion"], response_class=PlainTextResponse,
            summary="Markdown ingestion & validation report")
def ingestion_report(file_id: int, user: CurrentUser = Depends(require("ingestion:read"))):
    r = _rows("SELECT report_path FROM metadata.ingestion_file WHERE id=:i", {"i": file_id})
    if not r or not r[0]["report_path"]:
        raise HTTPException(404, "no report")
    p = Path(r[0]["report_path"]).resolve()
    if settings.reports_dir.resolve() not in p.parents or not p.exists():
        raise HTTPException(404, "report missing")
    return p.read_text(encoding="utf-8")


@router.post("/ingestion/upload", tags=["ingestion"], summary="Upload a workbook into the incoming folder")
async def upload(file: UploadFile = File(...), request: Request = None,
                 user: CurrentUser = Depends(require("ingestion:write"))):
    name = Path(file.filename or "upload").name
    ext = Path(name).suffix.lower()
    if ext not in (".xlsx", ".xlsm", ".xls", ".csv", ".json"):
        raise HTTPException(400, "Only .xlsx, .xlsm, .xls, .csv or .json files are accepted.")
    safe = "".join(ch if ch.isalnum() or ch in "._- ()" else "_" for ch in name)[:150]
    tmp = settings.incoming_dir / f".upload_{datetime.now():%Y%m%d%H%M%S}_{safe}.part"
    size, limit = 0, settings.max_upload_mb * 1024 * 1024
    with open(tmp, "wb") as out:
        while chunk := await file.read(1 << 20):
            size += len(chunk)
            if size > limit:
                out.close()
                tmp.unlink(missing_ok=True)
                raise HTTPException(413, f"File larger than {settings.max_upload_mb} MB.")
            out.write(chunk)
    dest = settings.incoming_dir / safe
    n = 1
    while dest.exists():
        dest = settings.incoming_dir / f"{Path(safe).stem}__{n}{ext}"
        n += 1
    shutil.move(str(tmp), dest)  # atomic rename -> watcher picks it up
    write_audit(user.username, "FILE_UPLOADED", "ingestion", dest.name, {"bytes": size},
                request.client.host if request and request.client else None)
    return {"ok": True, "stored_as": dest.name, "bytes": size,
            "message": "File placed in the incoming folder; it will be detected and processed automatically."}


@router.post("/ingestion/rescan", tags=["ingestion"], summary="Queue any files already sitting in incoming/")
def rescan(user: CurrentUser = Depends(require("ingestion:write"))):
    return {"queued": watcher.scan_existing()}


@router.get("/ingestion/watcher", tags=["ingestion"])
def watcher_status(user: CurrentUser = Depends(require("ingestion:read"))):
    st = watcher.status()
    st["enabled"] = settings.watcher_enabled
    st["incoming_files"] = sorted(p.name for p in settings.incoming_dir.iterdir() if p.is_file())
    return st


@router.post("/ingestion/files/{file_id}/rollback", tags=["ingestion"],
             summary="Revert the most recent successful ingestion (uses audit history)")
def rollback(file_id: int, user: CurrentUser = Depends(require("ingestion:write"))):
    try:
        return revert_file(file_id, user.username)
    except FatalIngestionError as exc:
        raise HTTPException(409, str(exc))


# ============================================================================ audit + reconciliation
@router.get("/admin/audit", tags=["admin"])
def audit(limit: int = Query(200, ge=1, le=2000), action: Optional[str] = None,
          user: CurrentUser = Depends(require("audit:read"))):
    with WriteSession() as db:
        return [dict(r._mapping) for r in db.execute(text(
            """SELECT id, occurred_at, actor, action, entity, entity_id, details, client_ip FROM audit.audit_log
               WHERE (CAST(:a AS text) IS NULL OR action = :a) ORDER BY id DESC LIMIT :l"""), {"a": action, "l": limit})]


@router.get("/reconciliation", tags=["reconciliation"],
            summary="Compare live PostgreSQL KPIs with MEDD 1.0 dashboard figures (division/institute/department/overview)")
def reconciliation(level: Literal["overview", "division", "institute", "department", "equipment"] = "division",
                   only_differences: bool = False, user: CurrentUser = Depends(require("reconciliation:read"))):
    A = Analytics(user)
    base = {r["name"]: r["metrics"] for r in _rows("SELECT name, metrics FROM metadata.legacy_baseline WHERE level=:l",
                                                    {"l": level})}
    if level == "overview":
        live = {"Maharashtra": A.summary(Filters())}
    else:
        live = {r["name"]: r for r in A.breakdown(Filters(), level)}
    keys = ["required", "available", "functional", "non_functional", "procurement", "net_requirement", "budget",
            "amc", "condemnation", "end_of_life", "gap_pct"]
    out = []
    for name in sorted(set(base) | set(live)):
        b, l_ = base.get(name, {}), live.get(name, {})
        diffs = {k: {"legacy": b.get(k), "live": l_.get(k),
                     "diff": None if b.get(k) is None or l_.get(k) is None else round(float(l_[k]) - float(b[k]), 2)}
                 for k in keys}
        match = all(d["diff"] is not None and abs(d["diff"]) < 0.5 for d in diffs.values())
        if only_differences and match:
            continue
        out.append({"name": name, "in_legacy": name in base, "in_live": name in live, "match": match, "metrics": diffs})
    return {"level": level, "rows": out, "matched": sum(r["match"] for r in out), "total": len(out),
            "note": "Legacy = figures embedded in the MEDD 1.0 index.html; live = current PostgreSQL data."}
