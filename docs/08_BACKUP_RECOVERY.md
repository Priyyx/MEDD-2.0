# Backup & Recovery

## Backup

```bash
cd backend
python scripts/backup_database.py              # -> backend/backups/medd_YYYYmmdd_HHMMSS.dump (pg_dump -Fc), keeps 14
python scripts/backup_database.py --keep 30 --out D:\MEDD_Backups
```

Each run also verifies the dump with `pg_restore --list`. **Schedule it daily:**

- Windows Task Scheduler: Program = `C:\path\to\backend\.venv\Scripts\python.exe`, Arguments = `scripts\backup_database.py`, Start in = `C:\path\to\backend`
- Linux cron: `30 1 * * * cd /opt/medd2/backend && .venv/bin/python scripts/backup_database.py`

Also back up these folders (file-level copy): `backend/data/archive/` (every source workbook ever loaded), `backend/data/reports/` and `backend/.env` (store it securely).

## Restore

1. Stop the API.
2. Run: `python scripts/restore_database.py backups/medd_20261112_090251.dump --yes-really`
3. Start the API. The dashboard shows the restored data version.

This round-trip was verified on 12 Nov 2026: a 10.5 MB dump was restored, the 52,036 line items were back, and the read-only role grants worked.

## Other recovery paths

| Situation | Action |
|---|---|
| A bad workbook was loaded | **Data Management → Roll back** (latest load), or upload the corrected workbook (only changed rows update) |
| A file failed | Nothing to recover. Production was not changed. Fix the file and drop it in `incoming/` again |
| Rebuild from scratch | `python scripts/setup_database.py --reset --yes-really`, then re-drop the latest workbook from `archive/` |
| Lost admin password | `python scripts/create_user.py admin admin` (sets a new password) |
