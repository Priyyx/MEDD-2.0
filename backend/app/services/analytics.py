"""Centralised KPI / analytics engine.

Every number on every dashboard module is produced here from ``analytics.mv_line_fact`` using ONE set of formulas
(see docs/03_KPI_DEFINITIONS.md):

    non_functional      = Σ available − Σ functional
    net_requirement     = Σ required − Σ functional                 (+ shortfall / − surplus)
    functional_shortfall= Σ max(required − functional, 0)           (line level)
    utilisation % (gap) = Σ functional ÷ Σ required × 100           (0 when Σ required = 0; util_defined=false)
    budget              = Σ (proposed procurement × unit cost)
    amc %               = Σ amc ÷ Σ functional × 100
    func %              = Σ functional ÷ Σ available × 100
    eol %               = Σ end_of_life ÷ Σ functional × 100
    proc %              = Σ procurement ÷ Σ required × 100
    est. cost (cost map)= Σ over lines with net req > 0 of (net requirement × unit cost)

All SQL is parameterised (no string interpolation of user input); sort keys and levels are allow-listed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.db.session import read_engine
from app.security.auth import CurrentUser, effective_divisions

AGG_SQL = """
  COALESCE(sum(required),0)::bigint            AS required,
  COALESCE(sum(available),0)::bigint           AS available,
  COALESCE(sum(functional),0)::bigint          AS functional,
  COALESCE(sum(non_functional),0)::bigint      AS non_functional,
  COALESCE(sum(procurement),0)::bigint         AS procurement,
  COALESCE(sum(budget),0)::float8              AS budget,
  COALESCE(sum(amc),0)::bigint                 AS amc,
  COALESCE(sum(condemnation),0)::bigint        AS condemnation,
  COALESCE(sum(end_of_life),0)::bigint         AS end_of_life,
  COALESCE(sum(functional_shortfall),0)::bigint AS functional_shortfall,
  count(DISTINCT institute_id)                 AS college_count,
  count(DISTINCT equipment_id)                 AS equipment_types,
  count(*)                                     AS line_items
