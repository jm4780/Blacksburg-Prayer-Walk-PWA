"""Coverage engine tests.

Everything here runs against the real Blacksburg network in
rebuild/data/out/network.geojson (1,598 segments, 156.54 mi). Walks follow real
segment geometry; noise is a correlated (AR(1)) two-dimensional error, which is
what consumer GPS actually does -- white noise averages out over a minute and
would make these tests far easier than reality.

Nothing here hardcodes a `seg_id`. Ids are only stable within one build of the
network, so every fixture is *found at runtime*: the parallel-street cases are
discovered by searching the shipped geometry for the tightest pairs of long,
near-parallel segments that do not share a junction, and walks are grown
through the junction graph from there. A rebuild that renumbers every segment
re-derives the same situations instead of silently testing the wrong streets.

The headline number the component is judged on is measured in
`test_false_positive_rate_across_all_traces` at the bottom: of every proposal
returned at confidence >= 0.5, what fraction names a street the simulated
walker never set foot on.
"""

from __future__ import annotations

import json
import math
import random
import sys
import zlib
from pathlib import Path

import pytest
from pyproj import Transformer
from shapely.geometry import LineString

REBUILD = Path(__file__).resolve().parents[1]
if str(REBUILD) not in sys.path:
    sys.path.insert(0, str(REBUILD))

from engine.coverage import Network, propose  # noqa: E402

NETWORK_JSON = REBUILD / "data" / "out" / "network.geojson"

WALK_SPEED_MS = 1.35        # a comfortable prayer-walk pace
SAMPLE_DT_S = 5.0           # what a backgrounded phone actually delivers
TICKED = 0.5                # contract rule 6: below this the confirm screen unticks


# --------------------------------------------------------------------------
# Network fixtures
# --------------------------------------------------------------------------


@pytest.fixture(scope="session")
def raw():
    with open(NETWORK_JSON) as fh:
        return json.load(fh)


@pytest.fixture(scope="session")
def net(raw):
    return Network(raw["features"])


@pytest.fixture(scope="session")
def segs(raw):
    """seg_id -> {props..., 'line': projected LineString} for the simulator."""
    tr = Transformer.from_crs("EPSG:4326", "EPSG:32617", always_xy=True)
    out = {}
    for f in raw["features"]:
        p = dict(f["properties"])
        p["line"] = LineString([tr.transform(lo, la)
                                for lo, la in f["geometry"]["coordinates"]])
        out[p["seg_id"]] = p
    return out


@pytest.fixture(scope="session")
def to_lonlat():
    return Transformer.from_crs("EPSG:32617", "EPSG:4326", always_xy=True)


@pytest.fixture(scope="session")
def adjacency(segs):
    """The contract's only adjacency rule: node -> segments touching it."""
    adj: dict[str, list[int]] = {}
    for s in segs.values():
        adj.setdefault(s["node_a"], []).append(s["seg_id"])
        adj.setdefault(s["node_b"], []).append(s["seg_id"])
    return adj


def bearing180(line: LineString) -> float:
    (x0, y0), (x1, y1) = line.coords[0], line.coords[-1]
    return math.degrees(math.atan2(x1 - x0, y1 - y0)) % 180.0


def walkable(s) -> bool:
    return (s["class"] == "minor" and s["line"].length > 30.0
            and s["node_a"] != s["node_b"])


# --------------------------------------------------------------------------
# Finding the situations the contract cares about, in the real data
# --------------------------------------------------------------------------


@pytest.fixture(scope="session")
def parallel_pairs(segs):
    """Real pairs of near-parallel streets under 80 m apart.

    This is the trap the whole component exists to avoid: two long streets
    running alongside each other, close enough that consumer GPS drifts from
    one to the other, and *not* sharing a junction -- so nothing but geometry,
    heading and route distance can separate them.
    """
    from shapely.strtree import STRtree

    ids = sorted(sid for sid, s in segs.items()
                 if s["line"].length > 150.0 and walkable(s))
    lines = [segs[i]["line"] for i in ids]
    tree = STRtree(lines)

    pairs = []
    for i, sid in enumerate(ids):
        s = segs[sid]
        for j in tree.query(s["line"], predicate="dwithin", distance=80.0):
            other = ids[j]
            if other <= sid:
                continue
            t = segs[other]
            if {s["node_a"], s["node_b"]} & {t["node_a"], t["node_b"]}:
                continue                       # sharing a junction is a corner
            db = abs(bearing180(s["line"]) - bearing180(t["line"]))
            if min(db, 180.0 - db) > 12.0:
                continue
            # Insist the separation is *sustained*: sampled all along one
            # segment, the other must stay 15-95 m away. Two streets that only
            # briefly come close are not the hazard we are testing.
            ds = [t["line"].distance(s["line"].interpolate(k / 20.0, normalized=True))
                  for k in range(21)]
            if max(ds) > 95.0 or min(ds) < 15.0:
                continue
            pairs.append((round(sum(ds) / len(ds), 2), sid, other))
    pairs.sort()
    assert pairs, "no near-parallel street pair found in the network"
    return pairs


