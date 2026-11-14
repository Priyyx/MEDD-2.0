"""MANDATORY ACCEPTANCE TEST
Upload a new Excel file -> detected automatically by the folder watcher -> validated -> processed -> PostgreSQL
updated -> analytical views refreshed -> dashboard APIs return the new KPIs -> refresh timestamp updated,
with a live notification delivered — and no code edited anywhere."""
import shutil
import time

import pytest
from sqlalchemy import text

from app.db.session import read_engine
from app.ingestion.watcher import IncomingWatcher
from app.services.events import hub
from tests.conftest import reset_production
from tests.fixtures import make_fixtures as mk

API = "/api/v1"


def test_end_to_end_upload_to_dashboard(client, admin_h, fixtures_dir, settings):
    reset_production()
    events = []
    hub.on_event(lambda p: events.append(p))
    hub.start_listener()
    time.sleep(1.5)
    before = client.get(f"{API}/dashboard/status", headers=admin_h).json()
    assert client.get(f"{API}/kpis/summary", headers=admin_h).json()["required"] == 0

    w = IncomingWatcher()
    w.start()
    try:
        src = mk.synthetic(fixtures_dir, name="ACCEPTANCE_master.xlsx", institutes=8, seed=21)
        tmp = settings.incoming_dir / ".ACCEPTANCE_master.xlsx.part"
        shutil.copy2(src, tmp)
        tmp.rename(settings.incoming_dir / "ACCEPTANCE_master.xlsx")       # 1. upload (atomic, like the API does)
        deadline = time.time() + 120
        while time.time() < deadline:                                       # 2. detected + processed automatically
            st = client.get(f"{API}/dashboard/status", headers=admin_h).json()
            if st["data_version"] > before["data_version"]:
                break
            time.sleep(1)
        else:
            pytest.fail("watcher did not process the file in time")
    finally:
        w.stop()

    li = st["last_ingestion"]
    assert li["status"].startswith("SUCCESS") and li["original_name"] == "ACCEPTANCE_master.xlsx"   # 3. validated
    with read_engine.connect() as c:                                                              # 4. PostgreSQL updated
        n = c.execute(text("SELECT count(*) FROM equipment_inventory.line_item WHERE is_active")).scalar()
        mv = c.execute(text("SELECT count(*) FROM analytics.mv_line_fact")).scalar()                # 5. views refreshed
    assert n > 0 and mv == n
    k = client.get(f"{API}/kpis/summary", headers=admin_h).json()                                  # 6. dashboard KPIs
    boot = client.get(f"{API}/dashboard/bootstrap", headers=admin_h).json()
    assert k["required"] > 0 and boot["overview"]["required"] == k["required"] and boot["overview"]["line_items"] == n
    assert st["last_refresh"] and st["last_refresh"] != before["last_refresh"]                     # 7. timestamp
    assert (settings.processed_dir / f"{li['id']:05d}_ACCEPTANCE_master.xlsx").exists()
    time.sleep(2)
    assert any(e.get("type") == "data_refreshed" and e.get("file") == "ACCEPTANCE_master.xlsx" for e in events)  # live push
