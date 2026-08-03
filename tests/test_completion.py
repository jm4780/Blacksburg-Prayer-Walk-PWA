"""Completion, reservation and metrics matrix (§20).

Covers: the three confirmation paths, idempotency, the plan surviving a
different-route report, reservation lifecycle, two simultaneous nearby walkers, and
the three dashboard numbers moving correctly.
"""
from __future__ import annotations

import pytest

from .conftest import DOWNTOWN, auth, network_version, register


@pytest.fixture(scope="module")
def h(client):
    return auth(register(client, "finisher@example.com")["token"])


def plan(client, headers, band="Medium", **overrides):
    """Generate, pick a band, return the walk.

    Cancels any walk left ACTIVE first: /api/walks/select now refuses to start a
    second walk while one is in progress, which is the behaviour under test in
    test_cannot_start_a_second_walk_while_one_is_active.
    """
    cur = client.get("/api/walks/current", headers=headers).json()
    if cur and cur["status"] == "ACTIVE":
        client.post(f"/api/walks/{cur['id']}/discard", headers=headers)
    body = {**DOWNTOWN, **overrides}
    r = client.post("/api/routes/generate", json=body, headers=headers).json()
    if band not in r["available_bands"]:
        band = r["available_bands"][0]
    w = client.post("/api/walks/select",
                    json=dict(request_id=r["request_id"], band=band), headers=headers)
    assert w.status_code == 200, w.text
    return w.json()


# ------------------------------------------------------------------- lifecycle
def test_walk_lifecycle(client, h):
    w = plan(client, h)
    assert w["status"] == "PREVIEW"
    assert client.post(f"/api/walks/{w['id']}/start", headers=h).json()["status"] == "ACTIVE"
    r = client.post(f"/api/walks/{w['id']}/complete",
                    json=dict(outcome="AS_PLANNED"), headers=h)
    assert r.status_code == 200
    assert client.get(f"/api/walks/{w['id']}", headers=h).json()["status"] == "COMPLETED"


def test_completion_is_idempotent(client, h):
    w = plan(client, h)
    client.post(f"/api/walks/{w['id']}/start", headers=h)
    first = client.post(f"/api/walks/{w['id']}/complete",
                        json=dict(outcome="AS_PLANNED"), headers=h).json()
    second = client.post(f"/api/walks/{w['id']}/complete",
                         json=dict(outcome="AS_PLANNED"), headers=h).json()
    assert first["segments_newly_recorded"] > 0
    assert second["segments_newly_recorded"] == 0
    assert second["idempotent"] is True


def test_metrics_do_not_move_on_a_repeat_submission(client, h):
    w = plan(client, h)
    client.post(f"/api/walks/{w['id']}/start", headers=h)
    client.post(f"/api/walks/{w['id']}/complete", json=dict(outcome="AS_PLANNED"),
                headers=h)
    before = client.get("/api/progress/metrics").json()
    client.post(f"/api/walks/{w['id']}/complete", json=dict(outcome="AS_PLANNED"),
                headers=h)
    after = client.get("/api/progress/metrics").json()
    assert before["percent_prayed_for"] == after["percent_prayed_for"]
    assert before["estimated_households_prayed_for"]["value"] == \
        after["estimated_households_prayed_for"]["value"]


def test_removing_skipped_segments(client, h):
    """§14: drop planned obligations the walker did not reach."""
    w = plan(client, h)
    client.post(f"/api/walks/{w['id']}/start", headers=h)
    full = client.get(f"/api/walks/{w['id']}", headers=h).json()
    some = _planned_required(client, w["id"], h)[:3]
    r = client.post(f"/api/walks/{w['id']}/complete",
                    json=dict(outcome="EDITED", segment_ids=some), headers=h).json()
    assert r["segments_recorded"] == len(some)
    assert r["segments_recorded"] < full["required_segment_count"]
    assert r["manual_removals"] == full["required_segment_count"] - len(some)
    assert r["manual_additions"] == 0


