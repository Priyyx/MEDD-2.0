# MEDD Maharashtra — Source-Code Audit of the Original Dashboard ZIP

**Audited package:** `medical_equipment_dashboard.zip` (preserved, read-only, in `original_snapshot/` with SHA-256 checksums in `original_snapshot/SHA256SUMS.txt`)
**Audit date:** 12 Nov 2026
**Reference deployment:** https://mhmedequip.netlify.app/

---

## 1. Package inventory (recursive)

| File | Size | Role |
|---|---|---|
| `index.html` | 5,457,165 bytes, 1,759 lines | **Entire application**: HTML shell, inline CSS (lines 9–173), inline JS (lines 313–1757), embedded dataset (line 314, a single 5.3 MB line) |
| `README.md` | 1,824 bytes | Netlify deploy notes; states the build is a static snapshot |
| `netlify.toml` | 558 bytes | Publish dir `.`, SPA redirect, security headers (X-Frame-Options, nosniff, Referrer-Policy) |
| `_redirects` | 21 bytes | SPA fallback `/* /index.html 200` |

**Not present in the ZIP** (relevant to the 2.0 brief):

- No backend code, API configuration, database connection, `.env`, package manifest or build tooling.
- **No Excel / CSV source data.** The master workbook and the unit-costing list exist only as pre-aggregated JSON inside `index.html`.
- No images or assets. The README mentions an "image-based division heat map"; the shipped code hides `#mapImg` and draws SVG district paths from `DATA.map` instead.
- The README mentions a "full React + FastAPI application". It is not in the package.

## 2. Architecture of the existing application

- **Entry point:** `index.html`. It is a single-page app with hash routing (`#executive`, `#gap`, `#drill/<metric>/<level>/<path…>`, `#division/<name>`, `#institute/<name>`, `#instdept/<inst>/<dept>`, `#department/<name>`, `#equip/<name>`, `#kpi/<key>`, `#uniqeq/<level>/<path…>`).
- **External dependencies (CDN):** Chart.js 4.4.1 and chartjs-plugin-datalabels 2.2.0. There are no other libraries.
- **Global state:** `state = {division, institute, department, subcat, equipment, bedded, metric, page}`. Every filter is a multi-select array.
- **Data source:** `const DATA = {…}`, a 5.3 MB literal. All calculations run in the browser over these pre-aggregated blocks.

### 2.1 Embedded `DATA` contract (must be preserved by the API)

| Key | Shape | Notes |
|---|---|---|
| `overview` | 21 KPIs | required 194,181; available 393,096; functional 369,992; non_functional 23,104; procurement 197,619; net_requirement −175,811; budget ₹4,377,983,348.38; amc 237,156; condemnation 7,018; end_of_life 2,891; college_count 35; gap_pct = util_pct 190.54; proc_pct 101.77; amc_pct 64.1; func_pct 94.12; eol_pct 0.78; equipment_types 1,071; line_items 52,036; divisions 6; department_count 36 |
| `divisions[6]` | KPI block + `departments[]`, `institutes[]`, `top_equipment[15]` | |
| `institutes[35]` | KPI block + `division`, `seat`, `departments[]` (each with `top_equipment[≤12]`), `top_equipment[15]` | 3.0 MB |
| `departments[36]` | KPI block + `divisions_bd[]`, `institutes[]`, `top_equipment[]` | |
| `state_depts[36]` | KPI block | Duplicate of `departments` without the nested arrays |
| `equipment_catalog[1071]` | per-equipment KPIs + `unit_cost` | |
| `equipment_names[1071]` | sorted names | |
| `equipment_div_map` | `{equipment: {division: {r,f,p,b,n,g}}}` | Used by the map when an equipment or sub-category filter is active |
| `eq_index` | `names`, `inst`, `dept`, `div`, `instdept`, `subcat` → arrays of equipment indices | Drives the Unique Equipment KPI and the filter cascades |
| `bedded_capacities` | `[50,100,150,200,250]` | Matches `institutes[].seat` |
| `cost_category`, `course_category`, `department_type` | line-item counts | Low/Medium/High, UG/PG/SS, Clinical/Non-Clinical/Other |
| `sub_categories[104]` | names | |
| `map` | `W, H, districts[{name, division, d (SVG path), cx, cy}], div_centroids` | 35 district shapes |
| `cost_map` | `eq[], div[], inst[], dept[], rows[23,907][11]` | Line-level rows **where Net Requirement > 0 only**: `[eq, div, inst, dept, req, avail, func, netreq, unit_cost, total, cat]` |

### 2.2 Modules (all 13 present and wired)

