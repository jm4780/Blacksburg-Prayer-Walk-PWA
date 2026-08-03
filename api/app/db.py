"""Database engine and session.

SQLite by default so the vertical slice runs with no infrastructure. The technical
plan specifies PostgreSQL 16 + PostGIS for the real deployment; nothing here depends
on SQLite, and switching is setting BPW_DATABASE_URL. PostGIS is not needed by the
application at all — all geometry lives in the frozen canonical network, which the API
reads from disk, and the database stores only ids, counts and timestamps.
"""
from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from .config import settings
from .models import Base

_url = settings().database_url
_kwargs = {"future": True}
if _url.startswith("sqlite"):
    # check_same_thread=False so TestClient and uvicorn's threadpool can share it.
    _kwargs["connect_args"] = {"check_same_thread": False}

engine = create_engine(_url, **_kwargs)

if _url.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA journal_mode=WAL")
        cur.close()

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False,
                            class_=Session)


def init_db() -> None:
    """Create any missing tables.

    Convenience for local work and tests. A real deployment runs

        alembic upgrade head

    which is the only path that can migrate an *existing* database forward.
    `alembic check` is kept green, so the two agree on the schema.
    """
    Base.metadata.create_all(engine)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
