"""Database backup (pg_dump custom format) with retention.

    python scripts/backup_database.py                 # -> backend/backups/medd_YYYYmmdd_HHMMSS.dump
    python scripts/backup_database.py --keep 30       # keep the newest 30 dumps
Schedule daily (Windows Task Scheduler / cron). Restore with scripts/restore_database.py.
"""
import argparse
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, urlparse

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
from app.config import get_settings  # noqa: E402


def pg_env(url: str) -> tuple[dict, str]:
    u = urlparse(url.replace("postgresql+psycopg://", "postgresql://"))
    env = {**os.environ, "PGHOST": u.hostname or "localhost", "PGPORT": str(u.port or 5432),
           "PGUSER": unquote(u.username or ""), "PGPASSWORD": unquote(u.password or "")}
    return env, u.path.lstrip("/")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(BACKEND / "backups"))
    ap.add_argument("--keep", type=int, default=14)
    a = ap.parse_args()
    if not shutil.which("pg_dump"):
        sys.exit("pg_dump not found on PATH (install PostgreSQL client tools)")
    env, db = pg_env(get_settings().database_url)
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    f = out / f"medd_{datetime.now():%Y%m%d_%H%M%S}.dump"
    subprocess.run(["pg_dump", "-Fc", "-Z", "6", "--no-owner", "-d", db, "-f", str(f)], env=env, check=True)
    # also archive the ingestion folders' reports (small) alongside
    print(f"backup written: {f} ({f.stat().st_size:,} bytes)")
    dumps = sorted(out.glob("medd_*.dump"))
    for old in dumps[:-a.keep]:
        old.unlink()
        print("pruned", old.name)
    # verify the dump is readable
    subprocess.run(["pg_restore", "--list", str(f)], env=env, check=True, stdout=subprocess.DEVNULL)
    print("backup verified (pg_restore --list OK)")


if __name__ == "__main__":
    main()
