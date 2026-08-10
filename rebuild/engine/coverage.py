"""Coverage engine — contracts.md §2.

    propose(trace, network, *, now=None) -> list[Proposal]

Decides which segments a recorded GPS trace actually covered. Never writes
anything; its output is a *proposal* a human ticks on the confirm screen.

The governing bias, from the contract: **a wrong match is worse than a missing
match.** Downtown parallel streets sit ~60 m apart and consumer GPS drifts
further than that. A missing proposal costs the walker one tap. A wrong
proposal silently corrupts a shared town map that nobody re-checks.

Design
------
A Hidden Markov Model decoded with Viterbi, in the Newson & Krumm (2009)
formulation, over candidate segments:

  states      one per (fix, nearby segment) pair, carrying the projection of
              that fix onto that segment
  emission    Gaussian in the perpendicular distance fix->segment, with
              sigma taken from *that fix's own* accuracy_m, times a heading
              term (a northbound trace cannot match an east-west street)
  transition  the *route* distance through the segment graph — shared node
              ids only, never proximity — compared against the straight-line
              distance the GPS says was travelled. Unreachable => impossible.

Three things are layered on top of the textbook model, all of them in service
of the "refuse to guess" bias:

1.  Forward-backward is run alongside Viterbi. The per-fix posterior of the
    decoded state is the honest measure of "could this have been the other
    street?", and it is what drives `confidence`. A parallel street that the
    geometry cannot separate drags the posterior toward 0.5 and the proposal
    lands below the 0.5 render threshold on its own.
2.  Chains are cut, never bridged: at a >90 s time gap (contract rule 5), at a
    fix with no candidate at all, and at any step where no transition from any
    surviving state is physically possible. Each piece is decoded
    independently, so a dropout can never invent the street in the middle.
3.  Fixes where the walker was not actually moving contribute no evidence and
    no covered metres. Standing still with a wandering GPS must not paint
    streets.

Coordinates are projected to the local UTM zone once; all geometry is planar
metres from there on.
"""

from __future__ import annotations

import bisect
import heapq
import math
from typing import Any, Iterable, Mapping, Sequence

from pyproj import Transformer
from shapely.geometry import LineString, Point
from shapely.strtree import STRtree

__all__ = ["propose", "Network", "Segment"]


# --------------------------------------------------------------------------
# Tunables. Every one of these is a policy knob; the comment says which way it
# moves the false-positive / missed-match trade-off.
# --------------------------------------------------------------------------

GAP_S = 90.0          # contract rule 5: longer than this is a dropout, hard cut
MIN_SIGMA_M = 6.0     # never believe a fix is better than this, whatever it claims
MAX_ACCURACY_M = 75.0 # a fix worse than this carries no usable information at all
CAND_RADIUS_MULT = 2.5
CAND_RADIUS_MIN_M = 35.0
CAND_RADIUS_MAX_M = 120.0
MAX_CANDIDATES = 10   # per fix, nearest first

HEADING_SIGMA_DEG = 30.0   # smaller => heading vetoes cross-streets harder
BETA_M = 10.0              # transition slack: |route - gps| in metres
MAX_WALK_SPEED_MS = 2.5    # brisk; anything faster is not this walker walking
MAX_INTERMEDIATE_SEGS = 4  # a single transition may not invent more than this
HOP_PENALTY = 0.7          # log-penalty per segment traversed without a fix on it
DIJKSTRA_RADIUS_M = 600.0

# Confidence shaping
COV_MID = 0.70        # fraction of a segment walked that scores 0.5 on its own
COV_WIDTH = 0.08
EVIDENCE_W0 = 2.5     # accuracy-weighted fix count that saturates the evidence term
# Separability. Downtown parallel streets sit ~60 m apart (contract rule 1).
# Past a certain accuracy no number of fixes can tell them apart -- piling up
# 40 m fixes buys agreement, not truth -- so confidence is capped by accuracy
# alone, independently of how much evidence there is.
SEPARABLE_ACC_M = 42.0
SEPARABLE_POWER = 4.0
AMBIGUOUS_POSTERIOR = 0.72   # below this the match is *not* clearly separated ...
AMBIGUOUS_RIVAL = 0.30       # ... nor is it, if one rival holds this share of the
                             #     posterior mass over the same fixes. (The network
                             #     contains a few places where one physical street
                             #     is carried by two overlapping geometries; nothing
                             #     can separate those, and this is what catches them.)
AMBIGUOUS_MARGIN = 0.5       # ... nor is it, if the typical fix sat this close to
                             #     a rival segment, relative to its own accuracy ...
JUNCTION_CLEAR_M = 35.0      # ... where "rival" ignores a segment sharing a junction
                             #     only while we are still within this of that
                             #     junction, since streets meet at corners ...
JUNCTION_CLEAR_FRAC = 0.35   # ... capped at this fraction of a short segment, or the
                             #     clearance would swallow the whole thing ...
MARGIN_PERCENTILE = 0.25     # ... judged at the low quartile, not the median, so a
                             #     rival hugging half the segment still counts ...
MARGIN_FLOOR_M = 25.0        # ... and never below this. The contract asks us to
                             #     resolve a ~60 m street grid; anything running
                             #     closer than 25 m is a service road, a divided
                             #     carriageway, or one street the network happens to
                             #     carry twice, and picking between the two copies is
                             #     a coin flip whatever the fixes say.