"""

LEVEL_COL = {"division": "division", "institute": "institute", "department": "department", "equipment": "equipment",
             "sub_category": "sub_category"}
SORTABLE = {"name", "required", "available", "functional", "non_functional", "procurement", "net_requirement",
            "budget", "amc", "condemnation", "end_of_life", "gap_pct", "util_pct", "amc_pct", "functional_shortfall",
            "unit_cost", "college_count", "equipment_types"}


def pct(n, d) -> float:
    return round(float(n) * 100.0 / float(d), 2) if d else 0.0


def block(r: dict, *, financial: bool = True) -> dict:
    """Turn a SQL aggregate row into the KPI block used by the frontend (MEDD 1.0 contract + additions)."""
    req, fn, av = int(r.get("required") or 0), int(r.get("functional") or 0), int(r.get("available") or 0)
    proc, amc, eol = int(r.get("procurement") or 0), int(r.get("amc") or 0), int(r.get("end_of_life") or 0)
    util = pct(fn, req)
    out = {
        "required": req, "available": av, "functional": fn, "non_functional": av - fn,
        "procurement": proc, "net_requirement": req - fn,
        "budget": round(float(r.get("budget") or 0), 2) if financial else None,
        "amc": amc, "condemnation": int(r.get("condemnation") or 0), "end_of_life": eol,
        "college_count": int(r.get("college_count") or 0),
        "gap_pct": util, "util_pct": util, "util_defined": req > 0,
        "proc_pct": pct(proc, req), "amc_pct": pct(amc, fn), "func_pct": pct(fn, av), "eol_pct": pct(eol, fn),
        "equipment_types": int(r.get("equipment_types") or 0),
        "functional_shortfall": int(r.get("functional_shortfall") or 0),
        "line_items": int(r.get("line_items") or 0),
    }
    if "name" in r:
        out["name"] = r["name"]
    if "unit_cost" in r:
        out["unit_cost"] = (float(r["unit_cost"]) if r["unit_cost"] is not None else 0.0) if financial else None
    return out


@dataclass
class Filters:
    division: list[str] = field(default_factory=list)
    institute: list[str] = field(default_factory=list)
    department: list[str] = field(default_factory=list)
    subcat: list[str] = field(default_factory=list)
    equipment: list[str] = field(default_factory=list)
    bedded: list[int] = field(default_factory=list)

    @classmethod
    def from_query(cls, qp, user: CurrentUser) -> "Filters":
        def lst(k):
            vals = qp.getlist(k) if hasattr(qp, "getlist") else (qp.get(k) or [])
            out = []
            for v in vals:
                out.extend([x for x in str(v).split("||") if x != ""])
            return out[:500]
        f = cls(division=lst("division"), institute=lst("institute"), department=lst("department"),
                subcat=lst("subcat"), equipment=lst("equipment"),
                bedded=[int(b) for b in lst("bedded") if str(b).isdigit()])
        f.apply_user_scope(user)
        return f

    def apply_user_scope(self, user: CurrentUser) -> None:
        eff = effective_divisions(user, self.division)
        self.division = eff or []

    def is_empty(self) -> bool:
        return not any([self.division, self.institute, self.department, self.subcat, self.equipment, self.bedded])

    def geo_only(self) -> "Filters":
        return Filters(division=self.division, institute=self.institute, bedded=self.bedded)

    def where(self, alias: str = "", skip: Iterable[str] = ()) -> tuple[str, dict]:
        a = f"{alias}." if alias else ""
        conds, p = [], {}
        mapping = [("division", "division"), ("institute", "institute"), ("department", "department"),
                   ("subcat", "sub_category"), ("equipment", "equipment"), ("bedded", "bedded_capacity")]
        for key, col in mapping:
            vals = getattr(self, key)
            if vals and key not in skip:
                conds.append(f"{a}{col} = ANY(:f_{key})")
                p[f"f_{key}"] = list(vals)
        return (" AND ".join(conds) if conds else "TRUE"), p

    def cache_key(self) -> tuple:
        return tuple(tuple(sorted(map(str, getattr(self, k)))) for k in
                     ("division", "institute", "department", "subcat", "equipment", "bedded"))


class Analytics:
    def __init__(self, user: CurrentUser, conn: Optional[Connection] = None):
        self.user = user
        self.fin = user.can("financial:read")
        self._conn = conn

    # ------------------------------------------------------------------ low level
    def q(self, sql: str, params: dict | None = None) -> list[dict]:
        if self._conn is not None:
            return [dict(r._mapping) for r in self._conn.execute(text(sql), params or {})]
        with read_engine.connect() as c:
            return [dict(r._mapping) for r in c.execute(text(sql), params or {})]

    def _scope_where(self, f: Filters, extra: str = "", skip: Iterable[str] = ()) -> tuple[str, dict]:
        w, p = f.where(skip=skip)
        if self.user.allowed_divisions is not None and "division" in skip:
            w += " AND division = ANY(:u_div)"
            p["u_div"] = list(self.user.allowed_divisions)
        if extra:
            w += f" AND ({extra})"
        return w, p

    # ------------------------------------------------------------------ summaries
    def summary(self, f: Filters) -> dict:
        w, p = self._scope_where(f)
        r = self.q(f"SELECT {AGG_SQL} FROM analytics.mv_line_fact WHERE {w}", p)[0]
        b = block(r, financial=self.fin)
        # "Medical Colleges — institutes in scope": MEDD 1.0 counts institutes matching the geographic and bedded
        # filters only (department / equipment / sub-category filters do not reduce the college count).
        gw, gp = self._scope_where(f.geo_only())
        b["college_count"] = int(self.q(f"SELECT count(DISTINCT institute_id) n FROM analytics.mv_line_fact WHERE {gw}", gp)[0]["n"])
        b["divisions"] = int(self.q(f"SELECT count(DISTINCT division) n FROM analytics.mv_line_fact WHERE {gw}", gp)[0]["n"])
        b["department_count"] = int(self.q(f"SELECT count(DISTINCT department) n FROM analytics.mv_line_fact WHERE {w}", p)[0]["n"])
        return b

    def breakdown(self, f: Filters, level: str, *, sort: str = "name", direction: str = "asc",
                  limit: int | None = None, offset: int = 0, extra_where: str = "", with_parent: bool = True,
                  search: str | None = None) -> list[dict]:
        if level not in LEVEL_COL:
            raise ValueError("invalid level")
        col = LEVEL_COL[level]
        w, p = self._scope_where(f, extra_where)
        if search:
            w += f" AND {col} ILIKE :q"
            p["q"] = f"%{search}%"
        extra_cols = ""
        if level == "institute" and with_parent:
            extra_cols = ", min(division) AS division, min(bedded_capacity) AS seat"
        if level == "equipment":
            extra_cols = ", max(unit_cost)::float8 AS unit_cost"
        rows = self.q(f"""SELECT {col} AS name, {AGG_SQL} {extra_cols} FROM analytics.mv_line_fact
                          WHERE {w} AND {col} IS NOT NULL GROUP BY {col}""", p)
        out = []
        for r in rows:
            b = block(r, financial=self.fin)
            if level == "institute" and with_parent:
                b["division"], b["seat"] = r["division"], r["seat"]
            out.append(b)
        out = sort_rows(out, sort, direction)
        if limit is not None:
            out = out[offset: offset + limit]
        return out

    def count_distinct(self, f: Filters, level: str, extra_where: str = "", search: str | None = None) -> int:
        col = LEVEL_COL[level]
        w, p = self._scope_where(f, extra_where)
        if search:
            w += f" AND {col} ILIKE :q"
            p["q"] = f"%{search}%"
        return int(self.q(f"SELECT count(DISTINCT {col}) n FROM analytics.mv_line_fact WHERE {w}", p)[0]["n"])

    # ------------------------------------------------------------------ drill-through (Division→Institute→Department→Equipment)
    def drill(self, f: Filters, level: str, path: list[str]) -> dict:
        levels = ["division", "institute", "department", "equipment"]
        if level not in levels:
            raise ValueError("invalid level")
        idx = levels.index(level)
        if len(path) < idx:
            raise ValueError("path too short for level")
        scoped = Filters(**{k: list(getattr(f, k)) for k in ("division", "institute", "department", "subcat",
                                                               "equipment", "bedded")})
        parent_names = dict(zip(levels, path[:idx]))
        for lv, name in parent_names.items():
            key = {"division": "division", "institute": "institute", "department": "department"}[lv]
            existing = getattr(scoped, key)
            if existing and name not in existing:
                setattr(scoped, key, ["__none__"])
            else:
                setattr(scoped, key, [name])
        scoped.apply_user_scope(self.user)
        parent = self.summary(scoped) if path else self.summary(f)
        parent["name"] = path[-1] if path else "Maharashtra"
        rows = self.breakdown(scoped, level, sort="name")
        return {"level": level, "path": path, "parent": parent, "rows": rows}

    # ------------------------------------------------------------------ cost mapping (Net Requirement page)
    def cost_mapping(self, f: Filters, *, q: str | None, cat: str | None, sort: str, direction: str,
                     page: int, per: int) -> dict:
        w, p = self._scope_where(f, "net_requirement > 0")
        if q:
            w += " AND (equipment ILIKE :q OR institute ILIKE :q OR division ILIKE :q OR department ILIKE :q)"
            p["q"] = f"%{q}%"
        cat_sql = "CASE WHEN cost_category ILIKE 'low%' THEN 'Low' WHEN cost_category ILIKE 'med%' THEN 'Medium' " \
                  "WHEN cost_category ILIKE 'high%' THEN 'High' ELSE cost_category END"
        if cat:
            w += f" AND {cat_sql} = :cat"
            p["cat"] = cat
        sort_map = {"eq": "eq", "div": "div", "inst": "inst", "dept": "dept", "req": "req", "avail": "avail",
                    "func": "func", "netreq": "netreq", "uc": "uc", "total": "total", "cat": "cat"}
        s = sort_map.get(sort, "total")
        d = "ASC" if direction == "asc" else "DESC"
        base = f"""SELECT equipment eq, division div, institute inst, department dept, sum(required) req,
                     sum(available) avail, sum(functional) func, sum(net_requirement) netreq,
                     max(COALESCE(unit_cost,0))::float8 uc, sum(est_total_cost)::float8 total, max({cat_sql}) cat
                   FROM analytics.mv_line_fact WHERE {w} GROUP BY equipment, division, institute, department"""
        tot = self.q(f"SELECT count(*) n, COALESCE(sum(total),0)::float8 g, COALESCE(sum(netreq),0) nr FROM ({base}) x", p)[0]
        p.update({"lim": per, "off": page * per})
        rows = self.q(f"SELECT * FROM ({base}) x ORDER BY {s} {d} NULLS LAST, eq, inst, dept LIMIT :lim OFFSET :off", p)
        if not self.fin:
            for r in rows:
                r["uc"] = r["total"] = None
        return {"rows": rows, "total": int(tot["n"]), "grand_total": float(tot["g"]) if self.fin else None,
                "net_requirement_total": int(tot["nr"]), "page": page, "per": per,
                "pages": max(1, -(-int(tot["n"]) // per))}

    def cost_mapping_all(self, f: Filters, q: str | None, cat: str | None, sort: str, direction: str) -> list[dict]:
        return self.cost_mapping(f, q=q, cat=cat, sort=sort, direction=direction, page=0, per=1_000_000)["rows"]


def sort_rows(rows: list[dict], key: str, direction: str) -> list[dict]:
    key = key if key in SORTABLE else "name"
    rev = direction != "asc"
    if key == "name":
        return sorted(rows, key=lambda r: str(r.get("name") or "").lower(), reverse=rev)
    return sorted(rows, key=lambda r: (r.get(key) is None, r.get(key) or 0), reverse=rev)


def data_status(conn: Optional[Connection] = None) -> dict[str, Any]:
    sql = """SELECT (SELECT value #>> '{}' FROM metadata.app_setting WHERE key='data_version') AS data_version,
                    (SELECT value #>> '{}' FROM metadata.app_setting WHERE key='last_refresh') AS last_refresh,
                    (SELECT row_to_json(f) FROM (SELECT id, original_name, status, finished_at, rows_inserted,
                       rows_updated, rows_unchanged, rows_deactivated, rows_rejected, warnings, errors, error_message
                       FROM metadata.ingestion_file ORDER BY id DESC LIMIT 1) f) AS last_ingestion,
                    (SELECT row_to_json(f) FROM (SELECT id, original_name, finished_at FROM metadata.ingestion_file
                       WHERE status IN ('SUCCESS','SUCCESS_WITH_WARNINGS') ORDER BY id DESC LIMIT 1) f) AS last_success,
                    (SELECT count(*) FROM analytics.mv_line_fact) AS line_items"""
    if conn is not None:
        r = conn.execute(text(sql)).one()
    else:
        with read_engine.connect() as c:
            r = c.execute(text(sql)).one()
    d = dict(r._mapping)
    d["data_version"] = int(d["data_version"] or 0)
    d["last_refresh"] = None if d["last_refresh"] in (None, "null") else d["last_refresh"]
    return d
