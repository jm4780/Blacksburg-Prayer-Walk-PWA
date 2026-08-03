"""Mission recommendation (Phase 3.5, Priorities 2–5, 8–10).

This covers the product claims that are easy to break silently:

  - a walk can be recommended with no identity and no location
  - the time slider's bounds are what the server actually honours
  - the words on the card never lie (no "Finish X" unless it finishes X, no
    "0 households", no parking language)
  - simultaneous walkers are given genuinely different walks
  - nothing that describes the optimiser reaches the browser
"""
from __future__ import annotations

import re

import pytest

from api.app.services import mission_service as svc

from .conftest import auth, register

# Wording the walker must never see. "Park" is checked as a whole word so that
# "Parkway" and "Park Street" — real Blacksburg street names — do not trip it.
FORBIDDEN_PHRASES = [
    r"\bpark(ing|ed)?\b", r"\bcoverage gain\b", r"\bwalk quality\b",
    r"\broute score\b", r"\befficiency\b", r"\bcluster\b", r"\bseed\b",
    r"\bGPS\b", r"\btracking\b",
]

# Keys that exist server-side and must not be serialised to the browser.
LEAKY_KEYS = {
    "score", "route_score", "walk_quality", "efficiency", "coverage_gain",
    "cluster", "cluster_id", "seed", "prize", "score_components", "meta",
}


@pytest.fixture(scope="module")
def slate(client):
    r = client.get("/api/missions/recommend?minutes=45")
    assert r.status_code == 200, r.text
    return r.json()


# ------------------------------------------------------------------ anonymous
def test_recommend_needs_no_identity(slate):
    """Priority 2: the dashboard and a real recommendation come before the form."""
    assert slate["available"] is True
    assert slate["mission"]["title"]
    assert slate["mission"]["geometry"]["coordinates"]


def test_recommend_needs_no_location(client):
    """Priority 5: no lat/lon in, a real walk out."""
    r = client.get("/api/missions/recommend?minutes=30")
    assert r.status_code == 200
    assert r.json()["mission"]["distance_miles"] > 0


def test_accept_requires_identity(slate, client):
    """Identity is asked for at the first moment it means something, and not before."""
    mid = slate["mission"]["id"]
    assert client.post(f"/api/missions/{mid}/accept?minutes=45").status_code == 401


# ------------------------------------------------------------------- the slider
def test_options_match_the_service_bounds(client):
    o = client.get("/api/missions/options").json()
    assert (o["min_minutes"], o["max_minutes"], o["step_minutes"]) == (20, 90, 5)
    assert o["pace_mph"] == svc.DEFAULT_PACE_MPH
    assert "estimate" in o["pace_note"].lower()


@pytest.mark.parametrize("asked,expected", [
    (5, 20), (19, 20), (20, 20), (22, 20), (23, 25), (45, 45), (88, 90), (240, 90),
])
def test_minutes_are_clamped_and_snapped(asked, expected):
    assert svc.clamp_minutes(asked) == expected


def test_the_walk_offered_is_near_the_time_asked_for(client):
    """A 30-minute ask must not come back as an hour.

    The engine targets a distance, not a duration, and a route that closes on the
    network will overshoot or undershoot. The tolerance below is what the product
    promises by saying "about": generous, but bounded.
    """
    for minutes in (25, 45, 75):
        m = client.get(f"/api/missions/recommend?minutes={minutes}").json()["mission"]
        assert m is not None, f"no mission at {minutes} min"
        assert abs(m["estimated_minutes"] - minutes) <= max(10, 0.35 * minutes), \
            f"asked {minutes}, offered {m['estimated_minutes']}"


def test_longer_time_offers_a_longer_walk(client):
    short = client.get("/api/missions/recommend?minutes=25").json()["mission"]
    long_ = client.get("/api/missions/recommend?minutes=80").json()["mission"]
    assert long_["distance_miles"] > short["distance_miles"]


