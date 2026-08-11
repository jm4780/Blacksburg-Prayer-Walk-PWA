"""The one-open-walk rule under simultaneous requests, and the schema that enforces it.

A walker may hold exactly one open walk — PREVIEW or ACTIVE — because an open walk
holds streets against everybody else in town. That rule used to be enforced by a read
followed by a write inside one transaction, with `SELECT … FOR UPDATE` meant to make the
pair atomic. PostgreSQL honours that clause; SQLite's dialect drops it, and the note in
the code claiming SQLite's single writer serialised the same work was wrong — SQLite
serialises writes, and this is a read *then* a write.

A reviewer measured the consequence against the running dev database: three simultaneous
accepts left two open walks, eight left three, and one participant ended up holding
three walks and seventy-one live street reservations at once. Those reservations are the
real harm — streets held against every other walker by walks nobody could see or finish.

These tests fire the accepts genuinely simultaneously, from a thread each, released
together by a barrier so they collide inside the endpoint rather than queueing politely.
They assert the two things that matter afterwards: exactly one open walk, and not one
live reservation belonging to anything else.
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from .conftest import DOWNTOWN, auth, register

REPO = Path(__file__).resolve().parents[1]
OPEN = ("PREVIEW", "ACTIVE")


def _fire_together(calls):
    """Run every call on its own thread, all released at the same instant."""
    barrier = threading.Barrier(len(calls))

    def run(fn):
        barrier.wait(timeout=30)
        return fn()

    with ThreadPoolExecutor(max_workers=len(calls)) as pool:
        return [f.result(timeout=60) for f in [pool.submit(run, c) for c in calls]]


def _open_walks(participant_id):
    from sqlalchemy import select

    from api.app.db import SessionLocal
    from api.app.models import Walk
    with SessionLocal() as db:
        return db.execute(
            select(Walk.id).where(Walk.participant_id == participant_id,
                                  Walk.status.in_(OPEN))).scalars().all()


def _live_reservations(participant_id):
    """walk_id -> how many streets that walk is holding right now."""
    from datetime import datetime, timezone

    from sqlalchemy import func, select

    from api.app.db import SessionLocal
    from api.app.models import Reservation
    with SessionLocal() as db:
        rows = db.execute(
            select(Reservation.walk_id, func.count(Reservation.id))
            .where(Reservation.participant_id == participant_id,
                   Reservation.released_at.is_(None),
                   Reservation.expires_at > datetime.now(timezone.utc))
            .group_by(Reservation.walk_id)).all()
    return {w: n for w, n in rows}


def _assert_one_slot(client, participant_id, responses):
    assert all(r.status_code in (200, 409) for r in responses), \
        [(r.status_code, r.text[:120]) for r in responses]
    assert any(r.status_code == 200 for r in responses), "every request was refused"

    walks = _open_walks(participant_id)
    assert len(walks) == 1, f"{len(walks)} open walks at once: {walks}"

    held = _live_reservations(participant_id)
    orphaned = {w: n for w, n in held.items() if w not in set(walks)}
    assert not orphaned, f"streets held by walks that are not open: {orphaned}"


@pytest.fixture(scope="module")
def racer(client):
    p = register(client, "racer@example.com", "Race", "Walker")
    return p["id"], auth(p["token"])


def test_several_simultaneous_accepts_leave_exactly_one_open_walk(client, racer):
    """Eight accepts at once — one phone on a flaky link, or two devices."""
    pid, h = racer
    slate = client.get("/api/missions/recommend?minutes=45").json()
    if not slate.get("available"):
        pytest.skip("nothing left to assign")
    ids = [slate["mission"]["id"]] + [a["id"] for a in slate["alternatives"]]

    picks = [ids[i % len(ids)] for i in range(8)]
    responses = _fire_together([
        (lambda m=m: client.post(f"/api/missions/{m}/accept?minutes=45", headers=h))
        for m in picks])

    _assert_one_slot(client, pid, responses)


def test_simultaneous_previews_of_different_sizes_leave_exactly_one_open_walk(
        client, racer):
    """The other door into a walk: /api/walks/select, three sizes at once."""
    pid, h = racer
    cur = client.get("/api/walks/current", headers=h).json()
    if cur:
        client.post(f"/api/walks/{cur['id']}/discard", headers=h)

    g = client.post("/api/routes/generate", json=DOWNTOWN, headers=h).json()
    bands = (g["available_bands"] * 3)[:3]
    responses = _fire_together([
        (lambda b=b: client.post("/api/walks/select",
                                 json=dict(request_id=g["request_id"], band=b),
                                 headers=h))
        for b in bands])

    _assert_one_slot(client, pid, responses)


def test_a_walk_in_progress_still_survives_a_burst_of_accepts(client, racer):
    """An ACTIVE walk is a commitment: a race must not replace it, or duplicate it."""
    pid, h = racer
    cur = client.get("/api/walks/current", headers=h).json()
    assert cur, "the previous test should have left one open walk"
    client.post(f"/api/walks/{cur['id']}/start", headers=h)

    slate = client.get("/api/missions/recommend?minutes=45").json()
    if not slate.get("available"):
        pytest.skip("nothing left to assign")
    mid = slate["mission"]["id"]
    responses = _fire_together([
        (lambda: client.post(f"/api/missions/{mid}/accept?minutes=45", headers=h))
        for _ in range(5)])

    assert all(r.status_code == 409 for r in responses), \
        [r.status_code for r in responses]
    assert _open_walks(pid) == [cur["id"]]
    client.post(f"/api/walks/{cur['id']}/discard", headers=h)


# ------------------------------------------------------- the schema behind the rule
#
# docs/15-pilot-deployment.md makes `alembic upgrade head` the only supported way to
# build the pilot's schema, so an index declared on the model alone would be absent in
# the one place the rule has to hold. These tests run the migrations the way a
# deployment does — in a subprocess, against a database of their own, so nothing here
# touches the settings cache the rest of the suite shares.

def _alembic(db_path: Path, *args: str):
    env = {**os.environ, "BPW_DATABASE_URL": f"sqlite:///{db_path}",
           "BPW_TIER": "development", "BPW_TOKEN_PEPPER": "test-pepper"}
    r = subprocess.run([sys.executable, "-m", "alembic", *args],
                       cwd=REPO, env=env, capture_output=True, text=True, timeout=180)
    assert r.returncode == 0, r.stderr[-2000:]
    return r


def _seed_open_walks(db_path: Path, how_many: int = 2) -> tuple[str, list[str]]:
    """A participant holding open walks, each holding a street.

    Two of them is the state the reviewer found in the dev database, built here on
    purpose — which is only possible before the migration adds the index. Returns the
    walk ids oldest first.
    """
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from api.app.models import Participant, Reservation, RouteRequest, Walk

    eng = create_engine(f"sqlite:///{db_path}")
    later = datetime.now(timezone.utc) + timedelta(hours=1)
    with Session(eng) as db:
        p = Participant(first_name="Race", last_name="Walker", email="r@example.com",
                        email_normalized="r@example.com", token_hash="hash-r")
        db.add(p)
        db.flush()
        req = RouteRequest(participant_id=p.id, network_id="n", engine_version="e",
                           start_node=0, start_source="MAP", seed=1, variants=[])
        db.add(req)
        db.flush()
        walks = []
        for n in range(1, how_many + 1):
            when = datetime(2026, 1, n, tzinfo=timezone.utc)
            w = Walk(participant_id=p.id, request_id=req.id, network_id="n",
                     engine_version="e", status="PREVIEW", band="Short",
                     target_miles=1.0, distance_miles=1.0, estimated_minutes=20,
                     planned_segment_ids=[], planned_required_ids=[],
                     score_components={}, created_at=when)
            db.add(w)
            db.flush()
            db.add(Reservation(walk_id=w.id, participant_id=p.id,
                               segment_id=f"SEG-00000{n}", expires_at=later))
            walks.append(w.id)
        db.commit()
        return p.id, walks


def test_the_migration_leaves_one_open_walk_and_releases_the_others_holds(tmp_path):
    """Any database this ships to may already be broken — repair it on the way past."""
    from sqlalchemy import create_engine, text

    db_path = tmp_path / "repair.db"
    _alembic(db_path, "upgrade", "7ec2c3ef667b")
    pid, (older, newer) = _seed_open_walks(db_path, 2)

    _alembic(db_path, "upgrade", "head")

    eng = create_engine(f"sqlite:///{db_path}")
    with eng.connect() as c:
        open_walks = c.execute(text(
            "SELECT id FROM walks WHERE participant_id = :p "
            "  AND status IN ('PREVIEW','ACTIVE')"), dict(p=pid)).scalars().all()
        still_held = c.execute(text(
            "SELECT walk_id FROM reservations WHERE released_at IS NULL")).scalars().all()

    # The newer walk is the one the walker was last looking at, so it survives.
    assert open_walks == [newer]
    # And the walk that lost the slot is holding nothing against the rest of the town.
    assert still_held == [newer]
    assert older not in still_held


def test_a_database_built_before_the_index_gains_it_on_startup(tmp_path):
    """`create_all` adds an index only alongside the table it belongs to, so a local
    database made before this change would run without the rule underneath it."""
    from sqlalchemy import create_engine, inspect

    from api.app.db import create_missing_indexes
    from api.app.models import Base

    db_path = tmp_path / "legacy.db"
    eng = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(eng)
    with eng.connect() as c:
        c.exec_driver_sql("DROP INDEX uq_walk_one_open_per_participant")
        c.commit()

    assert create_missing_indexes(eng) == ["uq_walk_one_open_per_participant"]
    assert "uq_walk_one_open_per_participant" in {
        ix["name"] for ix in inspect(eng).get_indexes("walks")}
    # And again is a no-op rather than an error.
    assert create_missing_indexes(eng) == []


def test_a_database_that_already_breaks_the_rule_still_starts(tmp_path, caplog):
    """It starts, it says so, and it names the migration that repairs it — rather than
    refusing to boot, or silently carrying on as if the rule were in force."""
    from sqlalchemy import create_engine

    from api.app.db import create_missing_indexes
    from api.app.models import Base

    db_path = tmp_path / "legacy-broken.db"
    eng = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(eng)
    with eng.connect() as c:
        c.exec_driver_sql("DROP INDEX uq_walk_one_open_per_participant")
        c.commit()
    _seed_open_walks(db_path, 2)

    with caplog.at_level("WARNING"):
        assert create_missing_indexes(eng) == []
    assert "alembic upgrade head" in caplog.text


def test_the_migrated_schema_refuses_a_second_open_walk(tmp_path):
    """The rule has to be the database's, not just the application's."""
    from sqlalchemy import create_engine, text
    from sqlalchemy.exc import IntegrityError

    db_path = tmp_path / "constraint.db"
    _alembic(db_path, "upgrade", "head")
    _pid, (only,) = _seed_open_walks(db_path, 1)

    eng = create_engine(f"sqlite:///{db_path}")
    with eng.connect() as c:
        rows = c.execute(text(
            "SELECT sql FROM sqlite_master WHERE type='index' "
            "  AND name='uq_walk_one_open_per_participant'")).scalars().all()
    assert rows and "UNIQUE" in rows[0] and "PREVIEW" in rows[0]

    with eng.connect() as c:
        # A finished walk beside an open one is fine — the index is partial on purpose.
        c.execute(text(
            "INSERT INTO walks (id, participant_id, request_id, network_id, "
            "  engine_version, status, band, target_miles, distance_miles, "
            "  estimated_minutes, planned_segment_ids, planned_required_ids, "
            "  planned_connector_ids, score_components, seed, final_segment_ids, "
            "  manual_additions, manual_removals, created_at) "
            "SELECT 'a-finished-walk', participant_id, request_id, network_id, "
            "  engine_version, 'COMPLETED', band, target_miles, distance_miles, "
            "  estimated_minutes, planned_segment_ids, planned_required_ids, "
            "  planned_connector_ids, score_components, seed, final_segment_ids, "
            "  manual_additions, manual_removals, created_at "
            "  FROM walks WHERE id = :k"), dict(k=only))
        c.commit()

        # A second open one is not.
        with pytest.raises(IntegrityError):
            c.execute(text(
                "INSERT INTO walks (id, participant_id, request_id, network_id, "
                "  engine_version, status, band, target_miles, distance_miles, "
                "  estimated_minutes, planned_segment_ids, planned_required_ids, "
                "  planned_connector_ids, score_components, seed, final_segment_ids, "
                "  manual_additions, manual_removals, created_at) "
                "SELECT 'second-open-walk', participant_id, request_id, network_id, "
                "  engine_version, 'PREVIEW', band, target_miles, distance_miles, "
                "  estimated_minutes, planned_segment_ids, planned_required_ids, "
                "  planned_connector_ids, score_components, seed, final_segment_ids, "
                "  manual_additions, manual_removals, created_at "
                "  FROM walks WHERE id = :k"), dict(k=only))
            c.commit()
