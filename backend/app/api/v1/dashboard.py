"""Dashboard / analytics endpoints (read-only connection)."""
from __future__ import annotations

import csv
import gzip
import io
import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response, StreamingResponse

from app.security.auth import CurrentUser, require, write_audit
from app.services import bootstrap
from app.services.analytics import Analytics, Filters, data_status, sort_rows
from app.services.cache import cache

router = APIRouter(tags=["dashboard"])
Level = Literal["division", "institute", "department", "equipment"]

FILTER_DOC = ("Filters (repeatable or '||'-separated): division, institute, department, subcat, equipment, bedded. "
              "The user's permitted divisions are always enforced server-side.")


def _filters(request: Request, user: CurrentUser) -> Filters:
    return Filters.from_query(request.query_params, user)


def _ver() -> int:
    return data_status()["data_version"]


def _ukey(user: CurrentUser) -> tuple:
    return (user.can("financial:read"), tuple(user.allowed_divisions or ()))


@router.get("/dashboard/bootstrap", summary="Full dashboard payload (MEDD 1.0 DATA contract) built from PostgreSQL")
def get_bootstrap(request: Request, user: CurrentUser = Depends(require("dashboard:read"))):
    # Serialised + gzip-compressed once per data version and permission scope; served from memory afterwards.
    def build():
        raw = json.dumps(bootstrap.build(user), default=str, separators=(",", ":")).encode()
        return raw, gzip.compress(raw, 6)
    raw, gz = cache.get_or_set(("bootstrap", _ver(), _ukey(user)), build)
    if "gzip" in request.headers.get("accept-encoding", ""):
        return Response(gz, media_type="application/json", headers={"Content-Encoding": "gzip", "Vary": "Accept-Encoding"})
    return Response(raw, media_type="application/json")


@router.get("/dashboard/status", summary="Last refresh timestamp, data version and latest ingestion")
def get_status(user: CurrentUser = Depends(require("dashboard:read"))):
    return data_status()


@router.get("/dashboard/scope", summary="Filtered KPI summary + division/institute/department breakdowns",
            description=FILTER_DOC)
def get_scope(request: Request, user: CurrentUser = Depends(require("dashboard:read"))):
    f = _filters(request, user)

    def build():
        A = Analytics(user)
        return {"filters": f.__dict__, "summary": A.summary(f),
                "divisions": A.breakdown(f, "division"), "institutes": A.breakdown(f, "institute"),
                "departments": A.breakdown(f, "department", sort="procurement", direction="desc")}
    return cache.get_or_set(("scope", _ver(), _ukey(user), f.cache_key()), build)


@router.get("/kpis/summary", summary="Executive KPI block for the active filters", description=FILTER_DOC)
def kpi_summary(request: Request, user: CurrentUser = Depends(require("dashboard:read"))):
    f = _filters(request, user)
    return cache.get_or_set(("sum", _ver(), _ukey(user), f.cache_key()), lambda: Analytics(user).summary(f))


@router.get("/kpis/breakdown", summary="KPI blocks grouped by a hierarchy level (server-side sort + pagination)")
def kpi_breakdown(request: Request, level: Level = "division", sort: str = "name",
                  dir: Literal["asc", "desc"] = "asc", page: int = Query(0, ge=0), per: int = Query(100, ge=1, le=2000),
                  q: str | None = Query(None, max_length=100), user: CurrentUser = Depends(require("dashboard:read"))):
    f = _filters(request, user)
    A = Analytics(user)
    rows = A.breakdown(f, level, sort=sort, direction=dir, search=q)
    return {"level": level, "total": len(rows), "page": page, "per": per, "rows": rows[page * per:(page + 1) * per]}


