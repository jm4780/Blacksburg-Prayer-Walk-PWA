"""Completion state and the Route object.

The engine holds no state of its own — a CompletionState is passed in per request.
That is what makes multiplayer straightforward later: two walkers routing at the same
moment each get the current state, and soft reservations become a prize multiplier
rather than a graph edit.
"""
from __future__ import annotations

import math
import random
from collections import defaultdict
from dataclasses import dataclass, field

M_PER_MILE = 1609.344

# Deviation from straight, in radians, that counts as a sharp turn (~60 degrees).
SHARP_TURN_RAD = 1.05


class CompletionState:
    """Which REQUIRED segments are already walked, plus optional soft reservations."""

    def __init__(self, net, complete: set[int] | None = None,
                 reserved: dict[int, float] | None = None):
        self.net = net
        self.complete = set(complete or ())
        # seg_idx -> prize multiplier in [0,1]. Reserved-by-someone-else edges are
        # damped, not removed, so a second walker is nudged rather than blocked (§21).
        self.reserved = dict(reserved or {})
        self._neighbour_cache: dict[int, int] = {}
        self._corridors = None

    # ------------------------------------------------------------------ query
    def is_complete(self, seg_idx: int) -> bool:
        return seg_idx in self.complete

    def prize_multiplier(self, seg_idx: int) -> float:
        return self.reserved.get(seg_idx, 1.0)

    def incomplete_required(self) -> list[int]:
        return [s.idx for s in self.net.segments
                if s.required and s.idx not in self.complete]

    def incomplete_miles(self) -> float:
        return sum(self.net.segments[i].length_m
                   for i in self.incomplete_required()) / M_PER_MILE

    def completion_fraction(self) -> float:
        req = [s for s in self.net.segments if s.required]
        if not req:
            return 1.0
        done = sum(s.length_m for s in req if s.idx in self.complete)
        return done / sum(s.length_m for s in req)

    def incomplete_neighbours(self, net, seg_idx: int) -> int:
        """How many incomplete REQUIRED segments touch this one. Drives the
        isolation bonus: a leftover with no incomplete neighbours is a true orphan
        and worth extra to clear."""
        key = seg_idx
        cached = self._neighbour_cache.get(key)
        if cached is not None:
            return cached
        seg = net.segments[seg_idx]
        count = 0
        for node in (seg.u, seg.v):
            for _, other in net.adjacency.get(node, ()):
                if other == seg_idx:
                    continue
                o = net.segments[other]
                if o.required and other not in self.complete:
                    count += 1
        self._neighbour_cache[key] = count
        return count

    def corridor_progress(self, net, covered: set[int]) -> tuple[int, int]:
        """(corridors touched, corridors this route completes).

        A "corridor" is a normalized street name. Completing one means every REQUIRED
        segment of that name is either already complete or covered by this route.
        """
        if self._corridors is None:
            c = defaultdict(list)
            for s in net.segments:
                if s.required and s.normalized_name:
                    c[s.normalized_name].append(s.idx)
            self._corridors = dict(c)
        touched, completed = set(), 0
        for idx in covered:
            nm = net.segments[idx].normalized_name
            if nm:
                touched.add(nm)
        for nm in touched:
            members = self._corridors.get(nm, ())
            if members and all(m in self.complete or m in covered for m in members):
                completed += 1
        return len(touched), completed

    # ------------------------------------------------------------ construction
    @classmethod
    def at_fraction(cls, net, fraction: float, seed: int = 0,
                    mode: str = "spatial") -> "CompletionState":
        """Synthetic completion state for stress testing.

        `spatial` completes whole neighbourhoods first, which is how a real project
        progresses — congregations work outward from where they live. `random` scatters
        completion, which is the harder case for the router and a useful upper bound on
        difficulty.
        """
        req = [s for s in net.segments if s.required]
        target = fraction * sum(s.length_m for s in req)
        rng = random.Random(seed)
        if mode == "random":
            order = req[:]
            rng.shuffle(order)
        else:
            # Grow from a random seed node, breadth-first, so completed area is contiguous.
            start = rng.choice(req)
            order, seen = [], set()
            frontier = [start.idx]
            seen.add(start.idx)
            while frontier and len(order) < len(req):
                nxt = []
                for idx in frontier:
                    order.append(net.segments[idx])
                    seg = net.segments[idx]
                    for node in (seg.u, seg.v):
                        for _, other in net.adjacency.get(node, ()):
                            if other in seen:
                                continue
                            o = net.segments[other]
                            if o.required:
                                seen.add(other)
                                nxt.append(other)
                rng.shuffle(nxt)
                frontier = nxt
            for s in req:  # anything unreached (other components)
                if s.idx not in seen:
                    order.append(s)
        done, acc = set(), 0.0
        for s in order:
            if acc >= target:
                break
            done.add(s.idx)
            acc += s.length_m
        return cls(net, done)

    @classmethod
    def only_dead_ends_left(cls, net, seed: int = 0) -> "CompletionState":
        """Everything complete except isolated dead-end stubs — the endgame."""
        done = {s.idx for s in net.segments
                if s.required and not s.is_dead_end}
        return cls(net, done)


