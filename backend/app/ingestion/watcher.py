"""Folder watcher: detects new or replaced files in data/incoming and feeds the ingestion pipeline.

Uses watchdog (inotify / FSEvents / ReadDirectoryChangesW). A periodic poll is kept as a safety net for network
drives or editors that save in ways watchdog misses. Files are only processed once their size has been stable
for WATCHER_SETTLE_SECONDS (so half-copied Excel files are never read), and Office lock files (~$x.xlsx) are ignored.
"""
from __future__ import annotations

import logging
import queue
import threading
import time
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from app.config import get_settings
from app.ingestion.pipeline import process_file
from app.ingestion.standardise import load_rules

log = logging.getLogger("medd.watcher")


def _eligible(p: Path) -> bool:
    name = p.name
    if name.startswith(("~$", ".", "~")) or name.endswith((".tmp", ".part", ".crdownload")):
        return False
    return p.suffix.lower() in load_rules()["supported_extensions"] or p.suffix  # unsupported -> failed/ with reason


class _Handler(FileSystemEventHandler):
    def __init__(self, q: "queue.Queue[Path]") -> None:
        self.q = q

    def _push(self, path: str) -> None:
        p = Path(path)
        if p.is_file() and _eligible(p):
            self.q.put(p)

    def on_created(self, event):
        if not event.is_directory:
            self._push(event.src_path)

    def on_modified(self, event):
        if not event.is_directory:
            self._push(event.src_path)

    def on_moved(self, event):
        if not event.is_directory:
            self._push(event.dest_path)


class IncomingWatcher:
    def __init__(self) -> None:
        self.s = get_settings()
        self.q: "queue.Queue[Path]" = queue.Queue()
        self.observer: Observer | None = None
        self._stop = threading.Event()
        self._worker: threading.Thread | None = None
        self.last_result: dict | None = None
        self.busy = False

    def _wait_stable(self, p: Path) -> bool:
        settle = self.s.watcher_settle_seconds
        last, stable_since = -1, None
        deadline = time.monotonic() + max(settle * 20, 60)
        while time.monotonic() < deadline and not self._stop.is_set():
            if not p.exists():
                return False
            size = p.stat().st_size
            if size == last and size > 0:
                if stable_since and time.monotonic() - stable_since >= settle:
                    try:  # make sure the writer released the file (Windows)
                        with open(p, "rb"):
                            return True
                    except OSError:
                        pass
                stable_since = stable_since or time.monotonic()
            else:
                last, stable_since = size, None
            time.sleep(0.5)
        return p.exists()

    def _work(self) -> None:
        seen_recent: dict[str, float] = {}
        last_poll = 0.0
        while not self._stop.is_set():
            try:
                p = self.q.get(timeout=1.0)
            except queue.Empty:
                if time.monotonic() - last_poll > self.s.watcher_poll_fallback_seconds:
                    last_poll = time.monotonic()
                    self.scan_existing()
                continue
            key = str(p)
            if time.monotonic() - seen_recent.get(key, 0) < 1.0:
                continue
            seen_recent[key] = time.monotonic()
            if not p.exists() or not self._wait_stable(p):
                continue
            try:
                self.busy = True
                log.info("detected %s", p.name)
                self.last_result = process_file(p, triggered_by="watcher")
            except Exception:  # pragma: no cover - pipeline already records failures
                log.exception("watcher failed on %s", p)
            finally:
                self.busy = False

    def scan_existing(self) -> int:
        n = 0
        for p in sorted(self.s.incoming_dir.iterdir(), key=lambda x: x.stat().st_mtime):
            if p.is_file() and _eligible(p):
                self.q.put(p)
                n += 1
        return n

    def start(self) -> None:
        self.s.ensure_dirs()
        self.observer = Observer()
        self.observer.schedule(_Handler(self.q), str(self.s.incoming_dir), recursive=False)
        self.observer.daemon = True
        self.observer.start()
        self._worker = threading.Thread(target=self._work, name="medd-ingest-worker", daemon=True)
        self._worker.start()
        queued = self.scan_existing()  # files dropped while the service was down
        log.info("watching %s (%d file(s) queued at start-up)", self.s.incoming_dir, queued)

    def stop(self) -> None:
        self._stop.set()
        if self.observer:
            self.observer.stop()
            self.observer.join(timeout=5)

    def status(self) -> dict:
        return {"running": bool(self.observer and self.observer.is_alive()), "busy": self.busy,
                "queue": self.q.qsize(), "folder": str(self.s.incoming_dir), "last_result": self.last_result}


watcher = IncomingWatcher()