AMBIGUOUS_CAP = 0.45         # ... and any of those means it can never tick (rule 1)
INFERRED_CAP = 0.40          # traversed by the best path but never directly seen
NOISE_FLOOR_CAP = 0.30

# Motion gating (do not paint streets while parked)
MOTION_WINDOW_S = 45.0     # look this far either side of a fix
MOTION_SMOOTH_S = 15.0     # ... after averaging positions over this half-window
MOTION_MIN_M = 30.0        # net displacement over 2*MOTION_WINDOW_S to count as walking
STATIONARY_WINDOW_S = 180.0  # whole-chain guard: over the best 3 minutes it had,
STATIONARY_MIN_M = 120.0     # a walk must have got at least this far ...
                             # (measured: real walks reach 200-320 m over their
                             # best 3 minutes, a parked phone with 30 m accuracy
                             # and correlated noise reaches 60-98 m)
STATIONARY_ACC_MULT = 3.0    # ... or this many times its own accuracy
MIN_PACE_MS = 0.45         # metres of a segment swept per second spent on it;
                           # below this the walker was loitering, not walking
PACE_MIN_DURATION_S = 25.0 # ... judged only once there is this much time to judge

MIN_EMIT_M = 20.0     # below this many covered metres, say nothing at all
NEG_INF = float("-inf")


# --------------------------------------------------------------------------
# Network
# --------------------------------------------------------------------------


class Segment:
    """One segment, pre-projected to metres with its geometry indexed."""

    __slots__ = (
        "seg_id", "name", "ref", "cls", "length_m",
        "node_a", "node_b", "line", "geom_len", "_cum", "_bearings",
    )

    def __init__(self, seg_id, name, ref, cls, length_m, node_a, node_b, line):
        self.seg_id = int(seg_id)
        self.name = name
        self.ref = ref
        self.cls = cls
        self.node_a = node_a
        self.node_b = node_b
        self.line = line
        self.geom_len = line.length
        # length_m is the town-clipped length. In the current build it equals
        # the drawn geometry for all 1,598 rows, but the two are kept distinct
        # on purpose: coverage *fractions* are measured against the geometry
        # (what a walker can actually be observed on) while reported matched_m
        # is capped at length_m (what counts toward the town total). If a future
        # build ever reintroduces the mismatch, this degrades to under-claiming
        # rather than to claiming street outside the town limit.
        self.length_m = float(length_m) if length_m else self.geom_len

        cum = [0.0]
        bearings = []
        cs = list(line.coords)
        for (x0, y0), (x1, y1) in zip(cs, cs[1:]):
            dx, dy = x1 - x0, y1 - y0
            cum.append(cum[-1] + math.hypot(dx, dy))
            bearings.append(math.degrees(math.atan2(dx, dy)) % 180.0)
        self._cum = cum
        self._bearings = bearings or [0.0]

    @property
    def cover_len(self) -> float:
        """Denominator for "how much of this did they walk", in geometry metres."""
        return self.geom_len if self.geom_len > 0 else 1.0

    def bearing_at(self, along: float) -> float:
        """Undirected bearing (0..180) of the sub-segment containing `along`."""
        i = bisect.bisect_right(self._cum, along) - 1
        i = max(0, min(i, len(self._bearings) - 1))
        return self._bearings[i]

    def node_at_end(self, which: str) -> str:
        return self.node_a if which == "a" else self.node_b


