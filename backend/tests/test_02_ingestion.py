"""Excel ingestion: detection, validation, staging, UPSERT, idempotency, duplicates, rollback, failure isolation."""
import json
import shutil
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import text

from app.db.session import read_engine, write_engine
from app.ingestion.pipeline import FatalIngestionError, process_file, revert_file
from tests.conftest import copy_to_tmp
from tests.fixtures import make_fixtures as mk

pytestmark = pytest.mark.usefixtures("clean_db")


def totals():
    with read_engine.connect() as c:
        return dict(c.execute(text("""SELECT count(*) n, COALESCE(sum(required),0) req, COALESCE(sum(available),0) av,
            COALESCE(sum(functional),0) fn, COALESCE(sum(procurement),0) pr, COALESCE(sum(budget),0)::float8 bud,
            COALESCE(sum(amc),0) amc, COALESCE(sum(end_of_life),0) eol, COALESCE(sum(condemnation),0) co
            FROM analytics.mv_line_fact""")).one()._mapping)


def expected_from_file(path: Path) -> dict:
    df = pd.read_excel(path, sheet_name="Equipment Data", header=2)
    costs = pd.read_excel(path, sheet_name="Unit Cost").set_index("Equipment Name")["Unit Cost"].to_dict()
    df["uc"] = df["Name of Equipment"].map(costs).fillna(0)
    return {"n": len(df), "req": int(df["Quantity Required as per NMC MSR"].sum()),
            "av": int(df["Quantity Available"].sum()), "fn": int(df["Quantity Functional"].sum()),
            "pr": int(df["Quantity Proposed for New Procurement"].sum()),
            "bud": float((df["Quantity Proposed for New Procurement"] * df["uc"]).sum()),
            "amc": int(df["Quantity under AMC/CMC"].sum()), "eol": int(df["Quantity Approaching End of Life"].sum()),
            "co": int(df["Quantity Proposed for Condemnation"].sum())}


def test_synthetic_workbook_loads_and_reconciles(fixtures_dir, settings):
    p = mk.synthetic(fixtures_dir, name="syn_a.xlsx")
    res = process_file(copy_to_tmp(p), "test")
    assert res["status"].startswith("SUCCESS"), res
    exp = expected_from_file(p)
    got = totals()
    for k in exp:
        assert got[k] == pytest.approx(exp[k]), k
    assert res["counts"]["rows_inserted"] == exp["n"]
    # file moved to processed + archived, report written
    assert any(settings.processed_dir.iterdir())
    assert any(settings.archive_dir.rglob("*syn_a.xlsx"))
    assert Path(res["report"]).exists()
    # staging kept with VALID rows and traceable raw data
    with read_engine.connect() as c:
        pass
    with write_engine.connect() as c:
        st = dict(c.execute(text("SELECT status, count(*) FROM staging.inventory_row GROUP BY status")).all())
        assert st.get("VALID") == exp["n"]
        raw = c.execute(text("SELECT raw FROM staging.inventory_row LIMIT 1")).scalar()
        assert "Name of Equipment" in raw


def test_identical_file_is_skipped_as_duplicate(fixtures_dir):
    p = mk.synthetic(fixtures_dir, name="syn_b.xlsx")
    process_file(copy_to_tmp(p), "test")
    before = totals()
    res = process_file(copy_to_tmp(p), "test")
    assert res["status"] == "DUPLICATE"
    assert totals() == before


def test_resaved_same_content_is_idempotent(fixtures_dir):
    p = mk.synthetic(fixtures_dir, name="syn_c.xlsx")
    process_file(copy_to_tmp(p), "test")
    before = totals()
    p2 = fixtures_dir / "syn_c_resaved.xlsx"
    book = pd.read_excel(p, sheet_name=None, header=None)
    with pd.ExcelWriter(p2) as xw:
        for k, v in book.items():
            v.to_excel(xw, sheet_name=k, index=False, header=False)
        pd.DataFrame([["resaved"]]).to_excel(xw, sheet_name="Notes", index=False)
    res = process_file(copy_to_tmp(p2), "test")
    assert res["status"].startswith("SUCCESS")
    assert res["counts"]["rows_inserted"] == 0 and res["counts"]["rows_updated"] == 0
    assert res["counts"]["rows_unchanged"] == before["n"]
    assert totals() == before


def test_changed_values_are_updated_with_history(fixtures_dir):
    process_file(copy_to_tmp(mk.synthetic(fixtures_dir, name="syn_d.xlsx")), "test")
    p2 = mk.synthetic(fixtures_dir, name="syn_d2.xlsx", bump=0.2)
    res = process_file(copy_to_tmp(p2), "test")
    assert res["counts"]["rows_updated"] > 0 and res["counts"]["rows_inserted"] == 0
    with write_engine.connect() as c:
        n = c.execute(text("SELECT count(*) FROM audit.line_item_history WHERE file_id=:f AND change_type='UPDATE'"),
                      {"f": res["file_id"]}).scalar()
    assert n == res["counts"]["rows_updated"]
    assert totals()["req"] == expected_from_file(p2)["req"]