def test_adding_nearby_segments(client, h, ns):
    """§14: add obligations the walker completed instead, in the same submission."""
    w = plan(client, h)
    client.post(f"/api/walks/{w['id']}/start", headers=h)
    planned = _planned_required(client, w["id"], h)
    extra = [s.id for s in ns.net.segments
             if s.required and s.id not in set(planned)][:2]
    r = client.post(f"/api/walks/{w['id']}/complete",
                    json=dict(outcome="EDITED", segment_ids=planned[:2] + extra),
                    headers=h).json()
    assert r["manual_additions"] == len(extra)
    assert r["manual_removals"] == len(planned) - 2
    assert r["segments_recorded"] == 2 + len(extra)


def test_edits_are_recorded_as_a_diff(client, h, ns):
    w = plan(client, h)
    client.post(f"/api/walks/{w['id']}/start", headers=h)
    planned = _planned_required(client, w["id"], h)
    extra = [s.id for s in ns.net.segments
             if s.required and s.id not in set(planned)][:1]
    client.post(f"/api/walks/{w['id']}/complete",
                json=dict(outcome="EDITED", segment_ids=planned[:1] + extra), headers=h)
    from sqlalchemy import select

    from api.app.db import SessionLocal
    from api.app.models import WalkEdit
    with SessionLocal() as db:
        rows = db.execute(select(WalkEdit)
                          .where(WalkEdit.walk_id == w["id"])).scalars().all()
    assert {r.segment_id for r in rows if r.kind == "ADDED"} == set(extra)
    assert {r.segment_id for r in rows if r.kind == "REMOVED"} == set(planned[1:])


def test_did_not_complete_records_nothing(client, h):
    """§14: no obligations, holds released, minimal audit data kept."""
    from api.app.db import SessionLocal
    from api.app.services import reservations as res

    before = client.get("/api/progress/metrics").json()
    w = plan(client, h)
    client.post(f"/api/walks/{w['id']}/start", headers=h)
    r = client.post(f"/api/walks/{w['id']}/complete",
                    json=dict(outcome="DID_NOT_COMPLETE"), headers=h).json()
    assert r["segments_recorded"] == 0
    assert r["final_distance_miles"] == 0.0

    after = client.get("/api/progress/metrics").json()
    assert after["percent_prayed_for"]["value"] == before["percent_prayed_for"]["value"]
    assert after["total_miles_walked"]["value"] == before["total_miles_walked"]["value"]
    with SessionLocal() as db:
        assert not (set(_planned_required(client, w["id"], h))
                    & res.held_segment_ids(db))
    # The walk itself survives, for debugging.
    assert client.get(f"/api/walks/{w['id']}", headers=h).json()["outcome"] \
        == "DID_NOT_COMPLETE"


def test_different_route_leaves_the_plan_intact(client, h, ns):
    """§14: the original planned route survives unchanged in the audit record."""
    w = plan(client, h)
    client.post(f"/api/walks/{w['id']}/start", headers=h)
    planned_before = _planned_all(client, w["id"])

    elsewhere = [s.id for s in ns.net.segments
                 if s.required and s.id not in planned_before][:4]
    client.post(f"/api/walks/{w['id']}/complete",
                json=dict(outcome="EDITED", segment_ids=elsewhere,
                          note="went up Draper instead"), headers=h)

    assert _planned_all(client, w["id"]) == planned_before
    from sqlalchemy import select

    from api.app.db import SessionLocal
    from api.app.models import Completion
    with SessionLocal() as db:
        got = set(db.execute(select(Completion.segment_id)
                             .where(Completion.walk_id == w["id"])).scalars())
    assert got == set(elsewhere)


