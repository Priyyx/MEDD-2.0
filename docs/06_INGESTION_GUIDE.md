# Ingestion Guide

## Folders (`backend/data/`)

| Folder | Meaning |
|---|---|
| `incoming/` | Drop files here, or use **Data Management → Upload**. They are watched continuously (watchdog plus a 30 s safety poll). Files already present at start-up are picked up. |
| `processing/` | The file being processed (renamed `NNNNN_<name>`) |
| `processed/` | Successfully applied files |
| `archive/YYYY/MM/` | Permanent copy of every successful file (`NNNNN_<sha8>_<name>`). `archive/duplicates/` holds re-uploads that were skipped |
| `failed/` | Rejected files plus `<file>.error.txt` explaining why. **Production data is untouched.** |
| `reports/` | For every file: a Markdown report, a JSON report and a CSV of row-level issues |

A file is processed only after its size has been stable for `WATCHER_SETTLE_SECONDS`, so half-copied files are never read. Office lock files (`~$…`) and `.tmp` / `.part` files are ignored.

## Supported formats

`.xlsx`, `.xlsm`, `.xls`, `.csv` (UTF-8/Windows-1252, delimiter auto-detected) and `.json`. JSON can be a list of records, or `{"sheets": {"name": [records]}}`. A workbook may contain several sheets of different kinds. Each sheet is classified independently:

| Dataset type | Recognised when these columns exist | Effect |
|---|---|---|
| inventory (master data) | institute + department + equipment + any quantity | line items + procurement / AMC / lifecycle values, unit costs from a `Costing` column |
| unit_cost | equipment + unit cost, no institute column | costing list (takes precedence over in-line costing) |
| institute | institute + division, no equipment column | institute master (division, bedded capacity) |

Header rows are found automatically within the first 25 rows. Title blocks and two-row merged headers are handled. The spellings that are recognised live in `config/column_mappings.yaml`; extend that file if a future workbook uses new headers. The validated master workbook maps all 17 data columns.

## Validation

| Severity | Examples | Effect |
|---|---|---|
| ERROR (row) | missing institute/department/equipment, non-numeric or negative or fractional quantity, unknown division, new institute without a division | row rejected, recorded in staging as REJECTED |
| ERROR (file) | unreadable file, no recognised sheet, **rejected rows > `max_reject_ratio` (5 %)** | whole file FAILED, nothing applied |
| WARNING | functional > available, condemnation > non-functional, AMC > functional, repeated line key, exact duplicate row, procurement outlier, procurement without unit cost, conflicting unit costs, institute division/bed mismatch | row loaded as-is, issue reported |
| INFO | blank treated as 0, new institute/department/equipment created, unmapped columns, skipped sheets/total rows | — |

## Standardisation rules (traceable — the original spelling is kept in `line_item.raw_names` and `staging.*.raw`)

1. Unicode normalisation, curly quotes → straight, dashes → `-`, whitespace collapsed.
2. HTML-unsafe characters `< " \ `` are replaced with look-alikes (‹ ″ ∖ ʹ), which prevents stored XSS. Inch marks therefore appear as ″.
3. Case-insensitive matching (`merge_case_variants`).
4. Approved aliases from `master_data.name_alias`. Division aliases are seeded (Aurangabad / Chhatrapati Sambhaji Nagar → Chh. Sambhaji Nagar, Kokan → Konkan). Each institute's `Short_Name` becomes an alias automatically.

> Changing a standardisation rule after go-live changes the keys of the names it affects. Plan rule changes together with a full reload, and review the deactivation counts in the report.

## Duplicates and idempotency

- **Same file again** (same SHA-256) → status DUPLICATE, skipped, nothing changes.
- **Same content, different file** → every row "unchanged" (row-hash comparison), nothing changes.
- **Rows repeated inside a file** are kept as separate occurrences (1.0 summed them all) and reported as warnings.

## Sync modes (`config/ingestion.yaml → sync_mode`)

- `snapshot` (default): the file is the full current record for each institute it contains. Previously loaded rows of those institutes that are missing from the file are **deactivated** (soft, reversible, audited). Institutes not in the file are untouched.
- `upsert`: insert and update only. Nothing is ever deactivated.

## Rollback

- A failed file is automatically rolled back (single transaction).
- The most recent successful load can be undone from **Data Management → ↶ Roll back** or with `POST /api/v1/ingestion/files/{id}/rollback`. This uses `audit.line_item_history`: inserts are deactivated, updates restored and deactivations re-activated. Unit-cost changes are kept in `financial.unit_cost_history`. Restore them by re-uploading the previous costing list.