| # | Module | Renderer | Data used |
|---|---|---|---|
| 1 | Executive Dashboard | `renderExec` → KPI cards, SVG map, division/institute tables, 2 charts | `scope()`, divisions, institutes, map |
| 2 | Decision Support AI | `renderChatbot`, `cbAnswer` (rule-based, client-side) | catalog, divisions, institutes, departments |
| 3 | Equipment Gap (Utilisation) | `renderAnalysis('gap')` | divisions, catalog |
| 4 | Procurement Planning | `renderAnalysis('procurement')` | |
| 5 | Net Requirement | `renderAnalysis('netreq')` + `renderCostMapping` | `cost_map` (client-side paging) |
| 6 | Budget & Financial | `renderAnalysis('financial')` | |
| 7 | Condemnation | `renderMetricPage('condemnation')` | |
| 8 | End of Life | `renderMetricPage('eol')` | |
| 9 | AMC/CMC Coverage | `renderMetricPage('amc')` | |
| 10 | Institute Dashboard | `renderListPage('facility')` | |
| 11 | Division Dashboard | `renderListPage('district')` | |
| 12 | Department Dashboard | `renderDepartmentList` | |
| 13 | Equipment Explorer | `renderEquipmentExplorer` | catalog (top 60) |

There are also cross-cutting views: the KPI detail (`#kpi/…`), the metric-aware 4-level drill-through (`#drill/…`), the Unique-Equipment drill (`#uniqeq/…`), detail pages for Division, Institute, Institute×Department, Department and Equipment, CSV/XLS export on every table, sortable headers, and searchable, paginated detail tables.

## 3. KPI formulas found in code

| KPI | Formula in code | Location |
|---|---|---|
| Non-Functional | `available − functional` | `COLDEF`, `sumBlocks` sums the stored `non_functional` |
| Utilisation % (`gap_pct` = `util_pct`) | `functional ÷ required × 100`, rounded to 2 dp; **0 when required = 0** | `sumBlocks`, map `effDiv` |
| Net Requirement | `required − functional` (+ = shortfall, − = surplus) | `sumBlocks`, `COLDEF` |
| Budget | `procurement × unit_cost` (unit cost from the unique-equipment costing list) | `COLDEF`; verified: 0 of 1,071 catalog rows violate it |
| Total Estimated Cost (cost map) | `net_requirement × unit_cost`, only rows with net requirement > 0 | `renderCostMapping`; verified on 23,907 rows |
| AMC % | `amc ÷ functional × 100` | `sumBlocks` |
| Func % | `functional ÷ available × 100` | `sumBlocks` |
| EoL % | `end_of_life ÷ functional × 100` | `sumBlocks` |
| Proc % | `procurement ÷ required × 100` | present in DATA (101.77); not recomputed in JS |
| Gap severity bands | ≥100 Adequate, ≥75 Near-adequate, ≥50 Moderate, ≥25 Low, else Critical | `GAP_BANDS` |
| Chatbot cost tiers | unit cost > ₹1 lakh / > ₹5 lakh / > ₹10 lakh, ranked by net requirement | `cbAnswer` |
| Chatbot procurement advice | suggestion > 1.25 × net → "verify"; < 0.75 × net → "may under-provision" | `cbRecommend` |

## 4. Reconciliation of the embedded data (verified by script)

| Check | Result |
|---|---|
| Σ divisions = overview (9 measures) | ✅ exact |
| Σ institutes = overview; Σ institutes per division = division | ✅ exact |
| Σ departments within institute = institute (required) | ✅ all 35 |
| Net requirement = required − functional (all institutes) | ✅ |
| Non-functional = available − functional (all institutes) | ✅ |
| Budget = procurement × unit cost (catalog) | ✅ 0 violations |
| Σ catalog non_functional = overview | ❌ 24,207 vs 23,104 — catalog level appears to clamp negatives at 0 (73 equipment types have functional > available) |

## 5. Issues, discrepancies and defects found

These are documented, not silently fixed. The 2.0 behaviour is listed for each one, and items needing your decision are marked **[DECISION]**.