def test_connectors_do_not_earn_coverage(client, h, ns):
    w = plan(client, h)
    client.post(f"/api/walks/{w['id']}/start", headers=h)
    connector = next(s.id for s in ns.net.segments if not s.required)
    r = client.post(f"/api/walks/{w['id']}/complete",
                    json=dict(outcome="EDITED", segment_ids=[connector]),
                    headers=h).json()
    assert r["segments_recorded"] == 0


def test_discarded_walk_cannot_be_completed(client, h):
    w = plan(client, h)
    client.post(f"/api/walks/{w['id']}/discard", headers=h)
    r = client.post(f"/api/walks/{w['id']}/complete",
                    json=dict(outcome="AS_PLANNED"), headers=h)
    assert r.status_code == 409


def test_cannot_complete_another_participants_walk(client, h):
    w = plan(client, h)
    other = auth(register(client, "intruder@example.com")["token"])
    assert client.get(f"/api/walks/{w['id']}", headers=other).status_code == 404
    assert client.post(f"/api/walks/{w['id']}/complete",
                       json=dict(outcome="AS_PLANNED"), headers=other).status_code == 404


# ---------------------------------------------------------------- reservations
def test_preview_reserves_and_discard_releases(client, h):
    from api.app.db import SessionLocal
    from api.app.services import reservations as res

    w = plan(client, h)
    with SessionLocal() as db:
        held = res.held_segment_ids(db)
    assert set(_planned_required(client, w["id"], h)) <= held

    client.post(f"/api/walks/{w['id']}/discard", headers=h)
    with SessionLocal() as db:
        held_after = res.held_segment_ids(db)
    assert not (set(_planned_required(client, w["id"], h)) & held_after)


def test_completing_releases_the_hold(client, h):
    from api.app.db import SessionLocal
    from api.app.services import reservations as res

    w = plan(client, h)
    client.post(f"/api/walks/{w['id']}/start", headers=h)
    client.post(f"/api/walks/{w['id']}/complete", json=dict(outcome="AS_PLANNED"),
                headers=h)
    with SessionLocal() as db:
        assert not (set(_planned_required(client, w["id"], h))
                    & res.held_segment_ids(db))


def test_expired_reservations_stop_counting(client, h):
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import update

    from api.app.db import SessionLocal
    from api.app.models import Reservation
    from api.app.services import reservations as res

    w = plan(client, h)
    with SessionLocal() as db:
        db.execute(update(Reservation).where(Reservation.walk_id == w["id"])
                   .values(expires_at=datetime.now(timezone.utc) - timedelta(minutes=1)))
        db.commit()
        assert not (set(_planned_required(client, w["id"], h))
                    & res.held_segment_ids(db))
    client.post(f"/api/walks/{w['id']}/discard", headers=h)


def test_two_nearby_walkers_both_get_routes(client):
    """§12: reservations nudge, they do not lock.

    Both walkers start on the same corner. The second must still get a usable route,
    and it should not be a carbon copy of the first.
    """
    a = auth(register(client, "sim-a@example.com")["token"])
    b = auth(register(client, "sim-b@example.com")["token"])

    wa = plan(client, a, band="Medium")
    ra = client.post(f"/api/walks/{wa['id']}/start", headers=a)
    assert ra.status_code == 200

    rb = client.post("/api/routes/generate", json=DOWNTOWN, headers=b).json()
    assert rb["available_bands"], "the second walker got no route at all"
    med = next(v for v in rb["variants"] if v["band"] == "Medium")
    assert med["available"]
    assert med["new_required_miles"] > 0.2, \
        "the second walker's route earned almost no new coverage"

    held = set(_planned_required(client, wa["id"], a))
    overlap = held & set(med["required_segment_ids"])
    assert len(overlap) < len(med["required_segment_ids"]), \
        "the second walker was routed onto exactly the held segments"

    client.post(f"/api/walks/{wa['id']}/discard", headers=a)


