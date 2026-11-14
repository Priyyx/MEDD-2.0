"""Name standardisation rules (traceable, deterministic, configurable).

Rules applied to every institute / department / equipment / division / sub-category name:
  1. Unicode NFKC normalisation; curly quotes -> straight; en/em dashes -> '-'; NBSP -> space
  2. Trim and collapse internal whitespace
  3. Matching key = lower-case of the cleaned name when ``merge_case_variants`` is on (default),
     so 'ABG Machine' and 'ABG machine' resolve to one equipment.
  4. Security: characters that are unsafe inside HTML/JS (< " backslash `) are replaced by visually identical typographic
     equivalents (‹ ″ ∖ ʹ). None occur in the current master workbook; this prevents stored-XSS via uploaded files.
  5. Approved alias table (master_data.name_alias + config/name_aliases.yaml) maps a key to a canonical name.
The original spelling of every source row is preserved in line_item.raw_names.
"""
from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

import yaml

from app.config import get_settings

_QUOTES = {"‘": "'", "’": "'", "‚": "'", "‛": "'", "“": '"', "”": '"',
           "′": "'", "´": "'", "`": "'"}
_DASHES = {"‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "−": "-"}
_UNSAFE = {"<": "\u2039", '"': "\u2033", "\\": "\u2216", "`": "\u02b9"}
_WS = re.compile(r"\s+")


@lru_cache
def load_rules() -> dict:
    path = get_settings().config_dir / "ingestion.yaml"
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def clean_name(value) -> str | None:
    if value is None:
        return None
    s = str(value)
    if s.strip() == "" or s.strip().lower() in {"nan", "none", "null", "-", "--", "n/a", "na"}:
        return None
    s = unicodedata.normalize("NFKC", s)
    for a, b in {**_QUOTES, **_DASHES}.items():
        s = s.replace(a, b)
    s = s.replace(" ", " ")
    for a, b in _UNSAFE.items():
        s = s.replace(a, b)
    s = _WS.sub(" ", s).strip()
    return s or None


def name_key(value: str | None, *, merge_case: bool | None = None) -> str | None:
    s = clean_name(value)
    if s is None:
        return None
    if merge_case is None:
        merge_case = bool(load_rules().get("standardisation", {}).get("merge_case_variants", True))
    return s.lower() if merge_case else s


def division_key(value: str | None) -> str | None:
    """Loose key for divisions: letters only, 'chhatrapati'/'chh' prefixes ignored, kokan==konkan."""
    s = clean_name(value)
    if s is None:
        return None
    k = re.sub(r"[^a-z]", "", s.lower())
    k = k.replace("chhatrapati", "").replace("chh", "")
    k = k.replace("konkan", "kokan").replace("division", "")
    return k
