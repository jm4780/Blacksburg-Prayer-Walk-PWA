"""Route engine — contracts.md §3.

    generate(start_lonlat, target_m, network, covered, *, seed=None) -> Route

FORMULATION
-----------
This is a *prize-collecting rural postman problem* (PCRPP) — equivalently an
orienteering problem with profits on arcs, or a single-vehicle capacitated arc
routing problem where the "capacity" is the walker's time budget.

    Given an undirected graph G = (V, E) with lengths l(e), a subset R ⊆ E of
    *required* arcs (the uncovered, walkable segments), a depot v0 and a budget
    B, find a closed walk from v0 of length ≈ B that maximises the length of
    required arcs it traverses.

Plain RPP wants to cover *all* of R at minimum cost; here the budget binds and
R is far larger than the budget, so the prize-collecting variant is the honest
model: choose which required arcs to service, then route them.

It is solved the classical way — **route-first-cluster-second by cheapest
insertion, then local search** — using the standard RPP → TSP transformation:

  1. Restrict R to a ball around the depot sized by the budget (this is the
     "cluster"; it is also what makes routes fill in one neighbourhood rather
     than scattering confetti across town).
  2. Compute the shortest-path metric between the endpoints of the chosen
     required arcs. Deadheading is free to use any segment, so connectors are
     shortest paths — that is what turns the arc problem into a node problem.
  3. Build a closed walk by **cheapest insertion** with a cost/prize ratio,
     inserting required arcs (in either orientation) until the budget is met.
  4. Improve with **2-opt** (sequence reversal, orientations flipped) and
     **or-opt** (relocate one arc), then re-fill the freed budget. Iterate.
  5. Perturb with **ruin and recreate** — tear out whatever the walk services
     inside its longest doubled-back stretch and let insertion rebuild it.
     This is the move that turns an out-and-back into a loop.
  6. Re-route the deadhead with **go-around repair**: shortest-path connectors
     are why an insertion solver doubles back at all (the cheapest way to the
     next street is usually the street you just walked), so any walk with a
     long repeated run is re-expanded on weights that treble ground already
     covered, and the result kept only if it scores better.
  7. Repeat from several seeded restarts, seeded at points spread across the
     whole candidate list so the restarts try different neighbourhoods rather
     than re-deriving the one nearest the start, and keep the best solution
     under the lexicographic objective in `_Solver.score`:
     (close to the asked-for time, then shape, then max new_m, then
     contiguity, then shorter).

SHAPE
-----
Contiguity alone does not describe a good walk. A 1.5 mile thread with two
dead-end spurs is perfectly contiguous — one connected block — and is still a
walk nobody wants: it is dull, it gives no signal about where to turn round,
and out at the edge of town it puts someone on a rural road with no footway.
Three terms, all from data already in the graph, carry the rest:

* **Compactness** — 4·pi·hull_area / length². A loop encloses ground, a thread
  encloses none. Walks a person judged good measure 0.36-0.57; ones they
  rejected, 0.22-0.30.
* **Repeated runs** — scored by the length of each contiguous doubled-back
  stretch, not by the total. 120 m back out of a cul-de-sac is unavoidable and
  costs nothing; 1.6 km back along one rural road is the failure.
* **Rural connectors** — corridors (see `RouteGraph._corridors`) longer than
  400 m are kept out of the set the walk deliberately services, while staying
  fully available as links. This is contract §3.5's "prefer segments that
  share junctions with many others over long isolated stretches", in the only
  proxy the graph supports.

Every step preserves closure — the walk starts and ends at the depot node by
construction, so priority 1 is structural rather than something we hope for.

Unsafe segments (class='motorway' with ref != 'US 460 Bus') are removed from
the graph entirely, so they cannot appear even as deadhead.

The start point snaps to the nearest junction, and the walk never leaves that
junction's connected component: 95% of the town's street length is in one
component, and padding a route by teleporting across town would be a lie. A
start in one of the dozens of tiny components gets the best short loop that
component allows, or an honest empty route if it allows none.

Repeated street is not automatically waste. Well over a third of this town's
segments are bridges — cul-de-sac stems, the one road into a subdivision — and
the only way back over a bridge is back over it. `route_stats()` reports
forced and avoidable repeat mileage separately for exactly this reason.

Pace: 3.0 mph = 80.47 m/min. A prayer walk is a strolling pace with stops, not
a fitness walk; 3.0 mph is the standard casual figure and errs slightly fast,
which the ±15% band absorbs.
"""

from __future__ import annotations

import math
import random
import time
from heapq import heappop, heappush
from typing import Any, Iterable, Sequence

from shapely.geometry import LineString

__all__ = [
    "generate",
    "build_graph",
    "contiguity",
    "meters_for_minutes",
    "minutes_for_meters",
    "route_stats",
    "PACE_M_PER_MIN",
]

# ---------------------------------------------------------------- constants --

PACE_MPH = 3.0
PACE_M_PER_MIN = 80.47                # 3.0 mph
BAND = 0.15                           # contract §3.2: ±15% of target
CLOSE_M = 100.0                       # contract §3.1
SAFE_MOTORWAY_REF = "US 460 Bus"      # Main St downtown; walkable

_UNCOVERED_DISCOUNT = 0.85   # deadhead prefers streets we still need
_MAX_CANDIDATES = 110        # required arcs considered per route
_NEAR_TOUR = 60              # arcs evaluated per insertion (nearest to tour)
_RESTARTS = 12
_RUIN_ITERS = 14           # ruin-and-recreate passes per restart
_TIME_BUDGET_S = 2.0         # hard wall; contract asks for < 3 s
_MAX_REPEATS = 3             # times one arc may be walked while padding
_INF = float("inf")

# -- shape of the walk (contracts §3.4, §3.5) --------------------------------
# Connected is not the same as compact: a 1.5 mile thread with two spurs is
# perfectly connected and is still a bad walk. These terms are what stop it.
_CORRIDOR_M = 400.0          # a run of street with no real junction in it for
                             # this long is a rural connector, not a
                             # neighbourhood street
_ISOLATED_PRIZE = 0.20       # how much a rural connector is worth to *service*;
                             # it stays fully usable as a link
_REPEAT_FREE_FRAC = 0.10     # repeated street below this share of the walk is free
_RUN_FREE_M = 250.0          # a cul-de-sac out-and-back this long is fine
_COMPACT_TARGET = 0.35       # 4·pi·hull_area / length², measured on good routes
_W_RUN = 1.5                 # weights on the three shape terms
_W_REPEAT = 1.0
_W_COMPACT = 1.0
_SHAPE_BUCKET = 0.05         # quantised, so shape only outranks new_m when the
                             # difference is real

