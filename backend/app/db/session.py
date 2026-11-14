"""Database engines.

Two pooled engines are used deliberately:
  * ``write_engine``  – ingestion, authentication, audit logging (role ``medd_app``)
  * ``read_engine``   – dashboards, analytics, chatbot (role ``medd_readonly``: SELECT only)
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings

_settings = get_settings()


def _make_engine(url: str, *, readonly: bool) -> Engine:
    eng = create_engine(
        url,
        pool_size=_settings.db_pool_size,
        max_overflow=_settings.db_max_overflow,
        pool_pre_ping=True,
        pool_recycle=1800,
        future=True,
    )

    @event.listens_for(eng, "connect")
    def _on_connect(dbapi_conn, _rec):  # pragma: no cover - driver hook
        with dbapi_conn.cursor() as cur:
            cur.execute(f"SET statement_timeout = {int(_settings.statement_timeout_ms)}")
            cur.execute("SET application_name = 'medd2-readonly'" if readonly else "SET application_name = 'medd2-app'")
            if readonly:
                cur.execute("SET default_transaction_read_only = on")
        dbapi_conn.commit()

    return eng


write_engine: Engine = _make_engine(_settings.database_url, readonly=False)
read_engine: Engine = _make_engine(_settings.database_url_readonly, readonly=True)

WriteSession = sessionmaker(bind=write_engine, expire_on_commit=False, future=True)
ReadSession = sessionmaker(bind=read_engine, expire_on_commit=False, future=True)


def get_write_db() -> Iterator[Session]:
    db = WriteSession()
    try:
        yield db
    finally:
        db.close()


def get_read_db() -> Iterator[Session]:
    db = ReadSession()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def write_tx() -> Iterator[Session]:
    """Transactional scope: commit on success, rollback on any exception."""
    db = WriteSession()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def db_ping() -> dict:
    out = {}
    for name, eng in (("write", write_engine), ("read", read_engine)):
        try:
            with eng.connect() as c:
                c.execute(text("select 1"))
            out[name] = "ok"
        except Exception as exc:  # pragma: no cover
            out[name] = f"error: {exc.__class__.__name__}"
    return out
