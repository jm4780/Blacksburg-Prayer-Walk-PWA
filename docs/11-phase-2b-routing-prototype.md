# Phase 2b — Routing Prototype

**Date:** 2026-08-03 · **Network:** `bbg-net-v1.0-b61d1067f9a57e32` (frozen, unmodified)
**Verdict: GO — integrate, with two conditions.**

Companion: [`10-routing-approach-evaluation.md`](10-routing-approach-evaluation.md)
(Step 0). Code in `api/routing/`, results in `api/routing/results/`.

> ⚠️ **Superseded in part by [`12-phase-2b1-corrections.md`](12-phase-2b1-corrections.md).**
> Phase 2b.1 shipped the length-scaled repeat penalty, multi-component routing, the
> Smart Road reclassification (network **v1.1**, required mileage 135.271 → **134.229**),
> and structured late-opportunity states. The architecture, approach evaluation and
> Step 0 reasoning below stand; the numbers and the two GO conditions have moved.
> **Two claims below are corrected there:** the Corporate Research Center is *not* cut
> off by the US-460 bypass (it is separated by unreviewed at-grade crossings), and the
> South Main zero-household result was a bad benchmark coordinate, not a data question.

---

## 1. Approaches considered

Ten approaches scored against the eleven criteria in the brief. Full table and
rejection reasoning in doc 10. Summary:

| Approach | Score | Verdict |
|---|--:|---|
| **Hybrid: cluster-first + GRASP + local search** | **48** | **chosen** |
| Cluster-first / route-second alone | 42 | outer layer of the choice |
| Node Orienteering via line graph | 33 | rejected — semantic mismatch |
| Simulated annealing / Tabu | 33 | rejected as primary; **upgrade path for Layer 3** |
| Multi-objective (Pareto) | 33 | rejected — variants differ by length, not trade-off |
| Genetic algorithm | 30 | rejected — five meta-parameters nobody will own |
| Pure graph search | 30 | cannot express the objective; used as a component |
| CARP / prize-collecting CARP | 29 | closest classical fit, too slow, wrong shape |
| Ant Colony | 28 | same as GA plus pheromone state |
| Chinese Postman / Rural Postman | 22 | wrong objective; T-join idea borrowed |

> **Sourcing caveat.** `arxiv.org`, `scholar.google.com` and `en.wikipedia.org` are all
> blocked by the environment's egress policy. Doc 10 is reasoned from domain knowledge
> and from the measured properties of our network, not from fetched literature. Named
> complexity results are recalled, not cited.

---

## 2. Final architecture

The problem is an **Arc Orienteering Problem**: closed walk from a start, edge prizes,
length budget, maximize distinct prize. NP-hard in general; our instance is small
(2,496 routable segments, 2,280 nodes) and its prize field becomes extremely sparse as
completion rises — which is what drove the design.

```
Layer 1  CLUSTER DISCOVERY   union-find over incomplete REQUIRED segments; score each
                             cluster by usable work vs access cost; take top 5
Layer 2  GRASP CONSTRUCTION  per cluster x 4 seeds: randomized greedy closed walk with
                             a restricted candidate list, feasibility invariant
                             "remaining budget >= distance home" checked every step
Layer 3  IMPROVEMENT         drop-worst-anchor and sampled 2-opt on the anchor sequence
VARIANTS                     build Quick, then extend into each longer band
```

