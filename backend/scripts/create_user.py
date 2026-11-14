"""Create or update a dashboard user.

    python scripts/create_user.py <username> <role> [--divisions "Pune,Konkan"] [--name "Full Name"]
roles: admin | data_manager | analyst | viewer   (password is prompted, min 10 chars)
"""
import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sqlalchemy import select  # noqa: E402

from app.db.models import AppUser  # noqa: E402
from app.db.session import write_tx  # noqa: E402
from app.security.auth import ROLE_PERMISSIONS, hash_password  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("username"); ap.add_argument("role", choices=list(ROLE_PERMISSIONS))
ap.add_argument("--divisions"); ap.add_argument("--name")
a = ap.parse_args()
pw = getpass.getpass("Password: ")
if pw != getpass.getpass("Repeat: "):
    sys.exit("passwords differ")
with write_tx() as db:
    u = db.execute(select(AppUser).where(AppUser.username == a.username)).scalar_one_or_none()
    if u is None:
        u = AppUser(username=a.username); db.add(u)
    u.role, u.full_name, u.password_hash, u.is_active = a.role, a.name, hash_password(pw), True
    u.allowed_divisions = [d.strip() for d in a.divisions.split(",")] if a.divisions else None
print(f"user {a.username} saved ({a.role})")
