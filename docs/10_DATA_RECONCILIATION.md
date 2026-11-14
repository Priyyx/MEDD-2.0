# Data Reconciliation — master workbook vs MEDD 1.0 dashboard vs MEDD 2.0 database

**Workbook:** `Medical_Equipment_Gap_Analysis_Master_Data.xlsx`. It has one sheet (`Sheet4`) with 52,036 rows and 21 columns. It was supplied for reference on 12 Nov 2026.

## 1. Ingestion result (MEDD 2.0)

| Item | Result |
|---|---|
| Sheet detected | `Sheet4` → inventory. Header row 1. **All 17 data columns mapped automatically**. The 3 instruction/remarks columns are kept in `staging.inventory_row.raw` |
| Rows read / accepted / rejected | **52,036 / 52,036 / 0** |
| Line items inserted | 52,036 (in about 40 s) |
| Warnings (row still loaded) | 2,230: 784 repeated line keys, 478 condemnation > non-functional, 396 functional > available, 348 exact duplicate rows, 199 AMC > functional, **23 procurement outliers**, 1 bedded-capacity mismatch with 1.0 master, 1 summary of equipment with procurement but no unit cost |

## 2. Database totals = workbook totals (exact)

| Measure | Workbook (pandas) | PostgreSQL (MEDD 2.0) | MEDD 1.0 embedded | README |
|---|---|---|---|---|
| Line items | 52,036 | 52,036 | 52,036 | — |
| Required (NMC MSR) | 193,398 | 193,398 | 194,181 | — |
| Available | 393,109 | 393,109 | 393,096 | — |
| Functional | 370,004 | 370,004 | 369,992 | — |
| Proposed procurement | 244,000 | 244,000 | 197,619 | — |
| **Budget** | **₹6,139,631,348.38** | **₹6,139,631,348.38** | ₹4,377,983,348.38 | **₹6,139,631,348** |
| AMC/CMC | 237,158 | 237,158 | 237,156 | — |
| Condemnation | 7,020 | 7,020 | 7,018 | — |
| End of life | 2,893 | 2,893 | 2,891 | — |
| Utilisation % | 191.32 | 191.32 | 190.54 | — |
| Procurement ÷ Required | **126.16 %** | 126.16 % | 101.77 % | **"Gap 126.16 %"** |

**Conclusion.** The README figures were produced from this workbook. The README's "Gap" is Procurement ÷ Required, an older definition. The live 1.0 site was built from a **revised** version of the workbook.

## 3. Where 1.0 and this workbook differ (institute level, all 35 compared)

| Institute | Required | Available | Functional | Procurement | Budget |
|---|---|---|---|---|---|
| Government Medical College, Chh. Sambhaji Nagar | — | — | — | **+46,292** | **+₹175.9 Cr** |
| Government Medical College, Nashik | −733 | — | — | — | — |
| SRTR GMC, Ambajogai | −50 | +13 | +12 | +89 | +₹25.5 lakh |

The other **32 institutes match 1.0 exactly** on all five measures.

The large difference comes from one row: **"Calorimeter / Spectrophotometer", 46,297 units × ₹38,000** at GMC Chh. Sambhaji Nagar (Excel row 14,450). It is almost certainly a data-entry error that was corrected before 1.0 was published. MEDD 2.0 **flags it as `PROCUREMENT_OUTLIER` and does not alter it**.

A test copy with that single cell changed to 5 was ingested. Only that row was updated (1 updated, 52,035 unchanged, 0 inserted or deactivated), and division procurement dropped by exactly 46,292.

## 4. Reconciliation of the 1.0 Cost-Mapping logic

The 23,907 line-level rows recoverable from 1.0's `cost_map` were ingested as a fixture. The 2.0 Cost Mapping API returns:

- Σ Net Requirement = **106,387**, identical to 1.0
- Σ Total Estimated Cost = **₹6,311,256,440.63**, identical to 1.0

This is a permanent automated test (`test_legacy_costmap_lines_reproduce_medd1_totals`).

## 5. Live reconciliation screen

**Data Management → KPI reconciliation vs MEDD 1.0** (API: `GET /api/v1/reconciliation?level=overview|division|institute|department|equipment`) compares the database with the 1.0 figures at every level. It highlights each difference.

## 6. Decision requested

Which workbook should be the production baseline?

- **(a)** This workbook as supplied (matches the README).
- **(b)** The corrected version used for the live 1.0 site (requires that file).
- **(c)** This workbook plus targeted corrections. Corrections should be made in the Excel, then re-uploaded. Only the changed rows update, and the change is fully audited.