# ---- dedicated module endpoints -------------------------------------------------------------------------------
MODULES = {
    "executive":     {"metric": "gap_pct", "eq_sort": "procurement"},
    "gap":           {"metric": "gap_pct", "eq_sort": "procurement"},
    "procurement":   {"metric": "procurement", "eq_sort": "procurement"},
    "net-requirement": {"metric": "net_requirement", "eq_sort": "procurement"},
    "financial":     {"metric": "budget", "eq_sort": "budget", "perm": "financial:read"},
    "condemnation":  {"metric": "condemnation", "eq_sort": "condemnation"},
    "end-of-life":   {"metric": "end_of_life", "eq_sort": "end_of_life"},
    "amc":           {"metric": "amc_pct", "eq_sort": "amc"},
}


@router.get("/modules/{module}", summary="Module analytics: summary, ranking by division and top equipment",
            description="module ∈ " + ", ".join(MODULES) + ". " + FILTER_DOC)
def module_data(module: str, request: Request, top: int = Query(50, ge=1, le=500),
                user: CurrentUser = Depends(require("dashboard:read"))):
    cfg = MODULES.get(module)
    if not cfg:
        raise HTTPException(404, "Unknown module")
    if cfg.get("perm") and not user.can(cfg["perm"]):
        raise HTTPException(403, "Financial data is restricted for your role.")
    f = _filters(request, user)

    def build():
        A = Analytics(user)
        m = cfg["metric"]
        asc = m in ("gap_pct", "amc_pct")
        return {"module": module, "metric": m, "summary": A.summary(f),
                "by_division": A.breakdown(f, "division", sort=m, direction="asc" if asc else "desc"),
                "top_equipment": A.breakdown(f, "equipment", sort=cfg["eq_sort"], direction="desc", limit=top)}
    return cache.get_or_set(("mod", module, top, _ver(), _ukey(user), f.cache_key()), build)


@router.get("/divisions", summary="Division Dashboard data")
def divisions(request: Request, sort: str = "gap_pct", dir: Literal["asc", "desc"] = "desc",
              user: CurrentUser = Depends(require("dashboard:read"))):
    return {"rows": Analytics(user).breakdown(_filters(request, user), "division", sort=sort, direction=dir)}


@router.get("/institutes", summary="Institute Dashboard data (server-side pagination)")
def institutes(request: Request, sort: str = "gap_pct", dir: Literal["asc", "desc"] = "desc",
               page: int = Query(0, ge=0), per: int = Query(100, ge=1, le=500), q: str | None = None,
               user: CurrentUser = Depends(require("dashboard:read"))):
    rows = Analytics(user).breakdown(_filters(request, user), "institute", sort=sort, direction=dir, search=q)
    return {"total": len(rows), "page": page, "per": per, "rows": rows[page * per:(page + 1) * per]}


@router.get("/departments", summary="Department Dashboard data")
def departments(request: Request, sort: str = "gap_pct", dir: Literal["asc", "desc"] = "desc",
                user: CurrentUser = Depends(require("dashboard:read"))):
    return {"rows": Analytics(user).breakdown(_filters(request, user), "department", sort=sort, direction=dir)}


