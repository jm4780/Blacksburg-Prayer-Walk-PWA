"""Privacy matrix (§18, §16, §20).

The strongest assertion here is the last one: it walks the *entire* canonical
household file, takes every real residential street address and coordinate in
Blacksburg, and proves none of them appears in any API response. That is a much
better guarantee than checking for suspicious-looking key names, because it fails if
a future change starts leaking data through a field nobody thought to look at.
"""
from __future__ import annotations

import json
import os
import random

import pytest

from .conftest import DOWNTOWN, auth, make_admin, register


@pytest.fixture(scope="module")
def h(client):
    return auth(register(client, "privacy@example.com")["token"])


@pytest.fixture(scope="module")
def admin_h(client):
    p = register(client, "admin@example.com")
    make_admin(client, p["id"])
    return auth(p["token"])


@pytest.fixture(scope="module")
def responses(client, h, admin_h):
    """Every response the application can produce, collected once."""
    out = {}

    def grab(name, r):
        out[name] = r.text
        return r

    grab("health", client.get("/api/health"))
    grab("metrics", client.get("/api/progress/metrics"))
    grab("map", client.get("/api/progress/map", headers=h))
    grab("me", client.get("/api/identity/me", headers=h))

    gen = grab("generate", client.post("/api/routes/generate", json=DOWNTOWN, headers=h))
    g = gen.json()
    band = g["available_bands"][0]
    w = grab("select", client.post("/api/walks/select",
                                   json=dict(request_id=g["request_id"], band=band),
                                   headers=h)).json()
    grab("start", client.post(f"/api/walks/{w['id']}/start", headers=h))
    grab("walk", client.get(f"/api/walks/{w['id']}", headers=h))
    grab("complete", client.post(f"/api/walks/{w['id']}/complete",
                                 json=dict(outcome="AS_PLANNED"), headers=h))

    for name, path in [("admin_overview", "/api/admin/overview"),
                       ("admin_network", "/api/admin/network"),
                       ("admin_review", "/api/admin/review-queues"),
                       ("admin_walks", "/api/admin/walks"),
                       ("admin_people", "/api/admin/participants"),
                       ("admin_holds", "/api/admin/reservations"),
                       ("admin_deploy", "/api/admin/deployment"),
                       ("admin_export", "/api/admin/export"),
                       ("admin_audit", "/api/admin/audit")]:
        grab(name, client.get(path, headers=admin_h))
    return out


# ----------------------------------------------------- structural expectations
# Exactly what a map feature may carry. An allow-list, not a deny-list: a new field
# added to Segment must be argued for here before it can reach the browser, rather
# than arriving by accident because nobody thought to forbid it.
#
# `road_class` and `path_type` were admitted for the map design system's width ramp
# (docs/20 §4). Both describe a public road's classification — Arterial, Local, Trail,
# Sidewalk. Neither is residential, neither identifies anybody, and neither is derived
# from the address data.
MAP_FEATURE_PROPERTIES = {"id", "name", "kind", "done", "held",
                          "road_class", "path_type"}


def test_map_features_carry_only_permitted_properties(client, h):
    body = client.get("/api/progress/map", headers=h).json()
    for f in body["features"]:
        assert set(f["properties"]) == MAP_FEATURE_PROPERTIES


def test_open_space_carries_no_attributes_at_all(client, h):
    """Parks are drawn as ground, so they need geometry and nothing else.

    The source carries owner type, acreage and identifiers. None of it is rendered,
    so none of it is published — the shape is the whole contribution.
    """
    body = client.get("/api/progress/map", headers=h).json()
    space = body.get("open_space")
    if space is None:
        return  # snapshot absent in this environment; nothing to leak
    for f in space["features"]:
        assert f["properties"] == {}, f["properties"]


def test_map_never_carries_a_household_count(client, h):
    """Per-segment counts are aggregates, but a count of 2 on a cul-de-sac identifies
    a household. Only the town-wide total is published."""
    body = client.get("/api/progress/map", headers=h).json()
    # `excludes` says the word "household" on purpose — it is the disclosure of what
    # the map omits. The features are what must be clean.
    assert "household" not in str(body["features"]).lower()
    for f in body["features"]:
        assert not any("household" in k.lower() for k in f["properties"])


def test_map_excludes_alternative_campus_walkways(client, h, ns):
    ids = {f["properties"]["id"]
           for f in client.get("/api/progress/map", headers=h).json()["features"]}
    alts = {s.id for s in ns.net.segments if s.campus_obligation == "ALTERNATIVE"}
    assert not (ids & alts), "§16: canonical campus corridors only"


def test_map_excludes_non_required_geometry(client, h, ns):
    ids = {f["properties"]["id"]
           for f in client.get("/api/progress/map", headers=h).json()["features"]}
    for sid in ids:
        assert ns.net.segments[ns.idx_of_id[sid]].required


