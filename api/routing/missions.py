"""Mission discovery: which unfinished area, which starting point, which route.

The routing engine answers *"given a start and a budget, find a strong closed walk."*
This module answers the question one level up: *"given a budget and the current state
of the project, where should someone go?"*

It sits **beside** the engine and only calls its public entry points. `best_route` is
not modified, re-tuned or reached into. If this module were deleted the engine would
behave exactly as it does today.

DELIBERATELY DOMAIN-NEUTRAL. The vocabulary here is coverage, clusters, route budget,
candidate starts and assignment — concepts any coverage problem shares. Nothing in this
file knows the walks are prayer walks, that `Segment.households` counts homes, or what
a mission is called. Naming and presentation live in `api/app/services/mission_service`.
The one concession is that `Segment.households` keeps its existing name, because it is
persisted in stored score components and renaming it would break replay (docs/17 §7).
It is read here as `value`.

The search is deliberately shallow: a handful of clusters, a handful of candidate
starts each. At ~15 ms per route that is well under a second, which keeps this
on-demand and avoids a precompute/invalidate layer that this stage of the product does
not need yet.
"""
from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass, field

import numpy as np

M_PER_MILE = 1609.344

# How many clusters of remaining coverage to consider, best first.
MAX_CLUSTERS = 8
# Candidate start nodes tried per cluster. Adaptive: a cluster many times larger than
# the budget deserves more probes, because it holds many genuinely different walks.
#
# This matters most at the *start* of a project. At 0% completion every incomplete
# segment in the main component is one connected cluster — 130 of the town's 145
# miles — so "one mission per cluster" yields one mission. Clusters only become a
# useful diversity axis once coverage has fragmented. Overlap does the work instead;
# see `_overlap`.
STARTS_PER_CLUSTER = 3
MAX_STARTS_PER_CLUSTER = 14
# Total routes evaluated per request, to bound latency.
MAX_ROUTE_EVALUATIONS = 26
# A cluster smaller than this is not worth a dedicated trip; it will be picked up as
# part of a neighbouring cluster's route instead.
MIN_CLUSTER_MILES = 0.15
# Two missions covering more than this share of the same ground are the same mission
# wearing a different hat. This is the diversity axis that works at every stage of a
# project, unlike cluster identity.
MAX_OVERLAP = 0.35
# A mission scoring below this fraction of the best one is not offered as an
# alternative. Documented tolerance for Priority 10.
QUALITY_TOLERANCE = 0.70
# Multiplier applied to coverage another walker currently holds.
RESERVED_VALUE_MULTIPLIER = 0.15


@dataclass
class CandidateStart:
    node_index: int
    lon: float
    lat: float
    degree: int
    streets: list           # street names meeting at this node, for a human description


@dataclass
class Mission:
    id: str
    cluster_id: int
    start: CandidateStart
    route: object                      # routing.state.Route
    budget_miles: float
    distance_miles: float
    new_coverage_miles: float
    value: int                         # sum of Segment.households on new coverage
    score: float
    completes_cluster: bool
    cluster_remaining_miles: float
    # {label: miles of new coverage carrying that label}. The application layer turns
    # this into a sentence; this module does not know what the labels mean.
    area_labels: dict = field(default_factory=dict)
    segment_ids: list = field(default_factory=list)
    required_segment_ids: list = field(default_factory=list)
    reserved_overlap: int = 0
    meta: dict = field(default_factory=dict)


# --------------------------------------------------------------------- clusters
def coverage_clusters(net, state) -> list[dict]:
    """Connected groups of incomplete required coverage, town-wide.

    Deliberately not `Engine.discover_clusters`: that one is scoped to a walker's
    component and scores each cluster by how far the walker must travel to reach it.
    Both of those assumptions exist only because the start is imposed from outside.
    Here there is no walker yet, so the clustering is plain connectivity.
    """
    incomplete = [s.idx for s in net.segments
                  if s.required and not state.is_complete(s.idx)]
    if not incomplete:
        return []

    parent = {i: i for i in incomplete}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    by_node = defaultdict(list)
    for i in incomplete:
        s = net.segments[i]
        by_node[s.u].append(i)
        by_node[s.v].append(i)
    for members in by_node.values():
        first = members[0]
        for other in members[1:]:
            ra, rb = find(first), find(other)
            if ra != rb:
                parent[rb] = ra

    groups = defaultdict(list)
    for i in incomplete:
        groups[find(i)].append(i)

    out = []
    for root, members in groups.items():
        length = sum(net.segments[i].length_m for i in members)
        if length / M_PER_MILE < MIN_CLUSTER_MILES:
            continue
        out.append(dict(
            id=root, members=members,
            miles=length / M_PER_MILE,
            value=sum(net.segments[i].households for i in members),
        ))
    return out


