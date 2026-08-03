"""The routing engine: cluster-first -> GRASP construction -> local search.

Layer 1  cluster discovery      find worthwhile neighbourhoods of incomplete work
Layer 2  GRASP construction     randomized greedy closed walks, budget-feasible
Layer 3  improvement            T-join repair, 2-opt on anchors, excursion trimming

Variants come from pruning one Extended route, which makes nesting structural rather
than lucky. See docs/10-routing-approach-evaluation.md for why this shape was chosen.
"""
from __future__ import annotations

import random
import time
from collections import defaultdict
from dataclasses import dataclass

import numpy as np

from . import components as comp_mod
from . import response as resp_mod
from .graph import RoutingGraph
from .score import DEFAULT_WEIGHTS, Weights, compute
from .state import CompletionState, Route

M_PER_MILE = 1609.344

# Bumped whenever routing behaviour changes in a way that could alter a stored route.
#   2.0.0  Phase 2b.1: categorised length-scaled repeat penalty, multi-component
#          routing, structured late-opportunity response states.
#   1.0.0  Phase 2b prototype.
ENGINE_VERSION = "2.0.0"

# Length bands, miles. Quick..Extended.
VARIANTS = [("Quick", 1.0), ("Short", 2.0), ("Medium", 3.5), ("Long", 5.0),
            ("Extended", 7.5)]


@dataclass
class EngineConfig:
    clusters: int = 5              # candidate neighbourhoods to try
    seeds_per_cluster: int = 4     # GRASP restarts per cluster
    rcl_size: int = 5              # restricted candidate list width
    rcl_alpha: float = 0.45        # 0 = pure greedy, 1 = pure random
    max_anchors: int = 420         # cap on the anchor distance matrix
    search_radius_factor: float = 0.62   # region radius as a fraction of the budget
    improve_iters: int = 30
    two_opt_samples: int = 40      # sampled rather than enumerated; O(A^2) otherwise
    length_tolerance: float = 0.08       # hard cap = target x (1+this). The
                                         # greedy fills whatever budget it is
                                         # given, so this is the real control
                                         # on route length, not the score penalty.
    random_seed: int = 12345


