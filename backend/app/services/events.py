"""Cross-process change notification + in-process fan-out to Server-Sent-Event subscribers.

The ingestion pipeline issues ``pg_notify('medd_events', …)`` *inside* its transaction, so a notification is
delivered only if the data actually committed. The API process LISTENs on that channel (works whether the
watcher runs inside the API process or as a separate worker), invalidates caches and pushes to browsers.
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from typing import Any, Callable

import psycopg

from app.config import get_settings

log = logging.getLogger("medd.events")
CHANNEL = "medd_events"


class EventHub:
    def __init__(self) -> None:
        self._subs: set[asyncio.Queue] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._lock = threading.Lock()
        self._callbacks: list[Callable[[dict], None]] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ---- subscription (SSE)
    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        with self._lock:
            self._subs.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        with self._lock:
            self._subs.discard(q)

    def on_event(self, cb: Callable[[dict], None]) -> None:
        self._callbacks.append(cb)

    def _dispatch(self, payload: dict) -> None:
        for cb in self._callbacks:
            try:
                cb(payload)
            except Exception:  # pragma: no cover
                log.exception("event callback failed")
        if self._loop is None:
            return
        with self._lock:
            subs = list(self._subs)
        for q in subs:
            def _put(q=q):
                try:
                    q.put_nowait(payload)
                except asyncio.QueueFull:
                    pass
            self._loop.call_soon_threadsafe(_put)

    def publish_local(self, payload: dict) -> None:
        self._dispatch(payload)

    # ---- LISTEN thread
    def start_listener(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._listen_forever, name="medd-pg-listen", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _listen_forever(self) -> None:
        url = get_settings().database_url.replace("postgresql+psycopg://", "postgresql://")
        while not self._stop.is_set():
            try:
                with psycopg.connect(url, autocommit=True) as conn:
                    conn.execute(f"LISTEN {CHANNEL}")
                    log.info("listening on %s", CHANNEL)
                    while not self._stop.is_set():
                        for n in conn.notifies(timeout=2.0):
                            try:
                                payload = json.loads(n.payload)
                            except Exception:
                                payload = {"type": "unknown", "raw": n.payload}
                            self._dispatch(payload)
            except Exception as exc:  # reconnect with backoff
                log.warning("LISTEN connection lost (%s); retrying in 5s", exc)
                time.sleep(5)


hub = EventHub()


def notify_sql(payload: dict[str, Any]) -> tuple[str, dict]:
    """SQL + params to emit a notification inside the current transaction."""
    return "SELECT pg_notify(:ch, :p)", {"ch": CHANNEL, "p": json.dumps(payload, default=str)[:7900]}
