"""Ingest a file synchronously from the command line (same pipeline the folder watcher uses).

    python scripts/ingest_file.py path/to/master.xlsx [--copy]
--copy  leave the original where it is (a copy is processed); default moves the file like the watcher does.
"""
import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.ingestion.pipeline import process_file  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("path")
ap.add_argument("--copy", action="store_true")
a = ap.parse_args()
p = Path(a.path)
if a.copy:
    tmpdir = Path(tempfile.mkdtemp())
    shutil.copy2(p, tmpdir / p.name)
    p = tmpdir / p.name
res = process_file(p, triggered_by="cli")
print(json.dumps({k: res.get(k) for k in ("file_id", "status", "counts", "issues", "error_message", "message",
                                           "data_version", "duration_ms", "report")}, indent=2, default=str))
sys.exit(0 if str(res.get("status", "")).startswith("SUCCESS") or res.get("status") == "DUPLICATE" else 1)
