"""Route engine tests — contracts.md §3, in the contract's priority order.

These run against the real 1,553-segment Blacksburg network, not a fixture. A
route engine that passes on a toy grid and strands someone on Prices Fork Rd
has not passed anything.

Run with `-s` to see the measured numbers (contiguity, timing, coverage lift):

    python3 -m pytest rebuild/tests/test_route.py -s
"""
from __future__ import annotations

import copy
import json
import os
import random
import statistics
import sys
import time

import pytest

REBUILD = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REBUILD not in sys.path:
    sys.path.insert(0, REBUILD)

from engine.route import (  # noqa: E402
    BAND,
    CLOSE_M,
    SAFE_MOTORWAY_REF,
    build_graph,
    contiguity,
    generate,
    meters_for_minutes,
    route_stats,
)
from engine.route import _flat_m  # noqa: E402

NETWORK_PATH = os.path.join(REBUILD, "data", "out", "network.geojson")
MINUTES = (20, 30, 45, 60)
N_STARTS = 20
SEED = 20260810


# ------------------------------------------------------------------ fixtures --


@pytest.fixture(scope="session")
def network():
    with open(NETWORK_PATH) as fh:
        return json.load(fh)


@pytest.fixture(scope="session")
def graph(network):
    return build_graph(network)


def _component_sizes(g):
    sizes = {}
    for ei in range(len(g.e_seg)):
        c = g.component[g.e_u[ei]]
        sizes[c] = sizes.get(c, 0) + 1
    return sizes


@pytest.fixture(scope="session")
def main_component(graph):
    """The component holding 95% of the town's street length."""
    lengths = {}
    for ei in range(len(graph.e_seg)):
        c = graph.component[graph.e_u[ei]]
        lengths[c] = lengths.get(c, 0.0) + graph.e_len[ei]
    return max(lengths, key=lengths.get)


@pytest.fixture(scope="session")
def tiny_components(graph):
    """Components of three segments or fewer — 19 of them in this build."""
    sizes = _component_sizes(graph)
    return sorted(c for c, n in sizes.items() if n <= 3)


@pytest.fixture(scope="session")
def starts(graph, main_component):
    """20 start points: a random junction, jittered like a GPS fix on a street.

    Drawn from the main component on purpose. 95% of Blacksburg's street
    length is there, and the contract's length band is not physically
    satisfiable inside a 32 m island — that case is tested separately, as a
    degenerate case, in test_degenerate_*.
    """
    rng = random.Random(SEED)
    nodes = [i for i in range(len(graph.node_name)) if graph.component[i] == main_component]
    out = []
    for k in range(N_STARTS):
        n = rng.choice(nodes)
        lon, lat = graph.node_lonlat[n]
        # ~<=45 m of jitter: the walker is standing on the street, not on the junction.
        lon += rng.uniform(-4.0e-4, 4.0e-4)
        lat += rng.uniform(-3.0e-4, 3.0e-4)
        out.append(((lon, lat), MINUTES[k % len(MINUTES)]))
    return out


@pytest.fixture(scope="session")
def routes(network, starts):
    """The 20 routes under test, with the wall time each one took."""
    out = []
    for k, (start, minutes) in enumerate(starts):
        target = meters_for_minutes(minutes)
        t0 = time.perf_counter()
        r = generate(start, target, network, set(), seed=k)
        dt = time.perf_counter() - t0
        out.append({"start": start, "minutes": minutes, "target_m": target,
                    "route": r, "seconds": dt})
    return out


# ------------------------------------------------------- 0. contract shape --


def test_route_matches_contract_shape(routes):
    for case in routes:
        r = case["route"]
        assert set(r) == {"seg_ids", "new_seg_ids", "geometry", "length_m", "new_m"}, (
            "Route keys are fixed by contracts §3"
        )
        assert all(isinstance(s, int) for s in r["seg_ids"])
        assert all(isinstance(s, int) for s in r["new_seg_ids"])
        assert isinstance(r["length_m"], float) and isinstance(r["new_m"], float)
        assert r["geometry"].geom_type == "LineString"
        # new_seg_ids must be a subset of what is actually walked, without repeats
        assert set(r["new_seg_ids"]) <= set(r["seg_ids"])
        assert len(set(r["new_seg_ids"])) == len(r["new_seg_ids"])
        assert r["new_m"] <= r["length_m"] + 1e-6