def grow(segs, adjacency, from_node, used, budget):
    """Walk outward from a junction, taking the longest street available."""
    path, cur, total = [], from_node, 0.0
    while total < budget:
        opts = [x for x in adjacency.get(cur, ())
                if x not in used and walkable(segs[x])]
        if not opts:
            break
        nxt = max(opts, key=lambda x: (segs[x]["line"].length, -x))
        used.add(nxt)
        path.append(nxt)
        total += segs[nxt]["line"].length
        n = segs[nxt]
        cur = n["node_b"] if n["node_a"] == cur else n["node_a"]
    return path


def path_through(segs, adjacency, sid, target_m, avoid=()):
    """A node-continuous walk that passes along `sid`, roughly `target_m` long."""
    used = {sid} | set(avoid)
    s = segs[sid]
    half = max(0.0, (target_m - s["line"].length) / 2.0)
    forward = grow(segs, adjacency, s["node_b"], used, half)
    backward = grow(segs, adjacency, s["node_a"], used, half)
    path = list(reversed(backward)) + [sid] + forward
    while len(path) > 2:
        try:
            path_polyline(segs, path)
            return path
        except AssertionError:
            path = path[1:] if len(path) > 3 else path[:-1]
    raise AssertionError(f"could not grow a walkable path through {sid}")


@pytest.fixture(scope="session")
def parallel_case(segs, adjacency, parallel_pairs):
    """The tightest real parallel-street trap, plus a walk down one of them.

    On the shipped network this comes out as W Roanoke St against Wall St,
    about 50 m apart and 2 degrees off parallel, in the middle of downtown --
    exactly the "~60 m apart" situation contracts.md rule 1 describes.
    """
    for sep, a, b in parallel_pairs:
        if sep < 20.0:
            continue                   # duplicate geometry, not two streets
        path = path_through(segs, adjacency, a, 450.0, avoid=[b])
        if len(path) >= 3 and sum(segs[x]["line"].length for x in path) > 300.0:
            return {"path": path, "under_test": a, "traps": [b], "sep": sep}
    raise AssertionError("no usable parallel-street case in the network")


@pytest.fixture(scope="session")
def clean_case(segs, adjacency, parallel_pairs, parallel_case):
    """A second, independent parallel trap, used for the clean 8 m walk."""
    for sep, a, b in parallel_pairs:
        if sep < 20.0 or a in parallel_case["path"] or b in parallel_case["path"]:
            continue
        path = path_through(segs, adjacency, a, 550.0, avoid=[b])
        if len(path) >= 3 and sum(segs[x]["line"].length for x in path) > 400.0:
            return {"path": path, "under_test": a, "traps": [b], "sep": sep}
    raise AssertionError("no second parallel-street case in the network")


@pytest.fixture(scope="session")
def long_case(segs, adjacency, clean_case):
    """A ~1 km walk, long enough to hide a three-minute hole inside it."""
    path = path_through(segs, adjacency, clean_case["under_test"], 1100.0,
                        avoid=clean_case["traps"])
    assert sum(segs[x]["line"].length for x in path) > 800.0
    return path


# --------------------------------------------------------------------------
# GPS trace simulator
# --------------------------------------------------------------------------


