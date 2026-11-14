# Test Report — MEDD Maharashtra 2.0

**Date:** 12 Nov 2026 · **Environment:** Ubuntu 24.04, Python 3.13, PostgreSQL 16.15, headless Chrome (Playwright) · **Data:** `Medical_Equipment_Gap_Analysis_Master_Data.xlsx` (52,036 rows) plus generated test fixtures

## Summary

| Suite | Result |
|---|---|
| Automated pytest suite (`backend/tests`, isolated `medd_test` DB) | **55 / 55 passed** (incl. real master workbook, `MEDD_MASTER_XLSX` set) |
| **Mandatory acceptance test** (`test_05_acceptance.py`) | **PASSED** |
| Browser smoke test, all 13 modules + Data Management (`tests/ui_smoke.py`) | **PASSED**, 0 JavaScript errors |
| Live refresh in an open browser (upload → toast → KPIs change, filters kept) | **PASSED** |
| Concurrent access / performance (`tests/perf_check.py`) | **PASSED**: 400 requests, 20 concurrent, 0 errors |
| Backup → restore round-trip | **PASSED** |
| **Final ZIP-based acceptance test** (extract → fresh venv → `pip install` → setup → start → drop Excel → dashboard) | **PASSED**: also re-ran the 55 tests from the extracted folder |

## 1. Database creation & migration (`test_01_database.py`, 7 tests)

All 10 schemas are created, the hierarchy FKs are present, and reference data is migrated (6 divisions, 35 districts, 35 institutes, 1,149 baseline rows). The read-only role cannot write and cannot read password hashes. Negative quantities are rejected by CHECK constraints. The audit log is append-only. Re-running the migration is a no-op.

## 2. Ingestion (`test_02_ingestion.py`, 13 tests)

| Scenario | Verified |
|---|---|
| Workbook with title rows above the header, inventory + unit-cost sheets | detected, loaded; DB totals = file totals for 9 measures; moved to processed/ + archive/; report written; staging rows VALID with raw source data |
| Same file uploaded twice | second is DUPLICATE; database unchanged |
| Same content re-saved (different checksum, extra sheet) | 0 inserted, 0 updated, all unchanged (idempotent) |
| Changed values | only changed rows updated; `audit.line_item_history` holds old → new |
| ~17 % invalid rows | file FAILED; **production totals identical before/after**; file + `.error.txt` in failed/; issues INVALID_QUANTITY / MISSING_REQUIRED / UNKNOWN_DIVISION recorded |
| 4 invalid rows (< 5 %) | SUCCESS_WITH_WARNINGS; bad rows rejected, others loaded |
| Snapshot sync with a subset (CSV) | missing rows deactivated (exact count); rollback restores the previous state exactly |
| Rollback of an older file | refused (only the latest load can be rolled back) |
| JSON input | loaded |
| Unrecognised workbook / `.txt` file | FAILED with a clear reason / moved to failed/ |
| New institute + division alias + case variants | institute created in "Chh. Sambhaji Nagar" (from "Chhatrapati Sambhaji Nagar"); "anatomy " → Anatomy; "ABG MACHINE" merged |
| **1.0 Cost-Mapping reconciliation** (23,907 real 1.0 rows) | Σ net requirement **106,387** and Σ estimated cost **₹6,311,256,440.63**, identical to MEDD 1.0 |

## 3. KPIs, filters, drill-downs, exports, security (`test_03_kpi_api.py`, 19 tests)

- Formulas, zero denominators and negative net requirement behave as specified in `03_KPI_DEFINITIONS.md`.
- **Reconciliation across levels:** Σ divisions = Σ institutes = Σ departments = Σ equipment = state total for 8 measures. Every division equals the sum of its institutes. Drill parent = Σ children at every level.
- **Consistency:** the same KPI is identical in `/kpis/summary`, `/dashboard/scope` and all 7 module endpoints.
- The bootstrap payload keeps the full 1.0 contract (16 keys). Combined filters are exact (institute × department × equipment).
- Server-side pagination and sorting work. CSV and Excel exports work.
- **Security:**
  - 401 without a token or with a forged token.
  - Account lock after 5 failed logins.
  - Viewer: budget is null, 403 on the financial module, exports, ingestion and users.
  - Analyst cannot upload.
  - A division-scoped user cannot widen their scope.
  - SQL-injection payloads in filters, search, sort and chat are inert.
  - Upload extension allow-list works. Security headers are present.

## 4. Decision Support AI (`test_04_chatbot.py`, 14 tests)

All 9 required question types (plus cost tiers) map to the correct analytical service, return methodology, and run in deterministic mode. Summary numbers equal the KPI engine. Filters are respected. Unknown questions return no fabricated figures. Viewers are refused budget figures.

## 5. Mandatory acceptance test (`test_05_acceptance.py`)

The real folder watcher (watchdog) is started and a new workbook is copied into `incoming/`. The test then confirms each step:

- **detected automatically**
- **validated** (SUCCESS)
- **PostgreSQL updated** (active line items > 0)
- **materialized view refreshed** (mv rows = active rows)
- **dashboard APIs** (`/kpis/summary`, `/dashboard/bootstrap`) return the new KPIs
- **last-refresh timestamp changed**
- file in processed/
- **`data_refreshed` notification delivered** through PostgreSQL LISTEN/NOTIFY

No code was edited at any point.

## 6. Real master workbook

52,036 rows read, **0 rejected**, 2,230 warnings (see `10_DATA_RECONCILIATION.md`). Database totals equal the workbook exactly, including Budget **₹6,139,631,348.38**. A corrected copy (one cell changed) updated **exactly 1 row** (52,035 unchanged). Rolling that load back restored the original figures.

## 7. Browser checks (headless Chrome, 1440 × 1000)

All 14 pages rendered with content. Filters changed the KPI cards. Drill-down to equipment level showed the full list (65 items for Medicine at BJ Medical, paginated 15 per page; 1.0 showed 12). The chatbot answered from the database, and the Cost Mapping table showed server-paged rows. There were **0 JS errors**.

Live refresh: with the dashboard open and filtered to Chh. Sambhaji Nagar, uploading a corrected workbook produced these results:
- The toast "Dashboard updated … (data version 2)" appeared.
- Procurement on the open page changed from 1,96,163 to 1,49,871.
- The filter stayed selected.

Screenshots are in `docs/screenshots/`.

## 8. Performance (single uvicorn worker, same machine as PostgreSQL)

| Run | Requests | Concurrency | Errors | Throughput | p50 | p95 | max |
|---|---|---|---|---|---|---|---|
| Cold cache | 400 | 20 | 0 | 138 req/s | 115 ms | 359 ms | 735 ms |
| Warm cache | 400 | 20 | 0 | 158 req/s | 119 ms | 201 ms | 307 ms |

Other timings:
- Chatbot: about 92 ms per answer.
- Bootstrap: built in 1.8 s once per data version, then served gzip-compressed (575 KB) in about 15 ms.
- Ingesting 52,036 rows: about 40 s end to end.

Concurrent first requests share a single computation (single-flight cache).

## Known limitations / follow-ups

- Rolling back unit-cost changes is done by re-uploading the previous costing list (history is kept in `financial.unit_cost_history`).
- The optional LLM phrasing layer (Anthropic API) is implemented but disabled. It was not exercised in tests because no API key is configured.
- The decisions listed in `03_KPI_DEFINITIONS.md` and `10_DATA_RECONCILIATION.md` are awaiting approval.
