# Phase 2b Step 0 — Routing Approach Evaluation

**Date:** 2026-08-03
**Decision:** Cluster-first → GRASP construction → local search with T-join repair,
with variants produced by pruning a single Extended route.

> **Sourcing note.** No literature could be consulted: `arxiv.org`, `scholar.google.com`
> and `en.wikipedia.org` are all denied by this environment's egress policy. This
> evaluation is reasoned from domain knowledge of arc routing and from the measured
> properties of our own network, not from fetched papers. Where I name a problem class
> or a known result I am recalling it, not citing it — treat named complexity results
> as "believed correct, worth verifying" rather than referenced fact.

---

## 1. What the problem actually is

Stripped of project vocabulary:

> Given an undirected graph *G(V,E)*, a start node *s*, a subset *R ⊆ E* of **required**
> edges each carrying a prize *p(e)* (currently: is it incomplete, how much household
> weight does it hold), and a length budget *L*, find a **closed walk** from *s* to *s*
> with length ≈ *L* maximizing total prize of **distinct** edges traversed, minus a
> penalty for repeated travel.

Prizes are on **edges**, not nodes. The walk may repeat edges (a walker can walk a
street twice) but earns the prize once. The budget is a target band, not a hard cap —
"about 3 miles" not "at most 3 miles."

That is the **Arc Orienteering Problem** (AOP), also met in the bicycle-routing
literature as the **Cycle Trip Planning Problem**. It is NP-hard: it contains the
Orienteering Problem, which contains TSP.

**Two properties of our instance matter more than the general theory:**

1. **The graph is tiny.** 1,515 required segments, ~2,240 routable edges, 2,579 nodes,
   135 miles. A request touches a neighbourhood, not the town.
2. **The prize field is extremely non-uniform and gets worse over time.** At 0%
   completion every required edge is worth something. At 95% completion the remaining
   incomplete edges are scattered singletons, and the interesting question stops being
   "which edges" and becomes "which *cluster* of leftovers is worth a trip."

Property 2 is the one that should drive the architecture, and it is the one a generic
AOP solver handles worst.

---

## 2. Candidate approaches

Scored against the criteria in the brief. **5 = excellent, 1 = poor.**

| Approach | Coverage-max | Closed loops | Prioritise incomplete | Scales to 100% done | Multi-length | Scoring weights | Compute | Tuning | Maintain | Multiplayer | **Total** |
|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|--:|
| Chinese Postman / RPP | 1 | 5 | 2 | 1 | 1 | 1 | 3 | 2 | 4 | 2 | **22** |
| CARP / Prize-collecting CARP | 4 | 4 | 4 | 3 | 2 | 3 | 2 | 2 | 2 | 3 | **29** |
| Node Orienteering via line graph | 4 | 4 | 4 | 3 | 3 | 4 | 3 | 3 | 2 | 3 | **33** |
| Pure graph search (A*/Dijkstra) | 1 | 2 | 2 | 1 | 3 | 2 | 5 | 5 | 5 | 4 | **30** |
| Genetic algorithm | 4 | 4 | 4 | 3 | 3 | 4 | 2 | 1 | 2 | 3 | **30** |
| Ant Colony Optimization | 4 | 4 | 4 | 3 | 3 | 3 | 2 | 1 | 2 | 2 | **28** |
| Simulated annealing / Tabu | 4 | 4 | 4 | 3 | 3 | 4 | 3 | 2 | 3 | 3 | **33** |
| Full multi-objective (Pareto) | 4 | 4 | 4 | 3 | 4 | 5 | 2 | 2 | 2 | 3 | **33** |
| Cluster-first / route-second | 4 | 4 | 5 | **5** | 4 | 4 | 4 | 4 | 4 | 4 | **42** |
| **Hybrid: cluster-first + GRASP + local search** | **5** | **5** | **5** | **5** | **5** | **5** | **4** | **5** | **4** | **4** | **48** |

### Why each competitor was rejected

**Chinese Postman / Rural Postman.** Solves the wrong problem: minimum-length traversal
of *all* required edges. Our user wants a 3-mile loop, not a 135-mile one, and RPP has
no notion of a budget or of choosing which edges are worth covering. It also degrades
badly as completion rises — the required set becomes disconnected and RPP's connecting
cost explodes. **Kept as a component:** the odd-degree-vertex matching (T-join) idea is
the right way to turn a chosen edge set into a walk with minimal repeat, and I use it
in the improvement layer.