def path_polyline(segs, seg_ids):
    """Stitch real segment geometry into one walked polyline, in metres.

    Each segment is flipped if needed so it continues from the junction the
    previous one ended at. Raises if the path is not node-continuous, so a bad
    fixture fails loudly instead of silently teleporting the walker.
    """
    assert len(seg_ids) >= 2
    first, second = segs[seg_ids[0]], segs[seg_ids[1]]
    shared = {first["node_a"], first["node_b"]} & {second["node_a"], second["node_b"]}
    ends = {first["node_a"], first["node_b"]} - shared
    if len(shared) != 1 or not ends:
        raise AssertionError(f"segments {seg_ids[:2]} are not simply adjacent")
    cur = ends.pop()

    pts: list[tuple[float, float]] = []
    for sid in seg_ids:
        s = segs[sid]
        coords = list(s["line"].coords)
        if cur == s["node_a"]:
            cur = s["node_b"]
        elif cur == s["node_b"]:
            coords.reverse()
            cur = s["node_a"]
        else:
            raise AssertionError(f"segment {sid} does not continue from node {cur}")
        if pts and math.dist(pts[-1], coords[0]) < 1e-6:
            coords = coords[1:]
        pts.extend(coords)
    return LineString(pts)


def segment_spans(segs, seg_ids):
    """Walked-distance interval [start, end] of each segment along the path."""
    spans, d = {}, 0.0
    for sid in seg_ids:
        ln = segs[sid]["line"].length
        spans[sid] = (d, d + ln)
        d += ln
    return spans


def simulate(segs, to_lonlat, seg_ids, *, accuracy_m, seed,
             dt=SAMPLE_DT_S, speed=WALK_SPEED_MS, t0=1_700_000_000.0,
             stop_at_m=None, rho=0.85, offset=(0.0, 0.0)):
    """Walk `seg_ids` end to end and return a list of Fix dicts.

    Noise is AR(1) per axis with correlation `rho` between consecutive fixes,
    scaled so the radial error's 68th percentile is about `accuracy_m`. That
    produces the sustained 20-40 m sideways excursions that make downtown
    parallel streets genuinely dangerous, instead of white noise that a matcher
    can average away. `offset` adds a constant metric bias on top.
    """
    rng = random.Random(seed)
    line = path_polyline(segs, seg_ids)
    total = line.length if stop_at_m is None else min(stop_at_m, line.length)
    sigma = accuracy_m / 1.5            # per axis
    ex = rng.gauss(0, sigma)
    ey = rng.gauss(0, sigma)
    k = math.sqrt(1.0 - rho * rho)

    fixes, d, t = [], 0.0, t0
    while d <= total + 1e-9:
        p = line.interpolate(d)
        ex = rho * ex + k * sigma * rng.gauss(0, 1)
        ey = rho * ey + k * sigma * rng.gauss(0, 1)
        lon, lat = to_lonlat.transform(p.x + ex + offset[0], p.y + ey + offset[1])
        fixes.append({
            "lat": lat,
            "lon": lon,
            # Phones report a noisy estimate of their own accuracy, not truth.
            "accuracy_m": round(accuracy_m * rng.uniform(0.85, 1.25), 1),
            "t": t,
        })
        d += speed * dt
        t += dt
    return fixes


def simulate_stationary(segs, to_lonlat, seg_id, *, accuracy_m, seed,
                        minutes=10.0, dt=SAMPLE_DT_S, t0=1_700_000_000.0, rho=0.9):
    """Someone standing on a street corner praying. GPS wanders; they do not."""
    rng = random.Random(seed)
    p = segs[seg_id]["line"].interpolate(0.5, normalized=True)
    sigma = accuracy_m / 1.5
    ex, ey = rng.gauss(0, sigma), rng.gauss(0, sigma)
    k = math.sqrt(1.0 - rho * rho)
    fixes, t = [], t0
    while t < t0 + minutes * 60.0:
        ex = rho * ex + k * sigma * rng.gauss(0, 1)
        ey = rho * ey + k * sigma * rng.gauss(0, 1)
        lon, lat = to_lonlat.transform(p.x + ex, p.y + ey)
        fixes.append({"lat": lat, "lon": lon,
                      "accuracy_m": round(accuracy_m * rng.uniform(0.85, 1.25), 1),
                      "t": t})
        t += dt
    return fixes


def punch_gap(fixes, start_s, seconds):
    """Delete every fix in a window: the app lost signal / was killed."""
    t0 = fixes[0]["t"] + start_s
    return [f for f in fixes if not (t0 <= f["t"] < t0 + seconds)]


