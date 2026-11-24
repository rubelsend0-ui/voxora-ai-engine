"""Engine / session management. SQLite for development, PostgreSQL for production."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings


@lru_cache
def get_engine() -> Engine:
    s = get_settings()
    kwargs: dict = {"pool_pre_ping": True}
    if s.is_sqlite:
        url = make_url(s.database_url)
        db = url.database
        kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
        if not db or db == ":memory:":
            kwargs["poolclass"] = StaticPool
        else:
            Path(db).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(s.database_url, **kwargs)

    if s.is_sqlite:

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _record):  # pragma: no cover - trivial
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA busy_timeout=30000")
            cur.close()

    return engine


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)


@contextmanager
def session_scope() -> Iterator[Session]:
    """Short-lived transactional session (used by workers and scripts)."""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()


def create_all_tables() -> None:
    import app.models  # noqa: F401  (registers all tables on Base.metadata)
    from app.database.base import Base

    Base.metadata.create_all(get_engine())


def reset_database_state() -> None:
    """Drop cached engines/sessions (tests change VOXORA_DATABASE_URL between runs)."""
    try:
        get_engine().dispose()
    except Exception:  # pragma: no cover
        pass
    get_engine.cache_clear()
    get_session_factory.cache_clear()
