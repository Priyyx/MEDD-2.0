"""Builds the dashboard bootstrap payload from PostgreSQL.

The payload keeps the exact contract of MEDD 1.0's embedded ``DATA`` object (see docs/01_SOURCE_CODE_AUDIT.md §2.1)
so every existing renderer, drill-down and filter keeps working unchanged — but every value is now computed live
from ``analytics.mv_line_fact``. ``cost_map`` is no longer embedded (served paginated by the API).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

import pandas as pd
from sqlalchemy import text

from app.db.session import read_engine
from app.security.auth import CurrentUser
from app.services.analytics import block, data_status

MEASURES = ["required", "available", "functional", "non_functional", "procurement", "budget", "amc", "condemnation",
            "end_of_life", "functional_shortfall"]


def _agg(df: pd.DataFrame, by: list[str]) -> pd.DataFrame:
    g = df.groupby(by, dropna=False, sort=False)
    out = g[MEASURES].sum()
    out["college_count"] = g["institute"].nunique()
    out["equipment_types"] = g["equipment"].nunique()
    out["line_items"] = g["lines"].sum()
    out["lines"] = out["line_items"]
    return out.reset_index()


def _blocks(df: pd.DataFrame, name_col: str, fin: bool, extra: list[str] = ()) -> list[dict]:
    out = []
    for r in df.to_dict("records"):
        b = block(r, financial=fin)
        b["name"] = r[name_col]
        for e in extra:
            b[e] = r.get(e)
        out.append(b)
    return out


def _eq_block(r: dict, fin: bool) -> dict:
    b = block(r, financial=fin)
    keep = ["name", "procurement", "budget", "required", "available", "functional", "end_of_life", "amc",
            "condemnation", "non_functional", "net_requirement", "amc_pct", "gap_pct", "functional_shortfall"]
    b["name"] = r["equipment"]
    return {k: b[k] for k in keep}


def _top(df: pd.DataFrame, n: int, fin: bool) -> list[dict]:
    d = df.sort_values(["procurement", "budget"], ascending=[False, False]).head(n)
    return [_eq_block(r, fin) for r in d.to_dict("records")]


def build(user: CurrentUser) -> dict:
    fin = user.can("financial:read")
    where, params = "TRUE", {}
    if user.allowed_divisions is not None:
        where, params = "division = ANY(:d)", {"d": list(user.allowed_divisions)}
    with read_engine.connect() as c:
        df = pd.read_sql(text(f"""
            SELECT division, institute, bedded_capacity, department, equipment, sub_category,
                   sum(required) required, sum(available) available, sum(functional) functional,
                   sum(non_functional) non_functional, sum(procurement) procurement, sum(budget)::float8 budget,
                   sum(amc) amc, sum(condemnation) condemnation, sum(end_of_life) end_of_life,
                   sum(functional_shortfall) functional_shortfall, max(unit_cost)::float8 unit_cost, count(*) lines
            FROM analytics.mv_line_fact WHERE {where}
            GROUP BY division, institute, bedded_capacity, department, equipment, sub_category"""), c, params=params)
        cats = {k: [dict(r._mapping) for r in c.execute(text(
            f"SELECT {k} AS name, count(*) AS count FROM analytics.mv_line_fact WHERE {where} AND {k} IS NOT NULL "
            f"GROUP BY {k} ORDER BY count DESC"), params)]
            for k in ("cost_category", "course_category", "department_type")}
        all_divs = [dict(r._mapping) for r in c.execute(text(
            "SELECT name, map_key, map_cx::float8 cx, map_cy::float8 cy FROM master_data.division ORDER BY name"))]
        districts = [dict(r._mapping) for r in c.execute(text(
            """SELECT d.name, v.map_key AS division, d.svg_path AS d, d.label_x::float8 cx, d.label_y::float8 cy
               FROM master_data.district d JOIN master_data.division v ON v.id=d.division_id ORDER BY d.id"""))]
        mapdim = c.execute(text("SELECT value FROM metadata.app_setting WHERE key='map'")).scalar() or {}
        status = data_status(c)
    if user.allowed_divisions is not None:
        all_divs = [d for d in all_divs if d["name"] in user.allowed_divisions]

    for m in MEASURES + ["lines"]:
        if m in df:
            df[m] = df[m].fillna(0)
    df["sub_category"] = df["sub_category"].astype(object).where(df["sub_category"].notna(), None)

    # equipment-level frame (sub-category collapsed)
    eqf = _agg(df, ["division", "institute", "bedded_capacity", "department", "equipment"])

    # ---------------- overview
    ov_row = _agg(df.assign(_all=1), ["_all"]).to_dict("records")[0] if len(df) else {}
    overview = block(ov_row, financial=fin)
    overview.update({"college_count": int(df["institute"].nunique()) if len(df) else 0,
                     "divisions": len(all_divs), "department_count": int(df["department"].nunique()) if len(df) else 0,
                     "equipment_types": int(df["equipment"].nunique()) if len(df) else 0,
                     "line_items": int(df["lines"].sum()) if len(df) else 0})

    # ---------------- equipment rollups
    cat_df = _agg(df, ["equipment"])
    uc = df.groupby("equipment")["unit_cost"].max() if len(df) else pd.Series(dtype=float)
    catalog = []
    for r in cat_df.sort_values(["procurement", "budget"], ascending=[False, False]).to_dict("records"):
        e = _eq_block(r, fin)
        v = uc.get(r["equipment"])
        e["unit_cost"] = (float(v) if v is not None and not pd.isna(v) else 0.0) if fin else None
        catalog.append(e)
    names = sorted(cat_df["equipment"].tolist(), key=str) if len(df) else []
    idx = {n: i for i, n in enumerate(names)}

    # ---------------- divisions
    div_df = _agg(df, ["division"]).set_index("division") if len(df) else pd.DataFrame()
    div_dept = _agg(df, ["division", "department"]) if len(df) else pd.DataFrame()
    div_inst = _agg(df, ["division", "institute"]) if len(df) else pd.DataFrame()
    div_eq = _agg(eqf, ["division", "equipment"]) if len(df) else pd.DataFrame()
    divisions = []
    for d in all_divs:
        n = d["name"]
        r = div_df.loc[n].to_dict() if len(df) and n in div_df.index else {}
        b = block(r, financial=fin)
        b["name"] = n
        if len(df):
            dd = div_dept[div_dept["division"] == n].sort_values("procurement", ascending=False)
            di = div_inst[div_inst["division"] == n]
            b["departments"] = _blocks(dd, "department", fin)
            b["institutes"] = sorted(_blocks(di, "institute", fin), key=lambda x: -x["net_requirement"])
            b["top_equipment"] = _top(div_eq[div_eq["division"] == n], 15, fin)
        else:
            b["departments"], b["institutes"], b["top_equipment"] = [], [], []
        divisions.append(b)

    # ---------------- institutes
    institutes = []
    if len(df):
        inst_df = _agg(df, ["division", "institute", "bedded_capacity"])
        inst_dept = _agg(eqf, ["institute", "department"])
        inst_eq = _agg(eqf, ["institute", "equipment"])
        # top-N per group computed once with vectorised sort + head (fast for 50k+ lines)
        ide_top = (_agg(eqf, ["institute", "department", "equipment"])
                   .sort_values(["procurement", "budget"], ascending=[False, False])
                   .groupby(["institute", "department"], sort=False).head(12))
        ide_map = {k: [_eq_block(r, fin) for r in g.to_dict("records")]
                   for k, g in ide_top.groupby(["institute", "department"], sort=False)}
        ie_top = inst_eq.sort_values(["procurement", "budget"], ascending=[False, False]).groupby("institute", sort=False).head(15)
        ie_map = {k: [_eq_block(r, fin) for r in g.to_dict("records")] for k, g in ie_top.groupby("institute", sort=False)}
        idep_map = {k: g.sort_values("procurement", ascending=False)
                    for k, g in inst_dept.groupby("institute", sort=False)}
        for r in inst_df.sort_values("institute").to_dict("records"):
            n = r["institute"]
            b = block(r, financial=fin)
            b.update({"name": n, "division": r["division"],
                      "seat": None if pd.isna(r["bedded_capacity"]) else int(r["bedded_capacity"])})
            deps = []
            for dr in idep_map.get(n, pd.DataFrame()).to_dict("records"):
                db_ = block(dr, financial=fin)
                db_["name"] = dr["department"]
                db_["top_equipment"] = ide_map.get((n, dr["department"]), [])
                deps.append(db_)
            b["departments"] = deps
            b["top_equipment"] = ie_map.get(n, [])
            institutes.append(b)

    # ---------------- departments (state-wide) with division / institute breakdowns
    departments, state_depts = [], []
    if len(df):
        dep_df = _agg(df, ["department"]).sort_values("procurement", ascending=False)
        dep_div = _agg(df, ["department", "division"])
        dep_inst = _agg(df, ["department", "institute", "division"])
        dep_eq = _agg(eqf, ["department", "equipment"])
        for r in dep_df.to_dict("records"):
            n = r["department"]
            b = block(r, financial=fin)
            b["name"] = n
            state_depts.append(dict(b))
            b["divisions_bd"] = sorted(_blocks(dep_div[dep_div["department"] == n], "division", fin), key=lambda x: x["name"])
            b["institutes"] = sorted(_blocks(dep_inst[dep_inst["department"] == n], "institute", fin, ["division"]),
                                     key=lambda x: -x["net_requirement"])
            b["top_equipment"] = _top(dep_eq[dep_eq["department"] == n], 15, fin)
            departments.append(b)

    # ---------------- equipment × division map (used by the heat map under equipment / sub-category filters)
    eq_div_map: dict = {}
    if len(df):
        for r in div_eq.to_dict("records"):
            req, fn = int(r["required"]), int(r["functional"])
            eq_div_map.setdefault(r["equipment"], {})[r["division"]] = {
                "r": req, "f": fn, "p": int(r["procurement"]), "b": (round(float(r["budget"]), 2) if fin else None),
                "n": req - fn, "g": round(fn * 100 / req, 2) if req else 0.0}
        zero = {"r": 0, "f": 0, "p": 0, "b": 0 if fin else None, "n": 0, "g": 0.0}
        for e in eq_div_map.values():
            for d in all_divs:
                e.setdefault(d["name"], dict(zero))

    # ---------------- equipment index (unique-equipment KPI + filter cascades) — complete, not truncated
    eq_index = {"names": names, "inst": defaultdict(set), "dept": defaultdict(set), "div": defaultdict(set),
                "instdept": defaultdict(lambda: defaultdict(set)), "subcat": defaultdict(set)}
    for r in df[["division", "institute", "department", "equipment", "sub_category"]].itertuples(index=False):
        i = idx[r.equipment]
        eq_index["inst"][r.institute].add(i)
        eq_index["dept"][r.department].add(i)
        eq_index["div"][r.division].add(i)
        eq_index["instdept"][r.institute][r.department].add(i)
        if r.sub_category:
            eq_index["subcat"][r.sub_category].add(i)
    for k in ("inst", "dept", "div", "subcat"):
        eq_index[k] = {n: sorted(v) for n, v in eq_index[k].items()}
    eq_index["instdept"] = {i: {d: sorted(v) for d, v in dd.items()} for i, dd in eq_index["instdept"].items()}

    bedded = sorted({int(b) for b in df["bedded_capacity"].dropna().unique()}) if len(df) else []
    return {
        "overview": overview, "divisions": divisions, "institutes": institutes, "departments": departments,
        "state_depts": state_depts, "equipment_catalog": catalog, "equipment_names": names,
        "equipment_div_map": eq_div_map, "eq_index": eq_index, "bedded_capacities": bedded,
        "cost_category": cats["cost_category"], "course_category": cats["course_category"],
        "department_type": cats["department_type"],
        "sub_categories": sorted(eq_index["subcat"].keys()),
        "map": {"W": mapdim.get("W", 771), "H": mapdim.get("H", 597), "districts": districts,
                "div_centroids": {d["map_key"]: [d["cx"], d["cy"]] for d in all_divs if d["map_key"]}},
        "meta": {**status, "generated_at": datetime.now(timezone.utc).isoformat(), "financial_visible": fin,
                 "user": {"username": user.username, "role": user.role, "full_name": user.full_name,
                          "allowed_divisions": user.allowed_divisions, "permissions": sorted(user.permissions)}},
    }
