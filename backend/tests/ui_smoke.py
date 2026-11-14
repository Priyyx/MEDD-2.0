"""Browser smoke test of all 13 MEDD modules + Data Management (Playwright, headless Chrome).

    python tests/ui_smoke.py http://localhost:8000 admin '<password>' [screenshot_dir]

Signs in, opens every module, applies filters, drills down, asks the chatbot and records any JavaScript error.
Exit code 1 if any page raised a JS error or rendered no content.
"""
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE, USER, PW = sys.argv[1], sys.argv[2], sys.argv[3]
SHOTS = Path(sys.argv[4]) if len(sys.argv) > 4 else None
PAGES = ["executive", "chatbot", "gap", "procurement", "netreq", "financial", "condemnation", "eol", "amc",
         "facility", "district", "department", "equipment", "admin"]
CHROME = "/usr/bin/google-chrome"


def main() -> int:
    errors, results = [], []
    with sync_playwright() as p:
        kw = {"headless": True}
        if Path(CHROME).exists():
            kw["executable_path"] = CHROME
        b = p.chromium.launch(**kw)
        pg = b.new_page(viewport={"width": 1440, "height": 1000})
        pg.on("pageerror", lambda e: errors.append(f"[{pg.url}] {e}"))
        pg.on("console", lambda m: m.type == "error" and errors.append(f"[console {pg.url}] {m.text}"))
        pg.goto(BASE + "/")
        pg.fill("#loginUser", USER)
        pg.fill("#loginPass", PW)
        pg.click("#loginBtn")
        pg.wait_for_selector("#kpis .kpi", timeout=60000)

        def snap(name):
            if SHOTS:
                SHOTS.mkdir(parents=True, exist_ok=True)
                pg.screenshot(path=str(SHOTS / f"{name}.png"), full_page=False)

        for page in PAGES:
            pg.evaluate(f"go('#{page}')")
            pg.wait_for_timeout(1800)
            html_len = pg.evaluate(f"document.getElementById('page-{page}').innerText.length")
            results.append({"page": page, "chars": html_len})
            snap(page)

        # filters: division + department, then executive KPIs must change
        pg.evaluate("go('#executive')"); pg.wait_for_timeout(800)
        before = pg.inner_text("#kpis")
        pg.evaluate("state.division=['Pune'];state.department=['Medicine'];onFilterChange()")
        pg.wait_for_timeout(2500)
        after = pg.inner_text("#kpis")
        results.append({"check": "filters change KPIs", "ok": before != after})
        snap("executive_filtered")
        # drill-through down to equipment level
        pg.evaluate("drillTo('procurement','division',[])"); pg.wait_for_timeout(1500)
        snap("drill_division")
        pg.evaluate("drillTo('procurement','equipment',['Pune','BJ Medical & Sassoon Hospital, Pune','Medicine'])")
        pg.wait_for_timeout(1500)
        rows = pg.evaluate("document.querySelectorAll('#detailTable tbody tr').length")
        results.append({"check": "drill to equipment level rows", "rows": rows, "ok": rows > 0})
        snap("drill_equipment")
        # KPI detail + institute detail
        pg.evaluate("go('#institute/'+encodeURIComponent('BJ Medical & Sassoon Hospital, Pune'))"); pg.wait_for_timeout(1500)
        snap("institute_detail")
        pg.evaluate("resetFilters()"); pg.wait_for_timeout(2000)
        # chatbot
        pg.evaluate("go('#chatbot')"); pg.wait_for_timeout(800)
        pg.fill("#cbin", "Which divisions have the highest equipment shortages?")
        pg.click("#cbsend")
        pg.wait_for_timeout(3000)
        txt = pg.inner_text("#cbmsgs")
        results.append({"check": "chatbot answered from DB", "ok": "functional shortfall" in txt.lower()})
        snap("chatbot_answer")
        # cost mapping table on net requirement
        pg.evaluate("go('#netreq')"); pg.wait_for_timeout(2500)
        cm = pg.evaluate("document.querySelectorAll('#cmTable tbody tr').length")
        results.append({"check": "cost mapping rows", "rows": cm, "ok": cm > 0})
        snap("netreq_costmap")
        b.close()
    empty = [r for r in results if "chars" in r and r["chars"] < 40]
    failed = [r for r in results if r.get("ok") is False]
    print(json.dumps({"results": results, "js_errors": errors}, indent=2))
    return 1 if errors or empty or failed else 0


if __name__ == "__main__":
    sys.exit(main())
