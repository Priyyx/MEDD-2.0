"""Migrate MEDD 1.0 reference/master data from the original dashboard into PostgreSQL (idempotent).

Source: backend/reference/legacy_dashboard_snapshot.json.gz — the `DATA` object extracted verbatim from the
original index.html (line 314).  What is migrated:

  master_data.division      6 divisions + SVG map key + label centroid
  master_data.district      35 district shapes (SVG path) used by the heat map
  metadata.app_setting.map  map canvas width/height
  master_data.institute     35 institutes with division and bedded capacity ("seat")
  master_data.department    36 departments
  master_data.equipment     equipment names (standardised; case variants merged per config)
  master_data.sub_category  104 sub-category names
  financial.equipment_unit_cost   unit costs from the unique-equipment costing list (source='legacy_1.0')
  metadata.legacy_baseline  1.0 KPI figures (overview/division/institute/department/equipment) — used ONLY by
                            the reconciliation report, never to render the dashboard.

NOT migrated (cannot be reconstructed — see docs/01_SOURCE_CODE_AUDIT.md A2): line-item quantities.
They must be ingested from the master Excel.
"""
from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from sqlalchemy import text  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db.session import write_tx  # noqa: E402
from app.ingestion.standardise import clean_name, division_key, name_key  # noqa: E402

KPI_KEYS = ["required", "available", "functional", "non_functional", "procurement", "net_requirement", "budget",
            "amc", "condemnation", "end_of_life", "college_count", "gap_pct", "util_pct", "proc_pct", "amc_pct",
            "func_pct", "eol_pct", "equipment_types", "line_items", "unit_cost"]


def _metrics(obj: dict) -> dict:
    return {k: obj[k] for k in KPI_KEYS if k in obj}


def load_snapshot() -> dict:
    path = get_settings().reference_dir / "legacy_dashboard_snapshot.json.gz"
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return json.load(fh)


