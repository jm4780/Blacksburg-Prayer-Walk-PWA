"""Routing and location matrix (§20).

Covers: device-location start, map-selected start, out-of-area start, missing start,
determinism under a fixed seed, diversity across seeds, nesting, unavailable bands,
independent components, and the late-opportunity states.
"""
from __future__ import annotations

import pytest

from .conftest import CRC, DOWNTOWN, auth, register

STATES = {"ROUTE_AVAILABLE", "LIMITED_LOCAL_COVERAGE", "LONGER_ROUTE_REQUIRED",
          "NO_USEFUL_ROUTE_NEAR_START", "SELECT_DIFFERENT_START_AREA"}


@pytest.fixture(scope="module")
def h(client):
    return auth(register(client, "router@example.com")["token"])


@pytest.fixture(scope="module")
def downtown(client, h):
    return client.post("/api/routes/generate", json=DOWNTOWN, headers=h).json()


# ---------------------------------------------------------------- start points
def test_device_location_start(client, h):
    r = client.post("/api/routes/generate",
                    json={**DOWNTOWN, "start_source": "DEVICE_LOCATION"}, headers=h)
    assert r.status_code == 200
    assert r.json()["available_bands"]


def test_map_selected_start(client, h):
    r = client.post("/api/routes/generate",
                    json={**DOWNTOWN, "start_source": "MAP"}, headers=h)
    assert r.status_code == 200


def test_missing_start_is_rejected(client, h):
    r = client.post("/api/routes/generate", json={}, headers=h)
    assert r.status_code == 422
    assert "start point" in r.json()["detail"]


@pytest.mark.parametrize("pt", [
    dict(lat=40.7128, lon=-74.0060),      # New York
    dict(lat=37.2296, lon=-100.0),        # far west
    dict(lat=0.0, lon=0.0),               # null island
])
def test_start_outside_blacksburg_is_rejected(client, h, pt):
    assert client.post("/api/routes/generate", json=pt, headers=h).status_code == 422


def test_route_generation_requires_authentication(client):
    assert client.post("/api/routes/generate", json=DOWNTOWN).status_code == 401


# ------------------------------------------------------- determinism, diversity
def test_same_seed_reproduces_the_same_routes(client, h, downtown):
    again = client.post("/api/routes/generate",
                        json={**DOWNTOWN, "seed": downtown["seed"]}, headers=h).json()
    a = {v["band"]: v["segment_ids"] for v in downtown["variants"]}
    b = {v["band"]: v["segment_ids"] for v in again["variants"]}
    assert a == b, "a stored seed must regenerate the identical route"


def test_different_seeds_give_different_routes(client, h):
    """§11: two walkers on the same corner should not get identical walks."""
    seen = set()
    for seed in (11, 22, 33, 44):
        r = client.post("/api/routes/generate", json={**DOWNTOWN, "seed": seed},
                        headers=h).json()
        med = next(v for v in r["variants"] if v["band"] == "Medium")
        seen.add(tuple(med["segment_ids"]))
    assert len(seen) > 1, "seeds produced no route diversity at all"


def test_diversity_stays_within_quality_tolerance(client, h):
    """Diversity may change which good route you get, never what counts as good."""
    quality = []
    for seed in (11, 22, 33, 44):
        r = client.post("/api/routes/generate", json={**DOWNTOWN, "seed": seed},
                        headers=h).json()
        med = next(v for v in r["variants"] if v["band"] == "Medium")
        if med["available"]:
            quality.append(med["new_required_miles"])
    assert quality
    assert min(quality) >= 0.6 * max(quality), \
        f"seed choice swung new coverage too far: {quality}"


# ------------------------------------------------------------------- structure
def test_five_bands_always_reported(client, downtown):
    assert [v["band"] for v in downtown["variants"]] == \
        ["Quick", "Short", "Medium", "Long", "Extended"]


def test_unavailable_bands_carry_a_reason(client, h):
    r = client.post("/api/routes/generate", json=CRC, headers=h).json()
    for v in r["variants"]:
        if not v["available"]:
            assert v["reason"], f"{v['band']} unavailable with no reason given"


def test_variants_nest_on_required_coverage(client, downtown):
    prev = None
    for v in downtown["variants"]:
        if not v["available"] or not v.get("nests_within_shorter"):
            prev = set(v["required_segment_ids"]) if v["available"] else prev
            continue
        cur = set(v["required_segment_ids"])
        if prev is not None:
            assert prev <= cur, f"{v['band']} dropped coverage from the shorter band"
        prev = cur


def test_distance_is_within_tolerance_of_the_target(client, downtown):
    for v in downtown["variants"]:
        if v["available"]:
            assert v["distance_miles"] <= v["target_miles"] * 1.12, \
                f"{v['band']} overshot: {v['distance_miles']} vs {v['target_miles']}"


def test_every_variant_reports_the_documented_fields(client, downtown):
    required = {
        "band", "target_miles", "available", "state", "reason", "distance_miles",
        "estimated_minutes", "new_required_miles", "repeated_miles", "efficiency",
        "households", "walk_quality", "dead_end_returns_miles", "closing_leg_miles",
        "segment_count", "required_segment_count", "nests_within_shorter",
        "component", "score_components", "campus_credited_miles", "segment_ids",
        "required_segment_ids", "geometry",
    }
    for v in downtown["variants"]:
        assert required <= set(v), f"missing {required - set(v)}"


def test_response_names_the_network_and_engine(client, downtown):
    assert downtown["network_version"] == "v1.2"
    assert downtown["network_id"].startswith("bbg-net-v1.2-")
    assert downtown["engine_version"] == "2.1.0"


# ------------------------------------------------------------------ components
def test_crc_routes_within_its_own_component(client, h, ns):
    r = client.post("/api/routes/generate", json=CRC, headers=h).json()
    comp = r["component"]
    assert comp is not None
    assert comp["classification"] == "VALID_INDEPENDENT_ROUTING_AREA"
    assert "Research Center" in comp["description"]
    # Nothing the router offers may leave the component it started in.
    for v in r["variants"]:
        for sid in v["segment_ids"]:
            idx = ns.idx_of_id[sid]
            seg = ns.net.segments[idx]
            node = ns.engine.g.node_index.get(seg.u)
            assert ns.engine.component_of_node.get(node) == comp["index"], \
                "the router crossed between components"


def test_response_state_is_one_of_the_five(client, downtown):
    assert downtown["state"] in STATES
    for v in downtown["variants"]:
        assert v["state"] in STATES
