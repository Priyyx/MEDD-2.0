"""Test harness: builds an isolated `medd_test` database (same roles, migrations and reference data as production)
and an isolated data folder. Never touches the `medd` database."""
import os
import shutil
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

# ---- isolate BEFORE the app modules are imported (engines are created at import time)
from app.config import _load_dotenv  # noqa: E402

_load_dotenv(BACKEND / ".env")
_TMP = Path(tempfile.mkdtemp(prefix="medd_test_"))
os.environ["MEDD_DATA_DIR"] = str(_TMP / "data")
os.environ["WATCHER_ENABLED"] = "false"
os.environ["WATCHER_SETTLE_SECONDS"] = "1"
os.environ["AUTH_ENABLED"] = "true"
for k in ("DATABASE_URL", "DATABASE_URL_READONLY"):
    os.environ[k] = os.environ[k].rsplit("/", 1)[0] + "/medd_test"

import psycopg  # noqa: E402
import pytest  # noqa: E402

SU = os.environ["PG_SUPERUSER_URL"]


def _create_test_db():
    with psycopg.connect(SU, autocommit=True) as cx:
        cx.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='medd_test' AND pid<>pg_backend_pid()")
        cx.execute("DROP DATABASE IF EXISTS medd_test")
        cx.execute("CREATE DATABASE medd_test OWNER medd_app TEMPLATE template0")
    with psycopg.connect(SU.rsplit("/", 1)[0] + "/medd_test", autocommit=True) as cx:
        cx.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
        cx.execute("GRANT CONNECT ON DATABASE medd_test TO medd_readonly")


_create_test_db()

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402

_cfg = Config(str(BACKEND / "alembic.ini"))
_cfg.set_main_option("script_location", str(BACKEND / "alembic"))
command.upgrade(_cfg, "head")

from scripts.migrate_legacy_reference import run as _migrate_legacy  # noqa: E402

_migrate_legacy()

from sqlalchemy import text  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db.models import AppUser  # noqa: E402
from app.db.session import write_tx  # noqa: E402
from app.ingestion.pipeline import refresh_analytics  # noqa: E402
from app.security.auth import hash_password  # noqa: E402
from tests.fixtures import make_fixtures  # noqa: E402

get_settings().ensure_dirs()
PASSWORD = "Test-Password-2026"
with write_tx() as db:
    refresh_analytics(db)
    for u, role, divs in (("t_admin", "admin", None), ("t_manager", "data_manager", None), ("t_analyst", "analyst", None),
                          ("t_viewer", "viewer", None), ("t_pune", "analyst", ["Pune"])):
        db.add(AppUser(username=u, full_name=u, role=role, allowed_divisions=divs, password_hash=hash_password(PASSWORD)))

FIX = _TMP / "fixtures"
FIX.mkdir()


@pytest.fixture(scope="session")
def fixtures_dir():
    return FIX


@pytest.fixture(scope="session")
def settings():
    return get_settings()


def reset_production():
    """Empty line items + ingestion bookkeeping (reference/master data kept), refresh analytics."""
    with write_tx() as db:
        db.execute(text("TRUNCATE equipment_inventory.line_item, metadata.ingestion_file, audit.line_item_history, "
                        "metadata.data_refresh, metadata.dataset_version RESTART IDENTITY CASCADE"))
        db.execute(text("UPDATE metadata.app_setting SET value='0'::jsonb WHERE key='data_version'"))
        refresh_analytics(db)
    s = get_settings()
    for d in (s.incoming_dir, s.processing_dir, s.processed_dir, s.failed_dir, s.archive_dir, s.reports_dir):
        shutil.rmtree(d, ignore_errors=True)
        d.mkdir(parents=True, exist_ok=True)
    from app.services.cache import cache
    cache.clear()


@pytest.fixture
def clean_db():
    reset_production()
    yield


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as c:
        yield c


def login(client, user):
    r = client.post("/api/v1/auth/login", json={"username": user, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["access_token"]}


@pytest.fixture(scope="session")
def admin_h(client):
    return login(client, "t_admin")


def copy_to_tmp(p: Path) -> Path:
    d = Path(tempfile.mkdtemp())
    shutil.copy2(p, d / p.name)
    return d / p.name


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(_TMP, ignore_errors=True)