@router.get("/equipment", summary="Equipment Explorer (all filters, server-side search/sort/pagination)")
def equipment(request: Request, sort: str = "procurement", dir: Literal["asc", "desc"] = "desc",
              page: int = Query(0, ge=0), per: int = Query(60, ge=1, le=1000), q: str | None = Query(None, max_length=100),
              user: CurrentUser = Depends(require("dashboard:read"))):
    f = _filters(request, user)
    key = ("eqx", _ver(), _ukey(user), f.cache_key(), sort, dir, q)
    rows = cache.get_or_set(key, lambda: Analytics(user).breakdown(f, "equipment", sort=sort, direction=dir, search=q))
    return {"total": len(rows), "page": page, "per": per, "pages": max(1, -(-len(rows) // per)),
            "rows": rows[page * per:(page + 1) * per]}


@router.get("/drill", summary="Metric-aware drill-through: Division → Institute → Department → Equipment",
            description="path is '||'-separated parent names. " + FILTER_DOC)
def drill(request: Request, level: Level = "division", path: str = "", user: CurrentUser = Depends(require("dashboard:read"))):
    parts = [p for p in path.split("||") if p] if path else []
    f = _filters(request, user)
    try:
        return cache.get_or_set(("drill", _ver(), _ukey(user), f.cache_key(), level, tuple(parts)),
                                lambda: Analytics(user).drill(f, level, parts))
    except ValueError as exc:
        raise HTTPException(400, str(exc))


# ---- Net Requirement: Cost Mapping table ---------------------------------------------------------------------
@router.get("/net-requirement/cost-mapping", summary="Cost Mapping table (Net Requirement > 0 lines), server-paginated")
def cost_mapping(request: Request, q: str | None = Query(None, max_length=100), cat: str | None = None,
                 sort: str = "total", dir: Literal["asc", "desc"] = "desc", page: int = Query(0, ge=0),
                 per: int = Query(25, ge=1, le=500), user: CurrentUser = Depends(require("dashboard:read"))):
    f = _filters(request, user)
    return cache.get_or_set(("cm", _ver(), _ukey(user), f.cache_key(), q, cat, sort, dir, page, per),
                            lambda: Analytics(user).cost_mapping(f, q=q, cat=cat, sort=sort, direction=dir, page=page, per=per))


@router.get("/exports/cost-mapping", summary="Export the full filtered Cost Mapping table (CSV or Excel)")
def export_cost_mapping(request: Request, format: Literal["csv", "xlsx"] = "csv", q: str | None = None,
                        cat: str | None = None, sort: str = "total", dir: Literal["asc", "desc"] = "desc",
                        user: CurrentUser = Depends(require("export:run"))):
    f = _filters(request, user)
    rows = Analytics(user).cost_mapping_all(f, q, cat, sort, dir)
    head = ["Equipment", "Division", "Institute", "Department", "Required", "Available", "Functional",
            "Net Requirement", "Unit Cost (Rs)", "Total Estimated Cost (Rs)", "Cost Category"]
    data = [[r["eq"], r["div"], r["inst"], r["dept"], r["req"], r["avail"], r["func"], r["netreq"],
             None if r["uc"] is None else round(r["uc"]), None if r["total"] is None else round(r["total"]), r["cat"]]
            for r in rows]
    write_audit(user.username, "EXPORT", "cost_mapping", None, {"format": format, "rows": len(data), "filters": f.__dict__},
                request.client.host if request.client else None)
    if format == "csv":
        buf = io.StringIO()
        buf.write("﻿")
        w = csv.writer(buf)
        w.writerow(head)
        w.writerows(data)
        return Response(buf.getvalue(), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": 'attachment; filename="MEDD_cost_mapping.csv"'})
    import pandas as pd
    out = io.BytesIO()
    with pd.ExcelWriter(out, engine="openpyxl") as xw:
        pd.DataFrame(data, columns=head).to_excel(xw, index=False, sheet_name="Cost Mapping")
    return Response(out.getvalue(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": 'attachment; filename="MEDD_cost_mapping.xlsx"'})


@router.get("/exports/{level}", summary="Export a filtered breakdown (division/institute/department/equipment) as CSV")
def export_breakdown(level: Level, request: Request, user: CurrentUser = Depends(require("export:run"))):
    f = _filters(request, user)
    rows = Analytics(user).breakdown(f, level, sort="name")
    cols = ["name", "required", "available", "functional", "non_functional", "net_requirement", "functional_shortfall",
            "gap_pct", "procurement", "budget", "amc", "amc_pct", "end_of_life", "condemnation"]
    buf = io.StringIO()
    buf.write("﻿")
    w = csv.writer(buf)
    w.writerow([c.replace("gap_pct", "utilisation_pct") for c in cols])
    for r in rows:
        w.writerow([r.get(c) for c in cols])
    write_audit(user.username, "EXPORT", level, None, {"rows": len(rows), "filters": f.__dict__})
    return Response(buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="MEDD_{level}.csv"'})
