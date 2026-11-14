"""MEDD 2.0 ingestion pipeline.

    file in incoming/ -> checksum + duplicate check -> processing/ -> read sheets -> detect header & dataset type
    -> parse + validate rows -> staging tables (committed, kept for traceability)
    -> ONE production transaction: resolve/standardise master data, UPSERT line items + satellites (procurement,
       maintenance, lifecycle, financial), snapshot deactivation, audit history, materialized-view refresh,
       data-version bump, pg_notify
    -> processed/ + archive/  (or failed/ with an error log)  -> JSON/Markdown/CSV report

Any exception or a reject ratio above the configured threshold rolls back the production transaction, so a
failed upload can never modify previously validated production data.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import math
import shutil
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.session import WriteSession, write_tx
from app.ingestion.mapping import detect_layout
from app.ingestion.reader import UnreadableFile, read_any
from app.ingestion.standardise import clean_name, division_key, load_rules, name_key
from app.services.events import notify_sql

log = logging.getLogger("medd.ingestion")
_LOCK = threading.Lock()
ADVISORY_LOCK_ID = 7_420_001

QTY_FIELDS = ["required_qty", "available_qty", "functional_qty", "proposed_qty", "amc_cmc_qty",
              "end_of_life_qty", "condemnation_qty"]
TEXT_FIELDS = ["division", "district", "institute", "institute_short_name", "department", "equipment", "sub_category", "course_category",
               "department_type", "cost_category"]
NULL_TOKENS = {"", "nan", "none", "null", "-", "--", "n/a", "na", "nil", "not applicable", "#n/a"}
SKIP_LABELS = {"total", "grand total", "sub total", "subtotal", "sum"}


class FatalIngestionError(Exception):
    pass


@dataclass
class Row:
    sheet: str
    row_no: int
    raw: dict
    f: dict
    rejected: bool = False


@dataclass
class Ctx:
    file_id: int
    issues: list = field(default_factory=list)
    counts: dict = field(default_factory=lambda: {k: 0 for k in (
        "rows_read", "rows_valid", "rows_rejected", "rows_inserted", "rows_updated", "rows_unchanged",
        "rows_deactivated")})
    extra: dict = field(default_factory=dict)
    _once: set = field(default_factory=set)

    def issue(self, severity, code, message, sheet=None, row=None, fld=None, value=None, once_key=None):
        if once_key is not None:
            if (code, once_key) in self._once:
                return
            self._once.add((code, once_key))
        self.issues.append({"severity": severity, "code": code, "message": message, "sheet_name": sheet,
                            "row_no": row, "field": fld, "value": None if value is None else str(value)[:500]})


# ---------------------------------------------------------------------------------------------- value parsing
def _is_blank(v) -> bool:
    if v is None:
        return True
    if isinstance(v, float) and math.isnan(v):
        return True
    return isinstance(v, str) and v.strip().lower() in NULL_TOKENS


def parse_number(v) -> tuple[float | None, str | None]:
    if _is_blank(v):
        return None, None
    if isinstance(v, bool):
        return None, "boolean is not a number"
    if isinstance(v, (int, float)):
        return float(v), None
    s = str(v).strip().replace(",", "").replace("₹", "").replace("Rs.", "").replace("Rs", "").replace("INR", "").strip()
    try:
        return float(s), None
    except ValueError:
        return None, f"'{v}' is not a number"


def parse_qty(v, tol: float) -> tuple[int, str | None, bool]:
    """-> (value, error, was_blank). Blank -> 0."""
    num, err = parse_number(v)
    if err:
        return 0, err, False
    if num is None:
        return 0, None, True
    if num < 0:
        return 0, f"negative quantity {num:g}", False
    if abs(num - round(num)) > tol:
        return 0, f"non-integer quantity {num:g}", False
    return int(round(num)), None, False


def _json_safe(v):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    if isinstance(v, (datetime, pd.Timestamp)):
        return v.isoformat()
    if isinstance(v, (int, float, str, bool)):
        return v
    return str(v)


def sha1(*parts) -> str:
    return hashlib.sha1("␟".join("" if p is None else str(p) for p in parts).encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------------------------- parse sheets
def parse_sheets(ctx: Ctx, path: Path, rules: dict) -> dict[str, list[Row]]:
    out: dict[str, list[Row]] = {"inventory": [], "unit_cost": [], "institute": []}
    tol = float(rules["validation"].get("integer_tolerance", 1e-4))
    sheets = read_any(path)
    if not sheets:
        raise FatalIngestionError("The file contains no non-empty worksheets.")
    sheet_meta = []
    for sh in sheets:
        lay = detect_layout(sh.grid, int(rules.get("header_scan_rows", 25)))
        if lay.dataset_type is None:
            ctx.issue("INFO", "SHEET_SKIPPED", f"Worksheet '{sh.name}' ignored: {lay.reason}", sheet=sh.name)
            sheet_meta.append({"sheet_name": sh.name, "dataset_type": "unrecognised", "header_row": None,
                               "column_map": {}, "unmapped_columns": [], "rows_read": 0})
            continue
        for d in lay.duplicate_mappings:
            ctx.issue("WARNING", "DUPLICATE_COLUMN", f"Column '{d}'", sheet=sh.name)
        if lay.unmapped:
            ctx.issue("INFO", "UNMAPPED_COLUMNS",
                      f"{len(lay.unmapped)} column(s) not used: {', '.join(map(str, lay.unmapped[:30]))}", sheet=sh.name)
        blanks = {f: 0 for f in QTY_FIELDS}
        rows: list[Row] = []
        g = sh.grid
        for r in range(lay.header_row + 1, g.shape[0]):
            raw = {(lay.all_headers[c] or f"col{c + 1}"): _json_safe(g.iat[r, c]) for c in range(g.shape[1])
                   if c < len(lay.all_headers) and not _is_blank(g.iat[r, c])}
            vals = {f: g.iat[r, c] for f, c in lay.columns.items()}
            if all(_is_blank(v) for v in vals.values()):
                continue
            row = Row(sh.name, r + 1, raw, {})
            f = row.f
            for k in TEXT_FIELDS:
                if k in vals:
                    f[k] = clean_name(None if _is_blank(vals[k]) else vals[k])
            label = (f.get("equipment") or f.get("institute") or "").lower()
            if label in SKIP_LABELS:
                ctx.issue("INFO", "TOTAL_ROW_SKIPPED", "Row looks like a total line and was skipped", sh.name, r + 1)
                continue
            if lay.dataset_type == "inventory":
                for k in ("institute", "department", "equipment"):
                    if not f.get(k):
                        ctx.issue("ERROR", "MISSING_REQUIRED", f"Required field '{k}' is empty", sh.name, r + 1, k)
                        row.rejected = True
                for k in QTY_FIELDS:
                    if k in vals:
                        q, err, blank = parse_qty(vals[k], tol)
                        if err:
                            ctx.issue("ERROR", "INVALID_QUANTITY", err, sh.name, r + 1, k, vals[k])
                            row.rejected = True
                        blanks[k] += blank
                        f[k] = q
                    else:
                        f[k] = 0
                if "unit_cost" in vals:
                    uc, err = parse_number(vals["unit_cost"])
                    if err or (uc is not None and uc < 0):
                        ctx.issue("WARNING", "INVALID_UNIT_COST", err or "negative unit cost ignored",
                                  sh.name, r + 1, "unit_cost", vals["unit_cost"])
                        uc = None
                    f["unit_cost"] = uc
                if "bedded_capacity" in vals:
                    b, err = parse_number(vals["bedded_capacity"])
                    f["bedded_capacity"] = int(b) if b is not None and not err and b >= 0 else None
            elif lay.dataset_type == "unit_cost":
                if not f.get("equipment"):
                    ctx.issue("ERROR", "MISSING_REQUIRED", "Equipment name is empty", sh.name, r + 1, "equipment")
                    row.rejected = True
                uc, err = parse_number(vals.get("unit_cost"))
                if err or uc is None or uc < 0:
                    ctx.issue("ERROR", "INVALID_UNIT_COST", err or ("unit cost missing" if uc is None else "negative unit cost"),
                              sh.name, r + 1, "unit_cost", vals.get("unit_cost"))
                    row.rejected = True
                f["unit_cost"] = uc
            elif lay.dataset_type == "institute":
                for k in ("institute", "division"):
                    if not f.get(k):
                        ctx.issue("ERROR", "MISSING_REQUIRED", f"Required field '{k}' is empty", sh.name, r + 1, k)
                        row.rejected = True
                b, err = parse_number(vals.get("bedded_capacity"))
                f["bedded_capacity"] = int(b) if b is not None and not err and b >= 0 else None
            rows.append(row)
        for k, n in blanks.items():
            if n and k in lay.columns:
                ctx.issue("INFO", "BLANK_TREATED_AS_ZERO", f"{n} blank value(s) in '{lay.column_headers[k]}' treated as 0",
                          sh.name, fld=k)
        out[lay.dataset_type].extend(rows)
        sheet_meta.append({"sheet_name": sh.name, "dataset_type": lay.dataset_type, "header_row": lay.header_row + 1,
                           "column_map": lay.column_headers, "unmapped_columns": lay.unmapped, "rows_read": len(rows)})
    ctx.extra["sheets"] = sheet_meta
    if not any(out.values()):
        raise FatalIngestionError("No worksheet matched a known dataset layout (inventory, unit cost or institute). "
                                  "Check headers against backend/config/column_mappings.yaml.")
    return out


# ---------------------------------------------------------------------------------------------- staging
def stage_rows(ctx: Ctx, parsed: dict[str, list[Row]]) -> None:
    with write_tx() as db:
        for meta in ctx.extra.get("sheets", []):
            db.execute(text("""INSERT INTO metadata.ingestion_sheet(file_id, sheet_name, dataset_type, header_row,
                               column_map, unmapped_columns, rows_read)
                               VALUES (:f,:s,:d,:h,CAST(:c AS jsonb),CAST(:u AS jsonb),:n)"""),
                       {"f": ctx.file_id, "s": meta["sheet_name"], "d": meta["dataset_type"], "h": meta["header_row"],
                        "c": json.dumps(meta["column_map"]), "u": json.dumps([str(x) for x in meta["unmapped_columns"]]),
                        "n": meta["rows_read"]})
        pg = db.connection().connection.driver_connection
        with pg.cursor() as cur:
            inv_cols = ["file_id", "sheet_name", "row_no", "raw", "division", "institute", "department", "equipment",
                        "sub_category", "course_category", "department_type", "cost_category", "bedded_capacity",
                        *QTY_FIELDS, "unit_cost", "status"]
            with cur.copy(f"COPY staging.inventory_row ({', '.join(inv_cols)}) FROM STDIN") as cp:
                for r in parsed["inventory"]:
                    f = r.f
                    cp.write_row([ctx.file_id, r.sheet, r.row_no, json.dumps(r.raw, default=str), f.get("division"),
                                  f.get("institute"), f.get("department"), f.get("equipment"), f.get("sub_category"),
                                  f.get("course_category"), f.get("department_type"), f.get("cost_category"),
                                  f.get("bedded_capacity"), *[f.get(k) for k in QTY_FIELDS], f.get("unit_cost"),
                                  "REJECTED" if r.rejected else "PENDING"])
            with cur.copy("COPY staging.unit_cost_row (file_id, sheet_name, row_no, raw, equipment, unit_cost, "
                          "cost_category, status) FROM STDIN") as cp:
                for r in parsed["unit_cost"]:
                    cp.write_row([ctx.file_id, r.sheet, r.row_no, json.dumps(r.raw, default=str), r.f.get("equipment"),
                                  r.f.get("unit_cost"), r.f.get("cost_category"), "REJECTED" if r.rejected else "PENDING"])
            with cur.copy("COPY staging.institute_row (file_id, sheet_name, row_no, raw, institute, division, "
                          "bedded_capacity, status) FROM STDIN") as cp:
                for r in parsed["institute"]:
                    cp.write_row([ctx.file_id, r.sheet, r.row_no, json.dumps(r.raw, default=str), r.f.get("institute"),
                                  r.f.get("division"), r.f.get("bedded_capacity"), "REJECTED" if r.rejected else "PENDING"])


def finalize_staging(ctx: Ctx, parsed: dict[str, list[Row]]) -> None:
    with write_tx() as db:
        for table, rows in (("inventory_row", parsed["inventory"]), ("unit_cost_row", parsed["unit_cost"]),
                            ("institute_row", parsed["institute"])):
            by_sheet: dict[str, list[int]] = {}
            for r in rows:
                if r.rejected:
                    by_sheet.setdefault(r.sheet, []).append(r.row_no)
            db.execute(text(f"UPDATE staging.{table} SET status='VALID' WHERE file_id=:f AND status='PENDING'"),
                       {"f": ctx.file_id})
            for sheet, nums in by_sheet.items():
                db.execute(text(f"UPDATE staging.{table} SET status='REJECTED' WHERE file_id=:f AND sheet_name=:s "
                                f"AND row_no = ANY(:n)"), {"f": ctx.file_id, "s": sheet, "n": nums})


# ---------------------------------------------------------------------------------------------- master resolution
class Resolver:
    """Resolves/creates master entities with standardised keys and approved aliases."""

    def __init__(self, db: Session, ctx: Ctx, rules: dict):
        self.db, self.ctx, self.rules = db, ctx, rules
        self.aliases: dict[tuple[str, str], str] = {
            (r.entity_type, r.alias_key): r.canonical_name
            for r in db.execute(text("SELECT entity_type, alias_key, canonical_name FROM master_data.name_alias WHERE approved"))}
        self.div = {}
        for r in db.execute(text("SELECT id, name FROM master_data.division")):
            self.div[division_key(r.name)] = (r.id, r.name)
        for (et, ak), cn in self.aliases.items():
            if et == "division" and division_key(cn) in self.div:
                self.div[division_key(ak)] = self.div[division_key(cn)]
        self.inst = {r.name_key: [r.id, r.division_id, r.bedded_capacity, r.name] for r in db.execute(
            text("SELECT id, name, name_key, division_id, bedded_capacity FROM master_data.institute"))}
        self.dept = {r.name_key: r.id for r in db.execute(text("SELECT id, name_key FROM master_data.department"))}
        self.eq = {r.name_key: r.id for r in db.execute(text("SELECT id, name_key FROM master_data.equipment"))}
        self.sc = {name_key(r.name, merge_case=True): r.id for r in db.execute(text("SELECT id, name FROM master_data.sub_category"))}

    def _alias(self, et: str, key: str) -> str:
        cn = self.aliases.get((et, key))
        return name_key(cn) if cn else key

    def division(self, name: str | None):
        if not name:
            return None
        return self.div.get(division_key(name))

    def institute(self, name: str, div_name: str | None, bedded: int | None, row: Row):
        k = self._alias("institute", name_key(name, merge_case=True))
        rec = self.inst.get(k)
        d = self.division(div_name) if div_name else None
        if div_name and d is None:
            self.ctx.issue("ERROR", "UNKNOWN_DIVISION", f"Division '{div_name}' is not one of the approved divisions "
                           "(add an alias in master_data.name_alias if it is a spelling variant)",
                           row.sheet, row.row_no, "division", div_name)
            return None
        if rec is None:
            policy = self.rules["validation"].get("new_institute_policy", "create")
            if d is None or policy != "create":
                self.ctx.issue("ERROR", "UNKNOWN_INSTITUTE",
                               f"Institute '{name}' is not in master data" + ("" if d else " and no valid division was given"),
                               row.sheet, row.row_no, "institute", name)
                return None
            new_id = self.db.execute(text("""INSERT INTO master_data.institute(name, name_key, division_id, bedded_capacity)
                                             VALUES (:n, :k, :d, :b) RETURNING id"""),
                                     {"n": name, "k": k, "d": d[0], "b": bedded}).scalar()
            rec = self.inst[k] = [new_id, d[0], bedded, name]
            self.ctx.issue("INFO", "NEW_INSTITUTE", f"New institute created: '{name}' in {d[1]}", row.sheet, row.row_no,
                           once_key=k)
            return rec
        if d is not None and d[0] != rec[1]:
            self.ctx.issue("WARNING", "INSTITUTE_DIVISION_MISMATCH",
                           f"'{rec[3]}' is recorded under a different division in master data; master kept "
                           f"(file says '{div_name}')", row.sheet, row.row_no, "division", div_name, once_key=k)
        if bedded is not None and rec[2] != bedded:
            if rec[2] is None:
                self.db.execute(text("UPDATE master_data.institute SET bedded_capacity=:b, updated_at=now() WHERE id=:i"),
                                {"b": bedded, "i": rec[0]})
                rec[2] = bedded
            else:
                self.ctx.issue("WARNING", "BEDDED_CAPACITY_MISMATCH",
                               f"Bedded capacity for '{rec[3]}' in file ({bedded}) differs from master ({rec[2]}); master kept",
                               row.sheet, row.row_no, "bedded_capacity", bedded, once_key=k)
        return rec

    def _get_or_create(self, cache: dict, table: str, et: str, name: str, row: Row, merge_case: bool | None = None):
        k = self._alias(et, name_key(name, merge_case=merge_case))
        if k in cache:
            return cache[k]
        if table == "sub_category":
            new_id = self.db.execute(text("INSERT INTO master_data.sub_category(name) VALUES (:n) "
                                          "ON CONFLICT (name) DO UPDATE SET name=EXCLUDED.name RETURNING id"), {"n": name}).scalar()
        else:
            new_id = self.db.execute(text(f"INSERT INTO master_data.{table}(name, name_key) VALUES (:n, :k) RETURNING id"),
                                     {"n": name, "k": k}).scalar()
        cache[k] = new_id
        self.ctx.issue("INFO", f"NEW_{table.upper()}", f"New {table.replace('_', ' ')} added to master data: '{name}'",
                       row.sheet, row.row_no, once_key=k)
        return new_id

    def short_alias(self, short: str, rec) -> None:
        k = name_key(short, merge_case=True)
        if k == name_key(rec[3], merge_case=True) or ("institute", k) in self.aliases:
            return
        self.db.execute(text("""INSERT INTO master_data.name_alias(entity_type, alias_key, canonical_name, source)
                               VALUES ('institute', :k, :c, 'excel:short_name') ON CONFLICT DO NOTHING"""),
                        {"k": k, "c": rec[3]})
        self.aliases[("institute", k)] = rec[3]

    def department(self, name, row):
        return self._get_or_create(self.dept, "department", "department", name, row, merge_case=True)

    def equipment(self, name, row):
        return self._get_or_create(self.eq, "equipment", "equipment", name, row)

    def sub_category(self, name, row):
        if not name:
            return None
        return self._get_or_create(self.sc, "sub_category", "sub_category", name, row, merge_case=True)


def cost_band(uc: float | None, rules: dict) -> str | None:
    bands = rules.get("cost_category_bands")
    if uc is None or uc <= 0 or not bands:
        return None
    for b in bands:
        if b.get("max") is None or uc < float(b["max"]):
            return b["name"]
    return None


# ---------------------------------------------------------------------------------------------- production apply
def _upsert_unit_cost(db: Session, ctx: Ctx, eq_id: int, uc: float, cat: str | None) -> bool:
    cur = db.execute(text("SELECT unit_cost FROM financial.equipment_unit_cost WHERE equipment_id=:e"), {"e": eq_id}).first()
    if cur is not None and float(cur.unit_cost) == float(uc):
        if cat:
            db.execute(text("UPDATE financial.equipment_unit_cost SET cost_category=:c WHERE equipment_id=:e "
                            "AND cost_category IS DISTINCT FROM :c"), {"c": cat, "e": eq_id})
        return False
    db.execute(text("""INSERT INTO financial.unit_cost_history(equipment_id, old_unit_cost, new_unit_cost, source_file_id)
                       VALUES (:e, :o, :n, :f)"""), {"e": eq_id, "o": None if cur is None else cur.unit_cost, "n": uc,
                                                    "f": ctx.file_id})
    db.execute(text("""INSERT INTO financial.equipment_unit_cost(equipment_id, unit_cost, cost_category, source, source_file_id)
                       VALUES (:e, :u, :c, 'excel', :f)
                       ON CONFLICT (equipment_id) DO UPDATE SET unit_cost=EXCLUDED.unit_cost,
                         cost_category=COALESCE(EXCLUDED.cost_category, financial.equipment_unit_cost.cost_category),
                         source='excel', source_file_id=EXCLUDED.source_file_id, updated_at=now()"""),
               {"e": eq_id, "u": uc, "c": cat, "f": ctx.file_id})
    return True


def apply_production(db: Session, ctx: Ctx, parsed: dict[str, list[Row]], rules: dict) -> None:
    v = rules["validation"]
    res = Resolver(db, ctx, rules)

    # ---- 1. institute master sheets
    for r in parsed["institute"]:
        if r.rejected:
            continue
        rec = res.institute(r.f["institute"], r.f["division"], r.f.get("bedded_capacity"), r)
        if rec is None:
            r.rejected = True

    # ---- 2. unit-cost sheets
    uc_changed = 0
    file_costs: dict[int, float] = {}
    for r in parsed["unit_cost"]:
        if r.rejected:
            continue
        eq_id = res.equipment(r.f["equipment"], r)
        uc = float(r.f["unit_cost"])
        if eq_id in file_costs and file_costs[eq_id] != uc:
            ctx.issue("WARNING", "CONFLICTING_UNIT_COST", f"'{r.f['equipment']}' has more than one unit cost in the "
                      f"costing list ({file_costs[eq_id]:g} kept, {uc:g} ignored)", r.sheet, r.row_no, "unit_cost", uc)
            continue
        if uc > float(v.get("unit_cost_warn_above", 5e8)):
            ctx.issue("WARNING", "UNIT_COST_OUTLIER", f"Unit cost ₹{uc:,.0f} is unusually high", r.sheet, r.row_no,
                      "unit_cost", uc)
        file_costs[eq_id] = uc
        uc_changed += _upsert_unit_cost(db, ctx, eq_id, uc, r.f.get("cost_category") or cost_band(uc, rules))

    # ---- 3. inventory line items
    inv = parsed["inventory"]
    tmp_rows = []
    seen: dict[str, int] = {}
    exact_seen: set[str] = set()
    inline_costs: dict[int, float] = {}
    for r in inv:
        if r.rejected:
            continue
        f = r.f
        rec = res.institute(f["institute"], f.get("division"), f.get("bedded_capacity"), r)
        if rec is None:
            r.rejected = True
            continue
        dep_id = res.department(f["department"], r)
        eq_id = res.equipment(f["equipment"], r)
        sc_id = res.sub_category(f.get("sub_category"), r)
        natural = (rec[0], dep_id, eq_id, sc_id or "", (f.get("course_category") or "").upper())
        nk = sha1(*natural)
        seen[nk] = occ = seen.get(nk, 0) + 1
        if occ > 1 and v.get("warn_repeated_business_key", True):
            ctx.issue("WARNING", "REPEATED_LINE_ITEM",
                      f"Same institute/department/equipment/sub-category/course appears more than once "
                      f"(occurrence {occ}); kept as a separate line item, as MEDD 1.0 did",
                      r.sheet, r.row_no, "equipment", f["equipment"])
        q = {k: f.get(k, 0) for k in QTY_FIELDS}
        values_sig = sha1(nk, *q.values())
        if values_sig in exact_seen:
            ctx.issue("WARNING", "EXACT_DUPLICATE_ROW", "Row is an exact duplicate of an earlier row", r.sheet, r.row_no)
        exact_seen.add(values_sig)
        if v.get("warn_functional_gt_available", True) and q["functional_qty"] > q["available_qty"]:
            ctx.issue("WARNING", "FUNCTIONAL_GT_AVAILABLE",
                      f"Functional ({q['functional_qty']}) exceeds available ({q['available_qty']})",
                      r.sheet, r.row_no, "functional_qty", q["functional_qty"])
        nonfunc = max(q["available_qty"] - q["functional_qty"], 0)
        if v.get("warn_condemnation_gt_nonfunctional", True) and q["condemnation_qty"] > nonfunc:
            ctx.issue("WARNING", "CONDEMNATION_GT_NONFUNCTIONAL",
                      f"Proposed condemnation ({q['condemnation_qty']}) exceeds non-functional ({nonfunc})",
                      r.sheet, r.row_no, "condemnation_qty", q["condemnation_qty"])
        if v.get("warn_amc_gt_functional", True) and q["amc_cmc_qty"] > q["functional_qty"]:
            ctx.issue("WARNING", "AMC_GT_FUNCTIONAL",
                      f"AMC/CMC units ({q['amc_cmc_qty']}) exceed functional ({q['functional_qty']})",
                      r.sheet, r.row_no, "amc_cmc_qty", q["amc_cmc_qty"])
        of, om = float(v.get("procurement_outlier_factor", 10)), int(v.get("procurement_outlier_min_units", 500))
        if q["proposed_qty"] > max(om, of * q["required_qty"]):
            ctx.issue("WARNING", "PROCUREMENT_OUTLIER",
                      f"Proposed procurement {q['proposed_qty']:,} is far above the requirement ({q['required_qty']:,}) for "
                      f"'{f['equipment']}' at '{f['institute']}' — please verify (value NOT changed)",
                      r.sheet, r.row_no, "proposed_qty", q["proposed_qty"])
        if f.get("institute_short_name"):
            res.short_alias(f["institute_short_name"], rec)
        if f.get("unit_cost") is not None and eq_id not in file_costs:
            if eq_id in inline_costs and inline_costs[eq_id] != f["unit_cost"]:
                ctx.issue("WARNING", "CONFLICTING_UNIT_COST", f"'{f['equipment']}' has different unit costs on "
                          "different rows; first value kept", r.sheet, r.row_no, "unit_cost", f["unit_cost"],
                          once_key=eq_id)
            else:
                inline_costs.setdefault(eq_id, float(f["unit_cost"]))
        bk = sha1(nk, occ)
        row_hash = sha1(bk, sc_id, f.get("course_category"), f.get("department_type"), f.get("cost_category"),
                        *q.values())
        raw_names = {k: r.raw.get(k) for k in r.raw} if r.raw else None
        tmp_rows.append([bk, rec[0], dep_id, eq_id, sc_id, f.get("course_category"), f.get("department_type"),
                         f.get("cost_category"), occ, q["required_qty"], q["available_qty"], q["functional_qty"],
                         q["proposed_qty"], q["amc_cmc_qty"], q["end_of_life_qty"], q["condemnation_qty"], row_hash,
                         r.sheet, r.row_no, json.dumps(raw_names, default=str)])
    for eq_id, uc in inline_costs.items():
        uc_changed += _upsert_unit_cost(db, ctx, eq_id, uc, cost_band(uc, rules))
    ctx.extra["unit_costs_changed"] = uc_changed

    total = len(inv) + len(parsed["unit_cost"]) + len(parsed["institute"])
    rejected = sum(r.rejected for rows in parsed.values() for r in rows)
    ctx.counts["rows_read"], ctx.counts["rows_rejected"] = total, rejected
    ctx.counts["rows_valid"] = total - rejected
    ratio = rejected / total if total else 0
    if ratio > float(v.get("max_reject_ratio", 0.05)):
        raise FatalIngestionError(f"{rejected} of {total} rows ({ratio:.1%}) failed validation, above the "
                                  f"{float(v['max_reject_ratio']):.0%} threshold. Nothing was applied to production. "
                                  "Fix the rows listed in the report and re-upload.")

    if tmp_rows:
        _apply_line_items(db, ctx, tmp_rows, rules)

    # procurement without unit cost (after all costs applied)
    if v.get("warn_procurement_without_unit_cost", True) and tmp_rows:
        miss = db.execute(text("""SELECT e.name, sum(t.proposed_qty) q FROM tmp_li t JOIN master_data.equipment e ON e.id=t.equipment_id
                                  LEFT JOIN financial.equipment_unit_cost u ON u.equipment_id=t.equipment_id
                                  WHERE t.proposed_qty>0 AND COALESCE(u.unit_cost,0)=0 GROUP BY e.name ORDER BY q DESC""")).all()
        if miss:
            ctx.issue("WARNING", "PROCUREMENT_WITHOUT_UNIT_COST",
                      f"{len(miss)} equipment item(s) with proposed procurement ({sum(m.q for m in miss):,} units) have no "
                      f"unit cost, so their budget is ₹0. Largest: " + "; ".join(f"{m.name} ({m.q})" for m in miss[:10]))


def _apply_line_items(db: Session, ctx: Ctx, tmp_rows: list, rules: dict) -> None:
    db.execute(text("""CREATE TEMP TABLE tmp_li (business_key char(40) PRIMARY KEY, institute_id int, department_id int,
        equipment_id int, sub_category_id int, course_category text, department_type text, cost_category text,
        occurrence smallint, required_qty int, available_qty int, functional_qty int, proposed_qty int, amc_cmc_qty int,
        end_of_life_qty int, condemnation_qty int, row_hash char(40), source_sheet text, source_row int, raw_names jsonb)
        ON COMMIT DROP"""))
    pg = db.connection().connection.driver_connection
    with pg.cursor() as cur:
        with cur.copy("COPY tmp_li FROM STDIN") as cp:
            for row in tmp_rows:
                cp.write_row(row)
    fid = {"fid": ctx.file_id}
    newvals = """jsonb_build_object('required',t.required_qty,'available',t.available_qty,'functional',t.functional_qty,
                 'procurement',t.proposed_qty,'amc',t.amc_cmc_qty,'end_of_life',t.end_of_life_qty,
                 'condemnation',t.condemnation_qty,'sub_category_id',t.sub_category_id,'course_category',t.course_category,
                 'department_type',t.department_type,'cost_category',t.cost_category)"""
    # history of changed rows (old -> new) BEFORE the upsert
    db.execute(text(f"""INSERT INTO audit.line_item_history(line_item_id, file_id, change_type, old_values, new_values)
        SELECT li.id, :fid, CASE WHEN li.is_active THEN 'UPDATE' ELSE 'REACTIVATE' END,
          jsonb_build_object('required',li.required_qty,'available',li.available_qty,'functional',li.functional_qty,
            'procurement',pp.proposed_qty,'amc',am.amc_cmc_qty,'end_of_life',lc.end_of_life_qty,
            'condemnation',lc.condemnation_qty,'sub_category_id',li.sub_category_id,'course_category',li.course_category,
            'department_type',li.department_type,'cost_category',li.cost_category), {newvals}
        FROM tmp_li t JOIN equipment_inventory.line_item li ON li.business_key=t.business_key
        LEFT JOIN procurement.procurement_proposal pp ON pp.line_item_id=li.id
        LEFT JOIN maintenance.amc_coverage am ON am.line_item_id=li.id
        LEFT JOIN lifecycle.lifecycle_status lc ON lc.line_item_id=li.id
        WHERE li.row_hash<>t.row_hash OR NOT li.is_active"""), fid)
    ret = db.execute(text("""INSERT INTO equipment_inventory.line_item AS li (business_key, institute_id, department_id,
          equipment_id, sub_category_id, course_category, department_type, cost_category, occurrence, required_qty,
          available_qty, functional_qty, row_hash, is_active, source_file_id, source_sheet, source_row, raw_names)
        SELECT business_key, institute_id, department_id, equipment_id, sub_category_id, course_category, department_type,
          cost_category, occurrence, required_qty, available_qty, functional_qty, row_hash, true, :fid, source_sheet,
          source_row, raw_names FROM tmp_li
        ON CONFLICT (business_key) DO UPDATE SET institute_id=EXCLUDED.institute_id, department_id=EXCLUDED.department_id,
          equipment_id=EXCLUDED.equipment_id, sub_category_id=EXCLUDED.sub_category_id,
          course_category=EXCLUDED.course_category, department_type=EXCLUDED.department_type,
          cost_category=EXCLUDED.cost_category, required_qty=EXCLUDED.required_qty,
          available_qty=EXCLUDED.available_qty, functional_qty=EXCLUDED.functional_qty, row_hash=EXCLUDED.row_hash,
          is_active=true, source_file_id=EXCLUDED.source_file_id, source_sheet=EXCLUDED.source_sheet,
          source_row=EXCLUDED.source_row, raw_names=EXCLUDED.raw_names, updated_at=now()
        WHERE li.row_hash <> EXCLUDED.row_hash OR NOT li.is_active
        RETURNING li.id, (xmax = 0) AS inserted"""), fid).all()
    inserted = sum(1 for r in ret if r.inserted)
    ctx.counts["rows_inserted"] = inserted
    ctx.counts["rows_updated"] = len(ret) - inserted
    ctx.counts["rows_unchanged"] = len(tmp_rows) - len(ret)
    db.execute(text(f"""INSERT INTO audit.line_item_history(line_item_id, file_id, change_type, new_values)
        SELECT li.id, :fid, 'INSERT', {newvals} FROM tmp_li t JOIN equipment_inventory.line_item li
        ON li.business_key=t.business_key WHERE li.id = ANY(:ids)"""),
               {"fid": ctx.file_id, "ids": [r.id for r in ret if r.inserted]})
    for table, col, src in (("procurement.procurement_proposal", "proposed_qty", "proposed_qty"),
                            ("maintenance.amc_coverage", "amc_cmc_qty", "amc_cmc_qty")):
        db.execute(text(f"""INSERT INTO {table} AS x (line_item_id, {col})
            SELECT li.id, t.{src} FROM tmp_li t JOIN equipment_inventory.line_item li ON li.business_key=t.business_key
            ON CONFLICT (line_item_id) DO UPDATE SET {col}=EXCLUDED.{col}, updated_at=now()
            WHERE x.{col} IS DISTINCT FROM EXCLUDED.{col}"""))
    db.execute(text("""INSERT INTO lifecycle.lifecycle_status AS x (line_item_id, end_of_life_qty, condemnation_qty)
        SELECT li.id, t.end_of_life_qty, t.condemnation_qty FROM tmp_li t
        JOIN equipment_inventory.line_item li ON li.business_key=t.business_key
        ON CONFLICT (line_item_id) DO UPDATE SET end_of_life_qty=EXCLUDED.end_of_life_qty,
          condemnation_qty=EXCLUDED.condemnation_qty, updated_at=now()
        WHERE (x.end_of_life_qty, x.condemnation_qty) IS DISTINCT FROM (EXCLUDED.end_of_life_qty, EXCLUDED.condemnation_qty)"""))
    if rules.get("sync_mode", "snapshot") == "snapshot":
        n = db.execute(text("""WITH gone AS (
              UPDATE equipment_inventory.line_item li SET is_active=false, updated_at=now(), source_file_id=:fid
              WHERE li.is_active AND li.institute_id IN (SELECT DISTINCT institute_id FROM tmp_li)
                AND NOT EXISTS (SELECT 1 FROM tmp_li t WHERE t.business_key=li.business_key)
              RETURNING li.id),
            h AS (INSERT INTO audit.line_item_history(line_item_id, file_id, change_type)
                  SELECT id, :fid, 'DEACTIVATE' FROM gone RETURNING 1)
            SELECT count(*) FROM h"""), fid).scalar()
        ctx.counts["rows_deactivated"] = int(n or 0)


def refresh_analytics(db: Session) -> None:
    populated = db.execute(text("SELECT ispopulated FROM pg_matviews WHERE schemaname='analytics' "
                                "AND matviewname='mv_line_fact'")).scalar()
    db.execute(text("REFRESH MATERIALIZED VIEW " + ("CONCURRENTLY " if populated else "") + "analytics.mv_line_fact"))


def bump_version(db: Session, file_id: int | None, duration_ms: int, description: str) -> int:
    ver = db.execute(text("""UPDATE metadata.app_setting SET value = to_jsonb(COALESCE((value #>> '{}')::bigint, 0) + 1),
                             updated_at = now() WHERE key='data_version' RETURNING (value #>> '{}')::bigint""")).scalar()
    now_iso = datetime.now(timezone.utc).isoformat()
    db.execute(text("UPDATE metadata.app_setting SET value=to_jsonb(CAST(:t AS text)), updated_at=now() WHERE key='last_refresh'"),
               {"t": now_iso})
    db.execute(text("INSERT INTO metadata.data_refresh(file_id, duration_ms, data_version) VALUES (:f,:d,:v)"),
               {"f": file_id, "d": duration_ms, "v": ver})
    db.execute(text("UPDATE metadata.dataset_version SET is_current=false WHERE is_current"))
    db.execute(text("""INSERT INTO metadata.dataset_version(file_id, description, line_items, is_current)
                       SELECT :f, :d, count(*), true FROM equipment_inventory.line_item WHERE is_active"""),
               {"f": file_id, "d": description})
    return int(ver)


# ---------------------------------------------------------------------------------------------- reporting
def write_report(ctx: Ctx, rec: dict) -> str:
    s = get_settings()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = s.reports_dir / f"{ctx.file_id:05d}_{stamp}_{Path(rec['original_name']).stem}"
    sev = {"ERROR": 0, "WARNING": 0, "INFO": 0}
    by_code: dict[tuple, int] = {}
    for i in ctx.issues:
        sev[i["severity"]] += 1
        by_code[(i["severity"], i["code"])] = by_code.get((i["severity"], i["code"]), 0) + 1
    payload = {**rec, "counts": ctx.counts, "severity_totals": sev, "sheets": ctx.extra.get("sheets", []),
               "unit_costs_changed": ctx.extra.get("unit_costs_changed", 0),
               "issue_summary": [{"severity": k[0], "code": k[1], "count": n} for k, n in sorted(by_code.items())],
               "issues": ctx.issues[:5000], "issues_truncated": len(ctx.issues) > 5000}
    Path(str(base) + ".json").write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    with open(str(base) + "_issues.csv", "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=["severity", "code", "sheet_name", "row_no", "field", "value", "message"])
        w.writeheader()
        for i in ctx.issues:
            w.writerow({k: i.get(k) for k in w.fieldnames})
    md = io.StringIO()
    md.write(f"# Ingestion & Validation Report — {rec['original_name']}\n\n")
    md.write(f"| Item | Value |\n|---|---|\n| File ID | {ctx.file_id} |\n| Status | **{rec['status']}** |\n"
             f"| SHA-256 | `{rec['sha256']}` |\n| Size | {rec['size_bytes']:,} bytes |\n| Triggered by | {rec['triggered_by']} |\n"
             f"| Sync mode | {rec.get('sync_mode')} |\n| Started | {rec.get('started_at')} |\n| Finished | {rec.get('finished_at')} |\n")
    if rec.get("error_message"):
        md.write(f"\n> **Failure reason:** {rec['error_message']}\n>\n> Production data was **not** modified.\n")
    md.write("\n## Record counts\n\n| Measure | Rows |\n|---|---|\n")
    for k, n in ctx.counts.items():
        md.write(f"| {k.replace('_', ' ')} | {n:,} |\n")
    md.write(f"| unit costs changed | {ctx.extra.get('unit_costs_changed', 0):,} |\n")
    md.write("\n## Worksheets\n\n| Sheet | Detected as | Header row | Rows | Unmapped columns |\n|---|---|---|---|---|\n")
    for sh in ctx.extra.get("sheets", []):
        md.write(f"| {sh['sheet_name']} | {sh['dataset_type']} | {sh['header_row'] or '—'} | {sh['rows_read']:,} | "
                 f"{', '.join(map(str, sh['unmapped_columns'][:8])) or '—'} |\n")
        if sh["column_map"]:
            md.write(f"|  | ↳ mapped: {'; '.join(f'{k} ← “{v}”' for k, v in sh['column_map'].items())} | | | |\n")
    md.write("\n## Issues by type\n\n| Severity | Code | Count |\n|---|---|---|\n")
    for (sv, code), n in sorted(by_code.items()):
        md.write(f"| {sv} | {code} | {n:,} |\n")
    md.write("\nFull row-level list: `" + Path(str(base) + "_issues.csv").name + "`\n")
    Path(str(base) + ".md").write_text(md.getvalue(), encoding="utf-8")
    return str(base) + ".md"


def _save_issues(file_id: int, issues: list) -> None:
    if not issues:
        return
    with write_tx() as db:
        pg = db.connection().connection.driver_connection
        with pg.cursor() as cur:
            with cur.copy("COPY metadata.validation_issue (file_id, sheet_name, row_no, severity, code, field, message, value) "
                          "FROM STDIN") as cp:
                for i in issues:
                    cp.write_row([file_id, i["sheet_name"], i["row_no"], i["severity"], i["code"], i["field"],
                                  i["message"], i["value"]])


# ---------------------------------------------------------------------------------------------- orchestration
def _unique_dest(folder: Path, name: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / name
    n = 1
    while dest.exists():
        dest = folder / f"{Path(name).stem}__{n}{Path(name).suffix}"
        n += 1
    return dest


def process_file(path: Path, triggered_by: str = "watcher") -> dict:
    """Process one file end-to-end. Thread- and process-safe (lock + PostgreSQL advisory lock)."""
    with _LOCK:
        return _process(Path(path), triggered_by)


def _process(path: Path, triggered_by: str) -> dict:
    s = get_settings()
    rules = load_rules()
    t0 = time.monotonic()
    if not path.exists():
        return {"status": "MISSING", "file": str(path)}
    if path.suffix.lower() not in rules["supported_extensions"]:
        dest = _unique_dest(s.failed_dir, path.name)
        shutil.move(str(path), dest)
        dest.with_suffix(dest.suffix + ".error.txt").write_text(
            f"Unsupported file type '{path.suffix}'. Supported: {', '.join(rules['supported_extensions'])}\n")
        return {"status": "FAILED", "error": "unsupported file type", "file": path.name}
    sha, size = file_sha256(path), path.stat().st_size
    with write_tx() as db:
        prior = db.execute(text("""SELECT id FROM metadata.ingestion_file WHERE sha256=:s
                                   AND status IN ('SUCCESS','SUCCESS_WITH_WARNINGS') ORDER BY id DESC LIMIT 1"""),
                           {"s": sha}).scalar()
        status0 = "DUPLICATE" if prior else "RECEIVED"
        fid = db.execute(text("""INSERT INTO metadata.ingestion_file(original_name, sha256, size_bytes, status, triggered_by,
                                 sync_mode, started_at) VALUES (:n,:s,:z,:st,:t,:m, now()) RETURNING id"""),
                         {"n": path.name, "s": sha, "z": size, "st": status0, "t": triggered_by,
                          "m": rules.get("sync_mode")}).scalar()
    if prior:
        dest = _unique_dest(s.archive_dir / "duplicates", f"{fid:05d}_{path.name}")
        shutil.move(str(path), dest)
        msg = f"Identical file (SHA-256) already processed as file #{prior}; skipped — no duplicate records created."
        with write_tx() as db:
            db.execute(text("UPDATE metadata.ingestion_file SET stored_path=:p, error_message=:m, finished_at=now() WHERE id=:i"),
                       {"p": str(dest), "m": msg, "i": fid})
            db.execute(text("INSERT INTO audit.audit_log(actor, action, entity, entity_id, details) VALUES "
                            "(:a,'INGESTION_DUPLICATE','ingestion_file',:i,CAST(:d AS jsonb))"),
                       {"a": triggered_by, "i": str(fid), "d": json.dumps({"file": path.name, "duplicate_of": prior})})
        log.info("duplicate file %s skipped (same as #%s)", path.name, prior)
        return {"file_id": fid, "status": "DUPLICATE", "message": msg}

    work = _unique_dest(s.processing_dir, f"{fid:05d}_{path.name}")
    shutil.move(str(path), work)
    with write_tx() as db:
        db.execute(text("UPDATE metadata.ingestion_file SET status='PROCESSING', stored_path=:p WHERE id=:i"),
                   {"p": str(work), "i": fid})

    ctx = Ctx(fid)
    parsed = {"inventory": [], "unit_cost": [], "institute": []}
    status, error, version = "FAILED", None, None
    try:
        parsed = parse_sheets(ctx, work, rules)
        stage_rows(ctx, parsed)
        with write_tx() as db:
            db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": ADVISORY_LOCK_ID})
            apply_production(db, ctx, parsed, rules)
            refresh_analytics(db)
            types = [k for k, v in parsed.items() if v]
            version = bump_version(db, fid, int((time.monotonic() - t0) * 1000), f"{path.name} ({', '.join(types)})")
        has_warn = any(i["severity"] in ("WARNING", "ERROR") for i in ctx.issues)
        status = "SUCCESS_WITH_WARNINGS" if has_warn else "SUCCESS"
    except (FatalIngestionError, UnreadableFile) as exc:
        error = str(exc)
        ctx.issue("ERROR", "FILE_REJECTED", error)
    except Exception as exc:  # unexpected: production transaction already rolled back by write_tx
        log.exception("ingestion failed for %s", path.name)
        error = f"Unexpected processing error ({exc.__class__.__name__}): {exc}"
        ctx.issue("ERROR", "PROCESSING_ERROR", error)

    try:
        finalize_staging(ctx, parsed)
    except Exception:  # staging bookkeeping must not mask the real outcome
        log.exception("could not finalise staging statuses")
    _save_issues(fid, ctx.issues)

    if status.startswith("SUCCESS"):
        dest = _unique_dest(s.processed_dir, work.name)
        shutil.move(str(work), dest)
        arch = s.archive_dir / datetime.now().strftime("%Y") / datetime.now().strftime("%m")
        shutil.copy2(dest, _unique_dest(arch, f"{fid:05d}_{sha[:8]}_{path.name}"))
    else:
        dest = _unique_dest(s.failed_dir, work.name)
        shutil.move(str(work), dest)
    sev = {k: sum(1 for i in ctx.issues if i["severity"] == k) for k in ("ERROR", "WARNING")}
    rec = {"file_id": fid, "original_name": path.name, "status": status, "sha256": sha, "size_bytes": size,
           "triggered_by": triggered_by, "sync_mode": rules.get("sync_mode"), "error_message": error,
           "data_version": version, "duration_ms": int((time.monotonic() - t0) * 1000),
           "started_at": None, "finished_at": datetime.now(timezone.utc).isoformat()}
    report = write_report(ctx, rec)
    if not status.startswith("SUCCESS"):
        dest.with_name(dest.name + ".error.txt").write_text(
            f"{error}\n\nFull report: {report}\nProduction data was NOT modified.\n", encoding="utf-8")
    with write_tx() as db:
        db.execute(text("""UPDATE metadata.ingestion_file SET status=:st, stored_path=:p, dataset_types=:dt,
            rows_read=:rr, rows_valid=:rv, rows_rejected=:rj, rows_inserted=:ri, rows_updated=:ru, rows_unchanged=:rn,
            rows_deactivated=:rd, warnings=:w, errors=:e, error_message=:em, report_path=:rp, finished_at=now()
            WHERE id=:i"""),
                   {"st": status, "p": str(dest), "dt": [k for k, v in parsed.items() if v] or None,
                    "rr": ctx.counts["rows_read"], "rv": ctx.counts["rows_valid"], "rj": ctx.counts["rows_rejected"],
                    "ri": ctx.counts["rows_inserted"], "ru": ctx.counts["rows_updated"],
                    "rn": ctx.counts["rows_unchanged"], "rd": ctx.counts["rows_deactivated"], "w": sev["WARNING"],
                    "e": sev["ERROR"], "em": error, "rp": report, "i": fid})
        db.execute(text("INSERT INTO audit.audit_log(actor, action, entity, entity_id, details) VALUES "
                        "(:a, :ac, 'ingestion_file', :i, CAST(:d AS jsonb))"),
                   {"a": triggered_by, "ac": "INGESTION_" + status, "i": str(fid),
                    "d": json.dumps({"file": path.name, "counts": ctx.counts, "error": error, "data_version": version})})
        # notify AFTER the bookkeeping row is final (production data was already committed above)
        if status.startswith("SUCCESS"):
            sql, params = notify_sql({"type": "data_refreshed", "data_version": version, "file_id": fid,
                                      "file": path.name, "status": status, "at": datetime.now(timezone.utc).isoformat()})
        else:
            sql, params = notify_sql({"type": "ingestion_failed", "file_id": fid, "file": path.name, "error": error})
        db.execute(text(sql), params)
    log.info("ingestion %s -> %s %s", path.name, status, ctx.counts)
    return {**rec, "counts": ctx.counts, "report": report,
            "issues": {"errors": sev["ERROR"], "warnings": sev["WARNING"]}}


def revert_file(file_id: int, actor: str) -> dict:
    """Undo the production changes of the MOST RECENT successful ingestion using audit.line_item_history."""
    with write_tx() as db:
        db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": ADVISORY_LOCK_ID})
        last = db.execute(text("""SELECT id FROM metadata.ingestion_file WHERE status IN ('SUCCESS','SUCCESS_WITH_WARNINGS')
                                  AND rows_read > 0 ORDER BY id DESC LIMIT 1""")).scalar()
        if last != file_id:
            raise FatalIngestionError(f"Only the most recent successful ingestion (#{last}) can be rolled back.")
        hist = db.execute(text("""SELECT line_item_id, change_type, old_values FROM audit.line_item_history
                                  WHERE file_id=:f ORDER BY id DESC"""), {"f": file_id}).all()
        n = 0
        for h in hist:
            if h.change_type == "INSERT":
                db.execute(text("UPDATE equipment_inventory.line_item SET is_active=false, updated_at=now() WHERE id=:i"),
                           {"i": h.line_item_id})
            elif h.change_type == "DEACTIVATE":
                db.execute(text("UPDATE equipment_inventory.line_item SET is_active=true, updated_at=now() WHERE id=:i"),
                           {"i": h.line_item_id})
            elif h.change_type in ("UPDATE", "REACTIVATE") and h.old_values:
                o = h.old_values
                db.execute(text("""UPDATE equipment_inventory.line_item SET required_qty=:r, available_qty=:a,
                    functional_qty=:fu, sub_category_id=:sc, course_category=:cc, department_type=:dt, cost_category=:ct,
                    is_active=:act, row_hash=md5(random()::text) || 'reverted', updated_at=now() WHERE id=:i"""),
                           {"r": o["required"], "a": o["available"], "fu": o["functional"], "sc": o.get("sub_category_id"),
                            "cc": o.get("course_category"), "dt": o.get("department_type"), "ct": o.get("cost_category"),
                            "act": h.change_type == "UPDATE", "i": h.line_item_id})
                db.execute(text("UPDATE procurement.procurement_proposal SET proposed_qty=COALESCE(:v,0) WHERE line_item_id=:i"),
                           {"v": o.get("procurement"), "i": h.line_item_id})
                db.execute(text("UPDATE maintenance.amc_coverage SET amc_cmc_qty=COALESCE(:v,0) WHERE line_item_id=:i"),
                           {"v": o.get("amc"), "i": h.line_item_id})
                db.execute(text("""UPDATE lifecycle.lifecycle_status SET end_of_life_qty=COALESCE(:e,0),
                                   condemnation_qty=COALESCE(:c,0) WHERE line_item_id=:i"""),
                           {"e": o.get("end_of_life"), "c": o.get("condemnation"), "i": h.line_item_id})
            n += 1
        db.execute(text("UPDATE metadata.ingestion_file SET status='ROLLED_BACK' WHERE id=:f"), {"f": file_id})
        refresh_analytics(db)
        ver = bump_version(db, None, 0, f"rollback of file #{file_id}")
        db.execute(text("INSERT INTO audit.audit_log(actor, action, entity, entity_id, details) VALUES "
                        "(:a,'INGESTION_ROLLED_BACK','ingestion_file',:i,CAST(:d AS jsonb))"),
                   {"a": actor, "i": str(file_id), "d": json.dumps({"changes_reverted": n})})
        sql, params = notify_sql({"type": "data_refreshed", "data_version": ver, "rollback_of": file_id})
        db.execute(text(sql), params)
    return {"file_id": file_id, "changes_reverted": n, "data_version": ver}