# -------------------------------------------------------------------- wording
def test_no_forbidden_words_anywhere_on_the_card(slate):
    blob = " ".join(str(slate["mission"][k]) for k in
                    ("title", "households_line", "area")
                    if slate["mission"].get(k))
    blob += " " + slate["mission"]["start"]["description"]
    for pattern in FORBIDDEN_PHRASES:
        assert not re.search(pattern, blob, re.I), f"{pattern!r} appears in: {blob}"


def test_start_is_described_as_a_place_not_as_parking(slate):
    d = slate["mission"]["start"]["description"]
    assert d and d != "the start of the route"
    assert not re.search(r"\bpark", d, re.I)


def test_households_line_never_reads_zero(client):
    """Priority 8: a campus route with no homes needs different words, not a zero."""
    for minutes in range(20, 95, 5):
        r = client.get(f"/api/missions/recommend?minutes={minutes}").json()
        for m in [r["mission"]] if r["mission"] else []:
            assert "0 households" not in m["households_line"]
            if not m["has_households"]:
                assert "household" not in m["households_line"].lower()


def test_finish_is_only_claimed_when_the_walk_finishes_something(client):
    """Priority 9/10: "Finish the remaining streets in Hethwood" is a promise."""
    for minutes in range(20, 95, 5):
        r = client.get(f"/api/missions/recommend?minutes={minutes}").json()
        m = r["mission"]
        if m and m["title"].lower().startswith("finish"):
            assert m["completes_area"] is True


def test_area_names_are_real_neighbourhoods_not_identifiers(client):
    """Priority 9: neighbourhoods are narrative. Never "cluster 7" or "component 3"."""
    seen = set()
    for minutes in range(20, 95, 5):
        m = client.get(f"/api/missions/recommend?minutes={minutes}").json()["mission"]
        if m and m["area"]:
            seen.add(m["area"])
    assert seen, "no mission carried a neighbourhood name"
    for name in seen:
        assert not re.fullmatch(r"[A-Z]*[-_ ]?\d+", name), name
        assert name[0].isupper(), name


# ------------------------------------------------------------------ no leakage
def test_no_engineering_metrics_reach_the_browser(slate):
    """Priority 8. The optimiser's numbers are real and stay on the server."""
    leaked = LEAKY_KEYS & set(slate["mission"])
    assert not leaked, f"engineering fields on the mission payload: {leaked}"


def test_no_raw_addresses_or_household_points_reach_the_browser(slate):
    """The standing privacy rule: aggregate household counts only."""
    m = slate["mission"]
    assert isinstance(m["households"], int)
    assert "addresses" not in m and "household_points" not in m
    # Geometry is the route line. Nothing else carries coordinates.
    assert m["geometry"]["type"] == "LineString"


# --------------------------------------------------------- simultaneous walkers
def test_the_slate_offers_several_genuinely_different_walks(slate):
    """Priority 10: five people asking at once must not be sent the same street."""
    assert slate["slate_size"] >= 3, slate["slate_size"]
    assert len(slate["alternatives"]) == slate["slate_size"] - 1
    titles = {slate["mission"]["title"], *(a["title"] for a in slate["alternatives"])}
    assert len(titles) >= 2, "the slate is one walk described several ways"


def test_different_people_are_given_different_walks(client):
    """The recommendation is deterministic per person and spread across the slate."""
    chosen = set()
    for i in range(6):
        p = register(client, f"slate{i}@example.com", "Slate", str(i))
        r = client.get("/api/missions/recommend?minutes=45", headers=auth(p["token"]))
        chosen.add(r.json()["mission"]["id"])
    assert len(chosen) >= 2, "everybody was given the identical walk"


def test_the_slate_cache_distinguishes_different_sets_of_holds():
    """Two different sets of held streets must not share a cached slate."""
    a = svc._reserved_fingerprint({1, 2, 3})
    b = svc._reserved_fingerprint({4, 5, 6})
    assert a != b
    assert a == svc._reserved_fingerprint({3, 2, 1}), "order must not matter"
    assert svc._reserved_fingerprint(set()) == svc._reserved_fingerprint(None)