_EARTH_M_PER_DEG = 111_320.0


# ------------------------------------------------------------ input parsing --


def _coords_of(obj: Any) -> list[tuple[float, float]] | None:
    """Pull a coordinate list out of whatever geometry representation we got."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        c = obj.get("coordinates")
        return [(float(x), float(y)) for x, y in c] if c else None
    if hasattr(obj, "coords"):                       # shapely
        return [(float(x), float(y)) for x, y in obj.coords]
    if isinstance(obj, (list, tuple)) and obj:
        return [(float(p[0]), float(p[1])) for p in obj]
    return None


def _iter_raw(network: Any) -> Iterable[dict]:
    if isinstance(network, dict) and "features" in network:
        return network["features"]
    if isinstance(network, dict):                    # {seg_id: feature}
        return list(network.values())
    return list(network)


def _normalise(network: Any) -> list[dict]:
    """Accept a FeatureCollection, a list of features, or a list of flat rows."""
    out = []
    for raw in _iter_raw(network):
        if not isinstance(raw, dict):
            raise TypeError(f"network entries must be dicts, got {type(raw).__name__}")
        props = raw.get("properties") if isinstance(raw.get("properties"), dict) else raw
        geom = raw.get("geometry")
        if geom is None:
            geom = raw.get("geom") or raw.get("coords") or props.get("geometry")
        coords = _coords_of(geom)
        if coords is None or len(coords) < 2:
            continue
        try:
            seg_id = int(props["seg_id"])
            node_a = str(props["node_a"])
            node_b = str(props["node_b"])
        except (KeyError, TypeError, ValueError):
            continue
        length = props.get("length_m")
        length = float(length) if length is not None else _geodesic_len(coords)
        drawn = _geodesic_len(coords)
        out.append(
            {
                "seg_id": seg_id,
                "name": props.get("name") or "",
                "ref": props.get("ref"),
                "class": props.get("class") or props.get("cls") or "minor",
                # What coverage counts (contracts §1: clipped to the town limit).
                "length_m": length,
                # What the walker's legs actually do. For 45 segments in this
                # build the drawn line runs well past the town limit while
                # length_m is clipped (seg 1, Glade Rd: 10 m counted, 1188 m
                # drawn). Budgeting on the clipped number would hand someone a
                # "30 minute" walk that takes an hour, so the walk is priced on
                # whichever is longer. It also makes those segments a terrible
                # deal per metre claimed, which keeps routes inside town.
                "walk_m": max(length, drawn),
                "node_a": node_a,
                "node_b": node_b,
                "coords": coords,
            }
        )
    return out


def _geodesic_len(coords: Sequence[tuple[float, float]]) -> float:
    total = 0.0
    for (x0, y0), (x1, y1) in zip(coords, coords[1:]):
        total += _flat_m(x0, y0, x1, y1)
    return total


def _flat_m(lon0: float, lat0: float, lon1: float, lat1: float) -> float:
    """Local equirectangular metres. Good to ~0.1% over a town."""
    mlat = math.radians((lat0 + lat1) * 0.5)
    dx = (lon1 - lon0) * _EARTH_M_PER_DEG * math.cos(mlat)
    dy = (lat1 - lat0) * _EARTH_M_PER_DEG
    return math.hypot(dx, dy)


def is_safe(seg: dict) -> bool:
    """contracts §3.5 — motorway is off limits unless it is Main St."""
    if (seg.get("class") or "").lower() != "motorway":
        return True
    return (seg.get("ref") or "") == SAFE_MOTORWAY_REF


# ---------------------------------------------------------------- the graph --


class RouteGraph:
    """Undirected multigraph of walkable segments, keyed by junction node id.

    Adjacency is a shared node id and nothing else (contracts §1).
    """

    def __init__(self, network: Any):
        segs = _normalise(network)
        self.segments: dict[int, dict] = {s["seg_id"]: s for s in segs}

        self.node_id: dict[str, int] = {}
        self.node_name: list[str] = []
        self.node_lonlat: list[tuple[float, float]] = []

        self.e_seg: list[int] = []
        self.e_len: list[float] = []      # metres walked  (budget)
        self.e_prize: list[float] = []    # metres claimed (coverage)
        self.e_u: list[int] = []
        self.e_v: list[int] = []
        self.adj: list[list[tuple[int, int]]] = []   # node -> [(nbr, edge_idx)]

        for s in sorted(segs, key=lambda s: s["seg_id"]):
            if not is_safe(s):
                continue                              # never walkable, not even deadhead
            u = self._node(s["node_a"], s["coords"][0])
            v = self._node(s["node_b"], s["coords"][-1])
            ei = len(self.e_seg)
            self.e_seg.append(s["seg_id"])
            self.e_len.append(s["walk_m"])
            self.e_prize.append(s["length_m"])
            self.e_u.append(u)
            self.e_v.append(v)
            self.adj[u].append((v, ei))
            if u != v:
                self.adj[v].append((u, ei))

        self.edge_of_seg: dict[int, int] = {sid: i for i, sid in enumerate(self.e_seg)}
        self.degree: list[int] = [len(a) for a in self.adj]
        self.component: list[int] = self._components()
        self.is_bridge: list[bool] = self._bridges()
        self.corridor: list[int] = []
        self.corridor_m: list[float] = []
        self.isolated: list[bool] = self._corridors()

    # -- construction helpers

    def _node(self, name: str, lonlat: tuple[float, float]) -> int:
        i = self.node_id.get(name)
        if i is None:
            i = len(self.node_name)
            self.node_id[name] = i
            self.node_name.append(name)
            self.node_lonlat.append((float(lonlat[0]), float(lonlat[1])))
            self.adj.append([])
        return i

    def _components(self) -> list[int]:
        comp = [-1] * len(self.node_name)
        cid = 0
        for start in range(len(self.node_name)):
            if comp[start] != -1:
                continue
            stack = [start]
            comp[start] = cid
            while stack:
                n = stack.pop()
                for m, _ in self.adj[n]:
                    if comp[m] == -1:
                        comp[m] = cid
                        stack.append(m)
            cid += 1
        self.n_components = cid
        return comp

    def _bridges(self) -> list[bool]:
        """Edges whose removal disconnects the graph (iterative Tarjan).

        A bridge is a street you *must* walk twice to get back — the stem of a
        cul-de-sac, the one road into a subdivision. Repeating a bridge is not
        a routing mistake; repeating anything else might be. 470 dead ends in
        this town make the distinction worth drawing.
        """
        n = len(self.node_name)
        disc = [-1] * n
        low = [0] * n
        bridge = [False] * len(self.e_seg)
        timer = 0
        for root in range(n):
            if disc[root] != -1:
                continue
            stack = [(root, -1, iter(self.adj[root]))]
            disc[root] = low[root] = timer
            timer += 1
            while stack:
                u, pe, it = stack[-1]
                advanced = False
                for v, ei in it:
                    if ei == pe:
                        continue
                    if disc[v] == -1:
                        disc[v] = low[v] = timer
                        timer += 1
                        stack.append((v, ei, iter(self.adj[v])))
                        advanced = True
                        break
                    if disc[v] < low[u]:
                        low[u] = disc[v]
                        stack[-1] = (u, pe, it)
                if advanced:
                    continue
                stack.pop()
                if stack:
                    p = stack[-1][0]
                    if low[u] < low[p]:
                        low[p] = low[u]
                    if low[u] > disc[p]:
                        bridge[pe] = True
        return bridge

    def _corridors(self) -> list[bool]:
        """Group segments into corridors and flag the long isolated ones.

        A *corridor* is a maximal run of street with no real junction inside
        it — merge across every node where exactly two segment-ends meet. One
        named road is therefore many corridors downtown (a junction every
        block) and one long corridor out at the town edge.

        Contracts §3.5 asks for "segments that share junctions with many
        others (a grid) over long isolated stretches". Without sidewalk data,
        this is the proxy the graph can actually support, and unlike a rule on
        single segments it generalises: Glade Rd west is 13 short segments and
        no per-segment rule catches it, while its corridor is 1.2 km with
        nothing joining it. 72 km of this town's 252 km sits in corridors over
        400 m, and that is the part a walker should be *passing through*
        rather than pacing.
        """
        n_e = len(self.e_seg)
        corr = [-1] * n_e
        cid = 0
        for e0 in range(n_e):
            if corr[e0] != -1:
                continue
            corr[e0] = cid
            stack = [e0]
            while stack:
                e = stack.pop()
                for node in (self.e_u[e], self.e_v[e]):
                    if self.degree[node] != 2:
                        continue                  # a real junction ends the corridor
                    for _, e2 in self.adj[node]:
                        if corr[e2] == -1:
                            corr[e2] = cid
                            stack.append(e2)
            cid += 1
        lengths = [0.0] * cid
        for e in range(n_e):
            lengths[corr[e]] += self.e_len[e]
        self.corridor = corr
        self.corridor_m = [lengths[corr[e]] for e in range(n_e)]
        self.n_corridors = cid
        return [m > _CORRIDOR_M for m in self.corridor_m]

    # -- queries

    def nearest_node(self, lon: float, lat: float) -> int:
        """Nearest junction. Segments are never subdivided (contracts §0)."""
        best, best_d = -1, _INF
        for i, (nlon, nlat) in enumerate(self.node_lonlat):
            d = _flat_m(lon, lat, nlon, nlat)
            if d < best_d:
                best, best_d = i, d
        return best

    def dijkstra(self, src: int, weight: list[float], cutoff: float,
                 new_len: list[bool] | None = None):
        """Min-cost tree from ``src``.

        Returns (cost, real, prev). ``weight`` may discount uncovered street,
        so ``real`` carries the true metres of the chosen path — the budget is
        always measured in real metres.  weight <= length, so a cost cutoff
        keeps a superset of the nodes within ``cutoff`` real metres.
        """
        if new_len is None:
            new_len = [False] * len(self.e_seg)
        cost = {src: 0.0}
        real = {src: 0.0}
        fresh = {src: 0.0}
        prev: dict[int, tuple[int, int]] = {}
        seen: set[int] = set()
        heap = [(0.0, src)]
        adj, e_len, e_prize = self.adj, self.e_len, self.e_prize
        while heap:
            d, u = heappop(heap)
            if u in seen:
                continue
            if d > cutoff:
                break
            seen.add(u)
            ru, fu = real[u], fresh[u]
            for v, ei in adj[u]:
                nd = d + weight[ei]
                if nd < cost.get(v, _INF):
                    cost[v] = nd
                    real[v] = ru + e_len[ei]
                    fresh[v] = fu + (e_prize[ei] if new_len[ei] else 0.0)
                    prev[v] = (u, ei)
                    heappush(heap, (nd, v))
        return cost, real, prev, fresh


_GRAPH_CACHE: list[tuple[int, Any, RouteGraph]] = []


def build_graph(network: Any) -> RouteGraph:
    """Build (or reuse) the walkable graph for a network object."""
    key = id(network)
    for k, obj, g in _GRAPH_CACHE:
        if k == key and obj is network:
            return g
    g = RouteGraph(network)
    _GRAPH_CACHE.append((key, network, g))
    del _GRAPH_CACHE[:-4]
    return g


# --------------------------------------------------------------- pace maths --


def meters_for_minutes(minutes: float, pace_mph: float = PACE_MPH) -> float:
    return float(minutes) * (pace_mph * 1609.344 / 60.0)


def minutes_for_meters(meters: float, pace_mph: float = PACE_MPH) -> float:
    return float(meters) / (pace_mph * 1609.344 / 60.0)


# ------------------------------------------------------------- the solution --


class _Sol:
    """A closed walk: an ordered list of serviced arcs (edge_idx, from, to)."""

    __slots__ = ("arcs", "length", "counts")

    def __init__(self):
        self.arcs: list[tuple[int, int, int]] = []
        self.length: float = 0.0
        self.counts: dict[int, int] = {}

    def copy(self) -> "_Sol":
        s = _Sol()
        s.arcs = list(self.arcs)
        s.length = self.length
        s.counts = dict(self.counts)
        return s


class _Solver:
    def __init__(self, g: RouteGraph, anchor: int, target_m: float,
                 covered: set[int], rng: random.Random, deadline: float):
        self.g = g
        self.anchor = anchor
        self.target = target_m
        self.lo = target_m * (1.0 - BAND)
        self.hi = target_m * (1.0 + BAND)
        # Aim at the target, not at the ceiling: someone with 30 minutes has 30
        # minutes, and a route that always lands at +14% is a route that lies.
        self.aim = target_m * 0.96
        self.cap = target_m * 1.10
        self.covered = covered
        self.rng = rng
        self.deadline = deadline

        self.weight = [
            l * (_UNCOVERED_DISCOUNT if sid not in covered else 1.0)
            for sid, l in zip(g.e_seg, g.e_len)
        ]
        self.is_new = [sid not in covered for sid in g.e_seg]
        # A rural connector is worth a fifth of its metres to *walk down and
        # back*; it stays worth full price when picked up in passing.
        self.prize = [
            p * (_ISOLATED_PRIZE if iso else 1.0)
            for p, iso in zip(g.e_prize, g.isolated)
        ]
        self._sp: dict[int, tuple[dict, dict, dict, dict]] = {}
        self._real: dict[int, dict] = {}
        self.cut = max(self.hi, 400.0)
        self.filler: list[int] = []   # any walkable arc in reach, for padding

    # -- shortest paths

    def sp(self, node: int):
        r = self._sp.get(node)
        if r is None:
            r = self.g.dijkstra(node, self.weight, self.cut, self.is_new)
            self._sp[node] = r
        return r

    def real_from(self, node: int) -> dict:
        """Distances from ``node`` to everywhere in reach, as a plain dict.

        The inner loops look up hundreds of thousands of distances, so they
        take this dict once per source node and index it directly rather than
        paying for a method call each time.
        """
        r = self._real.get(node)
        if r is None:
            r = self.sp(node)[1]
            self._real[node] = r
        return r

    def d(self, a: int, b: int) -> float:
        if a == b:
            return 0.0
        return self.real_from(a).get(b, _INF)

    def dnew(self, a: int, b: int) -> float:
        """Uncovered metres picked up while deadheading a -> b."""
        if a == b:
            return 0.0
        return self.sp(a)[3].get(b, 0.0)

    def path_edges(self, a: int, b: int) -> list[int]:
        if a == b:
            return []
        prev = self.sp(a)[2]
        out = []
        cur = b
        while cur != a:
            step = prev.get(cur)
            if step is None:
                return []
            p, ei = step
            out.append(ei)
            cur = p
        out.reverse()
        return out

    # -- candidate required arcs (the cluster)

    def candidates(self) -> list[int]:
        g = self.g
        _, real, _, _ = self.sp(self.anchor)
        comp = g.component[self.anchor]
        reach = []
        for ei in range(len(g.e_seg)):
            if g.component[g.e_u[ei]] != comp:
                continue
            du = real.get(g.e_u[ei], _INF)
            dv = real.get(g.e_v[ei], _INF)
            dmin = min(du, dv)
            if dmin > self.hi * 0.5:
                continue
            reach.append((dmin, ei))
        reach.sort(key=lambda t: (t[0], g.e_seg[t[1]]))
        req = [ei for _, ei in reach if g.e_seg[ei] not in self.covered]
        self.filler = [ei for _, ei in reach][: _MAX_CANDIDATES * 3]

        # Rural connectors are a link, not a destination: walking one down and
        # back is a mile of two-lane road with nothing to see and no signal
        # about where to turn round. Keep them out of the set we deliberately
        # service — they stay fully available as deadhead, and anything the
        # walk does pass through still counts as claimed. Only if the
        # neighbourhood is *made* of them (a start out on the town edge) do
        # they come back, because then they are all there is.
        grid = [ei for ei in req if not g.isolated[ei]]
        if sum(g.e_len[ei] for ei in grid) >= self.lo * 0.6:
            req = grid
        return req[:_MAX_CANDIDATES]

    # -- insertion mechanics

    def _endpoints(self, sol: _Sol):
        """Node before each position, and node after it."""
        a = self.anchor
        starts = [a] + [arc[2] for arc in sol.arcs]        # node the walk is at
        ends = [arc[1] for arc in sol.arcs] + [a]          # node it must reach
        return starts, ends

    def best_insertion(self, sol: _Sol, ei: int, cap: float):
        """Cheapest position and orientation for arc ``ei``.

        Returns (delta_metres, position, from_node, to_node, new_metres the
        connectors would pick up on the way), or None if it does not fit.
        """
        g = self.g
        u0, v0 = g.e_u[ei], g.e_v[ei]
        L = g.e_len[ei]
        starts, ends = self._endpoints(sol)
        real_from = self.real_from
        room = cap - sol.length
        ends_u, ends_v = (real_from(u0), real_from(v0))
        best = None
        best_delta = _INF
        for pos in range(len(sol.arcs) + 1):
            p, n = starts[pos], ends[pos]
            from_p = real_from(p)
            base = 0.0 if p == n else from_p.get(n, _INF)
            if base == _INF:
                continue
            if u0 == v0:
                orientations = ((u0, v0, ends_u),)
            else:
                orientations = ((u0, v0, ends_v), (v0, u0, ends_u))
            for a, b, from_b in orientations:
                d1 = 0.0 if p == a else from_p.get(a, _INF)
                if d1 == _INF:
                    continue
                d2 = 0.0 if b == n else from_b.get(n, _INF)
                if d2 == _INF:
                    continue
                delta = d1 + L + d2 - base
                if delta > room or delta >= best_delta - 1e-9:
                    continue
                bonus = self.dnew(p, a) + self.dnew(b, n) - self.dnew(p, n)
                best = (delta, pos, a, b, max(bonus, 0.0))
                best_delta = delta
        return best

    def insert(self, sol: _Sol, ei: int, delta: float, pos: int, a: int, b: int):
        sol.arcs.insert(pos, (ei, a, b))
        sol.length += delta
        sol.counts[ei] = sol.counts.get(ei, 0) + 1

    def remove(self, sol: _Sol, pos: int) -> tuple[int, float]:
        ei, a, b = sol.arcs[pos]
        starts, ends = self._endpoints(sol)
        p = starts[pos]
        n = sol.arcs[pos + 1][1] if pos + 1 < len(sol.arcs) else self.anchor
        gain = self.d(p, a) + self.g.e_len[ei] + self.d(b, n) - self.d(p, n)
        del sol.arcs[pos]
        sol.length -= gain
        sol.counts[ei] -= 1
        if sol.counts[ei] <= 0:
            del sol.counts[ei]
        return ei, gain

    # -- construction

    def _near_tour(self, sol: _Sol, pool: list[int], limit: int) -> list[int]:
        """The arcs closest to where the walk already is: keeps it contiguous."""
        if not sol.arcs or len(pool) <= limit:
            return pool[:limit] if len(pool) > limit else pool
        touch = {self.anchor}
        for _, a, b in sol.arcs:
            touch.add(a)
            touch.add(b)
        g = self.g
        e_u, e_v, e_seg = g.e_u, g.e_v, g.e_seg
        maps = [self.real_from(t) for t in touch]
        scored = []
        for ei in pool:
            u, v = e_u[ei], e_v[ei]
            best = _INF
            for m in maps:
                dd = m.get(u, _INF)
                d2 = m.get(v, _INF)
                if d2 < dd:
                    dd = d2
                if dd < best:
                    best = dd
                    if best <= 0.0:
                        break
            scored.append((best, e_seg[ei], ei))
        scored.sort()
        return [ei for _, _, ei in scored[:limit]]

    def construct(self, req: list[int], randomised: bool, first: int | None = None) -> _Sol:
        """Greedy cheapest-insertion by cost-per-new-metre.

        ``first`` seeds the walk with a chosen arc, which is how the restarts
        explore *different neighbourhoods* rather than the same one over and
        over — the cluster-first half of route-first-cluster-second.
        """
        sol = _Sol()
        pool = list(req)
        g = self.g
        if first is not None and first in pool:
            bi = self.best_insertion(sol, first, self.cap)
            if bi is not None:
                delta, pos, a, b, _ = bi
                self.insert(sol, first, delta, pos, a, b)
                pool.remove(first)
        while pool and sol.length < self.aim:
            if time.monotonic() > self.deadline:
                break
            options = []
            for ei in self._near_tour(sol, pool, _NEAR_TOUR):
                bi = self.best_insertion(sol, ei, self.cap)
                if bi is None:
                    continue
                delta, pos, a, b, bonus = bi
                gain = self.prize[ei] + bonus
                # Cost per new metre. A cul-de-sac's return trip is already
                # inside `delta`, so it is priced, not punished — Blacksburg has
                # 470 dead ends and walking out of one is correct. The only
                # thumb on the scale is a 3% preference for arcs whose ends are
                # real junctions, i.e. the grid (contracts §3.5).
                ratio = delta / max(gain, 1.0)
                if min(g.degree[g.e_u[ei]], g.degree[g.e_v[ei]]) >= 3:
                    ratio *= 0.97
                options.append((ratio, g.e_seg[ei], ei, delta, pos, a, b))
            if not options:
                break
            options.sort()
            pick = 0
            if randomised and len(options) > 1:
                k = min(3, len(options))
                pick = self.rng.randrange(k)
            _, _, ei, delta, pos, a, b = options[pick]
            self.insert(sol, ei, delta, pos, a, b)
            pool.remove(ei)
        return sol

    # -- local search

    def two_opt(self, sol: _Sol) -> bool:
        """Reverse a run of serviced arcs (flipping each) if it shortens the walk."""
        arcs = sol.arcs
        n = len(arcs)
        if n < 2:
            return False
        improved = False
        for i in range(n):
            p = self.anchor if i == 0 else arcs[i - 1][2]
            for j in range(i + 1, n):
                nx = self.anchor if j == n - 1 else arcs[j + 1][1]
                cur = self.d(p, arcs[i][1]) + self.d(arcs[j][2], nx)
                new = self.d(p, arcs[j][2]) + self.d(arcs[i][1], nx)
                if new < cur - 1e-6:
                    rev = [(e, b, a) for e, a, b in arcs[i:j + 1]][::-1]
                    arcs[i:j + 1] = rev
                    sol.length -= (cur - new)
                    improved = True
                    p = self.anchor if i == 0 else arcs[i - 1][2]
        return improved

    def or_opt(self, sol: _Sol) -> bool:
        """Relocate one serviced arc to its cheapest position."""
        improved = False
        for i in range(len(sol.arcs)):
            if time.monotonic() > self.deadline:
                break
            ei, a, b = sol.arcs[i]
            _, gain = self.remove(sol, i)
            bi = self.best_insertion(sol, ei, _INF)
            if bi is not None and bi[0] < gain - 1e-6:
                delta, pos, na, nb, _bonus = bi
                self.insert(sol, ei, delta, pos, na, nb)
                improved = True
            else:
                self.insert(sol, ei, gain, i, a, b)
        return improved

    def improve(self, sol: _Sol) -> None:
        for _ in range(3):
            if time.monotonic() > self.deadline:
                return
            a = self.two_opt(sol)
            b = self.or_opt(sol)
            if not (a or b):
                return

    def ruin(self, sol: _Sol, route: dict | None = None) -> None:
        """Tear part of the walk out so insertion can rebuild it differently.

        Two thirds of the time this is *aimed*: it removes whatever the walk
        was servicing inside its longest doubled-back stretch, which is the
        move that turns an out-and-back into a loop. The rest of the time it
        removes a random run, to keep the search from getting stuck on one
        idea.
        """
        if not sol.arcs:
            return
        if route is not None and self.rng.random() < 0.67:
            doomed = self._arcs_in_worst_run(sol, route)
            if doomed:
                for i in sorted(doomed, reverse=True):
                    self.remove(sol, i)
                return
        k = min(self.rng.randint(1, 3), len(sol.arcs))
        i = self.rng.randrange(len(sol.arcs) - k + 1)
        for _ in range(k):
            self.remove(sol, i)

    def _arcs_in_worst_run(self, sol: _Sol, route: dict) -> list[int]:
        """Serviced arcs sitting inside the walk's longest repeated stretch."""
        spans = getattr(self, "_spans", None)
        if not spans or len(spans) != len(sol.arcs):
            return []
        seg_ids = route["seg_ids"]
        counts: dict[int, int] = {}
        for s in seg_ids:
            counts[s] = counts.get(s, 0) + 1
        best = (0.0, 0, 0)
        run_m, run_from = 0.0, 0
        for i, s in enumerate(seg_ids):
            if counts[s] > 1:
                if run_m == 0.0:
                    run_from = i
                run_m += self.g.segments[s]["length_m"]
            elif run_m:
                if run_m > best[0]:
                    best = (run_m, run_from, i)
                run_m = 0.0
        if run_m > best[0]:
            best = (run_m, run_from, len(seg_ids))
        if best[0] <= _RUN_FREE_M:
            return []
        _, lo_i, hi_i = best
        return [j for j, (a, b) in enumerate(spans) if a < hi_i and b > lo_i]

    # -- budget filling

    def fill(self, sol: _Sol, req: list[int]) -> None:
        """Top the walk back up to the target with more uncovered street."""
        used = set(sol.counts)
        pool = [ei for ei in req if ei not in used]
        while pool and sol.length < self.aim:
            if time.monotonic() > self.deadline:
                return
            best = None
            for ei in self._near_tour(sol, pool, _NEAR_TOUR):
                bi = self.best_insertion(sol, ei, self.cap)
                if bi is None:
                    continue
                delta, pos, a, b, bonus = bi
                ratio = delta / max(self.prize[ei] + bonus, 1.0)
                if best is None or ratio < best[0]:
                    best = (ratio, ei, delta, pos, a, b)
            if best is None:
                return
            _, ei, delta, pos, a, b = best
            self.insert(sol, ei, delta, pos, a, b)
            pool.remove(ei)

    def pad(self, sol: _Sol) -> None:
        """Last resort: reach the bottom of the band with anything walkable.

        Only runs when the uncovered street nearby has run out — a small
        component, or a target longer than the neighbourhood. Repeats are
        capped so a tiny component returns a short honest loop instead of
        pacing the same street twenty times.
        """
        guard = 0
        while sol.length < self.lo and guard < 240:
            guard += 1
            if time.monotonic() > self.deadline:
                return
            need = self.target - sol.length
            best = None
            pool = [e for e in self.filler if not self.g.isolated[e]] or self.filler
            for ei in self._near_tour(sol, pool, _NEAR_TOUR * 2):
                if sol.counts.get(ei, 0) >= _MAX_REPEATS:
                    continue
                bi = self.best_insertion(sol, ei, self.cap)
                if bi is None:
                    continue
                delta, pos, a, b, _bonus = bi
                if delta <= 1e-6:
                    continue
                score = abs(need - delta)
                if best is None or score < best[0]:
                    best = (score, ei, delta, pos, a, b)
            if best is None:
                return
            _, ei, delta, pos, a, b = best
            self.insert(sol, ei, delta, pos, a, b)

    # -- expansion

    def expand(self, sol: _Sol, go_around: bool = False) -> dict:
        """Turn the arc sequence into an actual walk.

        Deadhead between serviced arcs is normally the shortest path, which is
        why an insertion solver alone can only ever double back: the cheapest
        way to the next street is usually the street you just walked. With
        ``go_around`` the connectors are re-routed as they are laid down, on
        weights that treble the cost of ground already covered — so if there is
        a way round the block within reach, the walk takes it. Costs one
        Dijkstra per connector, so it is only run on walks that are actually
        doubling back (see ``finish``), and the result is only kept if it
        scores better.
        """
        g = self.g
        seg_ids: list[int] = []
        coords: list[tuple[float, float]] = []
        at = self.anchor
        used: dict[int, int] = {}
        # Detours lengthen the walk, and the walker asked for a time, not a
        # shape. Going round the block is only allowed while it fits.
        slack = [max(0.0, self.cap - sol.length)]

        def connector(frm: int, to: int) -> list[int]:
            plain = self.path_edges(frm, to)
            if not go_around or not plain:
                return plain
            if not any(used.get(e) for e in plain):
                return plain                       # not retracing anything
            base = sum(g.e_len[e] for e in plain)
            w = [self.weight[e] * (1.0 + 2.0 * used.get(e, 0))
                 for e in range(len(g.e_seg))]
            _, _, prev, _ = g.dijkstra(frm, w, base * 3.0 + 300.0)
            alt, cur = [], to
            while cur != frm:
                step = prev.get(cur)
                if step is None:
                    return plain
                p, e = step
                alt.append(e)
                cur = p
            alt.reverse()
            # Only worth it if the detour is a detour, not an expedition,
            # and only while there is budget left to pay for it.
            alt_m = sum(g.e_len[e] for e in alt)
            if alt_m > base * 2.5 + 200.0 or alt_m - base > slack[0]:
                return plain
            slack[0] -= (alt_m - base)
            return alt

        def walk_edge(ei: int, frm: int):
            nonlocal at
            used[ei] = used.get(ei, 0) + 1
            seg = g.segments[g.e_seg[ei]]
            c = seg["coords"]
            if g.e_u[ei] != frm:                  # walking it from node_b to node_a
                c = c[::-1]
            if not coords:
                coords.extend(c)
            else:
                coords.extend(c[1:] if c[0] == coords[-1] else c)
            seg_ids.append(seg["seg_id"])
            at = g.e_v[ei] if g.e_u[ei] == frm else g.e_u[ei]

        # Where each serviced arc (and the deadhead that reaches it) lands in
        # the walk, so ruin-and-recreate can aim at a specific stretch of it.
        spans: list[tuple[int, int]] = []
        for ei, a, b in sol.arcs:
            first = len(seg_ids)
            for pe in connector(at, a):
                walk_edge(pe, at)
            walk_edge(ei, a)
            spans.append((first, len(seg_ids)))
            at = b
        for pe in connector(at, self.anchor):
            walk_edge(pe, at)
        self._spans = spans

        alon, alat = g.node_lonlat[self.anchor]
        if not coords:
            coords = [(alon, alat), (alon, alat)]
        length_m = sum(g.segments[s]["walk_m"] for s in seg_ids)
        new_ids: list[int] = []
        seen = set()
        for s in seg_ids:
            if s not in self.covered and s not in seen:
                seen.add(s)
                new_ids.append(s)
        new_m = sum(g.segments[s]["length_m"] for s in new_ids)
        return {
            "seg_ids": seg_ids,
            "new_seg_ids": new_ids,
            "geometry": LineString(coords),
            "length_m": round(length_m, 2),
            "new_m": round(new_m, 2),
        }

    # -- objective (contract §3, lexicographic)

    def score(self, route: dict) -> tuple:
        """The contract's priorities, in order, as a sortable key.

        Closure is structural, so priority 1 needs no term. Then the length
        band, then *shape*, then new metres, then contiguity, then shorter.

        Shape sits above new_m deliberately, and it is quantised so that it
        only overrules new_m when the difference is real. A 2.4 mile walk that
        is 62% new street but spends a mile of it pacing a rural road is worse
        than a 2.4 mile walk that is 80% new street around one neighbourhood,
        and before this term the engine could not tell them apart.
        """
        L = route["length_m"]
        dev = abs(L - self.target) / self.target if self.target else 0.0
        # Inside ±10% counts as hitting the time asked for; past that each 5%
        # is a step worse, and outside the contract's ±15% band is a cliff no
        # amount of good shape can climb back over. The free window stops the
        # engine buying shape with the walker's time, without making it
        # chase the exact metre at the cost of a worse walk.
        band = round(max(0.0, dev - 0.10) / 0.05)
        if dev > BAND:
            band += 100
        shape = _shape_penalty(self.g, route)
        cont = _contiguity_ids(self.g, route["new_seg_ids"])
        return (
            band,
            round(shape / _SHAPE_BUCKET),
            -round(route["new_m"], 2),
            -round(cont, 4),
            L,
        )


