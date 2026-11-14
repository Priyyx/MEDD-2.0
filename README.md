# MEDD Maharashtra 2.0 — Medical Equipment Decision Support (PostgreSQL-powered)

MEDD 2.0 continues the existing dashboard (https://mhmedequip.netlify.app/). It keeps the same 13 modules, layout, colours, filters, charts, drill-downs and exports. The difference is that every figure is now computed **live from PostgreSQL** through a FastAPI backend.

To update the data, drop the master Excel into `backend/data/incoming/`. The file is detected, validated, staged and applied to the database in one transaction, and every open dashboard refreshes itself. You do not edit any HTML, JavaScript or Python.

```
Excel ─▶ incoming/ ─▶ watcher ─▶ validate ─▶ staging ─▶ ONE transaction: UPSERT + audit + view refresh ─▶ NOTIFY ─▶ browsers refresh
                                     └─ failure ─▶ failed/ + error report, production data untouched
```

---

## 1. Folder structure

```
medd2/
├── original_snapshot/           untouched copy of the 1.0 ZIP (read-only) + SHA256SUMS.txt
├── frontend/                    the 1.0 dashboard, split into modules and wired to the API
│   ├── index.html               1.0 HTML shell (+ sign-in, data-status bar, Data Management page)
│   ├── css/styles.css           1.0 stylesheet, unchanged          css/medd2.css  2.0 additions only
│   ├── js/  config · api · state · exports · charts · filters · dashboard · drilldown ·
│   │        dataset-explorer · chatbot · realtime · auth · admin · main
│   └── assets/vendor/           Chart.js 4.4.1 + datalabels 2.2.0 (same versions as 1.0, served locally)
├── backend/
│   ├── app/
│   │   ├── main.py              FastAPI app: API (/api/v1), docs (/api/docs), serves the frontend at /
│   │   ├── config.py            settings from backend/.env
│   │   ├── db/                  SQLAlchemy models + pooled read/write engines
│   │   ├── ingestion/           reader · mapping · standardise · pipeline · watcher
│   │   ├── services/            analytics (KPI engine) · bootstrap · chatbot · cache · events
│   │   ├── security/            JWT auth, scrypt passwords, RBAC, audit
│   │   └── api/v1/              dashboard.py (analytics) · admin.py (auth, ingestion, chat, SSE, audit)
│   ├── alembic/                 migrations (0001_initial_schema.py)
│   ├── config/                  column_mappings.yaml · ingestion.yaml   ← business rules, editable
│   ├── data/ incoming · processing · processed · failed · archive · reports
│   ├── reference/               1.0 embedded DATA (for reference-data migration + reconciliation)
│   ├── scripts/                 setup_database · ingest_file · run_watcher · backup/restore · create_user
│   ├── tests/                   pytest suite, acceptance test, UI smoke test, performance check
│   ├── requirements.txt  ·  .env.example  ·  alembic.ini
├── docs/                        audit, database, KPIs, API, change log, ingestion, security, backup, tests, reconciliation
└── .vscode/                     launch configurations + tasks
```

## 2. Prerequisites

| Component | Version | Notes |
|---|---|---|
| Python | 3.11 – 3.13 | `python --version` |
| PostgreSQL | 14 – 17 (tested on 16) | Server + client tools (`psql`, `pg_dump`) on PATH |
| VS Code | recent | Python extension recommended (`.vscode/extensions.json`) |

## 3. Setup (first time) — VS Code

1. **Open the `medd2` folder** in VS Code (*File → Open Folder*).
2. **Create a virtual environment** (Terminal → New Terminal):
   ```bash
   cd backend
   python -m venv .venv
   # Windows:  .venv\Scripts\activate        macOS/Linux:  source .venv/bin/activate
   python -m pip install -r requirements.txt
   ```
3. **Configure secrets.** Copy `backend/.env.example` to `backend/.env` and replace every `change_me` value:
   - `PG_SUPERUSER_URL`: your local `postgres` superuser. It is used only by the setup script.
   - `MEDD_APP_PASSWORD` / `MEDD_READONLY_PASSWORD`: choose two passwords, and repeat them inside `DATABASE_URL` / `DATABASE_URL_READONLY`.
   - `JWT_SECRET`: generate one with `python -c "import secrets; print(secrets.token_urlsafe(48))"`.
   - `MEDD_ADMIN_PASSWORD`: the first administrator's password.
4. **Create the database.** This creates the roles and the database, runs the migrations, loads the reference data and creates the admin user:
   ```bash
   python scripts/setup_database.py
   ```
5. **Start the platform:**
   ```bash
   python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
   ```
   You can also use **Run and Debug → "MEDD 2.0: API + dashboard + watcher"**, or *Terminal → Run Task → "3. Start MEDD 2.0"*.
6. Open **http://127.0.0.1:8000** and sign in as the admin user. The API documentation is at http://127.0.0.1:8000/api/docs.
7. **Load data.** Copy `Medical_Equipment_Gap_Analysis_Master_Data.xlsx` into `backend/data/incoming/`, or upload it under **Data Management**. After about 40 s the dashboard shows a toast and refreshes.

## 4. Daily use

| Task | How |
|---|---|
| Update data | Drop a new or corrected workbook into `backend/data/incoming/`, or upload it under **Data Management**. A file identical to one already loaded is skipped. Changed rows are updated. In `snapshot` mode, rows that disappear for an institute in the file are deactivated (reversibly). |
| See what happened | **Data Management** shows history, per-row validation issues and the full report. Reports are also saved to `backend/data/reports/` (Markdown, JSON and CSV). |
| Undo the last load | **Data Management → ↶ Roll back** (data_manager or admin role). |
| Fix a header the system does not recognise | Add the spelling to `backend/config/column_mappings.yaml`. No code change is needed. |
| Change validation rules or sync mode | Edit `backend/config/ingestion.yaml`. |
| Add users | `python scripts/create_user.py <name> <admin\|data_manager\|analyst\|viewer> [--divisions "Pune"]` |
| Backup / restore | `python scripts/backup_database.py` · `python scripts/restore_database.py <dump> --yes-really` (see `docs/08_BACKUP_RECOVERY.md`) |
| Ingest from the command line | `python scripts/ingest_file.py path/to/file.xlsx --copy` |
| Run the watcher as a separate worker | Set `WATCHER_ENABLED=false` for the API, then `python scripts/run_watcher.py` |

## 5. Roles

| Role | Dashboards & AI | Budget / unit cost | Exports | Upload / rollback | Users / audit |
|---|---|---|---|---|---|
| admin | ✓ | ✓ | ✓ | ✓ | ✓ |
| data_manager | ✓ | ✓ | ✓ | ✓ | audit only |
| analyst | ✓ | ✓ | ✓ | view history only | — |
| viewer | ✓ | hidden | — | — | — |

Any user can also be limited to specific divisions (`allowed_divisions`). The server enforces this for every API, export and chatbot answer.

## 6. Tests

```bash
cd backend
python -m pytest tests -v                      # 55 tests incl. the mandatory end-to-end acceptance test
MEDD_MASTER_XLSX=/path/to/master.xlsx python -m pytest tests -v     # + real-workbook reconciliation
python tests/ui_smoke.py http://127.0.0.1:8000 admin '<pw>' shots/  # browser check of all 13 modules (needs playwright)
python tests/perf_check.py http://127.0.0.1:8000 admin '<pw>' 20 400
```

The tests create their own `medd_test` database and never touch `medd`. Results are in `docs/09_TEST_REPORT.md`.

## 7. Troubleshooting

| Symptom | Fix |
|---|---|
| `JWT_SECRET must be set…` at start-up | Set a 32+ character `JWT_SECRET` in `backend/.env` |
| `password authentication failed` | The passwords in `DATABASE_URL*` must match `MEDD_*_PASSWORD`. Re-run `setup_database.py` to re-sync the roles. |
| Dashboard says "no equipment data yet" | No workbook has been ingested yet. Drop the master Excel into `incoming/`. |
| File goes to `failed/` | Read `failed/<file>.error.txt` and the report under **Data Management**. Production data was not changed. |
| Header not recognised | Add it to `config/column_mappings.yaml`. The report lists unmapped columns. |
| Port 8000 busy | Add `--port 8010` to the uvicorn command |

## 8. Documentation index

`docs/01_SOURCE_CODE_AUDIT.md` · `02_DATABASE_DESIGN.md` · `03_KPI_DEFINITIONS.md` · `04_API.md` · `05_CHANGE_LOG.md` · `06_INGESTION_GUIDE.md` · `07_SECURITY.md` · `08_BACKUP_RECOVERY.md` · `09_TEST_REPORT.md` · `10_DATA_RECONCILIATION.md`
