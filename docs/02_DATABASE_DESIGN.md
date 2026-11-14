# Database Design — PostgreSQL (single source of truth)

Migration: `backend/alembic/versions/0001_initial_schema.py`. Future changes are made with `alembic revision` and `alembic upgrade head`. The ORM mirror is in `backend/app/db/models.py`.

## Hierarchy

`Maharashtra → master_data.division (6) → master_data.institute (35) → [line item] department (36) → equipment (≈1,036) → sub_category (104)`

District shapes (`master_data.district`, 35) hang off divisions and feed the heat map.

## Schemas and tables

| Schema | Table | Purpose / key |
|---|---|---|
| master_data | `division` | name UNIQUE, SVG map key, label centroid |
| | `district` | 35 SVG district paths → division |
| | `institute` | name, `name_key` UNIQUE (standardised), division FK, bedded_capacity, is_active |
| | `department` | name, `name_key` UNIQUE |
| | `equipment` | display name, `name_key` UNIQUE (case variants merged per rule) |
| | `sub_category` | name UNIQUE |
| | `name_alias` | approved mapping rules: (entity_type, alias_key) → canonical name. Seeded with division aliases and workbook `Short_Name`s |
| equipment_inventory | `line_item` | one row per institute × department × equipment × sub-category × course × occurrence. `business_key` = SHA-1 of the standardised natural key (UNIQUE, used for UPSERT). Required/available/functional quantities (CHECK ≥ 0), `non_functional_qty` GENERATED, `row_hash` for change detection, `is_active` (soft delete), source file/sheet/row and `raw_names` for traceability |
| procurement | `procurement_proposal` | 1:1 line item → proposed_qty |
| maintenance | `amc_coverage` | 1:1 line item → amc_cmc_qty |
| lifecycle | `lifecycle_status` | 1:1 line item → end_of_life_qty, condemnation_qty |
| financial | `equipment_unit_cost` | equipment → unit_cost, cost_category, source, source file |
| | `unit_cost_history` | every unit-cost change (old → new, file) |
| staging | `inventory_row`, `unit_cost_row`, `institute_row` | every incoming row: full raw JSON, parsed values, status PENDING / VALID / REJECTED |
| metadata | `ingestion_file` | filename, SHA-256, size, status, row counts (read/valid/rejected/inserted/updated/unchanged/deactivated), warnings, errors, report path, timestamps |
| | `ingestion_sheet` | per worksheet: detected type, header row, column map, unmapped columns |
| | `validation_issue` | row-level issues (severity, code, sheet, row, field, value, message) |
| | `dataset_version`, `data_refresh` | version history and the "last refresh" timestamp |
| | `app_setting` | `data_version`, `last_refresh`, map canvas |
| | `legacy_baseline` | MEDD 1.0 figures, used only for reconciliation |
| | `app_user` | users, scrypt hashes, role, allowed_divisions, lockout |
| audit | `audit_log` | append-only (trigger blocks UPDATE/DELETE): logins, uploads, ingestions, exports, chat queries, user changes, rollbacks |
| | `line_item_history` | INSERT / UPDATE (old + new values) / DEACTIVATE / REACTIVATE per line, per file |
| analytics | `mv_line_fact` (materialized view) | denormalised active line items with every derived measure (budget, net requirement, shortfall, est. cost). Unique index on line_item_id, so it is refreshed **CONCURRENTLY** inside the ingestion transaction. Indexed on division, institute, department, equipment, sub-category and bedded capacity |
| | `v_division_kpi`, `v_institute_kpi` | convenience views |

## Indexes (selected)

Partial indexes `WHERE is_active` on line_item (institute+department, equipment, sub-category). There are FK indexes on division/institute and the `ingestion_file(sha256)` lookup for duplicate detection. The materialized view has filter-column indexes.

## Roles

| Role | Rights |
|---|---|
| `medd_app` | Owner of all objects. Used by ingestion, authentication and audit. Not a superuser. |
| `medd_readonly` | `default_transaction_read_only=on`. SELECT on analytical schemas and non-sensitive metadata only (no `app_user`, no `audit`, no `staging`). Used by every dashboard API and the chatbot. |
| `postgres` (superuser) | Only used by `setup_database.py` / `restore_database.py` to create roles and the database. |

## Transactions and integrity

- One ingestion is one production transaction, serialised with `pg_advisory_xact_lock`. Any error rolls back everything.
- Staging rows are committed **before** the production transaction, so evidence survives a failure.
- `ON CONFLICT (business_key) DO UPDATE … WHERE row_hash <> EXCLUDED.row_hash` updates only rows that really changed. This makes ingestion idempotent.
- Snapshot sync deactivates, and never deletes, rows that are missing from a new file. This is recorded in `audit.line_item_history`.