def rank_clusters(clusters, budget_miles) -> list[dict]:
    """Best clusters first.

    Prefers clusters that a walk of this budget can make real progress on. A cluster
    far larger than the budget is still fine — you chip at it — but one that the budget
    can *finish* is worth more, because finishing an area is both motivating and good
    for the endgame: it avoids leaving scattered fragments behind.
    """
    for c in clusters:
        fit = min(c["miles"], budget_miles) / max(budget_miles, 0.01)
        finishable = 1.0 if c["miles"] <= budget_miles * 0.95 else 0.0
        c["cluster_score"] = (
            fit * 100.0
            + finishable * 35.0
            + min(c["value"], 1500) * 0.05
            + min(c["miles"], 10.0) * 2.0
        )
    return sorted(clusters, key=lambda c: -c["cluster_score"])


# ---------------------------------------------------------------------- starts
def starts_wanted(cluster, budget_miles: float) -> int:
    """How many places to probe in this cluster."""
    ratio = cluster["miles"] / max(budget_miles, 0.01)
    return int(max(STARTS_PER_CLUSTER, min(MAX_STARTS_PER_CLUSTER, round(ratio))))


def candidate_starts(net, graph, cluster, limit=STARTS_PER_CLUSTER) -> list[CandidateStart]:
    """Plausible places to begin a walk in this cluster.

    Quality rules from Priority 5, in the order they matter:

      - on routable geometry            guaranteed: only graph nodes are considered
      - a recognisable place            prefer junctions, and prefer named streets
      - not an obscure dead end         degree 1 nodes are excluded outright
      - supports a coherent loop        not decided here; the route result decides it
      - spread out                      candidates are taken from different parts of
                                        the cluster, so three tries explore three
                                        places rather than three adjacent corners
    """
    scored = []
    seen_nodes = set()
    for i in cluster["members"]:
        seg = net.segments[i]
        for node_id, coord in ((seg.u, seg.coords[0] if seg.coords else None),
                               (seg.v, seg.coords[-1] if seg.coords else None)):
            if node_id in seen_nodes or coord is None:
                continue
            seen_nodes.add(node_id)
            ni = graph.node_index.get(node_id)
            if ni is None:
                continue
            neighbours = net.adjacency.get(node_id, ())
            degree = len(neighbours)
            if degree < 2:
                continue                       # a dead end is a poor place to meet
            streets = sorted({net.segments[si].display_name
                              for _, si in neighbours
                              if net.segments[si].display_name})
            # A junction of two named streets is the easiest thing to find on a map.
            score = degree * 2.0 + len(streets) * 3.0 + (4.0 if len(streets) >= 2 else 0.0)
            scored.append((score, CandidateStart(
                node_index=ni, lon=float(coord[0]), lat=float(coord[1]),
                degree=degree, streets=streets)))

    scored.sort(key=lambda x: -x[0])

    # Spread: skip candidates very close to one already chosen, so the tries explore
    # different parts of the cluster instead of one busy intersection.
    chosen: list[CandidateStart] = []
    for _, cand in scored:
        if len(chosen) >= limit:
            break
        # Spread scales with how many we want: probing a 130-mile cluster from three
        # adjacent downtown corners would find three versions of the same walk.
        min_sep = 250.0 if limit <= 4 else 700.0
        if any(_rough_m(cand, c) < min_sep for c in chosen):
            continue
        chosen.append(cand)
    if not chosen and scored:
        chosen = [scored[0][1]]
    return chosen


def _rough_m(a: CandidateStart, b: CandidateStart) -> float:
    dx = (a.lon - b.lon) * 88_800.0
    dy = (a.lat - b.lat) * 111_320.0
    return float(np.hypot(dx, dy))


# -------------------------------------------------------------------- missions
def _overlap(a: "Mission", b: "Mission") -> float:
    """Share of the smaller mission's coverage that the larger one also covers."""
    sa, sb = set(a.required_segment_ids), set(b.required_segment_ids)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / min(len(sa), len(sb))


