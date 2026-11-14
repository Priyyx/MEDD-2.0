"""Central configuration. All secrets come from environment variables / .env — never from code."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = BACKEND_DIR.parent


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader (KEY=VALUE lines). Existing environment variables win."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


_load_dotenv(BACKEND_DIR / ".env")


def _bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    return default if v is None else v.strip().lower() in {"1", "true", "yes", "on"}


class Settings:
    def __init__(self) -> None:
        self.app_name = "MEDD Maharashtra 2.0"
        self.environment = os.getenv("MEDD_ENV", "development")
        # Read/write connection (ingestion, auth, audit). Must NOT be a superuser in production.
        self.database_url = os.getenv("DATABASE_URL", "postgresql+psycopg://medd_app:change_me@localhost:5432/medd")
        # Read-only connection used by analytics, dashboards and the chatbot.
        self.database_url_readonly = os.getenv("DATABASE_URL_READONLY", self.database_url)
        self.db_pool_size = int(os.getenv("DB_POOL_SIZE", "10"))
        self.db_max_overflow = int(os.getenv("DB_MAX_OVERFLOW", "10"))
        self.statement_timeout_ms = int(os.getenv("DB_STATEMENT_TIMEOUT_MS", "15000"))
        self.chat_statement_timeout_ms = int(os.getenv("CHAT_STATEMENT_TIMEOUT_MS", "5000"))

        self.jwt_secret = os.getenv("JWT_SECRET", "")
        self.jwt_algorithm = "HS256"
        self.jwt_expiry_minutes = int(os.getenv("JWT_EXPIRY_MINUTES", "480"))
        self.auth_enabled = _bool("AUTH_ENABLED", True)
        self.cors_origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()]
        self.force_https = _bool("FORCE_HTTPS", False)

        self.data_dir = Path(os.getenv("MEDD_DATA_DIR", str(BACKEND_DIR / "data"))).resolve()
        self.incoming_dir = self.data_dir / "incoming"
        self.processing_dir = self.data_dir / "processing"
        self.processed_dir = self.data_dir / "processed"
        self.failed_dir = self.data_dir / "failed"
        self.archive_dir = self.data_dir / "archive"
        self.reports_dir = self.data_dir / "reports"
        self.config_dir = BACKEND_DIR / "config"
        self.reference_dir = BACKEND_DIR / "reference"
        self.frontend_dir = Path(os.getenv("MEDD_FRONTEND_DIR", str(PROJECT_DIR / "frontend"))).resolve()

        self.watcher_enabled = _bool("WATCHER_ENABLED", True)
        self.watcher_settle_seconds = float(os.getenv("WATCHER_SETTLE_SECONDS", "3"))
        self.watcher_poll_fallback_seconds = float(os.getenv("WATCHER_POLL_SECONDS", "30"))
        self.max_upload_mb = int(os.getenv("MAX_UPLOAD_MB", "100"))

        self.cache_ttl_seconds = int(os.getenv("CACHE_TTL_SECONDS", "600"))

        # Optional LLM phrasing layer for the Decision Support AI. Deterministic engine is always used for numbers.
        self.llm_enabled = _bool("LLM_ENABLED", False)
        self.anthropic_api_key = os.getenv("ANTHROPIC_API_KEY", "")
        self.llm_model = os.getenv("LLM_MODEL", "claude-sonnet-5-5")
        self.llm_timeout_seconds = float(os.getenv("LLM_TIMEOUT_SECONDS", "20"))

        self.fy_label = os.getenv("MEDD_FY_LABEL", "FY 2025-26")

    def ensure_dirs(self) -> None:
        for p in (self.incoming_dir, self.processing_dir, self.processed_dir, self.failed_dir,
                  self.archive_dir, self.reports_dir):
            p.mkdir(parents=True, exist_ok=True)

    def validate(self) -> list[str]:
        problems = []
        if self.auth_enabled and (not self.jwt_secret or len(self.jwt_secret) < 32):
            problems.append("JWT_SECRET must be set to a random string of at least 32 characters.")
        if self.environment == "production" and not self.auth_enabled:
            problems.append("AUTH_ENABLED cannot be false in production.")
        return problems


@lru_cache
def get_settings() -> Settings:
    return Settings()