**Why cluster-first is the load-bearing choice.** Objective 4 ("clear coherent
neighbourhood clusters") is satisfied structurally — the route is built inside one
chosen cluster, not nudged toward cohesion by a penalty. And it is the answer to
"what happens at 95% done": cluster discovery names the few worthwhile targets
explicitly instead of grinding over a graph that is mostly worthless.

**Anchors are authoritative.** Every improvement move rewrites the anchor sequence and
re-derives the walk. An earlier version also had a "collapse retraces" move that edited
the segment sequence directly; it silently desynchronised anchors from the walk they
described and broke variant extension. The invariant is now documented in the code.

---

## 3. Optimization strategy

| Element | Choice | Rationale |
|---|---|---|
| Feasibility | `used + cost + dist_home(exit) <= budget` every step | Makes the walk closable without backtracking the search |
| Candidate ranking | prize / cost **ratio**, not raw prize | A rich segment far away is a bad next move |
| Diversification | GRASP restricted candidate list, `alpha = 0.45` | Different good routes from one start, at the cost of one loop rather than a population |
| Local search | first-improvement, cheapest moves first | Predictable latency; no cooling schedule to own |
| 2-opt | sampled (40 pairs) not enumerated | Anchors reach ~60 on long routes; O(A²) rebuilds would dominate |
| Distances | SciPy multi-source Dijkstra in C; anchor matrix per cluster | Was being rebuilt per GRASP seed — cost more than the seeds |
| Path recovery | Python Dijkstra with predecessor tracking, memoized both directions | Local search asks for the same anchor pairs constantly |
| Prize table | vectorized, computed once per cluster | Replaced ~400k Python calls per request; **10× speedup** |

Measured effect of the last three: 2,348 ms → 440 ms on the 7.5-mile case.

---

## 4. Candidate generation

**Strategy.** 5 clusters × 4 GRASP seeds = up to 20 candidate routes per request, each
improved, best-scoring wins.

**How clusters are discovered.** Union-find over incomplete REQUIRED segments sharing a
node. Each cluster is scored `density × 1000 + households × 0.4 + usable × 0.01`, where
`usable = min(cluster_length, budget − 2 × access)` — work you cannot reach and return
from is not work.

**Search-space pruning.**
- Cluster radius is **budget / 2**. Beyond that there is no round trip, so `usable` is
  zero by definition. (An earlier "adaptive radius" widened on failure and did nothing,
  because this cap bound every setting to the same value. Removed.)
- Candidate segments are dropped when `2 × dist_home + length > 1.35 × budget`.
- Anchors capped at 420; the walk falls back to a cached single-source Dijkstra if it
  steps outside the matrix. **This fallback matters** — without it, long routes stopped
  at half their budget.

**Why this balance.** 20 candidates is enough for GRASP's diversity to show (best and
median candidate differ by 10–25% on score) and cheap enough to stay inside 400 ms.

---

## 5. Scoring model

All components are computed and stored separately (`RouteScore`), so a weight change
can be replayed against stored routes via `score.rescore()` without re-running search.

| Weight | Value | Rationale |
|---|--:|---|
| `new_required_mile` | **+100** | The objective. Everything else is measured against a mile of new coverage. |
| `household` | +0.35 | 300 households ≈ one mile of street. Keeps dense blocks competitive with long empty ones. |
| `corridor_completion` | +25 | Finishing "Wilson Ave" reads as an accomplishment; a quarter-mile of it does not. |
| `dead_end_completion` | +12 | Dead ends are expensive (in and out) and get skipped without a nudge. |
| `isolation_bonus` | +8 | Orphaned leftovers are the endgame problem; pay to clear them early. |
| `cohesion` | +40 × [0,1] | Neighbourhood readability. |
| `repeat_mile` | **−45** | Below `new_required_mile`, so doubling back to reach new coverage is allowed but never free. |
| `connector_mile` | −12 | Necessary, not valuable. |
| `derived_connector_use` | −6 | Synthetic links no source asserted; usable, mildly discouraged. |
| `stress_mile` | −9 | Scaled by `(walk_stress−1)/4`. |
| `turn` | −0.7 | Only counted at nodes with a real choice (degree > 2). |
| `uturn` | −6 | Free at genuine dead ends, penalised at through-nodes. |
| `length_overshoot` | **−120** | A broken promise: asked for 3 miles, got 4. |
| `length_undershoot` | **−25** | Asymmetric on purpose — see below. |
| `loop_shape` | +18 × [0,1] | Loop rather than out-and-back. |

