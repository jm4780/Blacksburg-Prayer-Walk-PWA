"""What a walker's edits to their own walk may claim (§14).

An EDITED submission used to be unbounded. `completion.record` filtered the ids it was
given to ones that exist and are REQUIRED, and nothing checked that they had anything to
do with the walk. A reviewer credited three streets on the far side of Blacksburg against
a downtown walk simply by naming them in the request, and the town's coverage record
moved: 468 streets complete became 471.

The rule now is that a walk may claim its own route plus a quarter mile around it. That
is deliberately generous to the walk that actually happened — the next road over, the
block cut through, the far side of the square are all a hundred metres or two from the
route — and it refuses a claim about somewhere the walker demonstrably was not.

Its own database, because these tests record walks and every completed street changes
what the router offers the tests that come after it.
"""
from __future__ import annotations

import pytest

from .conftest import (DOWNTOWN, auth, register, streets_across_town,
                       streets_beside_the_route)


@pytest.fixture(scope="module")
def h(client):
    return auth(register(client, "editor@example.com", "Ed", "Walker")["token"])


def a_started_walk(client, headers, band="Medium"):
    cur = client.get("/api/walks/current", headers=headers).json()
    if cur:
        client.post(f"/api/walks/{cur['id']}/discard", headers=headers)
    g = client.post("/api/routes/generate", json=DOWNTOWN, headers=headers).json()
    if band not in g["available_bands"]:
        band = g["available_bands"][0]
    w = client.post("/api/walks/select",
                    json=dict(request_id=g["request_id"], band=band),
                    headers=headers)
    assert w.status_code == 200, w.text
    w = w.json()
    client.post(f"/api/walks/{w['id']}/start", headers=headers)
    return w


def planned_required(walk_id):
    from api.app.db import SessionLocal
    from api.app.models import Walk
    with SessionLocal() as db:
        return list(db.get(Walk, walk_id).planned_required_ids)


def test_a_walk_cannot_claim_streets_on_the_far_side_of_town(client, h, ns):
    w = a_started_walk(client, h)
    before = client.get("/api/progress/metrics").json()

    strays = streets_across_town(ns, w, 3)
    r = client.post(f"/api/walks/{w['id']}/complete",
                    json=dict(outcome="EDITED", segment_ids=strays), headers=h)

    assert r.status_code == 422, r.text
    detail = r.json()["detail"]
    assert "too far from this walk's route" in detail
    # Named as streets, so a walker can find them in their own list and untick them.
    assert "SEG-" not in detail

    after = client.get("/api/progress/metrics").json()
    assert after["required_segments_complete"] == before["required_segments_complete"]
    assert after["total_miles_walked"] == before["total_miles_walked"]
    # Nothing was written, so the walk is still there to be reported properly.
    assert client.get(f"/api/walks/{w['id']}", headers=h).json()["status"] == "ACTIVE"


def test_one_stray_street_does_not_slip_in_beside_honest_ones(client, h, ns):
    """The refusal is of the submission, not of the streets it got right — a screen
    that quietly drops part of the answer is a screen whose receipt lies."""
    from sqlalchemy import select

    from api.app.db import SessionLocal
    from api.app.models import Completion

    w = a_started_walk(client, h)
    planned = planned_required(w["id"])
    stray = streets_across_town(ns, w, 1)

    r = client.post(f"/api/walks/{w['id']}/complete",
                    json=dict(outcome="EDITED", segment_ids=planned[:3] + stray),
                    headers=h)
    assert r.status_code == 422, r.text
    assert "One street is" in r.json()["detail"]

    with SessionLocal() as db:
        assert not db.execute(select(Completion.segment_id)
                              .where(Completion.walk_id == w["id"])).scalars().all()

    # And the honest part of the same answer still records, on its own.
    ok = client.post(f"/api/walks/{w['id']}/complete",
                     json=dict(outcome="EDITED", segment_ids=planned[:3]), headers=h)
    assert ok.status_code == 200, ok.text
    assert ok.json()["segments_recorded"] == 3


def test_the_rule_holds_even_when_nothing_refuses_the_request(client, h, ns):
    """Belt and braces: the service credits nothing out of bounds, however it is called.

    The 422 above is what a walker sees. This is what protects the number if some other
    caller — an admin tool, a script, an endpoint written later — reaches the service
    directly and never asks.
    """
    from sqlalchemy import select

    from api.app.db import SessionLocal
    from api.app.models import Completion, Walk
    from api.app.services import completion as csvc

    w = a_started_walk(client, h)
    planned = planned_required(w["id"])
    strays = streets_across_town(ns, w, 2)

    with SessionLocal() as db:
        walk = db.get(Walk, w["id"])
        assert csvc.unsupported_edits(ns, walk, strays) == strays
        assert csvc.unsupported_edits(ns, walk, planned[:2]) == []
        r = csvc.record(db, ns, walk, "EDITED", planned[:2] + strays)
        got = set(db.execute(select(Completion.segment_id)
                             .where(Completion.walk_id == w["id"])).scalars())

    assert r["segments_recorded"] == 2
    assert got == set(planned[:2])
    assert not got & set(strays)


def test_a_walker_may_still_report_the_street_they_wandered_onto(client, h, ns):
    """The edit this bound must not break: skip part of the plan, add the road beside
    it, and have the addition recorded as an addition."""
    w = a_started_walk(client, h)
    planned = planned_required(w["id"])
    beside = streets_beside_the_route(ns, w, 2)

    r = client.post(f"/api/walks/{w['id']}/complete",
                    json=dict(outcome="EDITED", segment_ids=planned[:-2] + beside),
                    headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["manual_additions"] == 2
    assert body["manual_removals"] == 2
    assert body["segments_recorded"] == len(planned)


def test_a_walk_may_claim_a_street_it_only_passed_the_end_of(client, h, ns):
    """The bound is a distance from the route, not membership of the plan: a street the
    walker turned down and came back from is in, wherever it sits in the network."""
    from api.app.db import SessionLocal
    from api.app.models import Walk
    from api.app.services import completion as csvc

    w = a_started_walk(client, h)
    beside = streets_beside_the_route(ns, w, 5)
    with SessionLocal() as db:
        walk = db.get(Walk, w["id"])
        assert csvc.unsupported_edits(ns, walk, beside) == []
    client.post(f"/api/walks/{w['id']}/discard", headers=h)


def test_an_unedited_walk_is_untouched_by_the_bound(client, h):
    """AS_PLANNED answers with the plan itself and never consults the rule."""
    w = a_started_walk(client, h)
    r = client.post(f"/api/walks/{w['id']}/complete",
                    json=dict(outcome="AS_PLANNED"), headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["segments_recorded"] == len(planned_required(w["id"]))