def run() -> dict:
    D = load_snapshot()
    stats = {}
    with write_tx() as db:
        # ---- divisions + map
        cents = D["map"]["div_centroids"]
        for d in D["divisions"]:
            k = division_key(d["name"])
            c = cents.get(k) or [None, None]
            db.execute(text("""INSERT INTO master_data.division(name, map_key, map_cx, map_cy) VALUES (:n,:k,:x,:y)
                               ON CONFLICT (name) DO UPDATE SET map_key=EXCLUDED.map_key, map_cx=EXCLUDED.map_cx,
                               map_cy=EXCLUDED.map_cy, updated_at=now()"""),
                       {"n": clean_name(d["name"]), "k": k, "x": c[0], "y": c[1]})
        divs = {r.map_key: r.id for r in db.execute(text("SELECT id, map_key FROM master_data.division"))}
        div_by_name = {r.name: r.id for r in db.execute(text("SELECT id, name FROM master_data.division"))}
        for dist in D["map"]["districts"]:
            db.execute(text("""INSERT INTO master_data.district(name, division_id, svg_path, label_x, label_y)
                               VALUES (:n,:d,:p,:x,:y) ON CONFLICT (name) DO UPDATE SET division_id=EXCLUDED.division_id,
                               svg_path=EXCLUDED.svg_path, label_x=EXCLUDED.label_x, label_y=EXCLUDED.label_y"""),
                       {"n": dist["name"], "d": divs[dist["division"]], "p": dist["d"], "x": dist.get("cx"), "y": dist.get("cy")})
        db.execute(text("""INSERT INTO metadata.app_setting(key, value) VALUES ('map', CAST(:v AS jsonb))
                           ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, updated_at=now()"""),
                   {"v": json.dumps({"W": D["map"]["W"], "H": D["map"]["H"]})})
        stats["divisions"], stats["districts"] = len(D["divisions"]), len(D["map"]["districts"])

        # ---- division aliases (approved mapping rules)
        aliases = {"chhatrapati sambhaji nagar": "Chh. Sambhaji Nagar", "chhatrapati sambhajinagar": "Chh. Sambhaji Nagar",
                   "aurangabad": "Chh. Sambhaji Nagar", "chh sambhaji nagar": "Chh. Sambhaji Nagar",
                   "sambhajinagar": "Chh. Sambhaji Nagar", "kokan": "Konkan", "mumbai": "Konkan", "konkan division": "Konkan"}
        for a, c in aliases.items():
            db.execute(text("""INSERT INTO master_data.name_alias(entity_type, alias_key, canonical_name, source)
                               VALUES ('division', :a, :c, 'legacy_1.0') ON CONFLICT DO NOTHING"""), {"a": a, "c": c})

        # ---- institutes
        for i in D["institutes"]:
            n = clean_name(i["name"])
            db.execute(text("""INSERT INTO master_data.institute(name, name_key, division_id, bedded_capacity, source)
                               VALUES (:n, :k, :d, :b, 'legacy_1.0')
                               ON CONFLICT (name_key) DO UPDATE SET division_id=EXCLUDED.division_id,
                               bedded_capacity=COALESCE(master_data.institute.bedded_capacity, EXCLUDED.bedded_capacity)"""),
                       {"n": n, "k": name_key(n, merge_case=True), "d": div_by_name[clean_name(i["division"])], "b": i.get("seat")})
        stats["institutes"] = len(D["institutes"])

        # ---- departments
        for dp in D["departments"]:
            n = clean_name(dp["name"])
            db.execute(text("""INSERT INTO master_data.department(name, name_key) VALUES (:n, :k)
                               ON CONFLICT (name_key) DO NOTHING"""), {"n": n, "k": name_key(n, merge_case=True)})
        stats["departments"] = len(D["departments"])

        # ---- equipment (+ unit costs)
        eq_rows = 0
        for e in D["equipment_catalog"]:
            n = clean_name(e["name"])
            k = name_key(n)
            r = db.execute(text("""INSERT INTO master_data.equipment(name, name_key) VALUES (:n, :k)
                                   ON CONFLICT (name_key) DO UPDATE SET name_key=EXCLUDED.name_key RETURNING id"""),
                           {"n": n, "k": k}).one()
            eq_rows += 1
            uc = e.get("unit_cost")
            if uc is not None:
                db.execute(text("""INSERT INTO financial.equipment_unit_cost(equipment_id, unit_cost, source)
                                   VALUES (:e, :u, 'legacy_1.0')
                                   ON CONFLICT (equipment_id) DO UPDATE SET unit_cost =
                                     CASE WHEN financial.equipment_unit_cost.source = 'legacy_1.0'
                                          THEN GREATEST(financial.equipment_unit_cost.unit_cost, EXCLUDED.unit_cost)
                                          ELSE financial.equipment_unit_cost.unit_cost END"""),
                           {"e": r.id, "u": uc})
        stats["equipment_names_in_1.0"] = eq_rows
        stats["equipment_after_standardisation"] = db.execute(text("SELECT count(*) FROM master_data.equipment")).scalar()

        for sc in D["sub_categories"]:
            n = clean_name(sc)
            if n:
                db.execute(text("INSERT INTO master_data.sub_category(name) VALUES (:n) ON CONFLICT DO NOTHING"), {"n": n})

        # ---- reconciliation baseline (1.0 figures)
        def base(level, name, parent, obj):
            db.execute(text("""INSERT INTO metadata.legacy_baseline(level, name, parent, metrics)
                               VALUES (:l, :n, :p, CAST(:m AS jsonb))
                               ON CONFLICT (level, name, parent) DO UPDATE SET metrics=EXCLUDED.metrics"""),
                       {"l": level, "n": name, "p": parent or "", "m": json.dumps(_metrics(obj))})
        base("overview", "Maharashtra", "", D["overview"])
        for d in D["divisions"]:
            base("division", clean_name(d["name"]), "", d)
        for i in D["institutes"]:
            base("institute", clean_name(i["name"]), clean_name(i["division"]), i)
        for dp in D["state_depts"]:
            base("department", clean_name(dp["name"]), "", dp)
        for e in D["equipment_catalog"]:
            base("equipment", clean_name(e["name"]), "", e)
        stats["baseline_rows"] = db.execute(text("SELECT count(*) FROM metadata.legacy_baseline")).scalar()

        db.execute(text("""INSERT INTO audit.audit_log(actor, action, entity, details)
                           VALUES ('setup', 'LEGACY_REFERENCE_MIGRATED', 'master_data', CAST(:d AS jsonb))"""),
                   {"d": json.dumps(stats)})
    for k, v in stats.items():
        print(f"  ✓ {k}: {v}")
    return stats


if __name__ == "__main__":
    run()