def test_cannot_start_a_second_walk_while_one_is_active(client, h):
    """An ACTIVE walk is a commitment; a PREVIEW is browsing.

    Without this, an error on the completion path would leave a walk ACTIVE and its
    segments held, and the participant could quietly start another and hold both.
    """
    w = plan(client, h)
    client.post(f"/api/walks/{w['id']}/start", headers=h)
    g = client.post("/api/routes/generate", json=DOWNTOWN, headers=h).json()
    r = client.post("/api/walks/select",
                    json=dict(request_id=g["request_id"], band=g["available_bands"][0]),
                    headers=h)
    assert r.status_code == 409
    assert "already have a walk in progress" in r.json()["detail"]
    client.post(f"/api/walks/{w['id']}/discard", headers=h)


def test_reservations_never_expose_who_holds_them(client, h):
    w = plan(client, h)
    body = client.get("/api/progress/map", headers=h).json()
    # The `excludes` list legitimately contains the word "participant" — it is the
    # map telling you what it leaves out. Assert on the features themselves.
    assert "participant" not in str(body["features"]).lower()
    for f in body["features"]:
        assert set(f["properties"]) == {"id", "name", "kind", "done", "held"}
    client.post(f"/api/walks/{w['id']}/discard", headers=h)


# --------------------------------------------------------------------- metrics
def test_metrics_move_after_a_walk(client, h):
    before = client.get("/api/progress/metrics").json()
    w = plan(client, h, band="Long")
    client.post(f"/api/walks/{w['id']}/start", headers=h)
    client.post(f"/api/walks/{w['id']}/complete", json=dict(outcome="AS_PLANNED"),
                headers=h)
    after = client.get("/api/progress/metrics").json()

    assert after["percent_prayed_for"]["value"] >= before["percent_prayed_for"]["value"]
    assert after["total_miles_walked"]["value"] > before["total_miles_walked"]["value"]
    assert after["completed_walks"] == before["completed_walks"] + 1


def test_every_metric_carries_its_definition(client):
    m = client.get("/api/progress/metrics").json()
    for key in ("percent_prayed_for", "total_miles_walked",
                "estimated_households_prayed_for"):
        assert len(m[key]["definition"]) > 80, f"{key} has no usable definition"
    assert "ESTIMATE" in m["estimated_households_prayed_for"]["definition"]
    assert "not of occupied households" in \
        m["estimated_households_prayed_for"]["definition"]


def test_denominator_matches_the_frozen_network(client, ns):
    m = client.get("/api/progress/metrics").json()
    assert m["percent_prayed_for"]["denominator_miles"] == \
        pytest.approx(ns.required_denominator_miles, abs=0.01)
    assert m["network_version"] == network_version()


def test_percentage_never_exceeds_one_hundred(client):
    m = client.get("/api/progress/metrics").json()
    assert 0.0 <= m["percent_prayed_for"]["value"] <= 100.0


# --------------------------------------------------------------------- helpers
def _planned_required(client, walk_id, headers):
    from api.app.db import SessionLocal
    from api.app.models import Walk
    with SessionLocal() as db:
        return list(db.get(Walk, walk_id).planned_required_ids)


def _planned_all(client, walk_id):
    from api.app.db import SessionLocal
    from api.app.models import Walk
    with SessionLocal() as db:
        return list(db.get(Walk, walk_id).planned_segment_ids)


