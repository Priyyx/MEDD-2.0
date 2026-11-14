"""One-command database setup for MEDD Maharashtra 2.0.

    python scripts/setup_database.py            # create roles + DB, migrate, load reference data, create admin
    python scripts/setup_database.py --reset --yes-really   # DROP and rebuild the database (development only)

Steps (all idempotent):
  1. Create PostgreSQL roles  medd_app (read/write) and medd_readonly (SELECT only) using passwords from .env
  2. Create database `medd` owned by medd_app
  3. Run Alembic migrations (schemas, tables, constraints, indexes, materialized views, grants)
  4. Migrate MEDD 1.0 reference/master data + reconciliation baseline (scripts/migrate_legacy_reference.py)
  5. Create the initial administrator account from MEDD_ADMIN_USERNAME / MEDD_ADMIN_PASSWORD
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from app.config import get_settings  # noqa: E402  (loads .env)

import psycopg  # noqa: E402
from psycopg import sql  # noqa: E402


def _need(name: str) -> str:
    v = os.getenv(name)
    if not v or "change_me" in v:
        sys.exit(f"ERROR: set {name} in backend/.env (see .env.example)")
    return v


def _dbname() -> str:
    from urllib.parse import urlparse
    return urlparse(get_settings().database_url.replace("postgresql+psycopg://", "postgresql://")).path.lstrip("/") or "medd"


def create_roles_and_db(reset: bool) -> None:
    su_url = _need("PG_SUPERUSER_URL")
    dbn = _dbname()
    app_pw, ro_pw = _need("MEDD_APP_PASSWORD"), _need("MEDD_READONLY_PASSWORD")
    with psycopg.connect(su_url, autocommit=True) as cx:
        if reset:
            print(f"  ! dropping database {dbn}")
            cx.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=%s AND pid<>pg_backend_pid()", (dbn,))
            cx.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(dbn)))
        for role, pw in (("medd_app", app_pw), ("medd_readonly", ro_pw)):
            exists = cx.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (role,)).fetchone()
            verb = "ALTER" if exists else "CREATE"
            cx.execute(sql.SQL(verb + " ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD {}")
                       .format(sql.Identifier(role), sql.Literal(pw)))
            print(f"  ✓ role {role} {'updated' if exists else 'created'}")
        cx.execute("ALTER ROLE medd_readonly SET default_transaction_read_only = on")
        if not cx.execute("SELECT 1 FROM pg_database WHERE datname=%s", (dbn,)).fetchone():
            cx.execute(sql.SQL("CREATE DATABASE {} OWNER medd_app ENCODING 'UTF8' TEMPLATE template0").format(sql.Identifier(dbn)))
            print(f"  ✓ database {dbn} created")
        else:
            print(f"  ✓ database {dbn} exists")
    db_url = su_url.rsplit("/", 1)[0] + "/" + dbn
    with psycopg.connect(db_url, autocommit=True) as cx:
        cx.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
        for stmt in ("GRANT CONNECT ON DATABASE {} TO medd_readonly", "REVOKE CONNECT ON DATABASE {} FROM PUBLIC",
                     "GRANT CONNECT ON DATABASE {} TO medd_app"):
            cx.execute(sql.SQL(stmt).format(sql.Identifier(dbn)))


def run_migrations() -> None:
    from alembic import command
    from alembic.config import Config
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    command.upgrade(cfg, "head")
    print("  ✓ alembic migrations at head")


def create_admin() -> None:
    from sqlalchemy import select
    from app.db.models import AppUser
    from app.db.session import write_tx
    from app.security.auth import hash_password
    username = os.getenv("MEDD_ADMIN_USERNAME", "admin")
    password = _need("MEDD_ADMIN_PASSWORD")
    with write_tx() as db:
        if db.execute(select(AppUser).where(AppUser.username == username)).scalar_one_or_none():
            print(f"  ✓ admin user '{username}' exists")
            return
        db.add(AppUser(username=username, full_name="MEDD Administrator", role="admin",
                       password_hash=hash_password(password), is_active=True))
    print(f"  ✓ admin user '{username}' created (change the password after first login)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true", help="drop and recreate the database (DEV ONLY)")
    ap.add_argument("--yes-really", action="store_true")
    ap.add_argument("--skip-legacy", action="store_true", help="do not import MEDD 1.0 reference data")
    a = ap.parse_args()
    if a.reset and not a.yes_really:
        sys.exit("Refusing to --reset without --yes-really")
    s = get_settings()
    s.ensure_dirs()
    print("1/4 roles & database"); create_roles_and_db(a.reset)
    print("2/4 migrations"); run_migrations()
    if not a.skip_legacy:
        print("3/4 MEDD 1.0 reference data + reconciliation baseline")
        from scripts.migrate_legacy_reference import run as migrate_legacy
        migrate_legacy()
    print("4/4 administrator"); create_admin()
    from app.db.session import write_tx
    from app.ingestion.pipeline import refresh_analytics
    with write_tx() as db:   # make analytics queryable even before the first workbook arrives
        refresh_analytics(db)
    print("\nDatabase ready. Next: start the API (see README) and drop the master Excel into", s.incoming_dir)


if __name__ == "__main__":
    main()