class Network:
    """Projected, indexed segment set. Build once, reuse for every trace."""

    def __init__(self, features: Iterable[Mapping[str, Any]]):
        rows = [_as_segment_row(f) for f in features]
        rows = [r for r in rows if r is not None]
        if not rows:
            raise ValueError("network contains no segments")

        lon0 = sum(r["coords"][0][0] for r in rows) / len(rows)
        lat0 = sum(r["coords"][0][1] for r in rows) / len(rows)
        zone = int((lon0 + 180.0) // 6) + 1
        epsg = (32600 if lat0 >= 0 else 32700) + zone
        self.crs = f"EPSG:{epsg}"
        self._to_xy = Transformer.from_crs("EPSG:4326", self.crs, always_xy=True)

        self.segments: dict[int, Segment] = {}
        lines, ids = [], []
        for r in rows:
            xs, ys = self._to_xy.transform(
                [c[0] for c in r["coords"]], [c[1] for c in r["coords"]]
            )
            pts = list(zip(xs, ys))
            # Collapse duplicate vertices; a zero-length leg has no bearing.
            clean = [pts[0]]
            for p in pts[1:]:
                if math.dist(p, clean[-1]) > 1e-6:
                    clean.append(p)
            if len(clean) < 2:
                continue
            seg = Segment(r["seg_id"], r["name"], r["ref"], r["cls"],
                          r["length_m"], r["node_a"], r["node_b"], LineString(clean))
            self.segments[seg.seg_id] = seg
            lines.append(seg.line)
            ids.append(seg.seg_id)

        self._tree = STRtree(lines)
        self._tree_ids = ids

        # Adjacency is shared node ids and nothing else (contract §1).
        self.node_edges: dict[str, list[tuple[str, float, int]]] = {}
        for seg in self.segments.values():
            self.node_edges.setdefault(seg.node_a, []).append(
                (seg.node_b, seg.geom_len, seg.seg_id))
            self.node_edges.setdefault(seg.node_b, []).append(
                (seg.node_a, seg.geom_len, seg.seg_id))

        self._dijkstra_cache: dict[str, dict[str, tuple[float, str | None, int | None]]] = {}

    # -- geometry helpers --------------------------------------------------

    def project_fix(self, lon: float, lat: float) -> tuple[float, float]:
        return self._to_xy.transform(lon, lat)

    def nearby(self, x: float, y: float, radius: float) -> list[tuple[int, float]]:
        """(seg_id, distance) for every segment within `radius`, nearest first."""
        p = Point(x, y)
        idxs = self._tree.query(p, predicate="dwithin", distance=radius)
        out = [(self._tree_ids[i], self.segments[self._tree_ids[i]].line.distance(p))
               for i in idxs]
        out.sort(key=lambda t: t[1])
        return out

    # -- topology ----------------------------------------------------------

    def dijkstra(self, source: str) -> dict[str, tuple[float, str | None, int | None]]:
        """Bounded shortest paths over the junction graph, memoised per source.

        Returns node -> (distance, predecessor node, segment used to get here).
        """
        cached = self._dijkstra_cache.get(source)
        if cached is not None:
            return cached
        dist: dict[str, tuple[float, str | None, int | None]] = {source: (0.0, None, None)}
        pq = [(0.0, source)]
        while pq:
            d, n = heapq.heappop(pq)
            if d > dist[n][0] + 1e-9:
                continue
            for nxt, w, sid in self.node_edges.get(n, ()):
                nd = d + w
                if nd > DIJKSTRA_RADIUS_M:
                    continue
                if nxt not in dist or nd < dist[nxt][0] - 1e-9:
                    dist[nxt] = (nd, n, sid)
                    heapq.heappush(pq, (nd, nxt))
        self._dijkstra_cache[source] = dist
        return dist

    def path_segments(self, dist: dict, target: str) -> list[int]:
        """Segment ids on the shortest path back to that dijkstra's source."""
        out: list[int] = []
        node = target
        while True:
            entry = dist.get(node)
            if entry is None or entry[1] is None:
                break
            out.append(entry[2])
            node = entry[1]
            if len(out) > MAX_INTERMEDIATE_SEGS + 2:
                break
        out.reverse()
        return out


def _as_segment_row(f: Mapping[str, Any]) -> dict[str, Any] | None:
    """Accept a GeoJSON Feature, or a flat dict with the same property names."""
    props = f.get("properties") if isinstance(f, Mapping) else None
    geom = f.get("geometry") if isinstance(f, Mapping) else None
    if props is None:
        props = f
    if geom is None:
        geom = f.get("geom")
    if geom is None:
        return None
    if isinstance(geom, Mapping):
        coords = geom.get("coordinates")
    else:                       # shapely geometry or anything with .coords
        coords = list(getattr(geom, "coords", []))
    if not coords or len(coords) < 2:
        return None
    return {
        "seg_id": props["seg_id"],
        "name": props.get("name") or "",
        "ref": props.get("ref"),
        "cls": props.get("class") or props.get("cls"),
        "length_m": props.get("length_m"),
        "node_a": props["node_a"],
        "node_b": props["node_b"],
        "coords": [(c[0], c[1]) for c in coords],
    }


# A loaded network is meant to be built once and reused; callers who hand us a
# raw GeoJSON dict every call still get one build, not one per trace.
_NETWORK_CACHE: dict[int, tuple[Any, Network]] = {}


def _coerce_network(network: Any) -> Network:
    if isinstance(network, Network):
        return network
    key = id(network)
    hit = _NETWORK_CACHE.get(key)
    if hit is not None and hit[0] is network:
        return hit[1]
    if isinstance(network, Mapping) and "features" in network:
        feats = network["features"]
    else:
        feats = network
    built = Network(feats)
    if len(_NETWORK_CACHE) > 4:
        _NETWORK_CACHE.clear()
    _NETWORK_CACHE[key] = (network, built)
    return built


# --------------------------------------------------------------------------
# Trace handling
# --------------------------------------------------------------------------


class _Fix:
    __slots__ = ("lat", "lon", "acc", "t", "x", "y", "w", "moving")

    def __init__(self, lat, lon, acc, t):
        self.lat, self.lon, self.acc, self.t = lat, lon, acc, t


def _get(fix: Any, key: str, default=None):
    if isinstance(fix, Mapping):
        return fix.get(key, default)
    return getattr(fix, key, default)


def _read_trace(trace: Sequence[Any], net: Network) -> list[_Fix]:
    out: list[_Fix] = []
    for f in trace or ():
        lat, lon = _get(f, "lat"), _get(f, "lon")
        t = _get(f, "t")
        if lat is None or lon is None or t is None:
            continue
        acc = _get(f, "accuracy_m")
        acc = 25.0 if acc is None else float(acc)
        # A fix worse than MAX_ACCURACY_M cannot separate parallel streets, so
        # it is dropped outright rather than allowed to vote weakly. If that
        # opens a >90 s hole, the hole becomes a dropout, which is correct.
        if acc > MAX_ACCURACY_M or not math.isfinite(acc):
            continue
        fx = _Fix(float(lat), float(lon), max(acc, 1.0), float(t))
        fx.x, fx.y = net.project_fix(fx.lon, fx.lat)
        out.append(fx)
    out.sort(key=lambda f: f.t)
    # Weight per contract rule 4: a 65 m fix votes far more weakly than an 8 m
    # one (here, 13x more weakly, on top of its much flatter emission). It is
    # quadratic in accuracy and saturates, so that "very good" fixes do not run
    # away with the total.
    #
    # This term answers "how much observation is there", not "can observation
    # of this quality tell streets apart" -- that second question is the
    # separability factor at proposal time, and mixing the two here would
    # penalise a poor trace twice over.
    for f in out:
        f.w = min(1.0, (18.0 / max(f.acc, 6.0)) ** 2)
    return out


def _split_chains(fixes: list[_Fix]) -> list[list[_Fix]]:
    """Contract rule 5. Also cuts on physically impossible jumps."""
    chains: list[list[_Fix]] = []
    cur: list[_Fix] = []
    for f in fixes:
        if cur:
            dt = f.t - cur[-1].t
            d = math.dist((f.x, f.y), (cur[-1].x, cur[-1].y))
            teleport = d > MAX_WALK_SPEED_MS * max(dt, 1.0) + 4 * (f.acc + cur[-1].acc) + 60
            if dt > GAP_S or teleport:
                chains.append(cur)
                cur = []
        cur.append(f)
    if cur:
        chains.append(cur)
    return [c for c in chains if len(c) >= 2]


def _smoothed(chain: list[_Fix]) -> list[tuple[float, float]]:
    """Positions averaged over +-MOTION_SMOOTH_S, so jitter cancels and only
    genuine displacement survives."""
    ts = [f.t for f in chain]
    out = []
    for i in range(len(chain)):
        lo = bisect.bisect_left(ts, ts[i] - MOTION_SMOOTH_S)
        hi = bisect.bisect_right(ts, ts[i] + MOTION_SMOOTH_S)
        out.append((sum(chain[k].x for k in range(lo, hi)) / (hi - lo),
                    sum(chain[k].y for k in range(lo, hi)) / (hi - lo)))
    return out


def _mark_motion(chain: list[_Fix], sm: list[tuple[float, float]]) -> None:
    """Flag each fix as moving / parked.

    Asks how far the (smoothed) walker got between MOTION_WINDOW_S before this
    fix and MOTION_WINDOW_S after. A walker makes ~120 m in 90 s; a parked
    phone makes noise.
    """
    ts = [f.t for f in chain]
    n = len(chain)
    for i, f in enumerate(chain):
        lo = bisect.bisect_left(ts, ts[i] - MOTION_WINDOW_S)
        hi = bisect.bisect_right(ts, ts[i] + MOTION_WINDOW_S) - 1
        lo = max(0, min(lo, n - 1))
        hi = max(0, min(hi, n - 1))
        span = ts[hi] - ts[lo]
        if span <= 1.0:
            f.moving = True          # cannot tell; do not punish a short chain
            continue
        d = math.dist(sm[lo], sm[hi])
        # Threshold scales down when the window is truncated at a chain edge.
        need = max(MOTION_MIN_M, 1.2 * f.acc) * min(1.0, span / (2 * MOTION_WINDOW_S))
        f.moving = d >= need


def _chain_is_stationary(chain: list[_Fix], sm: list[tuple[float, float]]) -> bool:
    """Whole-chain guard: did this trace ever actually go anywhere?

    The statistic is the furthest the smoothed track got over any
    STATIONARY_WINDOW_S window -- *not* the overall diameter, because a walk
    that loops back to its start has a small diameter and is still a walk. A
    walker covers ~240 m in three minutes; correlated GPS noise around a
    stationary phone covers a few tens of metres and then comes back.
    """
    ts = [f.t for f in chain]
    accs = sorted(f.acc for f in chain)
    med = accs[len(accs) // 2]
    need = max(STATIONARY_MIN_M, STATIONARY_ACC_MULT * med)
    span = ts[-1] - ts[0]
    if span < STATIONARY_WINDOW_S:
        # Too short to judge on its own terms; scale the bar down with it.
        need *= max(0.15, span / STATIONARY_WINDOW_S)
    best, j = 0.0, 0
    for i in range(len(chain)):
        while ts[i] - ts[j] > STATIONARY_WINDOW_S:
            j += 1
        d = math.dist(sm[i], sm[j])
        if d > best:
            best = d
            if best >= need:
                return False
    return True


def _trace_headings(chain: list[_Fix]) -> list[tuple[float, float]]:
    """(bearing 0..180, reliability 0..1) per fix, from a local displacement."""
    ts = [f.t for f in chain]
    out = []
    n = len(chain)
    for i in range(n):
        lo = max(0, bisect.bisect_left(ts, ts[i] - 12.0) - 1)
        hi = min(n - 1, bisect.bisect_right(ts, ts[i] + 12.0))
        dx = chain[hi].x - chain[lo].x
        dy = chain[hi].y - chain[lo].y
        d = math.hypot(dx, dy)
        need = max(15.0, 1.2 * chain[i].acc)
        if d < 1e-6:
            out.append((0.0, 0.0))
            continue
        # Reliability grows with displacement relative to the noise floor: a
        # 20 m hop under a 25 m accuracy tells you nothing about direction.
        rel = max(0.0, min(1.0, (d / need - 0.8) / 1.2))
        out.append((math.degrees(math.atan2(dx, dy)) % 180.0, rel))
    return out


def _ang180(a: float, b: float) -> float:
    d = abs(a - b) % 180.0
    return min(d, 180.0 - d)


# --------------------------------------------------------------------------
# HMM
# --------------------------------------------------------------------------


class _Cand:
    __slots__ = ("seg", "dist", "along", "lp_emit", "_pt")

    def __init__(self, seg, dist, along, lp_emit):
        self.seg, self.dist, self.along, self.lp_emit = seg, dist, along, lp_emit
        self._pt = None

    @property
    def pt(self) -> Point:
        """Where on the segment this fix was matched (noise already removed)."""
        if self._pt is None:
            self._pt = self.seg.line.interpolate(self.along)
        return self._pt


def _candidates(net: Network, chain: list[_Fix]) -> list[list[_Cand]]:
    headings = _trace_headings(chain)
    out = []
    for f, (hdg, rel) in zip(chain, headings):
        r = min(CAND_RADIUS_MAX_M, max(CAND_RADIUS_MIN_M, CAND_RADIUS_MULT * f.acc))
        sigma = max(f.acc, MIN_SIGMA_M)
        cands = []
        for sid, dist in net.nearby(f.x, f.y, r)[:MAX_CANDIDATES]:
            seg = net.segments[sid]
            along = seg.line.project(Point(f.x, f.y))
            # Emission: Gaussian in perpendicular distance, sigma = this fix's
            # own accuracy. This is where rule 4 does its work -- at 8 m
            # accuracy a street 50 m away is e^-19 less likely; at 65 m it is
            # only e^-0.3 less likely, and the model knows it.
            lp = -0.5 * (dist / sigma) ** 2
            if rel > 0.0:
                # Rule 3: a trace running north cannot match an east-west street.
                dth = _ang180(hdg, seg.bearing_at(along))
                lp -= 0.5 * (dth / HEADING_SIGMA_DEG) ** 2 * rel
            cands.append(_Cand(seg, dist, along, lp))
        out.append(cands)
    return out


def _route(net: Network, a: _Cand, b: _Cand) -> tuple[float, list[int], list[tuple[int, float, float]]] | None:
    """Shortest on-network walk from a's projection to b's projection.

    Returns (distance, intermediate seg ids, extra covered intervals) or None
    when b is not reachable from a through shared node ids. This function is
    the whole of contract rule 2: there is no proximity fallback, so hopping to
    a parallel street is structurally impossible unless the walker could
    really have walked there in the time available.
    """
    if a.seg.seg_id == b.seg.seg_id:
        return abs(b.along - a.along), [], []

    best = None
    for exit_node, exit_along, out_iv in (
        (a.seg.node_a, a.along, (0.0, a.along)),
        (a.seg.node_b, a.seg.geom_len - a.along, (a.along, a.seg.geom_len)),
    ):
        dist = net.dijkstra(exit_node)
        for entry_node, entry_along, in_iv in (
            (b.seg.node_a, b.along, (0.0, b.along)),
            (b.seg.node_b, b.seg.geom_len - b.along, (b.along, b.seg.geom_len)),
        ):
            hit = dist.get(entry_node)
            if hit is None:
                continue
            total = exit_along + hit[0] + entry_along
            if best is not None and total >= best[0]:
                continue
            mids = [s for s in net.path_segments(dist, entry_node)
                    if s not in (a.seg.seg_id, b.seg.seg_id)]
            if len(mids) > MAX_INTERMEDIATE_SEGS:
                continue
            # Reaching the junction means the walker covered the rest of `a`
            # and the start of `b`; those metres are real and bounded by the
            # route distance the transition is scored on.
            extra = [(a.seg.seg_id, out_iv[0], out_iv[1]),
                     (b.seg.seg_id, in_iv[0], in_iv[1])]
            extra += [(s, 0.0, net.segments[s].geom_len) for s in mids]
            best = (total, mids, extra)
    return best


def _transitions(net: Network, chain: list[_Fix], cands: list[list[_Cand]]) -> list[dict]:
    """trans[i] maps (prev index, cur index) -> (log prob, extra intervals)."""
    trans: list[dict] = [dict()]
    for i in range(1, len(chain)):
        prev_f, cur_f = chain[i - 1], chain[i]
        dt = max(cur_f.t - prev_f.t, 1e-3)
        d_gps = math.dist((prev_f.x, prev_f.y), (cur_f.x, cur_f.y))
        beta = max(BETA_M, 0.6 * (prev_f.acc + cur_f.acc) / 2.0)
        # How far could they possibly have walked, allowing for both fixes'
        # error circles?
        reach = MAX_WALK_SPEED_MS * dt + 2.0 * (prev_f.acc + cur_f.acc) + 25.0
        detour = d_gps + 5.0 * beta + 40.0
        cap = min(reach, max(detour, 30.0))
        m: dict[tuple[int, int], tuple[float, list]] = {}
        for pi, pc in enumerate(cands[i - 1]):
            for ci, cc in enumerate(cands[i]):
                r = _route(net, pc, cc)
                if r is None:
                    continue          # unreachable => impossible, not unlikely
                d_route, mids, extra = r
                if d_route > cap:
                    continue
                lp = -abs(d_route - d_gps) / beta - HOP_PENALTY * len(mids)
                # A transition is *accepted* generously, because the error
                # circles are wide and the chain must not break spuriously.
                # Metres are *credited* only when the route is short enough
                # that the walker demonstrably covered it in the time between
                # the two fixes -- otherwise we keep the link and claim nothing.
                if d_route > MAX_WALK_SPEED_MS * dt + 15.0:
                    extra = []
                m[(pi, ci)] = (lp, extra)
        trans.append(m)
    return trans


def _logsumexp(vals: Iterable[float]) -> float:
    vals = [v for v in vals if v > NEG_INF]
    if not vals:
        return NEG_INF
    m = max(vals)
    return m + math.log(sum(math.exp(v - m) for v in vals))


def _subchains(chain, cands, trans) -> list[tuple[int, int]]:
    """Maximal index ranges that are decodable without inventing anything.

    Cut before any fix with no candidate, and before any step where nothing
    that survived is able to reach anything. Never bridge a cut.
    """
    out = []
    start = None
    reachable: set[int] = set()
    for i in range(len(chain)):
        if not cands[i]:
            if start is not None and i - start >= 1:
                out.append((start, i))
            start, reachable = None, set()
            continue
        if start is None:
            start, reachable = i, set(range(len(cands[i])))
            continue
        nxt = {ci for (pi, ci) in trans[i] if pi in reachable}
        if not nxt:
            out.append((start, i))
            start, reachable = i, set(range(len(cands[i])))
        else:
            reachable = nxt
    if start is not None:
        out.append((start, len(chain)))
    return [(a, b) for a, b in out if b - a >= 1]


def _decode(cands, trans, lo, hi):
    """Viterbi path plus forward-backward posteriors for cands[lo:hi]."""
    n = hi - lo
    # forward (alpha) and viterbi in one sweep
    alpha = [[NEG_INF] * len(cands[lo + k]) for k in range(n)]
    delta = [[NEG_INF] * len(cands[lo + k]) for k in range(n)]
    back = [[-1] * len(cands[lo + k]) for k in range(n)]
    for j, c in enumerate(cands[lo]):
        alpha[0][j] = delta[0][j] = c.lp_emit
    for k in range(1, n):
        i = lo + k
        tm = trans[i]
        inbound: dict[int, list[tuple[int, float]]] = {}
        for (pi, ci), (lp, _) in tm.items():
            inbound.setdefault(ci, []).append((pi, lp))
        for ci, c in enumerate(cands[i]):
            arcs = inbound.get(ci)
            if not arcs:
                continue
            a_terms = [alpha[k - 1][pi] + lp for pi, lp in arcs if alpha[k - 1][pi] > NEG_INF]
            if a_terms:
                alpha[k][ci] = _logsumexp(a_terms) + c.lp_emit
            best, bj = NEG_INF, -1
            for pi, lp in arcs:
                v = delta[k - 1][pi] + lp
                if v > best:
                    best, bj = v, pi
            if best > NEG_INF:
                delta[k][ci] = best + c.lp_emit
                back[k][ci] = bj

    # backward (beta)
    beta = [[NEG_INF] * len(cands[lo + k]) for k in range(n)]
    beta[n - 1] = [0.0] * len(cands[hi - 1])
    for k in range(n - 2, -1, -1):
        i = lo + k + 1
        outbound: dict[int, list[tuple[int, float]]] = {}
        for (pi, ci), (lp, _) in trans[i].items():
            outbound.setdefault(pi, []).append((ci, lp))
        for pi in range(len(cands[lo + k])):
            arcs = outbound.get(pi)
            if not arcs:
                continue
            terms = [lp + cands[i][ci].lp_emit + beta[k + 1][ci]
                     for ci, lp in arcs if beta[k + 1][ci] > NEG_INF]
            if terms:
                beta[k][pi] = _logsumexp(terms)

    post = []
    for k in range(n):
        tot = _logsumexp([a + b for a, b in zip(alpha[k], beta[k])])
        if tot == NEG_INF:
            post.append([0.0] * len(alpha[k]))
        else:
            post.append([math.exp(a + b - tot) if (a > NEG_INF and b > NEG_INF) else 0.0
                         for a, b in zip(alpha[k], beta[k])])

    # viterbi backtrack
    last = max(range(len(delta[n - 1])), key=lambda j: delta[n - 1][j])
    if delta[n - 1][last] == NEG_INF:
        return None
    path = [last]
    for k in range(n - 1, 0, -1):
        prev = back[k][path[-1]]
        if prev < 0:
            return None
        path.append(prev)
    path.reverse()
    return path, post


# --------------------------------------------------------------------------
# Accumulation and confidence
# --------------------------------------------------------------------------


class _Acc:
    __slots__ = ("seg", "intervals", "w", "post_w", "accs", "observed",
                 "rival", "margins")

    def __init__(self, seg):
        self.seg = seg
        self.intervals: list[list[float]] = []
        self.w = 0.0
        self.post_w = 0.0
        self.accs: list[float] = []
        self.observed = False
        # How much closer this segment was than the nearest rival, per fix.
        # A posterior can be confident and still wrong when two rows in the
        # network describe one physical street; a geometric margin cannot.
        self.margins: list[float] = []
        # Posterior mass that other segments held at the very fixes this one
        # was matched on. This is the number that says "could it have been the
        # street one block over?" -- posterior leaking to the *collinear
        # continuation of the same street* at a junction is harmless and gets
        # spread thin, while a real parallel-street rival concentrates.
        self.rival: dict[int, float] = {}

    def add_interval(self, a: float, b: float) -> None:
        if b < a:
            a, b = b, a
        if b - a > 1e-6:
            self.intervals.append([a, b])

    def covered_m(self) -> float:
        if not self.intervals:
            return 0.0
        iv = sorted(self.intervals)
        total, cur_a, cur_b = 0.0, iv[0][0], iv[0][1]
        for a, b in iv[1:]:
            if a <= cur_b:
                cur_b = max(cur_b, b)
            else:
                total += cur_b - cur_a
                cur_a, cur_b = a, b
        return total + cur_b - cur_a


def _logistic(x: float) -> float:
    if x < -60:
        return 0.0
    if x > 60:
        return 1.0
    return 1.0 / (1.0 + math.exp(-x))


# --------------------------------------------------------------------------
# Public entry point
# --------------------------------------------------------------------------


def propose(trace, network, *, now=None) -> list[dict]:
    """See contracts.md §2. Pure function: reads only, writes nothing."""
    net = _coerce_network(network)
    fixes = _read_trace(trace, net)
    if len(fixes) < 2:
        return []

    acc: dict[int, _Acc] = {}

    def bucket(seg) -> _Acc:
        a = acc.get(seg.seg_id)
        if a is None:
            a = acc[seg.seg_id] = _Acc(seg)
        return a

    n_chains = 0
    for chain in _split_chains(fixes):
        sm = _smoothed(chain)
        if _chain_is_stationary(chain, sm):
            continue                        # parked; paint nothing
        _mark_motion(chain, sm)
        if not any(f.moving for f in chain):
            continue
        cands = _candidates(net, chain)
        trans = _transitions(net, chain, cands)
        for lo, hi in _subchains(chain, cands, trans):
            if hi - lo < 2:
                continue                    # a lone fix proves nothing
            decoded = _decode(cands, trans, lo, hi)
            if decoded is None:
                continue
            path, post = decoded
            n_chains += 1
            n = hi - lo

            def state(k):
                return cands[lo + k][path[k]]

            # Split the decoded path into *runs*: maximal stretches of
            # consecutive moving fixes sitting on one segment. Runs, not
            # individual fixes, are the unit that earns covered metres.
            runs: list[list[int]] = []
            cur: list[int] = []
            for k in range(n):
                if not chain[lo + k].moving:
                    if cur:
                        runs.append(cur)
                    cur = []
                    continue
                if cur and state(cur[-1]).seg.seg_id == state(k).seg.seg_id:
                    cur.append(k)
                else:
                    if cur:
                        runs.append(cur)
                    cur = [k]
            if cur:
                runs.append(cur)

            # A segment only earns metres if the walker actually got somewhere
            # along it in the time they spent on it. Ten minutes of standing
            # still sweeps ~100 m of a street through GPS noise alone; at
            # 0.45 m/s that same 100 m would take under four minutes of real
            # walking, so the pace test rejects it. An out-and-back down a
            # cul-de-sac still passes -- the span is the whole segment even
            # though the net displacement is zero -- and time the walker was
            # detected as parked was already excluded from the runs.
            by_seg: dict[int, list[list[int]]] = {}
            for run in runs:
                by_seg.setdefault(state(run[0]).seg.seg_id, []).append(run)

            accepted: set[int] = set()
            for sid, seg_runs in by_seg.items():
                dur = sum(chain[lo + r[-1]].t - chain[lo + r[0]].t for r in seg_runs)
                ivs = [(min(state(k).along for k in r), max(state(k).along for k in r))
                       for r in seg_runs]
                probe = _Acc(net.segments[sid])
                for a0, a1 in ivs:
                    probe.add_interval(a0, a1)
                if dur >= PACE_MIN_DURATION_S and probe.covered_m() < MIN_PACE_MS * dur:
                    continue
                for r in seg_runs:
                    accepted.update(r)
                for a0, a1 in ivs:
                    bucket(net.segments[sid]).add_interval(a0, a1)

            for k in accepted:
                i = lo + k
                f = chain[i]
                c = state(k)
                a = bucket(c.seg)
                a.observed = True
                a.w += f.w
                a.post_w += f.w * post[k][path[k]]
                a.accs.append(f.acc)
                nearest_rival = math.inf
                # Distance from this fix to each end of the segment it matched.
                to_end = {c.seg.node_a: c.along,
                          c.seg.node_b: c.seg.geom_len - c.along}
                for j, other in enumerate(cands[i]):
                    if j == path[k]:
                        continue
                    # A segment sharing a junction with this one sits at zero
                    # distance *at that junction* by construction -- a corner,
                    # not an ambiguity -- so it is ignored while we are still
                    # near the corner. Further along it counts like any other
                    # rival, which is what catches a duplicated street that
                    # happens to share an endpoint with the one it duplicates.
                    clear = min(JUNCTION_CLEAR_M,
                                JUNCTION_CLEAR_FRAC * c.seg.geom_len)
                    at_corner = any(
                        to_end.get(nd, math.inf) < clear
                        for nd in (other.seg.node_a, other.seg.node_b))
                    if not at_corner:
                        # Measured from the matched point on the segment, not
                        # from the fix: this asks a question about the town's
                        # geometry ("does another street run alongside here?"),
                        # which is stable, rather than about one noisy fix,
                        # which under 25 m error would look ambiguous
                        # everywhere.
                        nearest_rival = min(nearest_rival,
                                            other.seg.line.distance(c.pt))
                    if post[k][j] > 0.0:
                        a.rival[other.seg.seg_id] = (
                            a.rival.get(other.seg.seg_id, 0.0) + f.w * post[k][j])
                a.margins.append(nearest_rival)

            # Crossing a junction between two accepted runs means the walker
            # really reached that junction, so the metres between their last
            # fix and the node are theirs, as are any short segments the route
            # had to pass through to get there.
            for k in range(1, n):
                if k not in accepted or (k - 1) not in accepted:
                    continue
                if state(k - 1).seg.seg_id == state(k).seg.seg_id:
                    continue
                entry = trans[lo + k].get((path[k - 1], path[k]))
                if entry is None:
                    continue
                for sid, iv_a, iv_b in entry[1]:
                    bucket(net.segments[sid]).add_interval(iv_a, iv_b)

    out: list[dict] = []
    for a in acc.values():
        covered = a.covered_m()
        if covered < MIN_EMIT_M:
            continue
        if a.observed and len(a.accs) < 2:
            continue          # one fix is a coincidence, not a walk down a street
        cov_frac = min(1.0, covered / a.seg.cover_len)
        # Rounded first, then clamped: rounding a value already at the cap can
        # nudge it above, and "claims more metres than the street has" is a
        # claim the confirm screen should never be able to make.
        matched_m = min(round(covered, 1), a.seg.length_m)

        f_cov = _logistic((cov_frac - COV_MID) / COV_WIDTH)
        if a.w > 0.0:
            mean_post = a.post_w / a.w
            f_ev = 1.0 - math.exp(-a.w / EVIDENCE_W0)
            med_acc = sorted(a.accs)[len(a.accs) // 2]
            f_sep = 1.0 / (1.0 + (med_acc / SEPARABLE_ACC_M) ** SEPARABLE_POWER)
            conf = mean_post * f_cov * f_ev * f_sep
            rival_id, rival_share = 0, 0.0
            if a.post_w > 0.0 and a.rival:
                rival_id, rival_mass = max(a.rival.items(), key=lambda kv: kv[1])
                rival_share = rival_mass / a.post_w
            reason = (f"{len(a.accs)} fixes, median accuracy {med_acc:.0f} m, "
                      f"posterior {mean_post:.2f}, covered {covered:.0f}/"
                      f"{a.seg.cover_len:.0f} m ({cov_frac * 100:.0f}%)")
            # Rule 1, stated literally: if the evidence did not clearly separate
            # this segment from its rivals, it may not render ticked.
            if f_sep < 0.9:
                reason += (f"; accuracy too coarse to separate a ~60 m street "
                           f"spacing (separability {f_sep:.2f})")
            if a.margins:
                ms = sorted(a.margins)
                margin = ms[min(len(ms) - 1, int(MARGIN_PERCENTILE * len(ms)))]
            else:
                margin = math.inf
            if mean_post < AMBIGUOUS_POSTERIOR or rival_share > AMBIGUOUS_RIVAL:
                conf = min(conf, AMBIGUOUS_CAP)
                reason += (f"; ambiguous against segment {rival_id} "
                           f"({rival_share * 100:.0f}% of the posterior mass)")
            # The floor matters as much as the accuracy term: we never claim
            # to localise better than MIN_SIGMA_M, so two lines running closer
            # together than MARGIN_FLOOR_M are unresolvable however good the
            # fixes say they are. (The shipped network has such a pair --
            # Honeysuckle Dr is carried twice, 11 m apart, for 330 m.)
            need_margin = max(MARGIN_FLOOR_M, AMBIGUOUS_MARGIN * med_acc)
            if margin < need_margin:
                conf = min(conf, AMBIGUOUS_CAP)
                reason += (f"; another segment runs {margin:.0f} m away along "
                           f"this one, under the {need_margin:.0f} m needed to "
                           f"tell them apart")
            # Covered metres inside the GPS noise floor are not evidence of a walk.
            if matched_m < max(25.0, 1.5 * med_acc):
                conf = min(conf, NOISE_FLOOR_CAP)
                reason += "; covered distance within the GPS noise floor"
        else:
            # Traversed by the best path between two fixes, but never directly
            # observed. Real enough to show; never confident enough to tick.
            conf = min(INFERRED_CAP, 0.25 * f_cov)
            reason = (f"traversed between fixes, no direct GPS evidence; "
                      f"covered {covered:.0f}/{a.seg.cover_len:.0f} m")
        if cov_frac < 0.8:
            reason += "; partial segment"
        if now is not None and fixes and (float(now) - fixes[-1].t) <= GAP_S:
            reason += "; trace may still be in progress"

        out.append({
            "seg_id": a.seg.seg_id,
            "name": a.seg.name,
            "confidence": round(max(0.0, min(1.0, conf)), 3),
            "matched_m": matched_m,
            "reason": reason,
        })

    out.sort(key=lambda p: (-p["confidence"], -p["matched_m"], p["seg_id"]))
    return out
