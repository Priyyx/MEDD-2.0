"""Run the incoming-folder watcher as a standalone worker process (alternative to WATCHER_ENABLED in the API).

    python scripts/run_watcher.py
"""
import logging
import signal
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.ingestion.watcher import watcher  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
watcher.start()
stop = False


def _sig(*_):
    global stop
    stop = True


signal.signal(signal.SIGINT, _sig)
signal.signal(signal.SIGTERM, _sig)
while not stop:
    time.sleep(1)
watcher.stop()