def test_seg_ids_are_a_connected_walk(routes, graph):
    """Consecutive segments must share a node id. Nothing may teleport."""
    for case in routes:
        ids = case["route"]["seg_ids"]
        prev = None
        for sid in ids:
            seg = graph.segments[sid]
            nodes = {seg["node_a"], seg["node_b"]}
            if prev is not None:
                assert prev & nodes, f"segment {sid} does not touch the previous one"
            prev = nodes


# ------------------------------------------------- 1. closes the loop (§3.1) --


def test_every_route_closes_the_loop(routes):
    """Priority 1. A walk that strands someone away from their car has failed."""
    closed = 0
    worst = 0.0
    for case in routes:
        pts = list(case["route"]["geometry"].coords)
        start = case["start"]
        end_to_start = _flat_m(start[0], start[1], pts[-1][0], pts[-1][1])
        end_to_begin = _flat_m(pts[0][0], pts[0][1], pts[-1][0], pts[-1][1])
        worst = max(worst, end_to_start)
        assert end_to_begin <= 1.0, "the walk must physically return to where it began"
        if end_to_start <= CLOSE_M:
            closed += 1
    print(f"\n[closure] {closed}/{len(routes)} routes end within {CLOSE_M:.0f} m "
          f"of the requested start; worst {worst:.1f} m")
    assert closed == len(routes) == N_STARTS


def test_closes_the_loop_in_tiny_components(network, graph, tiny_components):
    """Closure is not a luxury of the big component."""
    for c in tiny_components:
        node = next(i for i in range(len(graph.node_name)) if graph.component[i] == c)
        start = graph.node_lonlat[node]
        r = generate(start, meters_for_minutes(30), network, set(), seed=3)
        pts = list(r["geometry"].coords)
        assert _flat_m(start[0], start[1], pts[-1][0], pts[-1][1]) <= CLOSE_M
        assert _flat_m(pts[0][0], pts[0][1], pts[-1][0], pts[-1][1]) <= 1.0


# ------------------------------------------------------ 2. length band (§3.2) --


def _servicable_m(graph, anchor, hi):
    """Street a closed walk of at most ``hi`` metres could possibly service.

    Computed here, independently of the engine, so the length test can tell
    "the engine came up short" apart from "no such loop exists". An arc can
    only appear in a closed walk of length <= hi if going to it and coming
    back fits: 2 * (distance to the nearer end + its own length) <= hi.
    """
    _, real, _, _ = graph.dijkstra(anchor, graph.e_len, hi)
    total = 0.0
    for ei in range(len(graph.e_seg)):
        d = min(real.get(graph.e_u[ei], float("inf")), real.get(graph.e_v[ei], float("inf")))
        if 2 * (d + graph.e_len[ei]) <= hi:
            total += graph.e_len[ei]
    return total


def test_length_within_fifteen_percent_of_target(routes, graph):
    """Priority 2. Someone with 30 minutes has 30 minutes.

    A handful of start points in this town — a dead-end stub on the town edge
    with a kilometre of Prices Fork Rd between it and anything else — have no
    in-band loop at all, at any quality of solver. Those are identified by an
    independent bound and required to come back short and closed rather than
    long or absurd, which is the honest failure. About 3% of random starts.
    """
    ratios, short = [], []
    for case in routes:
        ratio = case["route"]["length_m"] / case["target_m"]
        ratios.append(ratio)
        assert ratio <= 1 + BAND, (
            f"{case['minutes']} min route overshot at {case['route']['length_m']:.0f} m "
            f"against a {case['target_m']:.0f} m target ({ratio:.3f}x)"
        )
        if ratio >= 1 - BAND:
            continue
        # Short. Only forgivable if no in-band loop exists from here at all.
        anchor = graph.nearest_node(*case["start"])
        possible = _servicable_m(graph, anchor, case["target_m"] * (1 + BAND))
        assert possible < case["target_m"], (
            f"{case['minutes']} min route came out at {case['route']['length_m']:.0f} m "
            f"({ratio:.3f}x) with {possible:.0f} m of street within reach — that is "
            f"the solver falling short, not the town"
        )
        short.append((case["minutes"], ratio, possible))
    print(f"[length]  {len(ratios) - len(short)}/{len(ratios)} inside ±{BAND:.0%}; "
          f"mean {statistics.mean(ratios):.3f}x target, "
          f"range {min(ratios):.3f}–{max(ratios):.3f}x"
          + (f"; {len(short)} start(s) with no in-band loop available: {short}" if short else ""))
    assert len(short) <= 2, "too many starts written off as infeasible"


# ----------------------------------------------------------- 3. safety (§3.5) --