**The asymmetry is the important one.** Overshoot is penalised nearly 5× harder than
undershoot, because undershooting usually means there was not enough incomplete work in
reach — information, not a fault. A 1.2-mile route that collects everything available
beats a 3.5-mile route padded with repeat travel to hit a number. The stress test at
75%+ completion is what forced this.

`walk_quality` (0–100) is computed and reported but **deliberately not optimized** — it
is what we tell the walker, not what the router maximizes.

---

## 6. Route variants

Five bands: Quick 1.0, Short 2.0, Medium 3.5, Long 5.0, Extended 7.5 miles.

**Construction: build Quick, then extend.** The original design built Extended and
pruned down. That produced degenerate short variants — a one-mile subset of an
eight-mile sweep is the first excursion and the walk home. Nesting has to be built in
the direction it is consumed.

**Nesting is defined on coverage** — the REQUIRED segments earned — not on every
segment traversed. A longer variant legitimately walks home a different way; the
connectors on that closing leg are incidental. Requiring the whole traversal to nest
made every extension past ~3.8 miles fail.

**When extension cannot grow**, the engine falls back to an independent search and takes
it only if it scores ≥15% better. Which branch ran is reported per variant
(`nested: true/false`). In the benchmark this happened at 2 of 30 location-variant
pairs, both from downtown at 0% completion where the good nearby work was already
inside the shorter route.

**When a band is impossible**, it is reported as unavailable with the reason and the
distance to the nearest un-walked street, rather than returning nothing. At 85%
completion, Quick and Short are genuinely unavailable from downtown — nearest work is
1.66 miles away.

---

## 7. Benchmark results

Full data: `api/routing/results/benchmark.json`. Walking speed 3.0 mph.

### Fresh network (0% complete)

| Location | Variant | mi | min | new mi | repeat | households | quality | score |
|---|---|--:|--:|--:|--:|--:|--:|--:|
| Downtown | Quick | 1.04 | 21 | 1.04 | 0.00 | 171 | 88.8 | 248 |
| Downtown | Short | 2.06 | 41 | 1.94 | 0.12 | 298 | 71.7 | 434 |
| Downtown | Medium | 3.78 | 76 | 2.80 | 0.98 | 486 | 52.2 | 583 |
| Downtown | Long | 5.39 | 108 | 4.64 | 0.70 | 696 | 64.7 | 961 |
| Downtown | Extended | 8.09 | 162 | 6.43 | 1.66 | 1,919 | 54.6 | 1,430 |
| VT campus | Medium | 3.62 | 72 | 2.66 | 0.59 | 356 | 64.0 | 527 |
| VT campus | Extended | 8.10 | 162 | 6.51 | 1.31 | 1,988 | 64.2 | 1,452 |
| Hethwood | Medium | 3.17 | 63 | 2.20 | 0.97 | 159 | 56.1 | 394 |
| Hethwood | Extended | 8.06 | 161 | 4.70 | 3.36 | 1,836 | 48.1 | 1,135 |
| North Main | Medium | 3.41 | 68 | 2.58 | 0.84 | 387 | 64.9 | 584 |
| South Main | Medium | 1.42 | 28 | 0.85 | 0.25 | 0 | 73.2 | 176 |
| Town boundary NW | Medium | 3.52 | 70 | 1.76 | 1.76 | 38 | 53.0 | 191 |

**Percentage gain** (`new_required / 135.271 mi town-wide`): Quick ≈ 0.77%, Medium ≈
2.1%, Extended ≈ 4.8% per walk from downtown.

Two locations are visibly weaker and both are the network telling the truth:

- **South Main** returns 0 households on every variant and cannot fill Medium. The snap
  point sits in the commercial/industrial strip; there are genuinely no associated
  households nearby. Worth a human look — it may also reflect held apartment complexes.
- **Near the town boundary (NW)** shows `repeat == new` exactly on every variant. It is
  a dead-end corridor: there is no loop to be had, only out-and-back. Correct, and ugly.