# --------------------------------------------------------------------- shape --


def _repeat_runs(g: RouteGraph, seg_ids: Sequence[int]) -> list[float]:
    """Lengths of the contiguous stretches the walk covers more than once.

    Run length is what matters, not the total. A 120 m out-and-back into a
    cul-de-sac is unavoidable and fine. A 1.6 km out-and-back along one rural
    road is the walk failing: it is dull, and it gives the walker no signal
    about where to turn around.
    """
    counts: dict[int, int] = {}
    for s in seg_ids:
        counts[s] = counts.get(s, 0) + 1
    runs: list[float] = []
    cur = 0.0
    for s in seg_ids:
        seg = g.segments.get(s)
        if seg is not None and counts[s] > 1:
            cur += seg["length_m"]
        elif cur:
            runs.append(cur)
            cur = 0.0
    if cur:
        runs.append(cur)
    return runs


def _compactness(route: dict) -> float:
    """4·pi·area / length² over the walk's convex hull. 1.0 is a circle.

    A loop encloses ground; a thread encloses none. Measured on routes a
    person judged good this lands at 0.36-0.57, and on ones they rejected at
    0.22-0.30.
    """
    L = route["length_m"]
    if L <= 0:
        return 1.0
    pts = list(route["geometry"].coords)
    if len(pts) < 3:
        return 0.0
    lat0 = sum(p[1] for p in pts) / len(pts)
    sx = _EARTH_M_PER_DEG * math.cos(math.radians(lat0))
    flat = LineString([((x - pts[0][0]) * sx, (y - pts[0][1]) * _EARTH_M_PER_DEG)
                       for x, y in pts])
    return 4.0 * math.pi * flat.convex_hull.area / (L * L)