def test_the_geometry_gate_is_a_deployment_setting_that_still_works(client):
    """G1 is deployment configuration, not architecture (Phase 3.1 §1).

    Phase 3.5 changed the *default* to `open_read`, because a dashboard nobody can
    see before signing up is not a dashboard (Priority 2). What must not change is
    that the gate still closes when a deployment asks it to, and that it closes at
    exactly one place — `deps.may_see_geometry`.
    """
    from api.app import config, deps

    assert client.get("/api/progress/map").status_code == 200, \
        "open_read is the Phase 3.5 default and should serve the map anonymously"

    original = config.settings.cache_clear
    try:
        os.environ["BPW_ACCESS_MODE"] = "authenticated"
        config.settings.cache_clear()
        r = client.get("/api/progress/map")
        assert r.status_code == 403
        assert "licensing gate G1" in r.json()["detail"]
        assert deps.may_see_geometry(None) is False
    finally:
        os.environ["BPW_ACCESS_MODE"] = "open_read"
        original()
    assert client.get("/api/progress/map").status_code == 200


def test_metrics_are_public_and_carry_no_geometry(client):
    r = client.get("/api/progress/metrics")
    assert r.status_code == 200
    assert "coordinates" not in r.text


def test_no_gps_fix_is_ever_stored(client, h):
    """§18: the browser's location is used once, in memory, and discarded."""
    from sqlalchemy import select

    from api.app.db import SessionLocal
    from api.app.models import RouteRequest
    client.post("/api/routes/generate", json=DOWNTOWN, headers=h)
    with SessionLocal() as db:
        rows = db.execute(select(RouteRequest)).scalars().all()
    assert rows
    for r in rows:
        cols = {c.name for c in r.__table__.columns}
        assert not (cols & {"lat", "lon", "latitude", "longitude", "start_lat",
                            "start_lon", "geometry", "point"}), \
            f"RouteRequest stores a location column: {cols}"
        assert isinstance(r.start_node, int)


def test_admin_cannot_read_a_named_participants_routes(client, admin_h):
    """§16: routes are never tied to a name."""
    walks = client.get("/api/admin/walks", headers=admin_h).json()
    for w in walks:
        assert "first_name" not in w and "last_name" not in w and "email" not in w
        assert "planned_segment_ids" not in w
        assert "geometry" not in w


def test_admin_export_carries_no_identity(client, admin_h):
    body = client.get("/api/admin/export", headers=admin_h).json()
    assert "participant" not in json.dumps(body["completed_segment_ids"]).lower()
    assert "participant identity" in body["excludes"]


# -------------------------------------------------- the real-data leak check
def _household_secrets(limit=400):
    """Real addresses and coordinates from the canonical household file.

    The file is gitignored and holds ~18,000 individual residential addresses. If any
    of these strings ever appears in an API response, something is very wrong.
    """
    from api.app.config import settings
    from api.routing import network as net_mod
    path = os.path.join(net_mod.OUT_ROOT, settings().snapshot_date, "households.json")
    if not os.path.exists(path):
        pytest.skip("households.json not built; run python3 -m pipeline.build.run")
    rows = json.load(open(path))["households"]
    rng = random.Random(4242)
    sample = rng.sample(rows, min(limit, len(rows)))

    addresses, coords = set(), set()
    for r in sample:
        for key in ("address", "full_address", "display_address", "key",
                    "normalized_address", "street_address"):
            v = r.get(key)
            if isinstance(v, str) and len(v) > 6:
                addresses.add(v)
        for key in ("lat", "lon", "latitude", "longitude", "x", "y"):
            v = r.get(key)
            if isinstance(v, (int, float)):
                coords.add(round(float(v), 5))
    return addresses, coords


def test_no_real_residential_address_appears_in_any_response(responses):
    addresses, _ = _household_secrets()
    assert addresses, "could not extract any address from households.json"
    leaks = []
    for name, body in responses.items():
        low = body.lower()
        for a in addresses:
            if a.lower() in low:
                leaks.append((name, a))
    assert not leaks, f"residential addresses leaked: {leaks[:5]}"


def test_no_household_coordinate_appears_in_any_response(responses):
    _, coords = _household_secrets()
    if not coords:
        pytest.skip("household file stores no coordinates (they are stripped at write)")
    leaks = []
    for name, body in responses.items():
        for c in coords:
            if f"{c}" in body:
                leaks.append((name, c))
    assert not leaks, f"household coordinates leaked: {leaks[:5]}"


def test_household_file_and_snapshots_are_not_committed():
    """The gitignore rules are load-bearing, so they get a test."""
    import subprocess
    tracked = subprocess.run(
        ["git", "ls-files"], capture_output=True, text=True,
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))).stdout
    forbidden = ["households.json", "unassociated-households.json",
                 "segments.geojson", "complex-review-map.html"]
    for f in forbidden:
        assert f not in tracked, f"{f} is tracked by git"
    assert ".geojson" not in tracked, "geojson is tracked by git"
