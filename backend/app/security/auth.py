"""Authentication (scrypt password hashing + JWT) and role-based access control."""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select, text

from app.config import get_settings
from app.db.models import AppUser
from app.db.session import WriteSession

settings = get_settings()

# ------------------------------------------------------------------ roles & permissions
ROLE_PERMISSIONS: dict[str, set[str]] = {
    "admin":        {"dashboard:read", "financial:read", "chat:use", "export:run", "ingestion:read",
                     "ingestion:write", "users:manage", "audit:read", "reconciliation:read"},
    "data_manager": {"dashboard:read", "financial:read", "chat:use", "export:run", "ingestion:read",
                     "ingestion:write", "audit:read", "reconciliation:read"},
    "analyst":      {"dashboard:read", "financial:read", "chat:use", "export:run", "ingestion:read",
                     "reconciliation:read"},
    "viewer":       {"dashboard:read", "chat:use"},   # no budget / unit-cost (sensitive) and no exports
}


@dataclass
class CurrentUser:
    username: str
    role: str
    full_name: Optional[str] = None
    allowed_divisions: Optional[list[str]] = None   # None = all divisions
    permissions: set[str] = field(default_factory=set)

    def can(self, perm: str) -> bool:
        return perm in self.permissions


ANONYMOUS_DEV = CurrentUser("dev-noauth", "admin", "Auth disabled (development)", None, ROLE_PERMISSIONS["admin"])

# ------------------------------------------------------------------ password hashing (stdlib scrypt)
_N, _R, _P = 2 ** 14, 8, 1


def hash_password(password: str) -> str:
    if len(password) < 10:
        raise ValueError("Password must be at least 10 characters.")
    salt = os.urandom(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    return f"scrypt${_N}${_R}${_P}${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt_b64, dk_b64 = stored.split("$")
        if algo != "scrypt":
            return False
        dk = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt_b64), n=int(n), r=int(r), p=int(p),
                            dklen=len(base64.b64decode(dk_b64)))
        return hmac.compare_digest(dk, base64.b64decode(dk_b64))
    except Exception:
        return False


# ------------------------------------------------------------------ JWT
def create_token(user: AppUser) -> tuple[str, int]:
    exp_minutes = settings.jwt_expiry_minutes
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user.username, "role": user.role, "name": user.full_name,
        "div": user.allowed_divisions, "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=exp_minutes)).timestamp()), "jti": secrets.token_hex(8),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm), exp_minutes * 60


def decode_token(token: str) -> CurrentUser:
    try:
        data = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired. Please sign in again.")
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid authentication token.")
    role = data.get("role")
    if role not in ROLE_PERMISSIONS:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unknown role.")
    # Re-check the account is still active (revocation on deactivate)
    with WriteSession() as db:
        u = db.execute(select(AppUser).where(AppUser.username == data["sub"])).scalar_one_or_none()
        if not u or not u.is_active:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account disabled.")
        return CurrentUser(u.username, u.role, u.full_name, u.allowed_divisions, ROLE_PERMISSIONS[u.role])


_bearer = HTTPBearer(auto_error=False)


def get_current_user(request: Request,
                     creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer)) -> CurrentUser:
    if not settings.auth_enabled:
        return ANONYMOUS_DEV
    token = creds.credentials if creds else None
    if not token:
        # EventSource (SSE) cannot send headers; accept token as query parameter for that endpoint only.
        if request.url.path.endswith("/events"):
            token = request.query_params.get("token")
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentication required.",
                            headers={"WWW-Authenticate": "Bearer"})
    return decode_token(token)


def require(*perms: str):
    def _dep(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        missing = [p for p in perms if not user.can(p)]
        if missing:
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Permission denied ({', '.join(missing)}).")
        return user
    return _dep


def authenticate(username: str, password: str) -> AppUser:
    with WriteSession() as db:
        u = db.execute(select(AppUser).where(AppUser.username == username)).scalar_one_or_none()
        now = datetime.now(timezone.utc)
        if u and u.locked_until and u.locked_until > now:
            raise HTTPException(status.HTTP_423_LOCKED, "Account temporarily locked after failed attempts. Try later.")
        if not u or not u.is_active or not verify_password(password, u.password_hash):
            if u:
                u.failed_logins = (u.failed_logins or 0) + 1
                if u.failed_logins >= 5:
                    u.locked_until = now + timedelta(minutes=15)
                    u.failed_logins = 0
                db.commit()
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid username or password.")
        u.failed_logins = 0
        u.locked_until = None
        u.last_login_at = now
        db.commit()
        db.refresh(u)
        db.expunge(u)
        return u


def effective_divisions(user: CurrentUser, requested: Iterable[str]) -> Optional[list[str]]:
    """Intersect requested division filter with the user's data scope. None = no restriction."""
    req = [r for r in requested if r]
    if user.allowed_divisions is None:
        return req or None
    allowed = set(user.allowed_divisions)
    if not req:
        return sorted(allowed)
    return [r for r in req if r in allowed] or ["__none__"]


def write_audit(actor: str, action: str, entity: str | None = None, entity_id: str | None = None,
                details: dict | None = None, client_ip: str | None = None) -> None:
    import json
    try:
        with WriteSession() as db:
            db.execute(text("INSERT INTO audit.audit_log(actor, action, entity, entity_id, details, client_ip) "
                            "VALUES (:a, :ac, :e, :eid, CAST(:d AS jsonb), :ip)"),
                       {"a": actor, "ac": action, "e": entity, "eid": entity_id,
                        "d": json.dumps(details or {}, default=str), "ip": client_ip})
            db.commit()
    except Exception:  # auditing must never break the request
        pass
