"""KPI formulas, cross-module consistency, filters, drill-downs, exports and security."""
import pytest

from app.services.analytics import block, pct
from app.ingestion.pipeline import process_file
from tests.conftest import copy_to_tmp, login, reset_production
from tests.fixtures import make_fixtures as mk

API = "/api/v1"


@pytest.fixture(scope="module", autouse=True)
def loaded(fixtures_dir):
    reset_production()
    p = mk.synthetic(fixtures_dir, name="kpi_set.xlsx", institutes=12, depts=6, eq_per_dept=10, seed=11)
    assert process_file(copy_to_tmp(p), "test")["status"].startswith("SUCCESS")
    yield


# ---------------------------------------------------------------- formulas
def test_formula_definitions():
    b = block({"required": 200, "available": 150, "functional": 120, "procurement": 40, "budget": 1000.0,
               "amc": 60, "end_of_life": 12, "condemnation": 3})
    assert b["non_functional"] == 30                 # available - functional
    assert b["net_requirement"] == 80                # required - functional
    assert b["gap_pct"] == b["util_pct"] == 60.0     # functional / required * 100
    assert b["amc_pct"] == 50.0 and b["func_pct"] == 80.0 and b["eol_pct"] == 10.0 and b["proc_pct"] == 20.0


def test_zero_denominators():
    b = block({"required": 0, "available": 0, "functional": 3})
    assert b["gap_pct"] == 0 and b["util_defined"] is False and b["func_pct"] == 0
    assert pct(5, 0) == 0.0


def test_surplus_gives_negative_net_requirement():
    b = block({"required": 10, "functional": 25, "available": 30})
    assert b["net_requirement"] == -15 and b["gap_pct"] == 250.0


# ---------------------------------------------------------------- consistency across levels & modules
def test_levels_reconcile(client, admin_h):
    s = client.get(f"{API}/kpis/summary", headers=admin_h).json()
    for level in ("division", "institute", "department", "equipment"):
        rows = client.get(f"{API}/kpis/breakdown", headers=admin_h, params={"level": level, "per": 2000}).json()["rows"]
        for k in ("required", "available", "functional", "procurement", "amc", "end_of_life", "condemnation"):
            assert sum(r[k] for r in rows) == s[k], (level, k)
        assert sum(r["budget"] for r in rows) == pytest.approx(s["budget"], abs=1)


def test_division_equals_sum_of_its_institutes(client, admin_h):
    divs = client.get(f"{API}/divisions", headers=admin_h).json()["rows"]
    for d in divs:
        insts = client.get(f"{API}/institutes", headers=admin_h, params={"division": d["name"], "per": 500}).json()["rows"]
        assert sum(i["required"] for i in insts) == d["required"]
        assert sum(i["functional"] for i in insts) == d["functional"]


def test_same_kpi_same_value_in_every_module(client, admin_h):
    params = {"division": "Pune"}
    s = client.get(f"{API}/kpis/summary", headers=admin_h, params=params).json()
    scope = client.get(f"{API}/dashboard/scope", headers=admin_h, params=params).json()["summary"]
    for m in ("gap", "procurement", "net-requirement", "financial", "condemnation", "end-of-life", "amc"):
        ms = client.get(f"{API}/modules/{m}", headers=admin_h, params=params).json()["summary"]
        for k in ("required", "functional", "gap_pct", "procurement", "budget", "net_requirement"):
            assert ms[k] == s[k] == scope[k], (m, k)


def test_bootstrap_contract_and_values(client, admin_h):
    d = client.get(f"{API}/dashboard/bootstrap", headers=admin_h).json()
    for key in ("overview", "divisions", "institutes", "departments", "state_depts", "equipment_catalog", "equipment_names",
                "equipment_div_map", "eq_index", "bedded_capacities", "cost_category", "course_category",
                "department_type", "sub_categories", "map", "meta"):
        assert key in d
    s = client.get(f"{API}/kpis/summary", headers=admin_h).json()
    assert d["overview"]["required"] == s["required"] and d["overview"]["budget"] == pytest.approx(s["budget"])
    assert len(d["divisions"]) == 6 and len(d["map"]["districts"]) == 35
    assert sum(x["required"] for x in d["divisions"]) == s["required"]


def test_filters_combine_exactly(client, admin_h):
    boot = client.get(f"{API}/dashboard/bootstrap", headers=admin_h).json()
    inst = boot["institutes"][0]
    dept = inst["departments"][0]
    eq = dept["top_equipment"][0]
    r = client.get(f"{API}/kpis/summary", headers=admin_h,
                   params={"institute": inst["name"], "department": dept["name"], "equipment": eq["name"]}).json()
    assert r["required"] == eq["required"] and r["functional"] == eq["functional"]


def test_drill_parent_equals_children(client, admin_h):
    d = client.get(f"{API}/drill", headers=admin_h, params={"level": "institute", "path": "Pune"}).json()
    assert d["parent"]["required"] == sum(r["required"] for r in d["rows"])
    inst = d["rows"][0]["name"]
    d2 = client.get(f"{API}/drill", headers=admin_h, params={"level": "department", "path": f"Pune||{inst}"}).json()
    dep = d2["rows"][0]["name"]
    d3 = client.get(f"{API}/drill", headers=admin_h, params={"level": "equipment", "path": f"Pune||{inst}||{dep}"}).json()
    assert d3["parent"]["required"] == sum(r["required"] for r in d3["rows"]) == d2["rows"][0]["required"]