def test_failed_file_never_touches_production(fixtures_dir, settings):
    process_file(copy_to_tmp(mk.synthetic(fixtures_dir, name="syn_e.xlsx")), "test")
    before = totals()
    bad = mk.synthetic(fixtures_dir, name="syn_bad.xlsx", seed=99, inject_errors=60)   # ~17% rejected > 5%
    res = process_file(copy_to_tmp(bad), "test")
    assert res["status"] == "FAILED"
    assert "threshold" in res["error_message"]
    assert totals() == before
    failed = list(settings.failed_dir.iterdir())
    assert any(f.name.endswith("syn_bad.xlsx") for f in failed)
    assert any(f.name.endswith(".error.txt") for f in failed)
    with write_engine.connect() as c:
        codes = {r[0] for r in c.execute(text("SELECT DISTINCT code FROM metadata.validation_issue WHERE file_id=:f"),
                                         {"f": res["file_id"]})}
    assert {"INVALID_QUANTITY", "MISSING_REQUIRED", "UNKNOWN_DIVISION"} <= codes


def test_few_bad_rows_are_rejected_but_file_succeeds(fixtures_dir):
    p = mk.synthetic(fixtures_dir, name="syn_f.xlsx", seed=5, inject_errors=4)
    res = process_file(copy_to_tmp(p), "test")
    assert res["status"] == "SUCCESS_WITH_WARNINGS"
    assert 1 <= res["counts"]["rows_rejected"] <= 4
    assert totals()["n"] == res["counts"]["rows_inserted"]


def test_snapshot_mode_deactivates_missing_rows_and_rollback(fixtures_dir):
    p = mk.synthetic(fixtures_dir, name="syn_g.xlsx", institutes=2)
    process_file(copy_to_tmp(p), "test")
    full = totals()
    df = pd.read_excel(p, sheet_name="Equipment Data", header=2)
    first_inst = df["Name of the Institute"].iloc[0]
    sub = df[(df["Name of the Institute"] != first_inst) | (df.index % 2 == 0)]
    p2 = fixtures_dir / "syn_g_subset.csv"
    sub.to_csv(p2, index=False)
    res = process_file(copy_to_tmp(p2), "test")
    assert res["status"].startswith("SUCCESS")
    assert res["counts"]["rows_deactivated"] == len(df) - len(sub)
    assert totals()["n"] == len(sub)
    out = revert_file(res["file_id"], "test")
    assert out["changes_reverted"] >= len(df) - len(sub)
    assert totals()["n"] == full["n"] and totals()["req"] == full["req"]


def test_rollback_only_latest(fixtures_dir):
    a = process_file(copy_to_tmp(mk.synthetic(fixtures_dir, name="syn_h.xlsx")), "test")
    process_file(copy_to_tmp(mk.synthetic(fixtures_dir, name="syn_h2.xlsx", bump=0.1)), "test")
    with pytest.raises(FatalIngestionError):
        revert_file(a["file_id"], "test")


def test_json_and_csv_supported(fixtures_dir):
    p = mk.synthetic(fixtures_dir, name="syn_i.xlsx", institutes=1)
    df = pd.read_excel(p, sheet_name="Equipment Data", header=2)
    jp = fixtures_dir / "syn_i.json"
    jp.write_text(json.dumps({"sheets": {"inventory": json.loads(df.to_json(orient="records"))}}))
    res = process_file(copy_to_tmp(jp), "test")
    assert res["status"].startswith("SUCCESS") and res["counts"]["rows_inserted"] == len(df)


def test_unrecognised_workbook_fails_cleanly(fixtures_dir):
    p = fixtures_dir / "random.xlsx"
    pd.DataFrame({"foo": [1, 2], "bar": [3, 4]}).to_excel(p, index=False)
    res = process_file(copy_to_tmp(p), "test")
    assert res["status"] == "FAILED" and "No worksheet matched" in res["error_message"]


def test_unsupported_extension_goes_to_failed(fixtures_dir, settings):
    p = fixtures_dir / "notes.txt"
    p.write_text("hello")
    res = process_file(copy_to_tmp(p), "test")
    assert res["status"] == "FAILED"
    assert (settings.failed_dir / "notes.txt").exists()


def test_new_institute_created_with_division_and_alias_standardisation(fixtures_dir):
    df = pd.DataFrame([{"Division": "Chhatrapati Sambhaji Nagar", "Institute Name": "New Test Medical College, Jalna",
                        "Department": "anatomy ", "Equipment List": "ABG MACHINE", "Quantity NMC MSR": 2,
                        "Quantity of Equipment Available": 1, "Quantity of Functional Equipment": 1, "Costing": 215000}])
    p = fixtures_dir / "new_inst.xlsx"
    df.to_excel(p, index=False)
    res = process_file(copy_to_tmp(p), "test")
    assert res["status"].startswith("SUCCESS"), res
    with read_engine.connect() as c:
        r = c.execute(text("SELECT division, department, equipment FROM analytics.mv_line_fact")).one()
    assert r.division == "Chh. Sambhaji Nagar"          # alias rule
    assert r.department == "Anatomy"                    # case-insensitive match to master
    assert r.equipment.lower() == "abg machine"          # case variants merged


def test_legacy_costmap_lines_reproduce_medd1_totals(fixtures_dir, client, admin_h):
    """REAL 1.0 line-level rows -> the 2.0 Cost Mapping table must reproduce 1.0's totals exactly."""
    p = mk.legacy_costmap(fixtures_dir)
    res = process_file(copy_to_tmp(p), "test")
    assert res["status"].startswith("SUCCESS") and res["counts"]["rows_inserted"] == 23907
    r = client.get("/api/v1/net-requirement/cost-mapping", headers=admin_h, params={"per": 5}).json()
    assert 23800 < r["total"] <= 23907   # rows differing only by equipment-name case are grouped (rule A7)
    assert r["net_requirement_total"] == 106387
    assert r["grand_total"] == pytest.approx(6311256440.63, abs=0.01)
