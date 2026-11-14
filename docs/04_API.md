# API Reference — MEDD Maharashtra 2.0

Interactive documentation (Swagger UI) is at **`/api/docs`**, ReDoc is at `/api/redoc`, and the machine-readable spec is `docs/openapi.json`.

**Authentication:** call `POST /api/v1/auth/login` with `{"username", "password"}`, then send `Authorization: Bearer <token>` on every other call. The exceptions are `/api/health`, `/api/v1/auth/login` and `/api/v1/auth/config`. EventSource cannot set headers, so the SSE stream accepts `?token=`.

**Shared filters** (any analytics endpoint): `division`, `institute`, `department`, `subcat`, `equipment`, `bedded`. Repeat a parameter or separate values with `||`. The user's permitted divisions are always intersected server-side.

| Method | Path | Tag | Summary |
|---|---|---|---|
| GET | `/api/health` | health | Health |
| GET | `/api/v1/dashboard/bootstrap` | dashboard | Full dashboard payload (MEDD 1.0 DATA contract) built from PostgreSQL |
| GET | `/api/v1/dashboard/status` | dashboard | Last refresh timestamp, data version and latest ingestion |
| GET | `/api/v1/dashboard/scope` | dashboard | Filtered KPI summary + division/institute/department breakdowns |
| GET | `/api/v1/kpis/summary` | dashboard | Executive KPI block for the active filters |
| GET | `/api/v1/kpis/breakdown` | dashboard | KPI blocks grouped by a hierarchy level (server-side sort + pagination) |
| GET | `/api/v1/modules/{module}` | dashboard | Module analytics: summary, ranking by division and top equipment |
| GET | `/api/v1/divisions` | dashboard | Division Dashboard data |
| GET | `/api/v1/institutes` | dashboard | Institute Dashboard data (server-side pagination) |
| GET | `/api/v1/departments` | dashboard | Department Dashboard data |
| GET | `/api/v1/equipment` | dashboard | Equipment Explorer (all filters, server-side search/sort/pagination) |
| GET | `/api/v1/drill` | dashboard | Metric-aware drill-through: Division → Institute → Department → Equipment |
| GET | `/api/v1/net-requirement/cost-mapping` | dashboard | Cost Mapping table (Net Requirement > 0 lines), server-paginated |
| GET | `/api/v1/exports/cost-mapping` | dashboard | Export the full filtered Cost Mapping table (CSV or Excel) |
| GET | `/api/v1/exports/{level}` | dashboard | Export a filtered breakdown (division/institute/department/equipment) as CSV |
| POST | `/api/v1/auth/login` | auth | Sign in; returns a JWT bearer token |
| GET | `/api/v1/auth/config` | auth | Public: whether sign-in is required |
| GET | `/api/v1/auth/me` | auth | Me |
| POST | `/api/v1/auth/change-password` | auth | Change Password |
| GET | `/api/v1/admin/users` | admin | List Users |
| PUT | `/api/v1/admin/users` | admin | Create or update a user |
| POST | `/api/v1/chat` | decision-support-ai | Ask the database-grounded Decision Support AI |
| GET | `/api/v1/events` | realtime | Server-Sent Events: data_refreshed / ingestion_failed |
| GET | `/api/v1/ingestion/files` | ingestion | Ingestion history |
| GET | `/api/v1/ingestion/files/{file_id}` | ingestion | One ingestion with issue summary + issues page |
| GET | `/api/v1/ingestion/files/{file_id}/report` | ingestion | Markdown ingestion & validation report |
| POST | `/api/v1/ingestion/upload` | ingestion | Upload a workbook into the incoming folder |
| POST | `/api/v1/ingestion/rescan` | ingestion | Queue any files already sitting in incoming/ |
| GET | `/api/v1/ingestion/watcher` | ingestion | Watcher Status |
| POST | `/api/v1/ingestion/files/{file_id}/rollback` | ingestion | Revert the most recent successful ingestion (uses audit history) |
| GET | `/api/v1/admin/audit` | admin | Audit |
| GET | `/api/v1/reconciliation` | reconciliation | Compare live PostgreSQL KPIs with MEDD 1.0 dashboard figures (division/institute/department/overview) |

## Permissions per endpoint group

| Group | Permission |
|---|---|
| dashboard / kpis / modules / drill / equipment / institutes / divisions / departments / cost-mapping / events | `dashboard:read` (all roles) |
| modules/financial | `financial:read` (admin, data_manager, analyst) — viewers receive `budget: null` everywhere else |
| exports/* | `export:run` (admin, data_manager, analyst) |
| chat | `chat:use` (all roles) |
| ingestion GET | `ingestion:read` · upload / rescan / rollback: `ingestion:write` (admin, data_manager) |
| admin/users | `users:manage` (admin) · admin/audit: `audit:read` · reconciliation: `reconciliation:read` |

## Examples

```bash
TOKEN=$(curl -s -X POST http://127.0.0.1:8000/api/v1/auth/login -H 'Content-Type: application/json' \
        -d '{"username":"admin","password":"..."}' | python -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')
curl -H "Authorization: Bearer $TOKEN" 'http://127.0.0.1:8000/api/v1/kpis/summary?division=Pune&department=Medicine'
curl -H "Authorization: Bearer $TOKEN" 'http://127.0.0.1:8000/api/v1/drill?level=department&path=Pune||BJ%20Medical%20%26%20Sassoon%20Hospital,%20Pune'
curl -H "Authorization: Bearer $TOKEN" -X POST http://127.0.0.1:8000/api/v1/chat -H 'Content-Type: application/json' \
     -d '{"question":"Which divisions have the highest equipment shortages?","filters":{"department":["Medicine"]}}'
curl -H "Authorization: Bearer $TOKEN" -F file=@Medical_Equipment_Gap_Analysis_Master_Data.xlsx http://127.0.0.1:8000/api/v1/ingestion/upload
```

## KPI block (returned by summary / breakdown / drill / modules) — real example: Pune

```json
{
 "required": 37043,
 "available": 160334,
 "functional": 157317,
 "non_functional": 3017,
 "procurement": 8136,
 "net_requirement": -120274,
 "budget": 484537117.13,
 "amc": 39693,
 "condemnation": 1272,
 "end_of_life": 686,
 "college_count": 6,
 "gap_pct": 424.69,
 "util_pct": 424.69,
 "util_defined": true,
 "proc_pct": 21.96,
 "amc_pct": 25.23,
 "func_pct": 98.12,
 "eol_pct": 0.44,
 "equipment_types": 989,
 "functional_shortfall": 19632,
 "line_items": 8948,
 "name": "Pune"
}
```