def random_walks(segs, count, *, target_m=600.0, seed=7):
    """Plausible walks drawn from anywhere in the real network.

    A handful of hand-picked paths can be tuned against by accident. These
    cannot: the walker wanders a random connected route through whatever
    Blacksburg actually looks like there -- cul-de-sacs, hairpins, duplicated
    geometry, clipped boundary streets and all -- which is what the headline
    false-positive number needs to survive.
    """
    adjacency: dict[str, list[int]] = {}
    for s in segs.values():
        adjacency.setdefault(s["node_a"], []).append(s["seg_id"])
        adjacency.setdefault(s["node_b"], []).append(s["seg_id"])

    rng = random.Random(seed)
    ids = sorted(segs)
    out, attempts = [], 0
    while len(out) < count and attempts < count * 80:
        attempts += 1
        start = rng.choice(ids)
        if not walkable(segs[start]):
            continue
        path, used = [start], {start}
        cur, total = segs[start]["node_b"], segs[start]["line"].length
        while total < target_m:
            opts = [x for x in adjacency.get(cur, ())
                    if x not in used and walkable(segs[x])]
            if not opts:
                break
            nxt = rng.choice(opts)
            used.add(nxt)
            path.append(nxt)
            total += segs[nxt]["line"].length
            n = segs[nxt]
            cur = n["node_b"] if n["node_a"] == cur else n["node_a"]
        if total < target_m or len(path) < 3:
            continue
        try:
            path_polyline(segs, path)      # reject anything not truly walkable
        except AssertionError:
            continue
        out.append(path)
    assert len(out) == count
    return out


# --------------------------------------------------------------------------
# Scoring helpers, shared with the false-positive sweep
# --------------------------------------------------------------------------

# Every (scenario, walked set, proposals) any test produces, for the sweep.
_RECORDS: list[tuple[str, set[int], list[dict]]] = []


def record(label, walked, proposals):
    _RECORDS.append((label, set(walked), proposals))
    return proposals


def ticked(proposals):
    return {p["seg_id"]: p for p in proposals if p["confidence"] >= TICKED}


def props_for(props, sid):
    return next((p for p in props if p["seg_id"] == sid), None)


def fp_rate(records):
    tp = fp = 0
    offenders = []
    for label, walked, props in records:
        for sid, p in ticked(props).items():
            if sid in walked:
                tp += 1
            else:
                fp += 1
                offenders.append((label, sid, p["name"], p["confidence"], p["reason"]))
    total = tp + fp
    return (fp / total if total else 0.0), tp, fp, offenders


def interior(path):
    """Segments the walker crossed end to end -- everything but the two ends."""
    return set(path[1:-1])


# --------------------------------------------------------------------------
# Sanity: the fixtures really are the situation we think they are
# --------------------------------------------------------------------------


def test_fixtures_are_the_hazard_the_contract_describes(segs, parallel_case, clean_case):
    for case in (parallel_case, clean_case):
        a, b = case["under_test"], case["traps"][0]
        assert 20.0 <= case["sep"] <= 80.0
        assert not ({segs[a]["node_a"], segs[a]["node_b"]}
                    & {segs[b]["node_a"], segs[b]["node_b"]})
        assert a in case["path"] and b not in case["path"]
        # The trap has to be somewhere the walker could plausibly have gone,
        # or avoiding it proves nothing.
        walked_nodes = set()
        for sid in case["path"]:
            walked_nodes |= {segs[sid]["node_a"], segs[sid]["node_b"]}
        trap_line = segs[b]["line"]
        assert min(segs[s]["line"].distance(trap_line) for s in case["path"]) < 90.0


# --------------------------------------------------------------------------
# 1. Clean walk, 8 m accuracy
# --------------------------------------------------------------------------


def test_clean_walk_proposes_the_streets_walked(net, segs, to_lonlat, clean_case):
    path, trap = clean_case["path"], clean_case["traps"][0]
    walked = set(path)
    for seed in range(6):
        trace = simulate(segs, to_lonlat, path, accuracy_m=8.0, seed=seed)
        props = record(f"clean/{seed}", walked, propose(trace, net))
        on = ticked(props)

        # No street the walker did not walk may render ticked, ever.
        assert not (set(on) - walked), f"seed {seed}: false positives {set(on) - walked}"

        # And specifically not the parallel street beside the one under test.
        assert trap not in on
        t = props_for(props, trap)
        assert t is None or t["confidence"] < TICKED

        # A missing match is cheap, but the engine still has to do its job:
        # the great majority of the metres walked must come back ticked.
        walked_m = sum(segs[s]["line"].length for s in path)
        got_m = sum(p["matched_m"] for p in on.values())
        assert got_m / walked_m >= 0.70, f"seed {seed}: only {got_m:.0f}/{walked_m:.0f} m"

        # Segments crossed end to end are unambiguous; they must be ticked.
        assert interior(path) <= set(on), (
            f"seed {seed}: missed interior segments {interior(path) - set(on)}")


