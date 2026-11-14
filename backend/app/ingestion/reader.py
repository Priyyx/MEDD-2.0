"""Read XLS / XLSX / XLSM / CSV / JSON into raw, header-less grids (one per worksheet)."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd


class UnreadableFile(Exception):
    pass


@dataclass
class RawSheet:
    name: str
    grid: pd.DataFrame   # header=None; every cell kept as the original Python object (str/float/int/datetime)


def _csv(path: Path) -> list[RawSheet]:
    last = None
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            df = pd.read_csv(path, header=None, dtype=object, encoding=enc, keep_default_na=False,
                             sep=None, engine="python")
            return [RawSheet(path.stem, df)]
        except UnicodeDecodeError as exc:
            last = exc
        except Exception as exc:  # malformed CSV
            raise UnreadableFile(f"CSV could not be parsed: {exc}") from exc
    raise UnreadableFile(f"CSV encoding not recognised: {last}")


def _json(path: Path) -> list[RawSheet]:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        raise UnreadableFile(f"JSON could not be parsed: {exc}") from exc
    sheets: dict[str, list] = {}
    if isinstance(data, list):
        sheets[path.stem] = data
    elif isinstance(data, dict):
        if "sheets" in data and isinstance(data["sheets"], dict):
            data = data["sheets"]
        for k, v in data.items():
            if isinstance(v, list):
                sheets[str(k)] = v
    if not sheets:
        raise UnreadableFile("JSON must be a list of records or an object of {sheet_name: [records]}")
    out = []
    for name, records in sheets.items():
        records = [r for r in records if isinstance(r, dict)]
        if not records:
            continue
        cols: list[str] = []
        for r in records:
            for k in r:
                if k not in cols:
                    cols.append(k)
        grid = [cols] + [[r.get(c) for c in cols] for r in records]
        out.append(RawSheet(name, pd.DataFrame(grid, dtype=object)))
    return out


def _excel(path: Path) -> list[RawSheet]:
    engine = "xlrd" if path.suffix.lower() == ".xls" else "openpyxl"
    try:
        book = pd.read_excel(path, sheet_name=None, header=None, dtype=object, engine=engine)
    except Exception as exc:
        raise UnreadableFile(f"Workbook could not be opened ({engine}): {exc}") from exc
    return [RawSheet(str(name), df) for name, df in book.items() if not df.dropna(how="all").empty]


def read_any(path: Path) -> list[RawSheet]:
    ext = path.suffix.lower()
    if ext in (".xlsx", ".xlsm", ".xls"):
        return _excel(path)
    if ext == ".csv":
        return _csv(path)
    if ext == ".json":
        return _json(path)
    raise UnreadableFile(f"Unsupported file type '{ext}'")