# ------------------------------------------------------- §20 metrics matrix
def test_duplicate_completion_by_two_users_counts_once(client, ns):
    """§15: the obligation completes once; both walks keep their contribution."""
    a = auth(register(client, "dup-a@example.com")["token"])
    b = auth(register(client, "dup-b@example.com")["token"])

    wa = plan(client, a, band="Short")
    client.post(f"/api/walks/{wa['id']}/start", headers=a)
    client.post(f"/api/walks/{wa['id']}/complete", json=dict(outcome="AS_PLANNED"),
                headers=a)

    shared = _planned_required(client, wa["id"], a)
    mid = client.get("/api/progress/metrics").json()

    wb = plan(client, b, band="Short")
    client.post(f"/api/walks/{wb['id']}/start", headers=b)
    rb = client.post(f"/api/walks/{wb['id']}/complete",
                     json=dict(outcome="EDITED", segment_ids=shared),
                     headers=b).json()
    after = client.get("/api/progress/metrics").json()

    # Coverage does not move — the same obligations were already complete.
    assert after["percent_prayed_for"]["value"] == mid["percent_prayed_for"]["value"]
    assert after["estimated_households_prayed_for"]["value"] == \
        mid["estimated_households_prayed_for"]["value"]
    # But both walks count toward miles walked, and B keeps its own contribution.
    assert after["total_miles_walked"]["value"] > mid["total_miles_walked"]["value"]
    assert after["completed_walks"] == mid["completed_walks"] + 1
    assert rb["segments_recorded"] == len(shared)


def test_households_deduplicate_across_walks(client, h, ns):
    """A household on a segment two walks both cover is counted once."""
    from api.app.db import SessionLocal
    from api.app.services import completion as csvc
    with SessionLocal() as db:
        done = csvc.completed_segment_ids(db)
        m = csvc.metrics(db, ns)
    expected = sum(ns.net.segments[i].households
                   for i in ns.indices(done) if ns.net.segments[i].required)
    assert m["estimated_households_prayed_for"]["value"] == expected


def test_campus_alternatives_do_not_double_count(client, h, ns):
    """§20: walking a parallel walkway credits the canonical side — once.

    The alternative itself is a connector and carries no obligation of its own, so
    the corridor cannot be completed twice.
    """
    alts = [s for s in ns.net.segments if s.campus_obligation == "ALTERNATIVE"]
    assert alts, "network has no campus alternatives to test"
    assert not any(s.required for s in alts), \
        "an ALTERNATIVE walkway is REQUIRED — that is a duplicate obligation"

    alt = next(s for s in alts if s.satisfies)
    credited = ns.net.credited({alt.idx})
    # Walking it twice credits the same canonical segments, not more.
    assert ns.net.credited({alt.idx}) == credited
    for i in credited:
        assert ns.net.segments[i].campus_obligation == "CANONICAL"


def test_excluded_segments_are_not_in_the_denominator(client, ns):
    """§20: EXCLUDED mileage affects neither half of the percentage."""
    m = client.get("/api/progress/metrics").json()
    denom = m["percent_prayed_for"]["denominator_miles"]
    assert denom == pytest.approx(ns.net.stats["required_miles"], abs=0.01)
    # Smart Road and the bypass are excluded, so they are absent entirely.
    assert not any(s.role == "EXCLUDED" for s in ns.net.segments)
    assert not any(s.normalized_name == "gordon c willis smart rd"
                   for s in ns.net.segments)
    assert ns.net.stats["excluded_miles"] > 40  # they exist in the canonical network
    assert denom < ns.net.stats["canonical_total_miles"]


def test_total_miles_includes_repeats_and_connectors(client, h, ns):
    """§4: total miles walked is the submitted route distance, not new coverage."""
    before = client.get("/api/progress/metrics").json()["total_miles_walked"]["value"]
    w = plan(client, h, band="Medium")
    client.post(f"/api/walks/{w['id']}/start", headers=h)
    r = client.post(f"/api/walks/{w['id']}/complete", json=dict(outcome="AS_PLANNED"),
                    headers=h).json()
    after = client.get("/api/progress/metrics").json()["total_miles_walked"]["value"]

    # The published figure is rounded to one decimal, so a difference of two rounded
    # values carries up to 0.1 mi of rounding error. That is the metric's precision,
    # not a discrepancy.
    assert after - before == pytest.approx(w["distance_miles"], abs=0.11)
    # The walk is longer than the new ground it earned — that is the point.
    assert w["distance_miles"] >= r["miles_credited"]