def test_clean_walk_matched_m_is_bounded_by_reality(net, segs, to_lonlat, clean_case):
    """Never claim more metres of a segment than the segment has."""
    trace = simulate(segs, to_lonlat, clean_case["path"], accuracy_m=8.0, seed=11)
    for p in propose(trace, net):
        assert 0.0 < p["matched_m"] <= segs[p["seg_id"]]["length_m"] + 1e-6
        assert 0.0 <= p["confidence"] <= 1.0


# --------------------------------------------------------------------------
# 2. Downtown parallel streets, 25 m noise
# --------------------------------------------------------------------------


def test_downtown_parallel_streets_are_never_proposed(net, segs, to_lonlat,
                                                      parallel_case, capsys):
    """The tightest real parallel pair in the network, walked under 25 m noise.

    The noise regularly puts fixes closer to the parallel street than to the
    one the walker is on, so a nearest-line matcher fails this outright.
    Topology plus the accuracy-weighted emission has to carry it.
    """
    path = parallel_case["path"]
    under_test, trap = parallel_case["under_test"], parallel_case["traps"][0]
    walked = set(path)
    with capsys.disabled():
        print(f"\n  parallel pair under test: {segs[under_test]['name']} "
              f"vs {segs[trap]['name']}, {parallel_case['sep']:.0f} m apart")
    for seed in range(8):
        trace = simulate(segs, to_lonlat, path, accuracy_m=25.0, seed=100 + seed)
        props = record(f"downtown/{seed}", walked, propose(trace, net))
        on = ticked(props)

        assert not (set(on) - walked), f"seed {seed}: proposed unwalked {set(on) - walked}"
        assert trap not in on, f"seed {seed}: proposed the parallel street"
        # The street under test is the point of the exercise; it must be found.
        assert under_test in on, f"seed {seed}: lost the street actually walked"


def test_a_trace_hugging_the_parallel_street_still_refuses_to_guess(
        net, segs, to_lonlat, parallel_case):
    """Bias the whole trace 30 m toward the parallel street and stay honest.

    The right answers are "the street under test, unsure" or "nothing". The one
    unacceptable answer is a ticked parallel street.
    """
    path = parallel_case["path"]
    under_test, trap = parallel_case["under_test"], parallel_case["traps"][0]
    a, b = segs[under_test]["line"], segs[trap]["line"]
    mid = a.interpolate(0.5, normalized=True)
    toward = b.interpolate(b.project(mid))
    dx, dy = toward.x - mid.x, toward.y - mid.y
    n = math.hypot(dx, dy) or 1.0
    bias = (30.0 * dx / n, 30.0 * dy / n)

    for seed in range(4):
        trace = simulate(segs, to_lonlat, path, accuracy_m=25.0, seed=770 + seed,
                         offset=bias)
        props = record(f"downtown-biased/{seed}", set(path), propose(trace, net))
        on = ticked(props)
        assert trap not in on, f"seed {seed}: biased trace ticked the parallel street"
        assert not (set(on) - set(path)), f"seed {seed}: {set(on) - set(path)}"


# --------------------------------------------------------------------------
# 3. Signal dropout
# --------------------------------------------------------------------------