**CARP / prize-collecting CARP.** Closest classical fit — a length budget behaves like a
vehicle capacity. But CARP partitions *all* required arcs across a fleet, and we want
one route for one walker right now. Good CARP solvers are memetic and take seconds to
minutes; we need sub-second. Rejected as the engine, borrowed as vocabulary.

**Node Orienteering via line-graph transformation.** Legitimate: map each edge to a node,
connect edges that share an endpoint, and run a node-OP solver. Our line graph is only
~2,240 nodes so size is not the obstacle. The problem is semantic: the transformation
loses the fact that traversing an edge *is* the reward, makes "walk this street twice"
awkward to express, and turns the naturally-cheap "how far am I from home" check into
something you have to re-derive. It buys access to node-OP solvers we do not otherwise
need. Rejected on maintainability, not capability.

**Pure graph search (A*, Dijkstra hybrids).** Cannot express the objective at all —
these find *shortest* paths, and our objective is explicitly not shortest. **Kept as a
component:** every layer below leans on Dijkstra for anchor-to-anchor distances and for
the home-distance feasibility check.

**Genetic algorithms.** Would work. Rejected on tuning cost and predictability: a GA has
population size, crossover operator, mutation rate, elitism and termination to tune, and
its runtime distribution has a long tail — bad for a request that must answer in under a
second. The scoring weights in this project will be tuned by a pastor looking at maps,
not by a researcher running experiments; a method with five extra meta-parameters is the
wrong tool.

**Ant Colony Optimization.** Same objection as GA, plus pheromone state that has to be
warmed up per request or maintained across requests. The latter interacts badly with the
completion state changing under it.

**Simulated annealing / Tabu search.** Genuinely good candidates and close to what I
chose — the improvement layer below is essentially a small deterministic local search
that SA/Tabu would generalise. Rejected as the *primary* method because both need a
starting solution anyway, and the quality of that starting solution matters more here
than the sophistication of the metaheuristic wrapped around it. Tabu tenure and cooling
schedules are also meta-parameters nobody on this project will want to own. **If route
quality turns out to be insufficient, upgrading the improvement layer to SA is the
first thing to try** — it drops in without touching anything else.

**Full multi-objective / Pareto.** Attractive on paper: we have six stated objectives.
But the brief gives them in *priority order*, which is a scalarization, not a Pareto
request. And the five variants differ by **length**, not by objective trade-off, so a
Pareto front does not map onto the product. Rejected as over-engineering; the weighted
scalarization keeps every component exposed, which delivers the tunability without the
machinery.

**Cluster-first / route-second alone.** Nearly right, and it is the outer layer of the
recommendation. Alone it under-delivers because once a cluster is chosen you still have
an AOP inside it; a naive greedy tour of a cluster zigzags.

---

## 3. Recommended architecture

Three layers, each replaceable.

```
  ┌─ Layer 1 ── CLUSTER DISCOVERY ────────────────────────────────┐
  │  Connected components of incomplete REQUIRED edges, reachable  │
  │  from the start. Scored by prize density and access cost.      │
  │  Output: top-K candidate target regions.                       │
  └────────────────────────────────────────────────────────────────┘
                              │  K regions
  ┌─ Layer 2 ── GRASP CONSTRUCTION ───────────────────────────────┐
  │  Per region × per seed: randomized greedy closed walk.         │
  │  Restricted candidate list ranked by prize/detour ratio.       │
  │  Invariant: remaining budget >= distance home, always.         │
  │  Output: N feasible candidate walks.                           │
  └────────────────────────────────────────────────────────────────┘
                              │  N candidates
  ┌─ Layer 3 ── IMPROVEMENT ──────────────────────────────────────┐
  │  T-join repair (drop pointless out-and-backs), 2-opt on the    │
  │  anchor sequence, drop-worst-excursion, insert-cheap-detour.   │
  │  Output: improved candidates, scored, best selected.           │
  └────────────────────────────────────────────────────────────────┘
                              │  best Extended route
  ┌─ VARIANTS ── PRUNE FROM EXTENDED ─────────────────────────────┐
  │  Remove least-valuable excursions until each length band is    │
  │  hit. Guarantees Quick ⊂ Short ⊂ Medium ⊂ Long ⊂ Extended.     │
  └────────────────────────────────────────────────────────────────┘
```