def _shape_penalty(g: RouteGraph, route: dict) -> float:
    """0 = a compact loop. Grows with threadiness, repetition and long runs."""
    L = route["length_m"]
    if L <= 0:
        return 0.0
    runs = _repeat_runs(g, route["seg_ids"])
    run_excess = sum(max(0.0, r - _RUN_FREE_M) for r in runs)

    counts: dict[int, int] = {}
    for s in route["seg_ids"]:
        counts[s] = counts.get(s, 0) + 1
    wasted = sum(g.segments[s]["length_m"] * (n - 1)
                 for s, n in counts.items() if s in g.segments)

    return (
        _W_RUN * (run_excess / L)
        + _W_REPEAT * max(0.0, wasted / L - _REPEAT_FREE_FRAC)
        + _W_COMPACT * max(0.0, _COMPACT_TARGET - _compactness(route)) / _COMPACT_TARGET
    )


# ---------------------------------------------------------------- contiguity --


def _contiguity_ids(g: RouteGraph, seg_ids: Sequence[int]) -> float:
    """Share of new metres sitting in the single largest connected block.

    1.0 = one neighbourhood. 0.3 = confetti. Union-find over shared node ids.
    """
    ids = [s for s in seg_ids if s in g.edge_of_seg]
    if len(ids) <= 1:
        return 1.0
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for s in ids:
        seg = g.segments[s]
        a, b = find(seg["node_a"]), find(seg["node_b"])
        if a != b:
            parent[a] = b
    blocks: dict[str, float] = {}
    total = 0.0
    for s in ids:
        seg = g.segments[s]
        r = find(seg["node_a"])
        blocks[r] = blocks.get(r, 0.0) + seg["length_m"]
        total += seg["length_m"]
    return max(blocks.values()) / total if total else 1.0


