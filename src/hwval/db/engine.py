"""Engine/session factory + schema bootstrap."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

import pandas as pd
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from hwval.config import get_settings
from hwval.db.models import Base

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def get_engine(echo: bool | None = None) -> Engine:
    global _engine, _SessionLocal
    if _engine is None:
        s = get_settings()
        kwargs: dict = {"echo": s.sql_echo if echo is None else echo, "future": True}
        if not s.database_url.startswith("sqlite"):
            kwargs.update(pool_pre_ping=True, pool_size=5, max_overflow=5)
        _engine = create_engine(s.database_url, **kwargs)
        _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False, future=True)
    return _engine


def dispose_engine() -> None:
    """Drop the cached engine (tests switch DATABASE_URL between cases)."""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine, _SessionLocal = None, None


@contextmanager
def session_scope() -> Iterator[Session]:
    get_engine()
    assert _SessionLocal is not None
    sess = _SessionLocal()
    try:
        yield sess
        sess.commit()
    except Exception:
        sess.rollback()
        raise
    finally:
        sess.close()


def init_db(drop: bool = False) -> None:
    eng = get_engine()
    if drop:
        Base.metadata.drop_all(eng)
    Base.metadata.create_all(eng)


def read_sql(sql: str, params: dict | None = None) -> pd.DataFrame:
    """Run a query and return a DataFrame. Used by the ML and report layers."""
    with get_engine().connect() as conn:
        return pd.read_sql(text(sql), conn, params=params or {})


def dialect_name() -> str:
    return get_engine().dialect.name


def healthcheck() -> dict:
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"ok": True, "dialect": dialect_name(), "url": _masked_url()}
    except Exception as exc:  # pragma: no cover - environment dependent
        return {"ok": False, "error": str(exc), "url": _masked_url()}


def _masked_url() -> str:
    url = get_settings().database_url
    if "@" in url and "//" in url:
        head, tail = url.split("//", 1)
        creds, host = tail.split("@", 1)
        user = creds.split(":", 1)[0]
        return f"{head}//{user}:***@{host}"
    return url
