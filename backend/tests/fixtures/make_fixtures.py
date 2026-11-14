"""TEST FIXTURE GENERATOR — produces workbooks used ONLY by the automated tests.

Two kinds of fixture are generated:

1. ``legacy_costmap_lines.xlsx`` — REAL line-level rows recovered from MEDD 1.0 (`DATA.cost_map`): the 23,907
   institute × department × equipment rows whose Net Requirement > 0, with their real Required / Available /
   Functional quantities, and the real unit-cost list. Procurement / AMC / EoL / condemnation are not available
   at line level in 1.0 and are left blank. Used to prove the pipeline reproduces 1.0's Cost-Mapping totals
   (Σ net requirement 106,387 · Σ estimated cost ₹6,311,256,440.63).

2. ``synthetic_master_*.xlsx`` — STRUCTURAL fixtures with real master names but SYNTHETIC (random, seeded)
   quantities, plus deliberately injected data-quality problems. These are clearly marked
   "TEST FIXTURE — NOT REAL DATA" in a README sheet and must never be loaded into a production database.
"""
from __future__ import annotations

import gzip
import json
import random
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
REF = HERE.parent.parent / "reference" / "legacy_dashboard_snapshot.json.gz"

INV_HEADERS = ["Sr. No.", "Division", "Name of the Institute", "Department", "Department Type", "Course Category",
               "Sub Category", "Name of Equipment", "Quantity Required as per NMC MSR", "Quantity Available",
               "Quantity Functional", "Quantity Proposed for New Procurement", "Quantity under AMC/CMC",
               "Quantity Approaching End of Life", "Quantity Proposed for Condemnation"]


def _snapshot() -> dict:
    with gzip.open(REF, "rt", encoding="utf-8") as fh:
        return json.load(fh)


def legacy_costmap(out: Path) -> Path:
    D = _snapshot()
    cm = D["cost_map"]
    inst_div = {i["name"]: i["division"] for i in D["institutes"]}
    rows = []
    for n, r in enumerate(cm["rows"], 1):
        inst = cm["inst"][r[2]]
        rows.append([n, inst_div.get(inst, cm["div"][r[1]]), inst, cm["dept"][r[3]], None, None, None, cm["eq"][r[0]],
                     r[4], r[5], r[6], None, None, None, None])
    costs = [[e["name"], e["unit_cost"]] for e in D["equipment_catalog"]]
    p = out / "legacy_costmap_lines.xlsx"
    with pd.ExcelWriter(p, engine="openpyxl") as xw:
        pd.DataFrame([["MEDD 1.0 recovered line-level rows (Net Requirement > 0 only). Test fixture."]],
                     columns=["About"]).to_excel(xw, sheet_name="README", index=False)
        pd.DataFrame(rows, columns=INV_HEADERS).to_excel(xw, sheet_name="Equipment Data", index=False)
        pd.DataFrame(costs, columns=["Unique Equipment Name", "Unit Cost (Rs)"]).to_excel(xw, sheet_name="Unit Cost", index=False)
    return p


def synthetic(out: Path, *, seed: int = 7, institutes: int = 6, depts: int = 5, eq_per_dept: int = 12,
              inject_errors: int = 0, name: str = "synthetic_master.xlsx", with_costs: bool = True,
              bump: float = 0.0, header_row_offset: int = 2) -> Path:
    """Synthetic quantities (seeded). ``bump`` > 0 changes ~that share of rows (to test updates)."""
    rnd = random.Random(seed)
    bump_rnd = random.Random(seed + 1000)   # separate stream so bumping does not change the base data
    D = _snapshot()
    insts = D["institutes"][:institutes]
    depts_all = [d["name"] for d in D["departments"] if not d["name"].startswith(("DM", "M.Ch"))]
    eqs = [e["name"] for e in D["equipment_catalog"] if e.get("unit_cost")]
    rows, n = [], 0
    for i in insts:
        for dp in rnd.sample(depts_all, depts):
            for eq in rnd.sample(eqs, eq_per_dept):
                n += 1
                req = rnd.randint(0, 12)
                av = rnd.randint(0, 14)
                fn = rnd.randint(0, av)
                if bump and bump_rnd.random() < bump:
                    req += 1
                rows.append([n, i["division"], i["name"], dp, rnd.choice(["Clinical", "Non - Clinical"]),
                             rnd.choice(["UG", "PG"]), None, eq, req, av, fn, rnd.randint(0, 4),
                             rnd.randint(0, fn), rnd.randint(0, 1), rnd.randint(0, av - fn)])
    for k in range(inject_errors):
        r = rows[rnd.randrange(len(rows))]
        kind = k % 4
        if kind == 0:
            r[9] = "abc"            # non-numeric quantity -> row rejected
        elif kind == 1:
            r[8] = -3               # negative quantity -> row rejected
        elif kind == 2:
            r[7] = None             # missing equipment -> row rejected
        else:
            r[1] = "Atlantis"       # unknown division -> row rejected
    p = out / name
    with pd.ExcelWriter(p, engine="openpyxl") as xw:
        pd.DataFrame([["TEST FIXTURE — NOT REAL DATA (synthetic quantities, seed=%d)" % seed]],
                     columns=["About"]).to_excel(xw, sheet_name="README", index=False)
        df = pd.DataFrame(rows, columns=INV_HEADERS)
        # put a title block above the header, like a typical government workbook
        title = pd.DataFrame([["MEDD — Equipment Gap Analysis (TEST FIXTURE)"] + [None] * (len(INV_HEADERS) - 1)] +
                             [[None] * len(INV_HEADERS)] * (header_row_offset - 1), columns=INV_HEADERS)
        title.to_excel(xw, sheet_name="Equipment Data", index=False, header=False)
        df.to_excel(xw, sheet_name="Equipment Data", index=False, startrow=header_row_offset)
        if with_costs:
            used = sorted({r[7] for r in rows if r[7]})
            cat = {e["name"]: e["unit_cost"] for e in D["equipment_catalog"]}
            pd.DataFrame([[e, cat.get(e)] for e in used], columns=["Equipment Name", "Unit Cost"]).to_excel(
                xw, sheet_name="Unit Cost", index=False)
    return p


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "generated"
    out.mkdir(parents=True, exist_ok=True)
    print(legacy_costmap(out))
    print(synthetic(out))