def test_pagination_and_sorting(client, admin_h):
    a = client.get(f"{API}/equipment", headers=admin_h, params={"per": 10, "page": 0, "sort": "required", "dir": "desc"}).json()
    b = client.get(f"{API}/equipment", headers=admin_h, params={"per": 10, "page": 1, "sort": "required", "dir": "desc"}).json()
    assert len(a["rows"]) == 10 and a["rows"][-1]["required"] >= b["rows"][0]["required"]
    cm = client.get(f"{API}/net-requirement/cost-mapping", headers=admin_h, params={"per": 7, "sort": "netreq", "dir": "desc"}).json()
    assert len(cm["rows"]) == 7 and all(r["netreq"] > 0 for r in cm["rows"])


def test_exports(client, admin_h):
    r = client.get(f"{API}/exports/cost-mapping", headers=admin_h, params={"format": "csv"})
    assert r.status_code == 200 and "Total Estimated Cost" in r.text
    r = client.get(f"{API}/exports/cost-mapping", headers=admin_h, params={"format": "xlsx"})
    assert r.status_code == 200 and r.content[:2] == b"PK"
    r = client.get(f"{API}/exports/institute", headers=admin_h)
    assert r.status_code == 200 and r.text.count("\n") > 5


# ---------------------------------------------------------------- security
def test_requires_authentication(client):
    assert client.get(f"{API}/dashboard/bootstrap").status_code == 401
    assert client.get(f"{API}/kpis/summary", headers={"Authorization": "Bearer forged.token.value"}).status_code == 401
    assert client.get("/api/health").status_code == 200


def test_wrong_password_and_lockout(client):
    for _ in range(5):
        assert client.post(f"{API}/auth/login", json={"username": "t_analyst", "password": "nope"}).status_code == 401
    assert client.post(f"{API}/auth/login", json={"username": "t_analyst", "password": "Test-Password-2026"}).status_code == 423
    from sqlalchemy import text
    from app.db.session import write_tx
    with write_tx() as db:
        db.execute(text("UPDATE metadata.app_user SET locked_until=NULL, failed_logins=0 WHERE username='t_analyst'"))


def test_viewer_cannot_see_financials_or_export_or_ingest(client):
    h = login(client, "t_viewer")
    boot = client.get(f"{API}/dashboard/bootstrap", headers=h).json()
    assert boot["overview"]["budget"] is None and boot["equipment_catalog"][0]["unit_cost"] is None
    assert client.get(f"{API}/modules/financial", headers=h).status_code == 403
    assert client.get(f"{API}/exports/cost-mapping", headers=h).status_code == 403
    assert client.get(f"{API}/ingestion/files", headers=h).status_code == 403
    assert client.post(f"{API}/ingestion/rescan", headers=h).status_code == 403
    assert client.get(f"{API}/admin/users", headers=h).status_code == 403


def test_analyst_cannot_modify_data(client):
    h = login(client, "t_analyst")
    assert client.get(f"{API}/ingestion/files", headers=h).status_code == 200
    r = client.post(f"{API}/ingestion/upload", headers=h, files={"file": ("x.csv", b"a,b\n1,2\n")})
    assert r.status_code == 403


def test_division_scoped_user_sees_only_their_division(client):
    h = login(client, "t_pune")
    boot = client.get(f"{API}/dashboard/bootstrap", headers=h).json()
    assert {d["name"] for d in boot["divisions"]} == {"Pune"}
    assert all(i["division"] == "Pune" for i in boot["institutes"])
    r = client.get(f"{API}/kpis/summary", headers=h, params={"division": "Nagpur"}).json()
    assert r["required"] == 0      # cannot widen scope via filters
    chat = client.post(f"{API}/chat", headers=h, json={"question": "summary"}).json()
    assert "permitted divisions" in chat["scope"]


def test_sql_injection_is_inert(client, admin_h):
    evil = "Pune'; DROP TABLE master_data.division; --"
    r = client.get(f"{API}/kpis/summary", headers=admin_h, params={"division": evil})
    assert r.status_code == 200 and r.json()["required"] == 0
    r = client.get(f"{API}/equipment", headers=admin_h, params={"q": "%' OR 1=1 --", "sort": "name; DROP TABLE x"})
    assert r.status_code == 200
    r = client.post(f"{API}/chat", headers=admin_h, json={"question": "'; DELETE FROM equipment_inventory.line_item; --"})
    assert r.status_code == 200
    assert client.get(f"{API}/divisions", headers=admin_h).json()["rows"]


def test_upload_validation(client):
    h = login(client, "t_manager")
    assert client.post(f"{API}/ingestion/upload", headers=h, files={"file": ("evil.exe", b"MZ")}).status_code == 400


def test_security_headers(client):
    r = client.get("/api/health")
    assert r.headers["x-content-type-options"] == "nosniff" and "frame-ancestors" in r.headers["content-security-policy"]