@dataclass
class Route:
    """A closed walk. `seg_seq` is the ordered list of segment indices traversed."""
    seg_seq: list = field(default_factory=list)
    start_node: int = -1
    anchors: list = field(default_factory=list)   # anchor node sequence, for pruning
    excursions: list = field(default_factory=list)  # (label, [seg_idx], gain) for variants
    # How many trailing entries of seg_seq are the walk home from the last anchor.
    # Repeats inside it are necessary travel, not avoidable doubling back.
    closing_leg: int = 0
    score: object = None
    meta: dict = field(default_factory=dict)

    def length_m(self, net) -> float:
        return sum(net.segments[i].length_m for i in self.seg_seq)

    def miles(self, net) -> float:
        return self.length_m(net) / M_PER_MILE

    def distinct(self) -> set:
        return set(self.seg_seq)

    def traversals(self, net) -> dict:
        """Categorise every repeated traversal.

        Three kinds of repeat, and they are not equally bad:

          DEAD_END_RETURN   the only way out of a cul-de-sac is back down it. Walking
                            it twice is the geometry, not a routing failure.
          CLOSING_LEG       the walk home from the last piece of new coverage. Necessary
                            unless the route happens to end where it started.
          AVOIDABLE         everything else — doubling back through ground already
                            covered because the search found nothing better.

        Penalising all three the same made the router avoid cul-de-sacs, which are
        exactly where households are.
        """
        seen, counts = set(), {}
        dead_end_m = closing_m = avoidable_m = 0.0
        extra_traversals = 0
        n = len(self.seg_seq)
        close_from = n - self.closing_leg
        for i, idx in enumerate(self.seg_seq):
            counts[idx] = counts.get(idx, 0) + 1
            if idx not in seen:
                seen.add(idx)
                continue
            seg = net.segments[idx]
            if counts[idx] > 2:
                extra_traversals += 1
            if seg.is_dead_end:
                dead_end_m += seg.length_m
            elif i >= close_from:
                closing_m += seg.length_m
            else:
                avoidable_m += seg.length_m
        total_m = sum(net.segments[i].length_m for i in self.seg_seq)
        repeat_m = dead_end_m + closing_m + avoidable_m
        return dict(
            dead_end_return_miles=dead_end_m / M_PER_MILE,
            closing_leg_miles=closing_m / M_PER_MILE,
            avoidable_miles=avoidable_m / M_PER_MILE,
            repeated_miles=repeat_m / M_PER_MILE,
            repeat_share=(repeat_m / total_m) if total_m else 0.0,
            extra_traversals=extra_traversals,
            max_traversals=max(counts.values()) if counts else 0,
        )

    def required_covered(self, net) -> set:
        """The REQUIRED segments this route earns. This is what nests across variants —
        the closing leg's connectors are incidental and may differ."""
        return {i for i in set(self.seg_seq) if net.segments[i].required}

    def segment_ids(self, net) -> list:
        return [net.segments[i].id for i in self.seg_seq]

    # ------------------------------------------------------------- geometry
    def node_sequence(self, net) -> list:
        """Walk the segment sequence and recover the node path."""
        if not self.seg_seq:
            return [self.start_node]
        nodes = [self.start_node]
        cur = self.start_node
        for idx in self.seg_seq:
            s = net.segments[idx]
            cur = s.v if s.u == cur else s.u
            nodes.append(cur)
        return nodes

    def turn_stats(self, net) -> tuple[int, int]:
        """(sharp turns, u-turns). A u-turn is retracing the same segment immediately
        at a node with degree > 1 — at a genuine dead end it is unavoidable and free."""
        turns = uturns = 0
        nodes = self.node_sequence(net)
        for i in range(1, len(self.seg_seq)):
            prev_i, cur_i = self.seg_seq[i - 1], self.seg_seq[i]
            if prev_i == cur_i:
                node = nodes[i]
                if len(net.adjacency.get(node, ())) > 1:
                    uturns += 1
                continue
            a, b = net.segments[prev_i], net.segments[cur_i]
            ang = deviation_angle(a, b, nodes[i])
            # Only count a turn where there was a choice. A bend in the road at a
            # degree-2 node is geometry, not a decision the walker makes.
            if (ang is not None and ang > SHARP_TURN_RAD
                    and len(net.adjacency.get(nodes[i], ())) > 2):
                turns += 1
        return turns, uturns

    def cohesion(self, net) -> float:
        """0..1 compactness: covered length vs the area it is spread over.

        A route that clears one neighbourhood scores high; one that strings together
        three distant pockets scores low. Uses the bounding box of covered geometry,
        which is crude but stable and cheap.
        """
        pts = []
        for idx in self.distinct():
            c = net.segments[idx].coords
            if c:
                pts.append(c[0])
                pts.append(c[-1])
        if len(pts) < 3:
            return 1.0
        xs = [p[0] * 0.79 for p in pts]
        ys = [p[1] for p in pts]
        w = (max(xs) - min(xs)) * 111_320.0
        h = (max(ys) - min(ys)) * 111_320.0
        diag = math.hypot(w, h)
        if diag <= 1:
            return 1.0
        length = sum(net.segments[i].length_m for i in self.distinct())
        # A compact neighbourhood sweep covers several times its own diagonal.
        return max(0.0, min(1.0, (length / diag) / 4.0))

    def loop_shape(self, net) -> float:
        """0..1 how loop-like rather than out-and-back.

        1.0 = every segment walked once. 0.0 = pure there-and-back.
        """
        if not self.seg_seq:
            return 0.0
        return len(self.distinct()) / len(self.seg_seq)


