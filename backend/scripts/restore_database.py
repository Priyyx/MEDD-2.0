"""Restore a backup produced by backup_database.py into the `medd` database.

    python scripts/restore_database.py backups/medd_20261112_020000.dump --yes-really
Stop the API first. Uses the superuser (PG_SUPERUSER_URL) to recreate the database, then re-applies grants.
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
from app.config import get_settings  # noqa: E402,F401  (loads .env)
from scripts.backup_database import pg_env  # noqa: E402

import psycopg  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("dump")
ap.add_argument("--yes-really", action="store_true")
a = ap.parse_args()
if not a.yes_really:
    sys.exit("This REPLACES the application database. Re-run with --yes-really.")
from psycopg import sql  # noqa: E402
su = os.environ["PG_SUPERUSER_URL"]
env, db = pg_env(get_settings().database_url)
with psycopg.connect(su, autocommit=True) as cx:
    cx.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=%s AND pid<>pg_backend_pid()", (db,))
    cx.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(db)))
    cx.execute(sql.SQL("CREATE DATABASE {} OWNER medd_app TEMPLATE template0").format(sql.Identifier(db)))
subprocess.run(["pg_restore", "--no-owner", "--role=medd_app", "-d", db, a.dump], env=env, check=True)
with psycopg.connect(su.rsplit("/", 1)[0] + "/" + db, autocommit=True) as cx:
    cx.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
    cx.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO medd_readonly").format(sql.Identifier(db)))
with psycopg.connect(get_settings().database_url.replace("postgresql+psycopg://", "postgresql://"), autocommit=True) as cx:
    cx.execute("""GRANT USAGE ON SCHEMA master_data, equipment_inventory, procurement, financial, maintenance, lifecycle,
                  analytics, metadata TO medd_readonly""")
    cx.execute("""GRANT SELECT ON ALL TABLES IN SCHEMA master_data, equipment_inventory, procurement, financial,
                  maintenance, lifecycle, analytics TO medd_readonly""")
    cx.execute("""GRANT SELECT ON metadata.app_setting, metadata.ingestion_file, metadata.data_refresh,
                  metadata.legacy_baseline, metadata.validation_issue, metadata.dataset_version TO medd_readonly""")
print("restore complete — start the API again")
