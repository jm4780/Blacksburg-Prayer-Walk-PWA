"""Phase 3.1: access mode, feedback, and the pilot summary.

The feedback tests care about one thing above all: that a complaint is
**reproducible**. A rating with no way to regenerate the route is a feeling; a rating
with a seed, a start node and a network version is a bug report.
"""
from __future__ import annotations

import importlib
from contextlib import contextmanager

import pytest

from .conftest import DOWNTOWN, auth, make_admin, network_version, register


@pytest.fixture(scope="module")
def h(client):
    return auth(register(client, "pilot@example.com", "Pilot", "Walker")["token"])


@pytest.fixture(scope="module")
def admin_h(client):
    p = register(client, "pilot-admin@example.com")
    make_admin(client, p["id"])
    return auth(p["token"])


def a_walk(client, headers, band="Short"):
    cur = client.get("/api/walks/current", headers=headers).json()
    if cur and cur["status"] == "ACTIVE":
        client.post(f"/api/walks/{cur['id']}/discard", headers=headers)
    g = client.post("/api/routes/generate", json=DOWNTOWN, headers=headers).json()
    if band not in g["available_bands"]:
        band = g["available_bands"][0]
    w = client.post("/api/walks/select",
                    json=dict(request_id=g["request_id"], band=band),
                    headers=headers).json()
    client.post(f"/api/walks/{w['id']}/start", headers=headers)
    return w, g


# ------------------------------------------------------------------- feedback
def test_feedback_is_reproducible(client, h):
    """Every rating carries the key that regenerates the exact route."""
    w, g = a_walk(client, h)
    r = client.post(f"/api/walks/{w['id']}/feedback",
                    json=dict(rating=2, easy_to_follow=False,
                              time_felt_accurate=True, had_bad_connection=True,
                              bad_connection_detail="crossed where there is no crosswalk",
                              completed_as_planned=False,
                              submitted_from="ACTIVE_WALK"), headers=h)
    assert r.status_code == 200, r.text
    rep = r.json()["reproduce"]
    assert rep["seed"] == g["seed"]
    assert rep["network_version"] == network_version()
    assert rep["engine_version"]
    assert rep["band"] == w["band"]
    assert rep["start_node"] is not None
    assert rep["coverage_area_id"] == g["coverage_area_id"]


def test_stored_seed_actually_regenerates_the_route(client, h):
    """The reproduction key is not decorative — it is exercised here."""
    w, g = a_walk(client, h, band="Medium")
    client.post(f"/api/walks/{w['id']}/feedback", json=dict(rating=1), headers=h)
    fb = client.get(f"/api/walks/{w['id']}/feedback", headers=h).json()

    again = client.post("/api/routes/generate",
                        json={**DOWNTOWN, "seed": fb["reproduce"]["seed"]},
                        headers=h).json()
    same = next(v for v in again["variants"] if v["band"] == w["band"])
    from api.app.db import SessionLocal
    from api.app.models import Walk
    with SessionLocal() as db:
        planned = list(db.get(Walk, w["id"]).planned_segment_ids)
    assert same["segment_ids"] == planned, \
        "the stored seed did not regenerate the route it was recorded against"


def test_feedback_is_one_row_per_walk(client, h):
    w, _ = a_walk(client, h)
    first = client.post(f"/api/walks/{w['id']}/feedback",
                        json=dict(rating=3, submitted_from="ACTIVE_WALK"),
                        headers=h).json()
    second = client.post(f"/api/walks/{w['id']}/feedback",
                         json=dict(rating=5, submitted_from="AFTER_SUBMISSION"),
                         headers=h).json()
    assert first["updated"] is False
    assert second["updated"] is True
    assert second["id"] == first["id"]
    assert client.get(f"/api/walks/{w['id']}/feedback", headers=h).json()["rating"] == 5


def test_feedback_available_from_both_places(client, h):
    for where in ("ACTIVE_WALK", "AFTER_SUBMISSION"):
        w, _ = a_walk(client, h)
        r = client.post(f"/api/walks/{w['id']}/feedback",
                        json=dict(rating=4, submitted_from=where), headers=h)
        assert r.status_code == 200


def test_cannot_rate_another_participants_walk(client, h):
    w, _ = a_walk(client, h)
    other = auth(register(client, "nosy@example.com")["token"])
    assert client.post(f"/api/walks/{w['id']}/feedback", json=dict(rating=1),
                       headers=other).status_code == 404


@pytest.mark.parametrize("rating", [0, 6, -1])
def test_rating_must_be_one_to_five(client, h, rating):
    w, _ = a_walk(client, h)
    assert client.post(f"/api/walks/{w['id']}/feedback", json=dict(rating=rating),
                       headers=h).status_code == 422


# -------------------------------------------------------------- pilot summary
def test_pilot_summary_reports_what_a_pilot_needs(client, h, admin_h):
    w, _ = a_walk(client, h)
    client.post(f"/api/walks/{w['id']}/complete", json=dict(outcome="AS_PLANNED"),
                headers=h)
    client.post(f"/api/walks/{w['id']}/feedback",
                json=dict(rating=5, had_bad_connection=False), headers=h)

    s = client.get("/api/admin/pilot-summary", headers=admin_h).json()
    for key in ("network", "participants", "walks", "manual_edits", "feedback",
                "route_generation", "late_opportunity_states", "coverage_areas"):
        assert key in s, f"pilot summary is missing {key}"
    assert s["walks"]["submitted"] >= 1
    assert s["feedback"]["responses"] >= 1
    assert s["feedback"]["average_rating"] is not None
    assert s["walks"]["completion_rate"] is not None
    assert s["network"]["version"] == network_version()