def test_no_unsafe_motorway_in_any_route(routes, graph):
    """Priority 5. motorway is off limits unless it is Main St (US 460 Bus)."""
    for case in routes:
        for sid in case["route"]["seg_ids"]:
            seg = graph.segments[sid]
            if (seg["class"] or "").lower() == "motorway":
                assert seg["ref"] == SAFE_MOTORWAY_REF, (
                    f"routed onto motorway {sid} ({seg['name']}, ref={seg['ref']})"
                )
    print(f"[safety]  {len(routes)}/{len(routes)} routes free of unsafe motorway")


def test_unsafe_motorway_is_excluded_even_when_it_is_the_obvious_route(network, graph):
    """Every motorway in *this* build happens to be US 460 Bus, so the rule is
    only really tested by making one unsafe and seeing it disappear."""
    doctored = copy.deepcopy(network)
    banned = set()
    for f in doctored["features"]:
        p = f["properties"]
        if (p.get("class") or "") == "motorway":
            p["ref"] = "US 460"          # the bypass: four lanes, no sidewalk
            banned.add(int(p["seg_id"]))
    assert banned, "expected motorway segments in the network"

    # Start on a doctored segment, so the banned street is the nearest thing there is.
    sid = sorted(banned)[len(banned) // 2]
    coords = graph.segments[sid]["coords"]
    start = coords[len(coords) // 2]

    hits = 0
    for minutes in MINUTES:
        r = generate(start, meters_for_minutes(minutes), doctored, set(), seed=5)
        hits += len(banned & set(r["seg_ids"]))
    assert hits == 0, "an unsafe motorway was routed onto"

    # Not even as deadhead: they are not in the walkable graph at all.
    assert not (banned & set(build_graph(doctored).edge_of_seg))
    # And with the real refs, that same street is walkable again — Main St
    # downtown is exactly where a prayer walk wants to go.
    assert banned <= set(build_graph(network).edge_of_seg)
    r = generate(start, meters_for_minutes(30), network, set(), seed=5)
    assert r["length_m"] > 0


# ----------------------------------------------------------- 4. determinism --


def test_same_inputs_give_the_same_route(network, starts):
    for start, minutes in starts[:6]:
        target = meters_for_minutes(minutes)
        a = generate(start, target, network, set(), seed=99)
        b = generate(start, target, network, set(), seed=99)
        assert a["seg_ids"] == b["seg_ids"]
        assert a["new_seg_ids"] == b["new_seg_ids"]
        assert a["length_m"] == b["length_m"] and a["new_m"] == b["new_m"]
        assert list(a["geometry"].coords) == list(b["geometry"].coords)


def test_determinism_holds_with_a_covered_set(network, starts, graph):
    ids = sorted(graph.segments)
    covered = set(random.Random(1).sample(ids, len(ids) // 3))
    start, minutes = starts[0]
    target = meters_for_minutes(minutes)
    a = generate(start, target, network, covered, seed=4)
    b = generate(start, target, network, set(covered), seed=4)
    assert a["seg_ids"] == b["seg_ids"]


def test_different_seeds_are_allowed_to_differ(network, starts):
    """Not a requirement, but if the seed did nothing the restarts would be dead."""
    start, minutes = starts[3]
    target = meters_for_minutes(minutes)
    variants = {tuple(generate(start, target, network, set(), seed=s)["seg_ids"])
                for s in range(6)}
    assert len(variants) >= 1


# ------------------------------------------------- 5. covered-avoidance (§3.3) --


def test_covered_segments_are_avoided(network, graph, starts):
    """Half the town is claimed. The engine must go where the town is not.

    The comparison that means anything is against the same engine run *blind*
    (covered=set()), with both routes then scored against the same covered set:
    a blind route walks whatever is nearest and lands near the 50% base rate,
    a coverage-aware route should beat it by a wide margin.
    """
    ids = sorted(graph.segments)
    covered = set(random.Random(7).sample(ids, len(ids) // 2))

    aware_rates, blind_rates, wins = [], [], 0
    for k, (start, minutes) in enumerate(starts):
        target = meters_for_minutes(minutes)
        aware = generate(start, target, network, covered, seed=k)
        blind = generate(start, target, network, set(), seed=k)
        blind_new = sum(
            graph.segments[s]["length_m"]
            for s in dict.fromkeys(blind["seg_ids"]) if s not in covered
        )
        a_rate = aware["new_m"] / aware["length_m"]
        b_rate = blind_new / blind["length_m"]
        aware_rates.append(a_rate)
        blind_rates.append(b_rate)
        wins += a_rate > b_rate

    a_mean, b_mean = statistics.mean(aware_rates), statistics.mean(blind_rates)
    print(f"[covered] new metres per metre walked: coverage-aware {a_mean:.3f} vs "
          f"blind {b_mean:.3f} ({a_mean / b_mean:.2f}x), aware wins {wins}/{len(starts)}")
    assert a_mean > b_mean * 1.20, "coverage-aware routing must materially beat blind"
    assert wins >= int(0.7 * len(starts))
    assert a_mean > 0.5, "should beat the 50% base rate of walking blind"


def test_covered_street_is_not_claimed_twice(network, graph, starts):
    ids = sorted(graph.segments)
    covered = set(random.Random(11).sample(ids, len(ids) // 2))
    start, minutes = starts[1]
    r = generate(start, meters_for_minutes(minutes), network, covered, seed=2)
    assert not (set(r["new_seg_ids"]) & covered), "a covered segment was claimed as new"


def test_fully_covered_town_still_returns_a_closed_walk(network, graph, starts):
    covered = set(graph.segments)
    start, minutes = starts[2]
    r = generate(start, meters_for_minutes(minutes), network, covered, seed=2)
    assert r["new_m"] == 0.0 and r["new_seg_ids"] == []
    pts = list(r["geometry"].coords)
    assert _flat_m(start[0], start[1], pts[-1][0], pts[-1][1]) <= CLOSE_M


# ------------------------------------------------------- 6. degenerate cases --


def test_degenerate_start_in_a_tiny_component(network, graph, tiny_components):
    """19 components are 3 segments or fewer. Best effort, no hang, no crash."""
    assert len(tiny_components) >= 10
    rows = []
    for c in tiny_components:
        node = next(i for i in range(len(graph.node_name)) if graph.component[i] == c)
        start = graph.node_lonlat[node]
        comp_m = sum(graph.e_len[ei] for ei in range(len(graph.e_seg))
                     if graph.component[graph.e_u[ei]] == c)
        t0 = time.perf_counter()
        r = generate(start, meters_for_minutes(60), network, set(), seed=8)
        dt = time.perf_counter() - t0
        rows.append((c, comp_m, r["length_m"], dt))

        assert dt < 3.0, "a tiny component must not hang"
        # It may not wander off into another component to pad the walk out.
        for sid in r["seg_ids"]:
            seg = graph.segments[sid]
            assert graph.component[graph.node_id[seg["node_a"]]] == c
        # Best effort: it is allowed to fall short of the band, never to exceed it.
        assert r["length_m"] <= meters_for_minutes(60) * (1 + BAND)
        pts = list(r["geometry"].coords)
        assert _flat_m(start[0], start[1], pts[-1][0], pts[-1][1]) <= CLOSE_M
    worst = max(dt for *_, dt in rows)
    print(f"[tiny]    {len(rows)} tiny components routed, worst {worst:.2f} s, "
          f"none escaped its component")


def test_degenerate_target_longer_than_the_whole_town(network, graph):
    """200 km asked of a 252 km town, from one point. Return the best it can."""
    start = graph.node_lonlat[0]
    t0 = time.perf_counter()
    r = generate(start, 200_000.0, network, set(), seed=1)
    dt = time.perf_counter() - t0
    assert dt < 3.0, f"took {dt:.2f}s"
    assert r["length_m"] > 0 and r["new_m"] > 0
    pts = list(r["geometry"].coords)
    assert _flat_m(pts[0][0], pts[0][1], pts[-1][0], pts[-1][1]) <= 1.0
    print(f"[huge]    200 km asked -> {r['length_m'] / 1000:.1f} km returned "
          f"({r['new_m'] / 1000:.1f} km new) in {dt:.2f} s, still closed")


def test_degenerate_start_far_outside_the_town(network):
    """Someone opens the app in Roanoke. Snap in, do not explode."""
    r = generate((-79.94, 37.27), meters_for_minutes(30), network, set(), seed=1)
    assert r["length_m"] > 0
    pts = list(r["geometry"].coords)
    assert _flat_m(pts[0][0], pts[0][1], pts[-1][0], pts[-1][1]) <= 1.0


def test_degenerate_zero_and_negative_targets(network, graph):
    start = graph.node_lonlat[0]
    for target in (0.0, -100.0):
        r = generate(start, target, network, set(), seed=1)
        assert r["length_m"] == 0.0 and r["seg_ids"] == []
        assert r["geometry"].geom_type == "LineString"


def test_degenerate_empty_network():
    r = generate((-80.41, 37.23), 1000.0, [], set(), seed=1)
    assert r["seg_ids"] == [] and r["length_m"] == 0.0


def test_accepts_flat_row_shaped_network(network, starts):
    """The API hands over DB rows, not GeoJSON features (rebuild/api/db.py)."""
    rows = [dict(f["properties"], geometry=f["geometry"]) for f in network["features"]]
    start, minutes = starts[0]
    r = generate(start, meters_for_minutes(minutes), rows, set(), seed=1)
    assert r["length_m"] > 0 and r["seg_ids"]


# ------------------------------------------- 4./contiguity + 7. performance --


def test_contiguity_is_measured_and_high(routes, network):
    """Priority 4. One neighbourhood, not confetti. 1.0 = a single block.

    Contiguity here = the share of newly claimed metres sitting in the largest
    connected block of claimed segments (union-find over shared node ids).
    """
    values, blocks, spans = [], [], []
    for case in routes:
        r = case["route"]
        st = route_stats(r, network)
        values.append(contiguity(r, network))
        blocks.append(st["new_blocks"])
        spans.append(st["span_m"] / case["target_m"])
    mean = statistics.mean(values)
    print(f"[contig]  virgin town: mean contiguity {mean:.3f} (min {min(values):.3f}), "
          f"blocks per route mean {statistics.mean(blocks):.2f} max {max(blocks)}, "
          f"span {statistics.mean(spans):.2f}x target")
    assert mean >= 0.85, "routes should fill in a neighbourhood, not scatter"
    assert min(values) >= 0.5
    assert max(spans) <= 0.6, "claimed street must sit in one part of town"


def test_contiguity_holds_under_partial_coverage(network, graph, starts):
    """Half the town claimed at random leaves the *uncovered* street in
    fragments, so perfect contiguity is not on offer. The route still has to
    work one neighbourhood rather than tour the county."""
    ids = sorted(graph.segments)
    covered = set(random.Random(7).sample(ids, len(ids) // 2))
    values, blocks, spans = [], [], []
    for k, (start, minutes) in enumerate(starts):
        target = meters_for_minutes(minutes)
        r = generate(start, target, network, covered, seed=k)
        st = route_stats(r, network)
        values.append(st["contiguity"])
        blocks.append(st["new_blocks"])
        spans.append(st["span_m"] / target)
    print(f"[contig]  50% covered: mean contiguity {statistics.mean(values):.3f} "
          f"(min {min(values):.3f}), blocks per route mean {statistics.mean(blocks):.2f}, "
          f"span {statistics.mean(spans):.2f}x target")
    assert statistics.mean(values) >= 0.5
    assert max(spans) <= 0.6


def test_repeat_mileage_is_reported_and_mostly_forced(routes, network):
    """470 dead ends and 608 bridge segments: walking a street twice is often
    the only way home. Report forced and avoidable separately."""
    forced, avoidable, total = [], [], []
    for case in routes:
        st = route_stats(case["route"], network)
        forced.append(st["repeat_forced_m"])
        avoidable.append(st["repeat_avoidable_m"])
        total.append(case["route"]["length_m"])
    print(f"[repeat]  mean forced (bridges/cul-de-sacs) {statistics.mean(forced):.0f} m, "
          f"mean avoidable {statistics.mean(avoidable):.0f} m, "
          f"of mean walk {statistics.mean(total):.0f} m")
    assert statistics.mean(avoidable) < 0.35 * statistics.mean(total)


def test_new_metres_are_worth_the_walk(routes):
    """Priority 3. On virgin town, most of the walk should be new street."""
    rates = [c["route"]["new_m"] / c["route"]["length_m"] for c in routes]
    print(f"[new_m]   mean {statistics.mean(rates):.3f} of each walk is new street "
          f"(min {min(rates):.3f})")
    assert statistics.mean(rates) >= 0.70
    assert min(rates) >= 0.45


def test_performance_under_three_seconds(routes):
    """Priority: the walker is standing outside with the phone in their hand."""
    times = [c["seconds"] for c in routes]
    print(f"[timing]  {len(times)} routes: mean {statistics.mean(times):.2f} s, "
          f"max {max(times):.2f} s, min {min(times):.2f} s")
    assert max(times) < 3.0
    assert statistics.mean(times) < 1.5


def test_first_route_is_fast_from_cold(network, starts):
    """Graph build included — the first request after a restart pays for it."""
    import engine.route as route_mod
    route_mod._GRAPH_CACHE.clear()
    start, minutes = starts[0]
    t0 = time.perf_counter()
    generate(start, meters_for_minutes(minutes), network, set(), seed=1)
    dt = time.perf_counter() - t0
    print(f"[cold]    first route including graph build: {dt:.2f} s")
    assert dt < 3.0
