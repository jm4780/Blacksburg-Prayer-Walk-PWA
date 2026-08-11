"""Database engine and session.

SQLite by default so the vertical slice runs with no infrastructure. The technical
plan specifies PostgreSQL 16 + PostGIS for the real deployment; nothing here depends
on SQLite, and switching is setting BPW_DATABASE_URL. PostGIS is not needed by the
application at all — all geometry lives in the frozen canonical network, which the API
reads from disk, and the database stores only ids, counts and timestamps.
"""
from __future__ import annotations

import logging
from collections.abc import Iterator

from sqlalchemy import create_engine, event, inspect
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session, sessionmaker

from .config import settings
from .models import Base

log = logging.getLogger("bpw")

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
    """Create any missing tables, and any index missing from a table that already exists.

    Convenience for local work and tests. A real deployment runs

        alembic upgrade head

    which is the only path that can migrate an *existing* database forward.
    `alembic check` is kept green, so the two agree on the schema.

    The second half matters because `create_all` adds indexes only along with the table
    they belong to. The one-open-walk rule is a partial unique index on an existing
    table (see models.Walk), so a database created before it would keep running without
    it — the application guard would hold, and the guarantee underneath it would be
    quietly missing. Rather than leave that difference invisible, add what is missing,
    and say plainly when the data will not allow it.
    """
    Base.metadata.create_all(engine)
    create_missing_indexes(engine)


def create_missing_indexes(bind) -> list[str]:
    """Add indexes the models declare and an existing database does not have.

    Returns the names created. Anything the data itself refuses is logged and skipped,
    never raised: a database that already breaks a rule must still start, so somebody
    can read the warning and run the migration that repairs it.
    """
    inspector = inspect(bind)
    created: list[str] = []
    for table in Base.metadata.sorted_tables:
        if not inspector.has_table(table.name):
            continue
        have = {ix["name"] for ix in inspector.get_indexes(table.name)}
        for index in table.indexes:
            if index.name in have:
                continue
            try:
                index.create(bind)
                created.append(index.name)
            except (IntegrityError, OperationalError) as exc:
                log.warning(
                    "DEPLOYMENT: could not create index %s on %s — the data already "
                    "breaks the rule it enforces (%s). Run `alembic upgrade head`, "
                    "which repairs the rows first.",
                    index.name, table.name, exc.orig)
    return created


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