### Mostly completed (85%)

| Location | Variant | mi | new mi | quality | note |
|---|---|--:|--:|--:|---|
| Downtown | Quick | — | — | — | unavailable; nearest work 1.66 mi |
| Downtown | Short | — | — | — | unavailable; nearest work 1.66 mi |
| Downtown | Medium | 3.46 | 0.04 | 54.7 | 1.66 mi approach each way |
| Downtown | Long | 5.38 | 0.36 | 63.4 | |
| Downtown | Extended | 7.31 | 1.77 | **92.6** | best quality in the whole benchmark |

The Extended variant at 85% completion scoring 92.6 with **zero repeat mileage** is the
clearest evidence the approach works late: given enough budget to reach the remaining
work, it produces an excellent loop.

---

## 8. Performance

| Metric | Value |
|---|--:|
| Network load + graph build | 330 ms + **3.7 ms** |
| Single route, median | **14.8 ms** |
| Single route, p90 | 131 ms |
| Single route, max | 217 ms |
| Five nested variants, median | **379 ms** |
| Five nested variants, max | 1,775 ms |

Median single-route latency is well inside interactive. The 1.8-second worst case for
five variants is downtown at 0% completion — the densest possible request, where the
extension fallback runs an extra independent search per band. Fixable by capping
`seeds_per_cluster` for the longer bands if it matters; it is not on the critical path
for a prototype.

---

## 9. Stress test across the project lifecycle

Medium (3.5 mi) from four locations, spatially-contiguous completion.

| Completion | Remaining | Route mi | New mi | Efficiency | Quality | ms |
|---|--:|--:|--:|--:|--:|--:|
| 0% | 135.3 | 3.69 | 2.94 | **0.80** | 66.0 | 154 |
| 25% | 101.4 | 3.71 | 2.72 | 0.74 | 63.8 | 129 |
| 50% | 67.6 | 3.60 | 1.66 | 0.47 | 61.3 | 93 |
| 75% | 33.8 | 2.83 | 0.18 | **0.12** | 54.0 | 29 |
| 90% | 13.5 | 3.18 | 0.04 | 0.01 | 52.8 | 8 |
| 98% | 2.7 | 3.18 | 0.04 | 0.01 | 52.8 | 7 |
| 98% scattered | 2.6 | 2.60 | 0.17 | 0.07 | 65.3 | 12 |
| dead ends only | 21.6 | 3.23 | 0.24 | 0.08 | 55.0 | 12 |

**This is the most important table in the report, and it does not say what I hoped.**

Efficiency holds well through 50% and then collapses. At 75%+ the router walks 3.5
miles to gain 0.04 — but that is not a routing failure. Under spatially-contiguous
completion the remaining work is one far-away region, so from a completed neighbourhood
there is genuinely nothing nearby, and the round trip *is* the route. The engine reports
this honestly (`approach_miles`, `nearest_incomplete_miles`) rather than pretending.

Two things confirm the diagnosis rather than a defect:

- **"98% scattered"** — same 2.6 remaining miles, randomly distributed instead of
  clustered — scores efficiency 0.07 and **quality 65.3**, the best of any late state.
  When leftovers are spread out, there is always something near, and the router finds it.
- **Downtown Extended at 85%** reaches 1.77 new miles at quality 92.6. Given the budget
  to cross town, the routes are excellent.

So the late-game problem is a **product** problem, not an algorithm one: at high
completion the app must say "the nearest un-walked street is 1.7 miles away — try
Extended, or start from Hethwood" instead of silently offering a poor Medium.

---

## 10. Route quality review

31 routes analysed (`api/routing/results/quality-review.json`).