def _mission_id(net, start_node: int, budget_miles: float, seg_ids) -> str:
    h = hashlib.sha256()
    h.update(net.network_id.encode())
    h.update(str(start_node).encode())
    h.update(f"{budget_miles:.2f}".encode())
    for s in seg_ids:
        h.update(s.encode())
    return h.hexdigest()[:16]


def score_mission(net, state, route, budget_miles, reserved: set) -> tuple[float, int, int]:
    """How good a mission is, on terms a person would recognise.

    Deliberately NOT the engine's route score. That one balances a dozen routing
    concerns against each other and is the right objective for choosing between routes
    from a fixed start. Choosing between *places to go* is a different question, and it
    is dominated by: how much unfinished ground does this cover, how much value is on
    it, and is somebody already there.
    """
    covered = route.required_covered(net)
    new = [i for i in covered if not state.is_complete(i)]
    new_miles = sum(net.segments[i].length_m for i in new) / M_PER_MILE
    value = sum(net.segments[i].households for i in new)
    overlap = sum(1 for i in new if i in reserved)

    fit = 1.0 - min(abs(route.miles(net) - budget_miles) / max(budget_miles, 0.01), 1.0)
    quality = (route.score.walk_quality / 100.0) if route.score else 0.5
    reserved_share = overlap / max(len(new), 1)

    score = (new_miles * 100.0
             + min(value, 2000) * 0.20
             + fit * 40.0
             + quality * 30.0
             - reserved_share * 120.0)
    return score, round(new_miles, 3), value


def discover(net, engine, state, budget_miles: float, reserved_indices: set | None = None,
             slate_size: int = 5, seed: int | None = None) -> list[Mission]:
    """A ranked slate of missions for this budget.

    Returns several genuinely different places, not one answer and four variations, so
    that simultaneous participants can be given different work (Priority 10).
    """
    reserved = set(reserved_indices or ())
    clusters = rank_clusters(coverage_clusters(net, state), budget_miles)
    if not clusters:
        return []

    missions: list[Mission] = []
    evaluated = 0

    for cluster in clusters[:MAX_CLUSTERS]:
        if evaluated >= MAX_ROUTE_EVALUATIONS:
            break
        want = starts_wanted(cluster, budget_miles)
        for cand in candidate_starts(net, engine.g, cluster, limit=want):
            if evaluated >= MAX_ROUTE_EVALUATIONS:
                break
            evaluated += 1
            route, meta = engine.best_route(cand.node_index, budget_miles, state)
            if route is None:
                continue
            score, new_miles, value = score_mission(net, state, route, budget_miles,
                                                    reserved)
            if new_miles < 0.1:
                continue                      # nothing meaningful gained
            covered = route.required_covered(net)
            new = [i for i in covered if not state.is_complete(i)]

            labels: dict = defaultdict(float)
            for i in new:
                lbl = net.segments[i].neighborhood
                labels[lbl or "__unlabelled__"] += net.segments[i].length_m / M_PER_MILE

            seg_ids = [net.segments[i].id for i in route.seg_seq]
            missions.append(Mission(
                id=_mission_id(net, cand.node_index, budget_miles, seg_ids),
                cluster_id=cluster["id"], start=cand, route=route,
                budget_miles=budget_miles,
                distance_miles=round(route.miles(net), 2),
                new_coverage_miles=new_miles, value=value, score=score,
                completes_cluster=new_miles >= cluster["miles"] - 0.05,
                cluster_remaining_miles=round(cluster["miles"], 2),
                area_labels={k: round(v, 3) for k, v in
                             sorted(labels.items(), key=lambda x: -x[1])},
                segment_ids=seg_ids,
                required_segment_ids=sorted(net.segments[i].id for i in covered),
                reserved_overlap=sum(1 for i in new if i in reserved),
                meta=dict(cluster_score=round(cluster["cluster_score"], 1),
                          engine=meta),
            ))

    if not missions:
        return []

    missions.sort(key=lambda m: -m.score)
    best = missions[0].score

    # Greedy: take the best, then the best that does not retread it, and so on.
    # Alternatives stay within a documented quality tolerance of the top result —
    # variety is not worth sending someone on a materially worse walk (Priority 10).
    slate: list[Mission] = []
    for m in missions:
        if len(slate) >= slate_size:
            break
        if slate and m.score < best * QUALITY_TOLERANCE:
            continue
        if any(_overlap(m, chosen) > MAX_OVERLAP for chosen in slate):
            continue
        slate.append(m)
    return slate