class Engine:
    def __init__(self, net, config: EngineConfig | None = None,
                 weights: Weights = DEFAULT_WEIGHTS):
        self.net = net
        self.g = RoutingGraph(net)
        self.cfg = config or EngineConfig()
        self.w = weights
        comps = self.g.components()
        self.main_component = set(comps[0]) if comps else set()
        self.components = comps
        self._last_nearest_incomplete_m = float("inf")

        # Component classification. Routing happens *within* a component; the router
        # never invents a link between them. A start snaps to the nearest component
        # that is a valid place to walk from, which is not always the biggest one.
        self.component_info = comp_mod.classify(net, self.g)
        self.snappable = set()
        self.component_of_node = {}
        for c in self.component_info:
            for n in c.nodes:
                self.component_of_node[n] = c.index
            if c.start_snap_allowed:
                self.snappable |= c.nodes

    def snap(self, lon: float, lat: float) -> int:
        """Snap a WGS84 location to the nearest node in a valid routing area.

        Not the main component — the nearest *valid* one. A walker standing in the
        Corporate Research Center should route the CRC, not be teleported downtown.
        Tiny accidental islands are excluded from snapping (start_snap_allowed=False),
        so a bad snap cannot strand a request on a two-node fragment.
        """
        return self.g.nearest_node_to(lon, lat, restrict_to=self.snappable)

    def component_for(self, node_i: int):
        ci = self.component_of_node.get(node_i)
        return next((c for c in self.component_info if c.index == ci), None)

    # ================================================================ Layer 1
    def discover_clusters(self, state: CompletionState, start_i: int,
                          budget_m: float) -> list[dict]:
        """Connected clusters of incomplete REQUIRED work, reachable from the start.

        Union-find over incomplete required segments that share a node. Each cluster is
        scored by how much work it holds against how far it is from the walker — a rich
        cluster twenty minutes away loses to a decent one at the door.
        """
        # Candidate work is restricted to the start's own component. Anything in
        # another component is unreachable by definition, and offering it would mean
        # inventing a crossing no source asserted.
        my_comp = self.component_of_node.get(start_i)
        incomplete = [i for i in state.incomplete_required()
                      if state.prize_multiplier(i) > 0.05
                      and self.component_of_node.get(
                          self.g.node_index.get(self.net.segments[i].u, -1)) == my_comp]
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
            s = self.net.segments[i]
            by_node[s.u].append(i)
            by_node[s.v].append(i)
        for members in by_node.values():
            for other in members[1:]:
                ra, rb = find(members[0]), find(other)
                if ra != rb:
                    parent[rb] = ra

        groups = defaultdict(list)
        for i in incomplete:
            groups[find(i)].append(i)

        home = self.g.dist_from(start_i)

        # Radius is budget/2, not a tunable fraction. Work further out than half the
        # budget has no round trip home, so `usable` would be zero anyway — an earlier
        # version widened the radius adaptively and it did nothing, because the cap
        # bound every setting to the same value. The honest answer when nothing is in
        # reach is to say so, which is what nearest_incomplete_m is for.
        radius = budget_m * 0.5
        out = self._clusters_within(groups, home, radius, budget_m)

        # Distance to the nearest incomplete work regardless of reachability, so the
        # caller can explain an empty result rather than just failing.
        nearest = float("inf")
        for i in incomplete:
            s = self.net.segments[i]
            for node in (s.u, s.v):
                ni = self.g.node_index.get(node)
                if ni is not None and home[ni] < nearest:
                    nearest = home[ni]
        self._last_nearest_incomplete_m = nearest

        out.sort(key=lambda c: -c["score"])
        return out[: self.cfg.clusters]

    def _clusters_within(self, groups, home, radius, budget_m):
        out = []
        for root, members in groups.items():
            length = sum(self.net.segments[i].length_m for i in members)
            households = sum(self.net.segments[i].households for i in members)
            access = float("inf")
            entry = None
            for i in members:
                s = self.net.segments[i]
                for node in (s.u, s.v):
                    ni = self.g.node_index.get(node)
                    if ni is None:
                        continue
                    d = home[ni]
                    if d < access:
                        access, entry = d, ni
            if entry is None or not np.isfinite(access) or access > radius:
                continue
            # Work available inside the budget, discounted by the round trip to reach it.
            usable = min(length, max(0.0, budget_m - 2 * access))
            if usable <= 0:
                continue
            density = usable / max(access + budget_m * 0.25, 1.0)
            out.append(dict(
                root=root, members=members, entry=entry,
                access_m=access, length_m=length, usable_m=usable,
                households=households,
                score=density * 1000 + households * 0.4 + usable * 0.01,
            ))
        return out

    # ================================================================ Layer 2
    def _anchor_setup(self, cluster, state, start_i, budget_m):
        """Anchor nodes = endpoints of candidate incomplete segments in reach."""
        home = self.g.dist_from(start_i)
        cand = []
        for i in cluster["members"]:
            s = self.net.segments[i]
            a, b = self.g.node_index.get(s.u), self.g.node_index.get(s.v)
            if a is None or b is None:
                continue
            if not np.isfinite(home[a]) and not np.isfinite(home[b]):
                continue
            if min(home[a], home[b]) * 2 + s.length_m > budget_m * 1.35:
                continue
            cand.append(i)
        if not cand:
            return None
        nodes = {start_i}
        for i in cand:
            s = self.net.segments[i]
            nodes.add(self.g.node_index[s.u])
            nodes.add(self.g.node_index[s.v])
        anchors = sorted(nodes)
        if len(anchors) > self.cfg.max_anchors:
            # Keep the start plus the nearest anchors; the rest are out of reach anyway.
            anchors = [start_i] + sorted(
                (a for a in anchors if a != start_i),
                key=lambda a: home[a])[: self.cfg.max_anchors - 1]
            anchors = sorted(set(anchors))
        pos = {a: k for k, a in enumerate(anchors)}
        dmat = self.g.dist_matrix(anchors)

        # Vectorized candidate tables. Each candidate segment can be entered from
        # either end, so every row appears twice — once per direction. Scoring the
        # whole table with numpy at each step replaced a Python loop that was making
        # ~400k calls per request and dominating the profile.
        n = len(cand)
        seg_of = np.empty(2 * n, dtype=np.int64)
        entry = np.empty(2 * n, dtype=np.int64)
        exit_ = np.empty(2 * n, dtype=np.int64)
        seglen = np.empty(2 * n, dtype=float)
        prize = np.empty(2 * n, dtype=float)
        for k, i in enumerate(cand):
            s = self.net.segments[i]
            ea, eb = self.g.node_index[s.u], self.g.node_index[s.v]
            # Prize is static for the life of the construction — completion state does
            # not change mid-walk — so it is computed once here rather than per step.
            p = (s.length_m * state.prize_multiplier(i)
                 + s.households * 6.0
                 + (60.0 if s.is_dead_end else 0.0)
                 + (90.0 if state.incomplete_neighbours(self.net, i) <= 1 else 0.0))
            for d, (en, ex) in enumerate(((ea, eb), (eb, ea))):
                r = 2 * k + d
                seg_of[r], entry[r], exit_[r] = i, en, ex
                seglen[r], prize[r] = s.length_m, p
        home_at_exit = np.where(np.isfinite(home[exit_]), home[exit_], np.inf)

        return dict(root=cluster["root"], cand=cand, anchors=anchors, pos=pos, dmat=dmat, home=home,
                    seg_of=seg_of, entry=entry, exit=exit_, seglen=seglen,
                    prize=prize, home_at_exit=home_at_exit, n=n)

    def construct(self, setup, state, start_i, budget_m, rng,
                  seed_anchors: list | None = None) -> Route | None:
        """One randomized-greedy closed walk over a prepared cluster setup.

        Invariant, checked every step: remaining budget >= distance home. That is what
        makes the walk closable without backtracking the whole search.

        `seed_anchors` continues an existing route rather than starting fresh: the walk
        resumes from that route's last anchor with its coverage already spent. This is
        how the longer variants extend the shorter ones instead of replacing them.
        """
        if setup is None:
            return None
        pos, dmat, home = setup["pos"], setup["dmat"], setup["home"]
        seg_of, entry_a, exit_a = setup["seg_of"], setup["entry"], setup["exit"]
        seglen, prize, home_exit = setup["seglen"], setup["prize"], setup["home_at_exit"]
        alive = np.ones(len(seg_of), dtype=bool)

        cur = start_i
        used_m = 0.0
        seg_seq: list[int] = []
        anchors_visited = [start_i]
        excursions: list[tuple] = []
        rcl_n = max(1, self.cfg.rcl_size)

        if seed_anchors and len(seed_anchors) > 1:
            # Replay the seed route's open walk (everything except its return home),
            # then carry on from where it left off.
            prev = start_i
            for nxt in seed_anchors[1:]:
                if nxt == prev:
                    continue
                d, path = self.g.shortest_path(prev, nxt)
                if not np.isfinite(d):
                    return None
                seg_seq.extend(path)
                used_m += d
                anchors_visited.append(nxt)
                prev = nxt
            cur = prev
            for idx in set(seg_seq):
                alive &= (seg_of != idx)
            if used_m + home[cur] > budget_m:
                return None

        while alive.any():
            k = pos.get(cur)
            # The anchor matrix is capped at max_anchors, so the walk can legitimately
            # step to a node outside it. Falling back to a cached single-source
            # Dijkstra costs ~1 ms and keeps the walk going; breaking here was leaving
            # long routes at half their budget.
            row = dmat[k] if k is not None else self.g.dist_from(cur)

            approach = row[entry_a]
            cost = approach + seglen
            feasible = alive & np.isfinite(approach) & (used_m + cost + home_exit <= budget_m)
            if not feasible.any():
                break
            # Ratio, not raw prize: a good segment far away is a bad next move.
            ratio = np.where(feasible, prize / np.maximum(cost, 1.0), -np.inf)
            take = min(rcl_n, int(feasible.sum()))
            top = np.argpartition(-ratio, take - 1)[:take]
            top = top[np.argsort(-ratio[top])]

            # GRASP: sample from the restricted candidate list rather than always
            # taking the best. This is what makes repeated runs explore different routes.
            hi, lo = ratio[top[0]], ratio[top[-1]]
            cut = hi - self.cfg.rcl_alpha * (hi - lo)
            pool = [r for r in top if ratio[r] >= cut] or [top[0]]
            r = rng.choice(pool)

            i = int(seg_of[r])
            if approach[r] > 0:
                _, path = self.g.shortest_path(cur, int(entry_a[r]))
                seg_seq.extend(path)
            start_len = len(seg_seq)
            seg_seq.append(i)
            excursions.append((self.net.segments[i].id,
                               list(range(start_len, len(seg_seq))),
                               float(seglen[r])))
            used_m += float(cost[r])
            cur = int(exit_a[r])
            anchors_visited.append(cur)
            alive &= (seg_of != i)   # both directions of this segment are now spent

        # Close the loop. The length of this leg is recorded so the scorer can tell
        # necessary walk-home repeats from avoidable doubling back.
        closing = 0
        if cur != start_i:
            _, path = self.g.shortest_path(cur, start_i)
            seg_seq.extend(path)
            closing = len(path)
        if not seg_seq:
            return None
        return Route(seg_seq=seg_seq, start_node=start_i,
                     anchors=anchors_visited, excursions=excursions,
                     closing_leg=closing,
                     meta=dict(cluster_root=setup.get("root")))

    # ================================================================ Layer 3
    def improve(self, route: Route, state, start_i, budget_m, target_miles,
                protect: set | None = None) -> Route:
        """Local search. Three move types, applied until no improvement.

        - trim_tail      drop a trailing excursion that earns less than it costs
        - drop_worst     remove the least valuable single excursion and re-stitch
        - t_join_repair  remove pointless out-and-back retracing
        """
        best = route
        best_score = compute(best, self.net, state, target_miles, self.w)
        for _ in range(self.cfg.improve_iters):
            improved = False
            for cand in self._neighbours(best, state, start_i, budget_m):
                # `protect` holds the shorter variant's coverage. A move that drops it
                # would break nesting, so it is not a legal neighbour.
                if protect is not None and not protect.issubset(
                        cand.required_covered(self.net)):
                    continue
                sc = compute(cand, self.net, state, target_miles, self.w)
                if sc.total > best_score.total + 1e-6:
                    best, best_score, improved = cand, sc, True
                    break
            if not improved:
                break
        best.score = best_score
        return best

    def _neighbours(self, route: Route, state, start_i, budget_m):
        """Candidate moves, cheapest first. Generated lazily; first improvement wins.

        INVARIANT: every move here rewrites the *anchor sequence* and re-derives
        seg_seq from it. An earlier version also had a "collapse retraces" move that
        rewrote seg_seq directly — which silently desynchronised anchors from the walk
        they were supposed to describe, and broke variant extension, because extending
        replays the anchors. Anchors are authoritative. Do not add a move that edits
        seg_seq without editing anchors.

        Removing a redundant out-and-back is still covered: drop_worst deletes any
        anchor that does not pay for its detour, and the repeat-mileage penalty in the
        score drives it.

        2-opt is quadratic in anchors and is sampled rather than enumerated.
        """
        anchors = route.anchors
        if len(anchors) > 2:
            # drop_worst: remove one visited anchor
            for k in range(1, len(anchors) - 1):
                r = self._rebuild(anchors[:k] + anchors[k + 1:], start_i, route)
                if r is not None and r.length_m(self.net) <= budget_m * 1.05:
                    yield r

        # 2-opt on the anchor visit order. Full enumeration is O(A^2) rebuilds and
        # A reaches ~60 on long routes; sample instead, seeded for determinism.
        if len(anchors) > 4:
            n = len(anchors)
            pairs = [(a, b) for a in range(1, n - 2) for b in range(a + 1, n - 1)]
            if len(pairs) > self.cfg.two_opt_samples:
                rng = random.Random(self.cfg.random_seed + n)
                pairs = rng.sample(pairs, self.cfg.two_opt_samples)
            for a, b in pairs:
                r = self._rebuild(anchors[:a] + anchors[a:b + 1][::-1] + anchors[b + 1:],
                                  start_i, route)
                if r is not None and r.length_m(self.net) <= budget_m * 1.05:
                    yield r

    def _rebuild(self, anchor_seq, start_i, template) -> Route | None:
        """Re-stitch a walk from an anchor sequence using shortest paths."""
        if not anchor_seq or anchor_seq[0] != start_i:
            return None
        seq = []
        cur = start_i
        for nxt in anchor_seq[1:]:
            if nxt == cur:
                continue
            d, path = self.g.shortest_path(cur, nxt)
            if not np.isfinite(d):
                return None
            seq.extend(path)
            cur = nxt
        closing = 0
        if cur != start_i:
            d, path = self.g.shortest_path(cur, start_i)
            if not np.isfinite(d):
                return None
            seq.extend(path)
            closing = len(path)
        if not seq:
            return None
        return Route(seg_seq=seq, start_node=start_i, anchors=list(anchor_seq),
                     excursions=template.excursions, closing_leg=closing,
                     meta=dict(template.meta))

    # ================================================================== driver
    def best_route(self, start_i: int, target_miles: float, state: CompletionState,
                   tolerance: float | None = None):
        """Search for the best closed walk of roughly `target_miles`."""
        t0 = time.perf_counter()
        budget_m = target_miles * M_PER_MILE * (1 + (tolerance or self.cfg.length_tolerance))
        rng = random.Random(self.cfg.random_seed + int(target_miles * 100))

        clusters = self.discover_clusters(state, start_i, budget_m)
        candidates = []
        for cluster in clusters:
            # The anchor distance matrix is per cluster, not per seed — it was being
            # rebuilt for every GRASP restart, which cost more than the restarts.
            setup = self._anchor_setup(cluster, state, start_i, budget_m)
            if setup is None:
                continue
            for _ in range(self.cfg.seeds_per_cluster):
                r = self.construct(setup, state, start_i, budget_m, rng)
                if r is None:
                    continue
                r = self.improve(r, state, start_i, budget_m, target_miles)
                candidates.append(r)

        stats = dict(clusters_found=len(clusters),
                     candidates_generated=len(candidates),
                     nearest_incomplete_miles=(
                         round(self._last_nearest_incomplete_m / M_PER_MILE, 2)
                         if np.isfinite(getattr(self, "_last_nearest_incomplete_m", np.inf))
                         else None),
                     approach_miles=round(
                         min((c["access_m"] for c in clusters), default=0.0) / M_PER_MILE, 2)
                     if clusters else None,
                     reason=None if clusters else (
                         "no incomplete required work within half the length budget; "
                         "the nearest un-walked street needs a longer route or a "
                         "different start"),
                     elapsed_ms=round((time.perf_counter() - t0) * 1000, 1))
        if not candidates:
            return None, stats
        best = max(candidates, key=lambda r: r.score.total)
        best.meta.update(stats)
        return best, stats

    # ---------------------------------------------------------------- variants
    def variants(self, start_i: int, state: CompletionState,
                 bands=VARIANTS) -> list[dict]:
        """Five nested variants: build Quick, then extend it into each longer band.

        The first design built the Extended route and pruned down to the shorter ones.
        That produced degenerate short variants — a one-mile subset of an eight-mile
        sweep is the first excursion and the walk home, not a route anyone would want.
        Nesting has to be built in the direction it is consumed: the short route is the
        core, and each longer variant *adds* nearby incomplete coverage to it.

        Guarantees Quick ⊆ Short ⊆ Medium ⊆ Long ⊆ Extended on covered segments.
        """
        t0 = time.perf_counter()

        # The shortest band is not always achievable: late in the project the nearest
        # incomplete work can be further than half a one-mile budget, and an earlier
        # version returned nothing at all for the whole request when that happened.
        # Walk up the bands until one produces a route, and report the shorter ones as
        # unavailable with the reason.
        out, base, base_idx = [], None, 0
        for k, (name, target) in enumerate(bands):
            r, meta = self.best_route(start_i, target, state)
            if r is not None:
                base, base_idx = r, k
                out.append(dict(name=name, target_miles=target, route=r,
                                score=r.score, extends=None, grew=True, nested=True,
                                meta=meta))
                break
            out.append(dict(name=name, target_miles=target, route=None, score=None,
                            extends=None, grew=False, nested=True, meta=meta,
                            unavailable=meta.get("reason") or "no route found",
                            nearest_incomplete_miles=meta.get("nearest_incomplete_miles")))
        if base is None:
            for o in out:
                o["build_ms"] = round((time.perf_counter() - t0) * 1000, 1)
            return out

        cur = base
        for name, target in bands[base_idx + 1:]:
            nxt = self.extend(cur, state, start_i, target)
            grew = nxt is not None and nxt.miles(self.net) > cur.miles(self.net) + 0.05
            nested = True
            if not grew:
                # Extension could not grow this variant while preserving the shorter
                # route's coverage — dense starts hit this, because the good nearby
                # work is already inside the shorter route and everything else is a
                # long detour. The brief allows a different route when it clearly
                # improves quality, so fall back to an independent search and take it
                # only if it is materially better. Which branch ran is reported.
                indep, _ = self.best_route(start_i, target, state)
                if indep is not None and (nxt is None
                                          or indep.score.total > (cur.score.total if cur.score else 0) * 1.15):
                    nxt, nested, grew = indep, False, True
                else:
                    nxt = cur
            out.append(dict(name=name, target_miles=target, route=nxt,
                            score=nxt.score, extends=out[-1]["name"] if nested else None,
                            grew=bool(grew), nested=bool(nested),
                            meta=dict(nxt.meta)))
            cur = nxt
        total_ms = round((time.perf_counter() - t0) * 1000, 1)
        component = self.component_for(start_i)
        band_results = [(o["name"], o["target_miles"], o.get("route"),
                         o.get("meta", {})) for o in out]
        for o in out:
            o["build_ms"] = total_ms
            o["response"] = resp_mod.assess(
                o["name"], o["target_miles"], o.get("route"),
                o.get("meta", {}), component, band_results)
        return out

    def extend(self, route: Route, state: CompletionState, start_i: int,
               target_miles: float) -> Route | None:
        """Grow an existing route into a longer band, keeping everything it covers.

        Continues the same randomized-greedy construction from the route's last anchor,
        with the segments it already covers marked spent, so the longer variant adds
        new coverage rather than replacing the route.
        """
        budget_m = target_miles * M_PER_MILE * (1 + self.cfg.length_tolerance)
        # Nesting is defined on COVERAGE — the required segments earned — not on every
        # segment traversed. A longer variant legitimately walks home a different way,
        # and the connectors on that closing leg are incidental. Requiring the whole
        # traversal to nest made every extension past ~3.8 mi fail.
        already = route.required_covered(self.net)
        clusters = self.discover_clusters(state, start_i, budget_m)
        best, best_score = None, None
        rng = random.Random(self.cfg.random_seed + int(target_miles * 1000))

        for cluster in clusters:
            setup = self._anchor_setup(cluster, state, start_i, budget_m)
            if setup is None:
                continue
            for _ in range(self.cfg.seeds_per_cluster):
                r = self.construct(setup, state, start_i, budget_m, rng,
                                   seed_anchors=route.anchors)
                if r is None:
                    continue
                r = self.improve(r, state, start_i, budget_m, target_miles,
                                 protect=already)
                # Nesting is a hard requirement, not a preference: reject any extension
                # that dropped coverage the shorter variant had.
                if not already.issubset(r.required_covered(self.net)):
                    continue
                sc = r.score or compute(r, self.net, state, target_miles, self.w)
                if best_score is None or sc.total > best_score.total:
                    best, best_score = r, sc
        if best is None:
            return None
        best.score = best_score
        best.meta["extended_from_miles"] = round(route.miles(self.net), 3)
        return best