def contiguity(route_or_ids: Any, network: Any) -> float:
    """Contiguity of a route's *new* segments, 0..1 (contract §3.4)."""
    g = build_graph(network)
    if isinstance(route_or_ids, dict):
        ids = route_or_ids.get("new_seg_ids") or route_or_ids.get("seg_ids") or []
    else:
        ids = list(route_or_ids)
    return _contiguity_ids(g, ids)


def route_stats(route: dict, network: Any, start_lonlat: Sequence[float] | None = None) -> dict:
    """Everything the contract asks to be measured, in one dict."""
    g = build_graph(network)
    geom = route["geometry"]
    pts = list(geom.coords)
    close_m = _flat_m(pts[0][0], pts[0][1], pts[-1][0], pts[-1][1])
    to_start = None
    if start_lonlat is not None:
        to_start = _flat_m(start_lonlat[0], start_lonlat[1], pts[-1][0], pts[-1][1])
    segs = [g.segments[s] for s in route["seg_ids"] if s in g.segments]
    # Repeat traversal, split honestly: a cul-de-sac must be walked twice, and
    # that is not the same failing as pacing a through street twice.
    counts: dict[int, int] = {}
    for s in route["seg_ids"]:
        counts[s] = counts.get(s, 0) + 1
    forced = avoidable = 0.0
    for s, n in counts.items():
        if n < 2 or s not in g.segments:
            continue
        seg = g.segments[s]
        extra = seg["length_m"] * (n - 1)
        ei = g.edge_of_seg.get(s)
        # Forced = the segment is a bridge: a cul-de-sac stem or the single
        # road into a subdivision. There is no way back except back over it.
        # Well over a third of this network is bridges by length, so a walk
        # with repeats is usually obeying the town, not wasting the walker.
        forced_repeat = ei is not None and g.is_bridge[ei]
        if forced_repeat:
            forced += extra
        else:
            avoidable += extra
    runs = _repeat_runs(g, route["seg_ids"])
    # Metres spent going up and back down a rural connector — the specific
    # failure this engine was rebuilt to stop. Passing along one *once*, as the
    # only link to a neighbourhood, is not counted: that is what links are for.
    paced_connector = sum(
        g.segments[s]["length_m"] * n
        for s, n in counts.items()
        if n > 1 and s in g.edge_of_seg and g.isolated[g.edge_of_seg[s]]
    )
    return {
        "compactness": round(_compactness(route), 3),
        "shape_penalty": round(_shape_penalty(g, route), 3),
        "max_repeat_run_m": round(max(runs), 1) if runs else 0.0,
        "repeat_runs": len(runs),
        "paced_connector_m": round(paced_connector, 1),
        "repeat_m": round(forced + avoidable, 2),
        "repeat_forced_m": round(forced, 2),     # dead ends: unavoidable
        "repeat_avoidable_m": round(avoidable, 2),
        "closure_m": round(close_m, 2),
        "end_to_start_m": None if to_start is None else round(to_start, 2),
        "length_m": route["length_m"],
        "new_m": route["new_m"],
        "new_fraction": (route["new_m"] / route["length_m"]) if route["length_m"] else 0.0,
        "contiguity": round(_contiguity_ids(g, route["new_seg_ids"]), 4),
        "new_blocks": _blocks(g, route["new_seg_ids"]),
        "span_m": round(_span(g, route["new_seg_ids"]), 1),
        "n_segments": len(route["seg_ids"]),
        "n_new": len(route["new_seg_ids"]),
        "deadhead_m": round(route["length_m"] - route["new_m"], 2),
        "streets": sorted({s["name"] for s in segs if s["name"]}),
        "minutes": round(minutes_for_meters(route["length_m"]), 1),
    }