def test_the_same_person_is_given_a_stable_walk(client):
    """Refreshing the page must not reshuffle the recommendation."""
    p = register(client, "stable@example.com", "Stable", "Walker")
    ids = {client.get("/api/missions/recommend?minutes=45",
                      headers=auth(p["token"])).json()["mission"]["id"]
           for _ in range(3)}
    assert len(ids) == 1


# --------------------------------------------------------------- accept → walk
def test_accepting_a_mission_produces_an_ordinary_walk(client):
    p = register(client, "accepts@example.com", "Ann", "Accepts")
    h = auth(p["token"])
    m = client.get("/api/missions/recommend?minutes=40", headers=h).json()["mission"]

    r = client.post(f"/api/missions/{m['id']}/accept?minutes=40", headers=h)
    assert r.status_code == 200, r.text
    walk_id = r.json()["walk_id"]

    w = client.get(f"/api/walks/{walk_id}", headers=h).json()
    assert w["status"] == "PREVIEW"
    assert w["distance_miles"] == m["distance_miles"]
    # The mission's required streets are held so nobody else is sent them.
    assert set(w["planned_required_ids"]) == set(m["required_segment_ids"])

    # And the existing machinery downstream still works unchanged.
    assert client.post(f"/api/walks/{walk_id}/start", headers=h).status_code == 200
    done = client.post(f"/api/walks/{walk_id}/complete", headers=h,
                       json=dict(outcome="AS_PLANNED"))
    assert done.status_code == 200, done.text
    assert done.json()["segments_newly_recorded"] > 0


def test_a_second_walk_is_refused_while_one_is_active(client):
    p = register(client, "twowalks@example.com", "Two", "Walks")
    h = auth(p["token"])
    m = client.get("/api/missions/recommend?minutes=30", headers=h).json()["mission"]
    first = client.post(f"/api/missions/{m['id']}/accept?minutes=30", headers=h).json()
    client.post(f"/api/walks/{first['walk_id']}/start", headers=h)

    again = client.get("/api/missions/recommend?minutes=30", headers=h).json()["mission"]
    r = client.post(f"/api/missions/{again['id']}/accept?minutes=30", headers=h)
    assert r.status_code == 409
    assert "in progress" in r.json()["detail"]


def test_a_stale_mission_id_is_refused_with_an_explanation(client):
    p = register(client, "stale@example.com", "Stale", "Mission")
    h = auth(p["token"])
    r = client.post("/api/missions/mission-that-never-was/accept?minutes=45", headers=h)
    assert r.status_code == 409
    assert "no longer available" in r.json()["detail"]


# --------------------------------------------------------------- directions out
def test_directions_point_at_the_start_and_nowhere_else(slate):
    """Priority 6: an external link to the start point only."""
    d = slate["mission"]["directions"]
    start = slate["mission"]["start"]
    for url in (d["apple"], d["google"], d["geo"]):
        assert f"{start['lat']:.6f}" in url and f"{start['lon']:.6f}" in url
    assert d["apple"].startswith("https://maps.apple.com/")
    assert d["google"].startswith("https://www.google.com/maps/dir/")
    assert d["geo"].startswith("geo:")


# ------------------------------------------------------------------- the cache
def test_the_slate_cache_is_dropped_when_the_town_moves(client):
    """A recommendation must never survive the completion that invalidates it."""
    p = register(client, "invalidates@example.com", "Cache", "Buster")
    h = auth(p["token"])
    before = client.get("/api/missions/recommend?minutes=35", headers=h).json()

    accepted = client.post(
        f"/api/missions/{before['mission']['id']}/accept?minutes=35", headers=h).json()
    client.post(f"/api/walks/{accepted['walk_id']}/start", headers=h)
    client.post(f"/api/walks/{accepted['walk_id']}/complete", headers=h,
                json=dict(outcome="AS_PLANNED"))

    after = client.get("/api/missions/recommend?minutes=35", headers=h).json()
    walked = set(before["mission"]["required_segment_ids"])
    still_offered = walked & set(after["mission"]["required_segment_ids"])
    assert not still_offered, "streets already prayed for were recommended again"
