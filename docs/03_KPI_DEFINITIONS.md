# KPI Definitions — single source of formulas

All KPIs are computed in `backend/app/services/analytics.py` (`block()`, `Analytics.*`) from **`analytics.mv_line_fact`**, which holds one row per active line item. Every module, drill level, export and chatbot answer calls the same functions. `tests/test_03_kpi_api.py::test_same_kpi_same_value_in_every_module` and `test_levels_reconcile` prove that they agree.

Aggregation is always **sum first, then ratio** (Σ functional ÷ Σ required). An average of percentages is never used.

| KPI | Formula | Origin | Edge cases |
|---|---|---|---|
| Required | Σ `Quantity NMC MSR` | 1.0 | blank → 0 |
| Available | Σ `Quantity of Equipment Available` | 1.0 | blank → 0 |
| Functional | Σ `Quantity of Functional Equipment` | 1.0 | blank → 0. Functional > Available is a **warning** (396 rows) |
| **Non-Functional** | Σ Available − Σ Functional | 1.0 (unchanged) | Can be negative where functional > available. Shown as-is, never clamped |
| **Utilisation %** (`gap_pct` = `util_pct`) | Σ Functional ÷ Σ Required × 100, 2 dp | 1.0 (unchanged) | **0 when Σ Required = 0** (as in 1.0). The API also returns `util_defined=false` |
| **Net Requirement** | Σ Required − Σ Functional | 1.0 (unchanged) | + shortfall / − surplus. Surpluses net off against shortfalls when aggregated |
| Functional Shortfall | Σ max(Required − Functional, 0) per line | Referenced by 1.0 (`functional_shortfall`) but never populated | **[DECISION]** Confirm the definition. Units still needed with no netting of surpluses |
| Procurement | Σ `Quantity Proposed for New Procurement` | 1.0 | Outliers > max(500, 10 × required) are flagged, not changed |
| **Budget** | Σ (Proposed procurement × unit cost) | 1.0 (unchanged) | Unit cost comes from the costing list or the line's `Costing` column (consistent per equipment in the workbook). No unit cost → ₹0, listed in the report |
| Total Estimated Cost (Cost Mapping) | Σ over lines with Net Req > 0 of Net Req × unit cost | 1.0 (unchanged) | Reproduces 1.0 exactly: ₹6,311,256,440.63 on 1.0's recovered rows |
| AMC % | Σ AMC/CMC ÷ Σ Functional × 100 | 1.0 | 0 when functional = 0 |
| Func % | Σ Functional ÷ Σ Available × 100 | 1.0 | |
| EoL % | Σ End-of-life ÷ Σ Functional × 100 | 1.0 | |
| Proc % | Σ Procurement ÷ Σ Required × 100 | 1.0 (`proc_pct`) | This is the README's "Gap 126.16%" |
| Medical Colleges | Count of institutes matching Division / Institute / Bedded filters | 1.0 behaviour | Department, equipment and sub-category filters do not reduce it (as in 1.0) |
| Unique Equipment | Count of distinct standardised equipment names in scope | 1.0 | 1,070 workbook spellings → 1,036 after merging case variants (rule A7) |

## Severity bands (unchanged from 1.0 `GAP_BANDS`)

| Band | Utilisation % | Colour |
|---|---|---|
| Adequate | ≥ 100 | #1a9850 |
| Near-adequate | 75 – <100 | #a6d96a |
| Moderate | 50 – <75 | #fee08b |
| Low | 25 – <50 | #fc8d59 |
| Critical | < 25 | #d73027 |

## Decision-support rules used by the AI (all from 1.0 code — nothing invented)

| Rule | Value | Source in 1.0 |
|---|---|---|
| Priority / "immediate procurement" | Critical band (< 25 %) with Net Req > 0, ranked by functional shortfall | `GAP_BANDS` |
| Inadequate AMC/CMC | AMC % < 70 % | `buildAnalysisRecs` |
| Cost tiers | unit cost > ₹1 lakh / > ₹5 lakh / > ₹10 lakh | `cbAnswer` |
| Procurement check | proposal > 1.25 × net need → verify. < 0.75 × net need → under-provision | `cbRecommend` |
| Cost category fallback | Low ≤ ₹1,00,000 < Medium < ₹10,00,000 ≤ High | Observed in the workbook. Used only when the "Cost Category" column is blank (2 rows) |

## Items needing approval (not silently changed)

1. **Functional Shortfall definition** (above).
2. **Inverted severity colours** in 1.0 `buildGroupRecs` / `detailForEquipment`: utilisation ≥ 100 % is shown red ("crit"). This is preserved as-is pending approval.
3. **Merging equipment names that differ only by case**: default ON (`config/ingestion.yaml → merge_case_variants`). Set it to `false` to reproduce 1.0's count.
4. **Which workbook version is authoritative.** See `10_DATA_RECONCILIATION.md`.
5. **"Bedded Capacity" = the workbook's "Seat Capacity" column** (50–250). Confirm it means beds and not MBBS intake.
