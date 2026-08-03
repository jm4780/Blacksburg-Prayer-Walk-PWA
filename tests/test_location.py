"""Location and small-component matrix (§20).

Permission granted and denied are browser-side and covered in `web/e2e/slice.mjs`;
what the server can be held to is what it does with the point it is handed. These are
the awkward starts: a parking lot, a spot between two valid components, inside the
Corporate Research Center, and on a component too small to support the Quick band.
"""
from __future__ import annotations

import pytest

from .conftest import CRC, DOWNTOWN, auth, register

BANDS = ("Quick", "Short", "Medium", "Long", "Extended")


@pytest.fixture(scope="module")
def h(client):
    return auth(register(client, "walker-location@example.com")["token"])


def generate(client, h, lat, lon, **kw):
    return client.post("/api/routes/generate",
                       json=dict(lat=lat, lon=lon, **kw), headers=h)


def test_start_snaps_to_a_public_walking_node(client, h, ns):
    """A parking lot has no centreline, so the start must land on the nearest public
    walking node rather than failing or snapping to nothing."""
    # Middle of a large surface lot behind the downtown block.
    r = generate(client, h, 37.2288, -80.4155).json()
    assert r["component"] is not None
    node = r["variants"][0]["start_point"] if r["variants"] else None
    assert r["coverage_area_id"], "no coverage area resolved for a lot start"
    # Whatever it snapped to has to be a node the router will actually route from.
    assert ns.engine.component_of_node.get(
        ns.engine.g.node_index.get(
            next(s.u for s in ns.net.segments), -1)) is not None or node is None


def test_start_never_snaps_into_an_invalid_component(client, h, ns):
    """Start snapping is restricted to components a walk can legitimately begin in."""
    for lat, lon in ((37.2296, -80.4139), (37.2010, -80.4069), (37.2380, -80.4460)):
        r = generate(client, h, lat, lon).json()
        comp = r["component"]
        assert comp is not None
        assert comp["classification"] == "VALID_INDEPENDENT_ROUTING_AREA", \
            f"{lat},{lon} snapped into {comp['classification']}"


def test_start_inside_the_corporate_research_center(client, h):
    r = generate(client, h, CRC["lat"], CRC["lon"]).json()
    assert "Research Center" in r["component"]["description"]
    assert r["coverage_area_id"] == f"comp-{r['component']['index']}"
    # The CRC is a valid area with real work in it, so something must be offered.
    assert r["available_bands"], "no route offered inside the CRC"


def test_start_near_multiple_components_picks_one_and_stays_in_it(client, h, ns):
    """Prices Fork Rd runs between the main network and the campus corridors, which
    v1.2 leaves in separate components. A start there must commit to one."""
    r = generate(client, h, 37.2295, -80.4310).json()
    ci = r["component"]["index"]
    for v in r["variants"]:
        for sid in v["segment_ids"]:
            seg = ns.net.segments[ns.idx_of_id[sid]]
            node = ns.engine.g.node_index.get(seg.u)
            assert ns.engine.component_of_node.get(node) == ci


def test_tiny_component_offers_complete_this_area(client, h, ns):
    """§9: a component below the Quick band gets a focused option, not a sixth size."""
    small = [c for c in ns.components
             if c.classification == "VALID_INDEPENDENT_ROUTING_AREA"
             and 0.2 < c.required_miles < 1.0]
    assert small, "no sub-Quick valid component in the network to test against"
    c = small[0]
    seg = next(ns.net.segments[i] for i in c.segment_indices
               if ns.net.segments[i].required and ns.net.segments[i].coords)
    lon, lat = seg.coords[len(seg.coords) // 2]

    r = generate(client, h, lat, lon).json()
    comp = r["component"]
    assert comp["required_miles"] < 1.0
    assert comp["complete_area_miles"] is not None, \
        "small component did not advertise a complete-this-area distance"
    assert r["available_bands"], "small component offered nothing at all"


def test_no_useful_route_state_is_structured_not_padded(client, h, ns):
    """§9/§10: when there is nothing worth walking, say so — do not inflate a route."""
    from api.app.services.network_state import network_service
    from api.routing.state import CompletionState

    ns2 = network_service()
    # Everything complete: there is nothing left anywhere.
    everything = CompletionState(ns2.net, {s.idx for s in ns2.net.segments if s.required})
    eng = ns2.engine_with_seed(7)
    start = eng.snap(DOWNTOWN["lon"], DOWNTOWN["lat"])
    out = eng.variants(start, everything)
    for v in out:
        assert v.get("route") is None
        assert v["response"].state in {
            "NO_USEFUL_ROUTE_NEAR_START", "SELECT_DIFFERENT_START_AREA",
            "LONGER_ROUTE_REQUIRED"}
        assert v["response"].reason


def test_coverage_area_and_state_version_are_recorded(client, h):
    """§7: both are resolved server-side and stored, so a route is reproducible."""
    from sqlalchemy import select

    from api.app.db import SessionLocal
    from api.app.models import RouteRequest

    r = generate(client, h, DOWNTOWN["lat"], DOWNTOWN["lon"]).json()
    assert r["coverage_area_id"]
    assert r["completion_state_version"].startswith("cs-")
    with SessionLocal() as db:
        row = db.get(RouteRequest, r["request_id"])
    assert row.coverage_area_id == r["coverage_area_id"]
    assert row.completion_state_version == r["completion_state_version"]


def test_requested_family_narrows_the_response(client, h):
    r = generate(client, h, DOWNTOWN["lat"], DOWNTOWN["lon"],
                 requested_family="Medium").json()
    assert [v["band"] for v in r["variants"]] == ["Medium"]


def test_variants_carry_the_versions_that_produced_them(client, h):
    r = generate(client, h, DOWNTOWN["lat"], DOWNTOWN["lon"]).json()
    for v in r["variants"]:
        assert v["network_version"] == "v1.2"
        assert v["engine_version"] == r["engine_version"]
        assert v["seed"] == r["seed"]