| # | Finding | Severity | MEDD 2.0 treatment |
|---|---|---|---|
| A1 | **README headline figures do not match the embedded data.** README: Budget ₹6,139,631,348, Gap 126.16%. Embedded: Budget ₹4,377,983,348.38, Utilisation 190.54%. | High | **Explained** once the master workbook was supplied (see `10_DATA_RECONCILIATION.md`). The README figures come from `Medical_Equipment_Gap_Analysis_Master_Data.xlsx`; its "Gap 126.16%" is Procurement ÷ Required (an older Gap definition). The embedded data came from a corrected version: 3 institutes differ, including a 46,297-unit outlier. **[DECISION]** Which workbook version is authoritative? |
| A2 | **Master Excel is not in the package.** Line items cannot be rebuilt from the embedded data: per-department equipment lists are truncated to 12. | Resolved | The master workbook was provided separately. It ingests with 0 rejected rows (52,036 lines). Master/reference data (divisions, district map, institutes, departments, unit costs) is also migrated from the 1.0 snapshot. |
| A3 | `functional_shortfall` is referenced in 9 places but never present in `DATA`, so it renders as "—". | Medium | Computed server-side as `max(required − functional, 0)` summed at line level. **[DECISION]** confirm the definition. |
| A4 | Recommendation severity is **inverted** in `buildGroupRecs` and `detailForEquipment`: `gap_pct ≥ 100` → red "crit". This is legacy "Gap" semantics. Elsewhere, higher utilisation is better. | Medium | Kept as-is to avoid changing business behaviour. **[DECISION]** approve the flip to the utilisation semantics. |
| A5 | When an equipment filter is combined with Division, Institute or Department filters, `scope()` returns **state-wide** equipment totals (the code comment says "we approximate using the global catalog"). | Medium | 2.0 computes the exact intersection in SQL (`/api/v1/kpis/summary`). KPI cards under such filters will differ from 1.0, and they are now correct. |
| A6 | The drill-through to the equipment level and the "complete equipment list" use `top_equipment` (max 12 per institute×department), so lists are silently incomplete. | Medium | Equipment-level drill and lists are served by the API with full, paginated results. |
| A7 | 33 equipment names differ only by case or spacing (`ABG Machine` / `ABG machine`, `C-ARM` / `C-arm`, …). This inflates the Unique Equipment count (1,071). | Low | Standardisation rule `merge_case_variants` (default **on**, configurable). The unique count will be lower than 1,071 and the difference is reported. **[DECISION]** |
| A8 | 73 equipment types have functional > available, which is a data-quality violation. | Low | Flagged per row as a validation **warning** (not rejected). |
| A9 | 201 equipment types (85,950 units proposed) have no unit cost, so their budget is ₹0 and the headline budget is understated. | Medium | Kept at ₹0 (no invented costs). Listed in the validation report as "procurement without unit cost". |
| A10 | Utilisation % = 0 when required = 0 (e.g. "DM – Interventional Radiology" shows 0% with 3 functional units). | Low | Same rule kept for consistency. The API also returns `util_defined=false` so the UI can show "n/a". |
| A11 | Dead code: `renderGIS`, `renderHotspots` (panels removed), `metricSeg2`, `#mapImg`. | Info | Kept (harmless) so nothing is removed. |
| A12 | "Bedded Capacity" filter values (50–250) come from `institute.seat`. These look like MBBS intake seats, not bed counts. | Info | Kept, and stored as `institute.bedded_capacity`. **[DECISION]** confirm the meaning. |
| A13 | The Unique-Equipment KPI applies division OR institute (`else if`), not both. | Info | Equivalent in practice (institutes are scoped to divisions). Preserved. |
| A14 | The map hides the official division image and relies on SVG district paths. | Info | Paths are migrated into `master_data.district`. |
| A15 | Chatbot equipment answers are state-wide even when a location is named (the code prints a disclaimer). | Medium | The server-side chatbot answers equipment × location exactly and respects the active filters. |
| A16 | Everything runs client-side over 5.3 MB of inline JSON. There is no authentication, the data is public, and there is no refresh. | High | Replaced by the authenticated API with RBAC, caching and SSE refresh. |

## 6. Reuse plan

- **Reused unchanged:** all CSS (moved to `frontend/css/styles.css`), the HTML shell, the formatters, `METRICS`/`COLDEF`/`GAP_BANDS`, routing, every page and detail renderer, the drill-through builder, the slicer widget, sort and export helpers, and the map renderer.
- **Changed:** `const DATA = {…}` is replaced by `let DATA` loaded from `GET /api/v1/dashboard/bootstrap`. That payload is built from PostgreSQL with the same contract. Further changes:
  - `scope()` → exact server KPIs.
  - The cost-mapping table → server-side pagination, sort and search.
  - Equipment-level lists → server.
  - The chatbot → server.
  - Equipment Explorer → server pagination and full filter support.
- **Added:** login, data-status bar with last refresh, SSE live refresh, and a Data Management page (ingestion history and upload).

The full file-by-file change log is in `docs/05_CHANGE_LOG.md`.
