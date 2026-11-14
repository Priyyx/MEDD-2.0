"""Concurrent-access / performance check against a running server.

    python tests/perf_check.py http://localhost:8000 admin '<password>' [concurrency] [requests]
"""
import json
import statistics
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

BASE, USER, PW = sys.argv[1], sys.argv[2], sys.argv[3]
CONC = int(sys.argv[4]) if len(sys.argv) > 4 else 20
N = int(sys.argv[5]) if len(sys.argv) > 5 else 400


def call(path, data=None, tok=None):
    req = urllib.request.Request(BASE + path, data=json.dumps(data).encode() if data else None,
                                 headers={"Content-Type": "application/json", **({"Authorization": "Bearer " + tok} if tok else {})})
    t = time.perf_counter()
    with urllib.request.urlopen(req, timeout=60) as r:
        body = r.read()
        return r.status, time.perf_counter() - t, len(body)


tok = json.loads(urllib.request.urlopen(urllib.request.Request(BASE + "/api/v1/auth/login",
      data=json.dumps({"username": USER, "password": PW}).encode(), headers={"Content-Type": "application/json"})).read())["access_token"]
divs = ["Pune", "Nagpur", "Konkan", "Amravati", "Nashik", "Chh. Sambhaji Nagar"]
paths = []
for i in range(N):
    d = urllib.parse.quote(divs[i % 6])
    paths.append([f"/api/v1/dashboard/scope?division={d}", f"/api/v1/modules/gap?division={d}",
                  f"/api/v1/equipment?division={d}&page={i % 5}", f"/api/v1/net-requirement/cost-mapping?division={d}&page={i % 7}",
                  f"/api/v1/drill?level=institute&path={d}", "/api/v1/dashboard/bootstrap",
                  f"/api/v1/kpis/summary?division={d}&department=Medicine&bedded={50 * (1 + i % 5)}"][i % 7])
t0 = time.perf_counter()
with ThreadPoolExecutor(CONC) as ex:
    res = list(ex.map(lambda p: call(p, tok=tok), paths))
wall = time.perf_counter() - t0
lat = sorted(r[1] for r in res)
out = {"requests": len(res), "concurrency": CONC, "errors": sum(1 for r in res if r[0] != 200),
       "throughput_rps": round(len(res) / wall, 1), "p50_ms": round(statistics.median(lat) * 1000),
       "p95_ms": round(lat[int(len(lat) * .95) - 1] * 1000), "max_ms": round(lat[-1] * 1000)}
chat = [call("/api/v1/chat", {"question": q}, tok)[1] for q in
        ["summary", "Which divisions have the highest equipment shortages?", "Ventilator in Pune", "Compare Pune and Nagpur"]]
out["chat_avg_ms"] = round(sum(chat) / len(chat) * 1000)
print(json.dumps(out, indent=2))