def test_dropout_matches_both_sides_and_invents_nothing(net, segs, to_lonlat, long_case):
    path = long_case
    walked = set(path)
    spans = segment_spans(segs, path)
    line = path_polyline(segs, path)

    # A three-minute hole starting exactly once the first segment is behind us,
    # so at least the second segment is swallowed whole.
    gap_start_m = spans[path[1]][0]
    gap_start_s = gap_start_m / WALK_SPEED_MS
    gap_s = 180.0
    gap_end_m = gap_start_m + gap_s * WALK_SPEED_MS
    assert gap_end_m < line.length, "the hole must sit inside the walk"

    # Which segments was the walker's phone actually awake for?
    observed_m = {}
    for sid, (a, b) in spans.items():
        observed_m[sid] = (max(0.0, min(b, gap_start_m) - a)
                           + max(0.0, b - max(a, gap_end_m)))
    swallowed = [s for s, m in observed_m.items() if m < 10.0]
    assert swallowed, "the hole should swallow at least one whole segment"

    for seed in range(5):
        full = simulate(segs, to_lonlat, path, accuracy_m=8.0, seed=200 + seed)
        trace = punch_gap(full, gap_start_s, gap_s)
        assert len(trace) < len(full)
        props = record(f"dropout/{seed}", walked, propose(trace, net))
        on = ticked(props)

        assert not (set(on) - walked)

        # Nothing is invented across the hole: a segment the phone never saw
        # must not come back ticked.
        for sid in swallowed:
            assert sid not in on, f"seed {seed}: invented {sid} across the dropout"

        # Both sides of the hole are matched. (Exactly which post-gap segments
        # come back is a recall question, and recall is the cheap failure, so
        # the assertion is on substance: a fully-observed post-gap segment.)
        assert path[0] in on, f"seed {seed}: lost the pre-dropout segment"
        post_gap = [s for s in path if spans[s][0] >= gap_end_m]
        assert post_gap
        assert any(s in on and on[s]["matched_m"] > 100.0 for s in post_gap), (
            f"seed {seed}: nothing substantial matched after the dropout")

        # No proposal may claim metres the phone was asleep for. 25 m of slack
        # covers the last fix before the hole and the first one after it.
        for p in props:
            assert p["matched_m"] <= observed_m[p["seg_id"]] + 25.0, (
                f"seed {seed}: seg {p['seg_id']} claims {p['matched_m']} m "
                f"but only {observed_m[p['seg_id']]:.0f} m were observed")


def test_dropout_is_not_bridged_even_when_geometry_would_allow_it(
        net, segs, to_lonlat, clean_case):
    """Two fixes ten minutes apart on the same street are two walks, not one."""
    trace = simulate(segs, to_lonlat, clean_case["path"], accuracy_m=8.0, seed=31)
    head = trace[:6]
    tail = [{**f, "t": f["t"] + 600.0} for f in trace[-6:]]
    props = propose(head + tail, net)
    total = sum(p["matched_m"] for p in props if p["confidence"] >= TICKED)
    walked_head_tail = 2 * 5 * WALK_SPEED_MS * SAMPLE_DT_S     # ~68 m of real walking
    assert total <= walked_head_tail + 60.0, (
        f"bridged the ten-minute gap: claimed {total:.0f} m")


# --------------------------------------------------------------------------
# 4. App suspended mid-segment
# --------------------------------------------------------------------------


def test_partial_final_segment_is_proposed_but_low_confidence(
        net, segs, to_lonlat, clean_case):
    path = clean_case["path"]
    spans = segment_spans(segs, path)
    last = path[-1]
    last_a, last_b = spans[last]
    half = last_a + (last_b - last_a) * 0.5

    for seed in range(5):
        trace = simulate(segs, to_lonlat, path, accuracy_m=8.0,
                         seed=300 + seed, stop_at_m=half)
        props = record(f"suspended/{seed}", set(path), propose(trace, net))
        by_id = {p["seg_id"]: p for p in props}

        # Not silently dropped.
        assert last in by_id, f"seed {seed}: dropped the partly-walked final segment"
        p = by_id[last]
        # Not silently completed.
        assert p["confidence"] < TICKED, f"seed {seed}: ticked a half-walked street"
        assert p["confidence"] > 0.0
        seg_len = segs[last]["line"].length
        assert 0.25 * seg_len <= p["matched_m"] <= 0.75 * seg_len, (
            f"seed {seed}: claimed {p['matched_m']} m of a {seg_len:.0f} m segment")
        assert "partial" in p["reason"]

        # The segments that *were* walked end to end are unaffected.
        on = ticked(props)
        assert not (set(on) - set(path))
        assert interior(path) <= set(on), f"seed {seed}: lost the completed segments"


# --------------------------------------------------------------------------
# 5. Stationary noise
# --------------------------------------------------------------------------


def test_standing_still_does_not_paint_streets(net, segs, to_lonlat,
                                               clean_case, parallel_case):
    """Someone stands and prays for ten minutes while the GPS wanders 30 m."""
    spots = [clean_case["under_test"], parallel_case["under_test"],
             clean_case["path"][0], parallel_case["path"][-1]]
    for seg_id in spots:
        for seed in range(4):
            trace = simulate_stationary(segs, to_lonlat, seg_id,
                                        accuracy_m=30.0, seed=400 + seed)
            assert len(trace) > 100
            # They stood on `seg_id`; they walked nothing at all.
            props = record(f"stationary/{seg_id}/{seed}", set(), propose(trace, net))
            on = ticked(props)
            assert not on, f"seg {seg_id} seed {seed}: painted {list(on)} while parked"
            assert all(p["confidence"] < 0.15 for p in props), (
                f"seg {seg_id} seed {seed}: {props}")