def _span(g: RouteGraph, seg_ids: Sequence[int]) -> float:
    """Widest straight-line gap between any two claimed segments, in metres.

    The other half of contiguity: a small span means the walk filled in one
    part of town. A single closed walk cannot spread further than about half
    its own length, which is why scattered spurs are structurally impossible
    here rather than merely discouraged.
    """
    mids = []
    for s in seg_ids:
        seg = g.segments.get(s)
        if seg:
            c = seg["coords"][len(seg["coords"]) // 2]
            mids.append(c)
    worst = 0.0
    for i, a in enumerate(mids):
        for b in mids[i + 1:]:
            d = _flat_m(a[0], a[1], b[0], b[1])
            if d > worst:
                worst = d
    return worst


def _blocks(g: RouteGraph, seg_ids: Sequence[int]) -> int:
    ids = [s for s in seg_ids if s in g.segments]
    if not ids:
        return 0
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for s in ids:
        seg = g.segments[s]
        a, b = find(seg["node_a"]), find(seg["node_b"])
        if a != b:
            parent[a] = b
    return len({find(g.segments[s]["node_a"]) for s in ids})


# ------------------------------------------------------------------- public --


def generate(start_lonlat, target_m, network, covered=None, *, seed=None) -> dict:
    """Generate a closed prayer walk. See module docstring for the formulation.

    start_lonlat : (lon, lat)
    target_m     : desired walk length in metres  (minutes * 80.47)
    network      : segment set — FeatureCollection, feature list, or row list
    covered      : set of seg_ids already claimed; they still may be walked as
                   deadhead but earn nothing
    seed         : any hashable; identical inputs give an identical route
    """
    deadline = time.monotonic() + _TIME_BUDGET_S
    g = build_graph(network)
    covered = set(int(c) for c in (covered or ()))
    target_m = float(target_m)
    lon, lat = float(start_lonlat[0]), float(start_lonlat[1])

    if not g.e_seg:
        return {"seg_ids": [], "new_seg_ids": [], "length_m": 0.0, "new_m": 0.0,
                "geometry": LineString([(lon, lat), (lon, lat)])}

    anchor = g.nearest_node(lon, lat)
    rng = random.Random(0 if seed is None else seed)

    if target_m <= 0:
        alon, alat = g.node_lonlat[anchor]
        return {"seg_ids": [], "new_seg_ids": [], "length_m": 0.0, "new_m": 0.0,
                "geometry": LineString([(alon, alat), (alon, alat)])}

    solver = _Solver(g, anchor, target_m, covered, rng, deadline)
    req = solver.candidates()
    if not req:                      # nothing new within reach: walk anyway
        req = solver.filler[:_MAX_CANDIDATES]

    best_route = None
    best_key = None

    def finish(sol: _Sol, rounds: int = 2):
        # One round is enough after a small ruin; the full treatment is only
        # worth it on a freshly constructed walk.
        for _ in range(rounds):
            solver.improve(sol)
            solver.fill(sol, req)
            if time.monotonic() > deadline:
                break
        if sol.length < solver.lo:
            solver.pad(sol)
        route = solver.expand(sol)
        key = solver.score(route)
        # If it doubles back a long way, see whether the deadhead can go round
        # instead. Kept only if the walk that produces is genuinely better.
        runs = _repeat_runs(g, route["seg_ids"])
        if runs and max(runs) > _RUN_FREE_M and time.monotonic() < deadline:
            alt = solver.expand(sol, go_around=True)
            alt_key = solver.score(alt)
            if alt_key < key:
                route, key = alt, alt_key
            else:
                solver.expand(sol)     # restore the spans of the kept walk
        return route, key

    for r in range(_RESTARTS):
        # Each restart is seeded on a different arc, so the restarts try
        # different neighbourhoods instead of re-deriving the same one.
        # Seeds spread across the whole candidate list, which is sorted by
        # distance from the start. Seeding only on the nearest arcs anchors
        # every restart to the same few streets; if the good neighbourhood is
        # 500 m away, no amount of local search will find it from there.
        seeds = [e for e in req if not g.isolated[e]] or req
        first = seeds[(r * len(seeds)) // _RESTARTS] if (r and seeds) else None
        sol = solver.construct(req, randomised=(r > 0), first=first)
        route, key = finish(sol)
        if best_key is None or key < best_key:
            best_key, best_route = key, route

        # Ruin and recreate: tear a short run of serviced arcs out of the walk
        # and let the insertion heuristic rebuild it. This is what gets a route
        # out of the local minimum where it walks a street twice because the
        # arcs happened to be inserted in an awkward order.
        cur_key, cur_route = key, route
        for _ in range(_RUIN_ITERS):
            if time.monotonic() > deadline:
                break
            cand = sol.copy()
            solver.ruin(cand, cur_route)
            c_route, c_key = finish(cand, rounds=1)
            if c_key < cur_key:
                sol, cur_key, cur_route = cand, c_key, c_route
                if c_key < best_key:
                    best_key, best_route = c_key, c_route
        if time.monotonic() > deadline:
            break

    return best_route
