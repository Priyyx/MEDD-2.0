"""Header-row detection, column -> canonical field mapping and worksheet classification."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache

import pandas as pd
import yaml

from app.config import get_settings

_PAREN = re.compile(r"\([^)]*\)|\[[^\]]*\]")
_NONALNUM = re.compile(r"[^a-z0-9/<]+")
_UNIT_WORDS = {"nos", "no", "numbers", "number", "in", "rs", "inr", "units", "unit(s)", "qty", "quantity", "of", "the"}


def norm_header(h) -> str:
    if h is None or (isinstance(h, float) and pd.isna(h)):
        return ""
    s = str(h).replace("₹", " rs ").lower()
    s = _NONALNUM.sub(" ", s)
    return " ".join(s.split())


def loose_header(h) -> str:
    """Second-chance key: drop bracketed text and unit/filler words ('Qty. Available (Nos)' -> 'available')."""
    s = _PAREN.sub(" ", str(h or "")).replace("₹", " ")
    words = [w for w in norm_header(s).split() if w not in _UNIT_WORDS]
    return " ".join(words)


@lru_cache
def load_mapping() -> dict:
    with open(get_settings().config_dir / "column_mappings.yaml", encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)
    compiled = {}
    for ds, spec in cfg["datasets"].items():
        exact, loose = {}, {}
        for fld, syns in spec["fields"].items():
            for s in syns + [fld.replace("_", " ")]:
                exact.setdefault(norm_header(s), fld)
                loose.setdefault(loose_header(s), fld)
        compiled[ds] = {"spec": spec, "exact": exact, "loose": loose}
    return compiled


def match_field(header, ds: str) -> str | None:
    m = load_mapping()[ds]
    h = norm_header(header)
    if not h:
        return None
    if h in m["exact"]:
        return m["exact"][h]
    lh = loose_header(header)
    if lh and lh in m["loose"]:
        return m["loose"][lh]
    return None


@dataclass
class SheetLayout:
    dataset_type: str | None
    header_row: int | None                       # 0-based row index of the (last) header row
    columns: dict[str, int] = field(default_factory=dict)        # canonical field -> column index
    column_headers: dict[str, str] = field(default_factory=dict) # canonical field -> original header text
    unmapped: list[str] = field(default_factory=list)
    duplicate_mappings: list[str] = field(default_factory=list)
    all_headers: list[str] = field(default_factory=list)          # every header cell (for full-row traceability)
    reason: str = ""


def _headers_for(grid: pd.DataFrame, r: int, combine_prev: bool) -> list[str]:
    row = [grid.iat[r, c] for c in range(grid.shape[1])]
    if not combine_prev or r == 0:
        return [("" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v)) for v in row]
    prev = [grid.iat[r - 1, c] for c in range(grid.shape[1])]
    out, carry = [], ""
    for p, v in zip(prev, row):
        p = "" if p is None or (isinstance(p, float) and pd.isna(p)) else str(p)
        v = "" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v)
        carry = p or carry               # merged cells: carry the group label across
        out.append(f"{carry} {v}".strip() if v else (p or ""))
    return out


def _map(headers: list[str], ds: str) -> tuple[dict, dict, list, list]:
    cols, orig, unmapped, dups = {}, {}, [], []
    for idx, h in enumerate(headers):
        if not norm_header(h):
            continue
        f = match_field(h, ds)
        if f is None:
            unmapped.append(h)
        elif f in cols:
            dups.append(f"{h} (also matches '{f}', first column kept)")
        else:
            cols[f], orig[f] = idx, h
    return cols, orig, unmapped, dups


def detect_layout(grid: pd.DataFrame, scan_rows: int) -> SheetLayout:
    mapping = load_mapping()
    best: tuple[int, SheetLayout] | None = None
    n = min(scan_rows, grid.shape[0])
    for r in range(n):
        for combine in (False, True):
            headers = _headers_for(grid, r, combine)
            for ds, m in mapping.items():
                spec = m["spec"]
                cols, orig, unmapped, dups = _map(headers, ds)
                if not all(f in cols for f in spec.get("required", [])):
                    continue
                if spec.get("required_any") and not any(f in cols for f in spec["required_any"]):
                    continue
                if any(f in cols for f in spec.get("forbid", [])):
                    continue
                # also refuse if an inventory-only identity column exists for non-inventory types
                score = len(cols) * 10 - len(unmapped) - (1 if combine else 0)
                if ds == "inventory":
                    score += 5
                lay = SheetLayout(ds, r, cols, orig, unmapped, dups, headers)
                if best is None or score > best[0]:
                    best = (score, lay)
    if best is None:
        return SheetLayout(None, None, reason="No header row with the required columns was found in the first "
                                               f"{n} rows (see config/column_mappings.yaml).")
    return best[1]