def test_walk_then_long_stop_credits_only_the_walk(net, segs, to_lonlat, clean_case):
    """A walk that ends with five minutes of standing and praying.

    The streets walked should still come back; the standing must not extend
    them or add the cross street the walker happens to be loitering near.
    """
    path = clean_case["path"]
    walk = simulate(segs, to_lonlat, path, accuracy_m=10.0, seed=55)
    stop_start = walk[-1]["t"] + SAMPLE_DT_S
    stand = simulate_stationary(segs, to_lonlat, path[-1], accuracy_m=25.0,
                                seed=56, minutes=5.0, t0=stop_start)
    props = record("walk-then-stop", set(path), propose(walk + stand, net))
    on = ticked(props)
    assert not (set(on) - set(path))
    walked_m = sum(segs[s]["line"].length for s in path)
    assert sum(p["matched_m"] for p in on.values()) <= walked_m + 5.0
    assert interior(path) <= set(on), "the walk itself was lost"


# --------------------------------------------------------------------------
# Contract conformance
# --------------------------------------------------------------------------


def test_proposal_shape_and_purity(net, segs, to_lonlat, parallel_case):
    trace = simulate(segs, to_lonlat, parallel_case["path"], accuracy_m=12.0, seed=9)
    snapshot = json.dumps(trace, sort_keys=True)
    props = propose(trace, net, now=trace[-1]["t"] + 5.0)
    assert json.dumps(trace, sort_keys=True) == snapshot, "propose() mutated its input"
    assert isinstance(props, list)
    seen = set()
    for p in props:
        assert set(p) == {"seg_id", "name", "confidence", "matched_m", "reason"}
        assert isinstance(p["seg_id"], int) and p["seg_id"] not in seen
        seen.add(p["seg_id"])
        assert isinstance(p["name"], str) and p["name"]
        assert 0.0 <= p["confidence"] <= 1.0
        assert p["matched_m"] > 0.0
        assert isinstance(p["reason"], str) and p["reason"]
    # Sorted most-confident first, so the confirm screen can render in order.
    assert props == sorted(props,
                           key=lambda p: (-p["confidence"], -p["matched_m"], p["seg_id"]))


def test_degenerate_traces_return_nothing(net):
    assert propose([], net) == []
    assert propose([{"lat": 37.229, "lon": -80.414, "accuracy_m": 8.0, "t": 0.0}], net) == []
    # Fixes too poor to separate anything are dropped, not believed weakly.
    junk = [{"lat": 37.229 + i * 1e-5, "lon": -80.414, "accuracy_m": 400.0, "t": i * 5.0}
            for i in range(60)]
    assert propose(junk, net) == []


def test_low_quality_fixes_do_not_outvote_good_ones(net, segs, to_lonlat, clean_case):
    """Contract rule 4. Same walk, better fixes must not be less certain."""
    path = clean_case["path"]
    good = propose(simulate(segs, to_lonlat, path, accuracy_m=8.0, seed=5), net)
    poor = propose(simulate(segs, to_lonlat, path, accuracy_m=45.0, seed=5), net)
    g = {p["seg_id"]: p["confidence"] for p in good}
    p_ = {p["seg_id"]: p["confidence"] for p in poor}
    for sid in interior(path):
        assert g.get(sid, 0.0) >= p_.get(sid, 0.0), sid
    # And the poor trace must not have gone on to invent streets.
    assert not ({s for s, c in p_.items() if c >= TICKED} - set(path))