def test_pilot_summary_never_names_a_walker_against_a_route(client, admin_h):
    """§8: no participant identity or precise location in pilot reporting."""
    s = client.get("/api/admin/pilot-summary", headers=admin_h).json()
    text = str(s).lower()
    for banned in ("@example.com", "first_name", "last_name", "email",
                   "latitude", "longitude", '"lat"', '"lon"'):
        assert banned not in text, f"pilot summary leaked {banned}"
    # Starting areas are components, never coordinates.
    for area in s["coverage_areas"]:
        assert area.startswith("comp-"), area


def test_pilot_summary_requires_admin(client, h):
    assert client.get("/api/admin/pilot-summary", headers=h).status_code == 403


def test_flagged_routes_carry_their_reproduction_key(client, h, admin_h):
    w, _ = a_walk(client, h)
    client.post(f"/api/walks/{w['id']}/feedback",
                json=dict(rating=1, had_bad_connection=True,
                          bad_connection_detail="unsafe crossing"), headers=h)
    s = client.get("/api/admin/pilot-summary", headers=admin_h).json()
    flagged = s["feedback"]["flagged"]
    assert flagged, "a flagged route did not appear in the pilot summary"
    assert all(f["reproduce"]["seed"] is not None for f in flagged)


def test_admin_feedback_list_is_usable(client, admin_h):
    rows = client.get("/api/admin/feedback", headers=admin_h).json()
    assert rows
    assert {"rating", "band", "reproduce", "comment"} <= set(rows[0])


def test_connector_candidates_are_exposed_to_admin(client, admin_h):
    d = client.get("/api/admin/connector-candidates", headers=admin_h).json()
    assert d["candidates"] > 0
    assert d["promoted"] == 0, "a connector was promoted without a network version bump"
    r = d["rows"][0]
    assert {"required_miles_recovered", "recommendation", "confidence",
            "map_location", "evidence_for", "evidence_against"} <= set(r)


# --------------------------------------------------------------- access modes
@contextmanager
def access_mode(mode: str, **extra):
    """Run a block under a different deployment access mode, then put it back.

    Restoring to whatever the mode *was* rather than to a literal: Phase 3.5 moved
    the default from `authenticated` to `open_read`, and a test that restored to a
    hard-coded mode silently reconfigured every test that ran after it.
    """
    from api.app import config
    cfg = config.settings()
    previous = {k: getattr(cfg, k) for k in ("access_mode", *extra)}
    object.__setattr__(cfg, "access_mode", mode)
    for k, v in extra.items():
        object.__setattr__(cfg, k, v)
    try:
        yield cfg
    finally:
        for k, v in previous.items():
            object.__setattr__(cfg, k, v)


def test_access_mode_controls_anonymous_geometry(client):
    """G1 is deployment configuration: one setting, no API change."""
    from api.app import config

    # Phase 3.5 default: the dashboard and the progress map are readable before
    # anybody signs up (Priority 2).
    assert config.settings().access_mode == "open_read"
    assert client.get("/api/progress/map").status_code == 200

    with access_mode("authenticated") as cfg:
        assert cfg.geometry_is_public is False
        assert client.get("/api/progress/map").status_code == 403

    with access_mode("public") as cfg:
        assert cfg.geometry_is_public is True
        assert client.get("/api/progress/map").status_code == 200

    assert client.get("/api/progress/map").status_code == 200


def test_public_access_mode_still_hides_residential_data(client):
    """Making geometry public must not make anything else public."""
    with access_mode("public"):
        body = client.get("/api/progress/map").text
        assert "household" not in body.lower().split('"excludes"')[0]
        assert "participant" not in body.lower().split('"excludes"')[0]


def test_invite_mode_gates_registration(client):
    with access_mode("invite", invite_code="walk-with-us"):
        bad = client.post("/api/identity/register",
                          json=dict(first_name="No", last_name="Code",
                                    email="nocode@example.com"))
        assert bad.status_code == 403
        assert "invite code" in bad.json()["detail"]

        ok = client.post("/api/identity/register",
                         json=dict(first_name="Has", last_name="Code",
                                   email="hascode@example.com",
                                   invite_code="walk-with-us"))
        assert ok.status_code == 200
        # Identity model is unchanged by the gate: still name, email, opaque token.
        assert ok.json()["token"]


def test_deployment_check_warns_on_invite_without_a_code():
    from api.app.config import Settings
    s = Settings(tier="pilot", token_pepper="x", access_mode="invite", invite_code="")
    assert any("INVITE_CODE is unset" in w for w in s.check())


def test_deployment_check_warns_when_geometry_goes_public():
    from api.app.config import Settings
    s = Settings(tier="pilot", token_pepper="x", access_mode="public")
    assert any("G1" in w for w in s.check())


def test_response_rate_can_never_exceed_one(client, h, admin_h):
    """A rate above 100% discredits every number beside it.

    Feedback can be left from the active-walk screen, before the walk is submitted, so
    dividing all feedback by submitted walks produced 200% on a real pilot screen.
    """
    w, _ = a_walk(client, h)                       # started, not submitted
    client.post(f"/api/walks/{w['id']}/feedback", json=dict(rating=4), headers=h)
    s = client.get("/api/admin/pilot-summary", headers=admin_h).json()["feedback"]
    assert s["response_rate"] is None or 0.0 <= s["response_rate"] <= 1.0, s
    assert s["responses"] >= s["responses_on_submitted_walks"]
    assert s["responses_on_walks_still_in_progress"] >= 1