### Why this is the best fit

**It matches the shape of the problem as completion rises.** Layer 1 is the answer to
"what happens at 95% done." When leftovers are scattered, cluster discovery names the
few worthwhile targets explicitly and the search never wastes time elsewhere. A generic
AOP solver would grind over the whole graph rediscovering that most of it is worthless.

**Neighbourhood cohesion is structural, not a penalty term.** Objective 4 ("clear
coherent neighbourhood clusters") is satisfied by construction because the route is
built inside one chosen cluster. Getting cohesion from a scoring penalty instead means
fighting the optimizer.

**GRASP gives diversity cheaply.** Randomized greedy with a restricted candidate list
produces genuinely different good routes from the same start, which is what "generate
multiple candidates rather than one greedy solution" asks for — and it costs one extra
loop, not a population.

**Every weight stays visible.** Score components are computed and stored separately, so
retuning is editing a weights dict. No retraining, no re-derivation.

**Pruning guarantees nesting.** Building the longest route once and cutting it down is
the only construction I know that makes Quick ⊂ Extended true by definition rather than
by luck.

### Expected computational complexity

Let *n* = nodes in the working region, *m* = edges, *A* = anchor nodes (endpoints of
candidate incomplete edges, typically 100–400), *K* = clusters tried, *S* = GRASP seeds.

| Stage | Complexity | Measured target |
|---|---|---|
| Home-distance Dijkstra | O(m log n) | ~2 ms |
| Cluster discovery (union-find + scoring) | O(m α(n)) | ~3 ms |
| Anchor all-pairs (SciPy multi-source Dijkstra, C) | O(A · m log n) | ~15 ms for A=300 |
| GRASP construction | O(K · S · steps · \|RCL\|) | ~5 ms per candidate |
| Local search | O(iters · A) per candidate | ~3 ms per candidate |
| **Total per request** | dominated by K·S candidates | **target < 400 ms** |

The anchor distance matrix is the only quadratic-ish term and it is computed in C. Every
other stage is linear-ish in a small graph.

### Where approximation is acceptable

- **Everywhere in route selection.** There is no "correct" prayer-walk route. A route
  within a few percent of optimal that reads well on a map beats a proven optimum that
  zigzags.
- **Distances between anchors** are exact (Dijkstra); only the *sequencing* is heuristic.
- **The length band** is a target ±15%, not a constraint. Hitting 2.9 miles when asked
  for 3.0 is not an error.
- **Not acceptable:** claiming an edge is covered when the route does not traverse it, or
  routing over an edge that is not in the graph. Coverage accounting must be exact —
  it feeds a number a congregation trusts.

### How scoring weights evolve

Weights live in one dataclass with documented units. Every route carries its full score
breakdown, so a weight change can be replayed against stored routes without re-running
the search. Adding a new component means adding one field and one term; nothing else
changes. The benchmark harness re-runs all scenarios so a weight change can be judged on
its effect across the town, not on one example.

### Future multiplayer compatibility

The engine takes completion state as an argument and holds no state of its own. Two
walkers routing simultaneously each get the current state; soft reservations (spec §21)
become another prize multiplier — reserved edges get their prize damped rather than
removed, so a second walker is nudged elsewhere without being blocked. That is a
one-line change in the prize function.

---

## 4. Risks in this choice

| Risk | Mitigation |
|---|---|
| Cluster-first can miss a route that spans two adjacent clusters | Clusters are seeds, not fences — construction may leave the cluster if the budget allows; the cluster only biases where it starts |
| GRASP quality depends on the RCL size | Exposed as a tuning parameter; benchmark harness measures it |
| Local search may be too weak for long routes | Upgrade path to simulated annealing is drop-in at Layer 3 |
| Pruning from Extended can make short variants worse than a purpose-built short route | Measured in the benchmark; if the gap is material, fall back to constructing short variants independently and accept weaker nesting |