| Metric | Mean | Median | p90 | Max |
|---|--:|--:|--:|--:|
| Sharp turns / mile | 3.37 | 3.30 | 5.6 | 7.9 |
| U-turns / mile | 0.20 | 0.00 | 0.81 | 1.1 |
| Runs per distinct street | 1.59 | 1.67 | 2.0 | 2.12 |
| Loop shape | 0.69 | 0.67 | 0.93 | 1.0 |
| Cohesion | 0.58 | 0.57 | 0.78 | 0.98 |
| Repeated share | 0.31 | 0.33 | 0.50 | 0.52 |
| Street runs (turn-by-turn steps) | 17.4 | 16 | 35 | 42 |
| Walk quality | 64.9 | 60.3 | 82.3 | 92.6 |

> The turn-angle helper was returning the same direction vector for the incoming and
> outgoing segment, making every deviation angle zero — turns/mile read 0.08 and all
> zigzagging was invisible to the score. Fixed; the numbers above are post-fix.

**Findings and recommendations:**

| Severity | Issue | Recommendation |
|---|---|---|
| **MEDIUM** | Repeat traversal on longer routes — p90 50% of traversals are repeats | Scale `repeat_mile` with route length: a 7-mile route should tolerate proportionally less doubling back than a 1-mile one. Currently −45/mi is outbid by +100/mi of new coverage at any length. |
| LOW | Streets entered more than once (1.59 runs per street) | Add a small continuous-run bonus. Improves how the route reads as directions without changing what it covers. |
| LOW | Cohesion measured from a bounding box | Punishes legitimately linear neighbourhoods. Replace with convex-hull area or street-name entropy **before** raising its weight. |
| LOW | Synthetic connectors appear in routes (max 4) | Within policy — only HIGH_CONFIDENCE route. But surface them in turn-by-turn text ("cross here") so a walker is not surprised by a link no source asserted. |
| INFO | **Campus routing is behaving** | 12 campus segments across 4 campus routes, **0 of them ALTERNATIVE**. The Phase 2a.1 corridor normalization is holding — routes use canonical corridors and never claim a duplicate obligation. |

Zigzagging and U-turns are both acceptable: 3.4 sharp turns per mile is a normal
neighbourhood sweep, and the median route has zero U-turns.

---

## 11. Known limitations

1. **Late-game routing needs product support, not more algorithm** (§9). Above ~75%
   completion the engine should drive UI copy about where the remaining work is.
2. **"Approved connector" is a placeholder definition.** No human connector-approval
   pass has run, so it currently means "OPTIONAL_CONNECTOR, walkable, authoritative
   source". 761 connectors qualify on that basis. Tighten to an explicit allow list
   after review and re-freeze.
3. **41 required segments (4.31 mi) are unreachable** in the main component — the
   Corporate Research Center across the 460 bypass, the Smart Road. The router cannot
   route to them and does not pretend to. Coverage can never reach 100% until they are
   reclassified or connected.
4. **Cohesion is a crude proxy** (bounding box). Do not raise its weight before
   replacing the measure.
5. **No elevation.** `Slope` in the source is uniformly zero (Phase 2a finding), so
   walk stress is speed- and class-based only. A hilly route and a flat route score the
   same.
6. **Household counts on routes exclude 6,279 held units** — routes through complexes
   under review under-report their household reach.
7. **Reservations are implemented but untested** — `prize_multiplier` damps reserved
   segments; no multi-walker scenario has been run.
8. **Deterministic seed.** Same start + same state gives the same route every time. Good
   for testing, but two walkers starting together get identical routes. Vary the seed
   per participant when this reaches the app.
9. **Length bands are hard-coded** in `VARIANTS` and not yet user-configurable.
10. **South Main returns zero households** on every variant — plausible for a commercial
    strip, but worth one human check that it is not an association artefact.

---

## 12. Recommended tuning opportunities

Ordered by expected benefit per unit of effort:

1. **Length-scaled repeat penalty** (§10 MEDIUM finding). One-line change, directly
   improves the weakest measured dimension on long routes.
2. **Continuous-run bonus** — makes routes read better as directions for near-zero cost.
3. **Replace cohesion with a hull or entropy measure**, then consider raising its weight.
4. **Cap `seeds_per_cluster` on the longer bands** to pull the 1.8 s worst case down.
5. **Upgrade Layer 3 to simulated annealing** if route quality proves insufficient in
   the pilot. Drop-in at one interface; no other layer changes.
