"""Optional: reconcile the REAL master workbook end-to-end.
Runs only when MEDD_MASTER_XLSX points to "Medical_Equipment_Gap_Analysis_Master_Data.xlsx" (or a newer version)."""
import os
from pathlib import Path

import pandas as pd
import pytest

from app.ingestion.pipeline import process_file
from tests.conftest import copy_to_tmp, reset_production

MASTER = os.getenv("MEDD_MASTER_XLSX")
pytestmark = pytest.mark.skipif(not MASTER or not Path(MASTER).exists(), reason="MEDD_MASTER_XLSX not provided")


def test_master_workbook_totals_match_source(client, admin_h):
    reset_production()
    df = pd.read_excel(MASTER, dtype=object)
    num = lambda c: pd.to_numeric(df[c], errors="coerce").fillna(0)  # noqa: E731
    exp = {"required": num("Quantity NMC MSR").sum(), "available": num("Quantity of Equipment Available").sum(),
           "functional": num("Quantity of Functional Equipment").sum(),
           "procurement": num("Quantity Proposed for New Procurement").sum(),
           "condemnation": num("Quantity Proposed for Condemnation").sum(),
           "amc": num("Quantity under active AMC/CMC").sum(),
           "budget": (num("Quantity Proposed for New Procurement") * num("Costing")).sum()}
    res = process_file(copy_to_tmp(Path(MASTER)), "test")
    assert res["status"].startswith("SUCCESS") and res["counts"]["rows_rejected"] == 0
    assert res["counts"]["rows_inserted"] == len(df)
    s = client.get("/api/v1/kpis/summary", headers=admin_h).json()
    for k, v in exp.items():
        assert s[k] == pytest.approx(v, abs=0.01), k
    assert s["line_items"] == len(df) and s["college_count"] == df["Institute Name"].nunique()