def test_heading_rules_out_the_cross_street(net, segs, to_lonlat, adjacency, clean_case):
    """Contract rule 3: a trace running north cannot match an east-west street."""
    path = clean_case["path"]
    # A street leaving one of the walked junctions at a sharp angle to the walk.
    crossings = []
    for sid in path:
        for node in (segs[sid]["node_a"], segs[sid]["node_b"]):
            for other in adjacency.get(node, ()):
                if other in path or not walkable(segs[other]):
                    continue
                db = abs(bearing180(segs[sid]["line"]) - bearing180(segs[other]["line"]))
                if min(db, 180.0 - db) > 60.0 and segs[other]["line"].length > 60.0:
                    crossings.append(other)
    assert crossings, "no cross street at any junction on the walk"

    for seed in range(4):
        on = ticked(propose(simulate(segs, to_lonlat, path, accuracy_m=10.0,
                                     seed=13 + seed), net))
        assert not (set(crossings) & set(on)), (
            f"seed {seed}: ticked a cross street the walker turned past")
        assert not (set(on) - set(path))


# --------------------------------------------------------------------------
# Headline metric
# --------------------------------------------------------------------------


def test_false_positive_rate_across_all_traces(net, segs, to_lonlat, capsys,
                                               clean_case, parallel_case, long_case):
    """Of all proposals at confidence >= 0.5, how many were never walked?

    This runs its own sweep over every scenario and every accuracy the app
    realistically sees, plus sixty random walks from anywhere in town, and
    folds in every record the tests above produced.
    """
    records = list(_RECORDS)

    scenarios = [("clean", clean_case["path"]), ("downtown", parallel_case["path"]),
                 ("long", long_case)]
    scenarios += [(f"random{i}", p) for i, p in enumerate(random_walks(segs, 60))]

    by_acc: dict[float, list] = {}
    for name, path in scenarios:
        for acc in (8.0, 15.0, 25.0, 40.0, 60.0):
            for seed in range(2 if name.startswith("random") else 5):
                # crc32, not hash(): PYTHONHASHSEED randomises str hashing and
                # the headline metric has to be reproducible run to run.
                label = f"{name}/{acc}/{seed}"
                trace = simulate(segs, to_lonlat, path, accuracy_m=acc,
                                 seed=zlib.crc32(label.encode()) % 100_000)
                rec = (f"sweep/{label}", set(path), propose(trace, net))
                records.append(rec)
                by_acc.setdefault(acc, []).append(rec)

    def recall_of(recs):
        walked_total = ticked_total = 0.0
        for _label, walked, props in recs:
            if not walked:
                continue
            walked_total += sum(segs[s]["line"].length for s in walked)
            ticked_total += sum(p["matched_m"] for p in ticked(props).values()
                                if p["seg_id"] in walked)
        return ticked_total / walked_total if walked_total else 0.0

    rate, tp, fp, offenders = fp_rate(records)
    parallel = [r for r in records
                if "downtown" in r[0] or "clean" in r[0] or "biased" in r[0]]
    p_rate, p_tp, p_fp, p_off = fp_rate(parallel)
    usable = [r for acc, rs in by_acc.items() if acc <= 25.0 for r in rs]

    with capsys.disabled():
        print("\n" + "=" * 72)
        print("COVERAGE ENGINE — measured over %d simulated traces" % len(records))
        print("=" * 72)
        print(f"  proposals at confidence >= 0.5 : {tp + fp}")
        print(f"  ... naming a street walked     : {tp}")
        print(f"  ... naming a street NOT walked : {fp}")
        print(f"  FALSE-POSITIVE RATE            : {rate * 100:.2f}%")
        print(f"  parallel-street cases only     : {p_rate * 100:.2f}% "
              f"({p_fp}/{p_tp + p_fp} ticked)")
        print(f"  recall, walked metres ticked   : {recall_of(records) * 100:.1f}% overall")
        for acc in sorted(by_acc):
            r, _tp, _fp, _o = fp_rate(by_acc[acc])
            print(f"      accuracy {acc:>4.0f} m           : "
                  f"recall {recall_of(by_acc[acc]) * 100:5.1f}%   fp {r * 100:.2f}%")
        for o in offenders[:10]:
            print("  FP:", o)
        print("=" * 72)

    assert p_rate == 0.0, f"parallel-street false positives: {p_off}"
    assert rate == 0.0, f"false positives: {offenders[:10]}"
    # Guard against passing the above by proposing nothing: within the accuracy
    # band where the geometry can actually separate a 60 m street grid, the
    # engine has to return most of the metres walked. Above that band it is
    # *supposed* to refuse, so it is excluded from the recall bar.
    assert recall_of(usable) >= 0.70, f"recall too low to be useful: {recall_of(usable):.2f}"
    assert recall_of(by_acc[60.0]) < 0.25, "ticked streets it could not possibly resolve"