6. **Tune `rcl_alpha`** (0.45) — the diversity/greed dial. Not yet swept.
7. **Per-participant random seed** for multiplayer variety.
8. **Elevation from a DEM**, which would also close the D2 grade gap from Phase 2a.

Every one of these is a weights or config change except 5 and 8.

---

## 13. Go / no-go for integrating into the PWA

# ✅ GO — with two conditions

| Criterion | Status |
|---|---|
| Produces closed loops from arbitrary starts | ✅ 30/30 location-variant pairs at 0% completion |
| Maximizes coverage, not shortest distance | ✅ efficiency 0.80 at 0%, 0.74 at 25% |
| Prioritizes incomplete segments | ✅ new-required mileage dominates the score |
| Five nested variants | ✅ nesting on coverage guaranteed; fallback reported when not |
| Scales as completion approaches 100% | ⚠️ **degrades honestly, needs product support** (§9) |
| Interactive latency | ✅ median 15 ms single route, 379 ms for five variants |
| Tunable without redesign | ✅ one weights dataclass; stored components support rescoring |
| Inspectable | ✅ per-route score breakdown, visual review page, repeatable harness |
| Multiplayer-ready | ✅ engine is stateless; reservations are a prize multiplier |
| Does not modify the canonical network | ✅ read-only; network id checked on load |

**Condition 1 — the late-game UX must be designed before launch.** Above ~75%
completion the honest answer is often "there is nothing good within a mile of you."
The engine surfaces `nearest_incomplete_miles` and `approach_miles` for exactly this;
the app has to use them. Shipping without it means walkers get progressively worse
routes with no explanation, at precisely the point the project is nearly finished and
morale matters most.

**Condition 2 — apply the length-scaled repeat penalty and re-run the harness.** It is
the one measured defect with a known fix, and the harness makes verifying it a
five-minute job.

Neither condition blocks starting integration.

---

## 14. Files

```
api/routing/
  network.py     frozen network v1.0, checksum, routing-graph membership rule
  graph.py       CSR graph, Dijkstra, memoized paths, component analysis
  state.py       CompletionState, Route, turn/cohesion/loop geometry
  score.py       Weights, RouteScore, rescore()
  engine.py      cluster discovery -> GRASP -> improvement -> variants
  bench.py       Step 7-8 harness
  quality.py     Step 9 review
  viz.py         representative-route visualisation
  results/
    benchmark.json       full Step 7-8 data + frozen network manifest
    quality-review.json  Step 9 metrics and findings
    routes.html          13 representative routes (gitignored — derived geometry)
```

Reproduce:

```
python3 -m api.routing.bench
python3 -m api.routing.quality
python3 -m api.routing.viz
```

### Frozen network manifest (Step 1)

| | |
|---|---|
| Canonical network version | **v1.0** |
| Network id | `bbg-net-v1.0-b61d1067f9a57e32` |
| Build date | 2026-08-03 (snapshot 2026-08-03) |
| Checksum | sha256 over (id, role, type, connector_class, length, nodes, households, campus_obligation) for every canonical segment, sorted; first 16 hex |
| Required mileage | 135.271 mi (124.848 street + 10.423 trail) |
| Connector mileage | 68.903 mi authoritative + 0.871 mi derived |
| Excluded mileage | 48.278 mi (not in the routing graph) |
| Campus corridor mileage | 11.359 mi canonical |
| Routable total | 205.045 mi across **2,496 segments / 2,280 nodes** |
| Households | 11,029 on required coverage · 6,279 held |
| Excluded from routing graph | 460 EXCLUDED · 30 CROSSING_REVIEW_REQUIRED · 8 LIKELY_FALSE · 4 UNRESOLVED |

The engine records this id on every route. A changed network produces a different id,
so any stored route is always traceable to the network it was computed on.