def _unit(vx, vy):
    n = math.hypot(vx, vy)
    return (vx / n, vy / n) if n > 1e-12 else None


def _dir_into(seg, node):
    """Unit vector of travel arriving at `node` along `seg`."""
    if not seg.coords or len(seg.coords) < 2:
        return None
    if seg.u == node:          # arriving at the segment's start: travelling backwards
        p, q = seg.coords[1], seg.coords[0]
    else:                      # arriving at the segment's end: travelling forwards
        p, q = seg.coords[-2], seg.coords[-1]
    return _unit((q[0] - p[0]) * 0.79, q[1] - p[1])


def _dir_out_of(seg, node):
    """Unit vector of travel leaving `node` along `seg`."""
    if not seg.coords or len(seg.coords) < 2:
        return None
    if seg.u == node:          # leaving from the segment's start: forwards
        p, q = seg.coords[0], seg.coords[1]
    else:                      # leaving from the segment's end: backwards
        p, q = seg.coords[-1], seg.coords[-2]
    return _unit((q[0] - p[0]) * 0.79, q[1] - p[1])


def deviation_angle(a, b, node):
    """How far travel deviates from straight passing through `node`, in radians.

    0 = dead straight, pi = full reversal. An earlier version returned the same vector
    for both segments because the "outgoing" branch negated twice, which made every
    angle zero and hid all the zigzagging from the score.
    """
    va = _dir_into(a, node)
    vb = _dir_out_of(b, node)
    if va is None or vb is None:
        return None
    dot = max(-1.0, min(1.0, va[0] * vb[0] + va[1] * vb[1]))
    return math.acos(dot)
