"""Test fixtures.

Each test module gets its own SQLite file so the suite can run in any order and a
metrics assertion in one file is not perturbed by a walk recorded in another. The
canonical network is loaded once per session — it takes a couple of seconds and is
immutable.
"""
from __future__ import annotations

import os
import tempfile

import pytest

os.environ.setdefault("BPW_TIER", "development")
os.environ.setdefault("BPW_TOKEN_PEPPER", "test-pepper")

# Downtown Blacksburg. Every routing test starts here unless it says otherwise.
DOWNTOWN = dict(lat=37.2296, lon=-80.4139)
# Corporate Research Center — its own valid routing component (network v1.2).
CRC = dict(lat=37.2010, lon=-80.4069)


@pytest.fixture(scope="module")
def client(request):
    """A TestClient bound to a fresh database."""
    fd, path = tempfile.mkstemp(suffix=".db", prefix="bpw-test-")
    os.close(fd)
    os.environ["BPW_DATABASE_URL"] = f"sqlite:///{path}"

    # Settings and the SQLAlchemy engine are module-level and cached, so they have to
    # be imported *after* the environment is set and reloaded per module.
    import importlib

    from api.app import config
    config.settings.cache_clear()
    from api.app import db as db_mod
    importlib.reload(db_mod)
    from api.app import deps, models
    importlib.reload(deps)
    from api.app.routers import admin, identity, missions, progress
    from api.app.routers import routes as routes_router
    for m in (identity, routes_router, missions, progress, admin):
        importlib.reload(m)
    # Slates are cached across requests; a fresh database must start from a fresh
    # cache or one module's completions leak into another's recommendation.
    from api.app.services import mission_service
    mission_service.invalidate()
    from api.app import main as main_mod
    importlib.reload(main_mod)

    from fastapi.testclient import TestClient
    with TestClient(main_mod.app) as c:
        c._db_path = path
        yield c

    # And again on the way out. `network_service()` is lru_cached and shared across
    # modules, so a slate cached under one module's database can key identically under
    # the next one's — same network id, same empty-state fingerprint — and be served
    # against a database that knows nothing about it.
    mission_service.invalidate()
    os.unlink(path)


@pytest.fixture(scope="module")
def ns():
    from api.app.services.network_state import network_service
    return network_service()


def network_version() -> str:
    """The canonical network version, from the manifest rather than a literal.

    Pinning "v1.2" into a dozen assertions made publishing v1.3 look like a dozen
    regressions. What these tests are actually for is that a response names the
    network that produced it, so a stored route stays traceable — not that the
    number never moves.
    """
    from api.app.services.network_state import network_service
    return f"v{network_service().net.version}"


def register(client, email="walker@example.com", first="Test", last="Walker"):
    r = client.post("/api/identity/register",
                    json=dict(first_name=first, last_name=last, email=email))
    assert r.status_code == 200, r.text
    return r.json()


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def make_admin(client, participant_id: str):
    """Promote a participant directly in the database.

    There is deliberately no API for this: an application that can grant itself
    administrator rights over HTTP is one request away from anyone else doing so.
    """
    from sqlalchemy import update

    from api.app.db import SessionLocal
    from api.app.models import Participant
    with SessionLocal() as db:
        db.execute(update(Participant).where(Participant.id == participant_id)
                   .values(is_admin=True))
        db.commit()
