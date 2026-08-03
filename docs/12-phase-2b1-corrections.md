# Phase 2b.1 — Routing Corrections and Integration Readiness

**Date:** 2026-08-03
**Canonical network:** **v1.1** · `bbg-net-v1.1-3855ef9c4c15358a`
**Routing engine:** **v2.0.0**
**Verdict: GO for PWA integration.** All seven gates pass.

Manifest: `api/routing/results/integration-candidate-2.0.0.json`.

---

## 1. Length-scaled repeat penalty

### What changed

One flat `repeat_mile = −45` became five terms that distinguish *why* a segment was
walked twice:

| Weight | Value | What it covers |
|---|--:|---|
| `repeat_avoidable_mile` | −55 × band factor | Doubling back through covered ground because nothing better was found |
| `repeat_closing_mile` | −20 | The walk home from the last piece of new coverage |
| `repeat_dead_end_mile` | −6 | A cul-de-sac must be walked twice. Token cost only. |
| `repeat_share_quadratic` | −260 × share² × length factor | Repeat as a *proportion* of the route |
| `repeat_extra_traversal` | −14 each | Third and later passes over one segment |

Band factor = `√(target / 2.0 mi)` — 0.71 for Quick, 1.32 for Medium, 1.94 for
Extended. A seven-mile route is held to a tighter standard per mile than a one-mile one.

**Categorisation is done at build time, not inferred.** Each route records
`closing_leg` — how many trailing segments are the walk home — so the scorer can tell
necessary travel from avoidable doubling back rather than guessing from geometry.

### Before and after — controlled A/B

A straight Phase 2b vs Phase 2b.1 benchmark comparison would be dishonest: the
location set changed (South Main moved, CRC added) *and* the network changed (Smart
Road excluded). So this runs the **same code over the same 89 routes**, changing only
the weights (`api/routing/ab_repeat.py`).

| Metric | Before | After | Δ |
|---|--:|--:|--:|
| **Avoidable repeat miles** | 0.546 | **0.468** | **−14.2%** |
| **Avoidable repeat share** | 0.128 | **0.114** | **−11.1%** |
| **Third-or-later passes** | 0.809 | **0.371** | **−54.2%** |
| **U-turns** | 0.944 | **0.775** | **−17.9%** |
| Sharp turns | 14.775 | 13.775 | −6.8% |
| Total repeat miles | 1.304 | 1.213 | −7.0% |
| **Dead-end returns** | 0.178 | **0.200** | **+12.7%** |
| **New required miles** | 2.029 | **2.038** | **+0.4%** |
| **Households** | 399.8 | **414.7** | **+3.7%** |
| **Walk quality** | 65.3 | **66.9** | **+2.4%** |
| Route distance | 4.064 | 4.003 | −1.5% |
| Compute time | 699 ms | 710 ms | +1.6% |
| Route-size availability | 89 / 105 | 89 / 105 | unchanged |

Score fell 5.6%, which is expected and not a regression: the new weights are strictly
more punitive on repeats, so an identical route scores lower. Scores are not comparable
across weight sets; the physical metrics above are.

**Dead-end returns rising 12.7% is the intended effect, not a side effect.** Under the
flat penalty the router avoided cul-de-sacs because entering one guaranteed a repeat
charge — and cul-de-sacs are where households are. Households up 3.7% with coverage
flat is that behaviour reversing.

**Coverage and coherence were not damaged.** New required mileage +0.4%, households
+3.7%, walk quality +2.4%, U-turns and turns both down. Nothing traded off.

### Full harness re-run

Post-change quality review over 35 routes (`results/quality-review.json`):

| Metric | Mean | Median | p90 | Max |
|---|--:|--:|--:|--:|
| Avoidable repeat share | 0.08 | 0.06 | **0.13** | 0.31 |
| Closing-leg miles | 0.42 | 0.28 | 1.20 | 1.77 |
| Dead-end return miles | 0.20 | 0.08 | 0.40 | 1.42 |
| Extra traversals | 0.26 | 0 | 1 | 2 |
| Turns / mile | 3.29 | 2.8 | 5.8 | 7.9 |
| U-turns / mile | 0.22 | 0.0 | 0.81 | 1.1 |
| Loop shape | 0.72 | 0.73 | 0.93 | 1.0 |
| Walk quality | 71.0 | 68.2 | 82.1 | 91.5 |

The repeat finding has dropped from **MEDIUM** to **INFO**: *"p90 0.13 of route mileage
is avoidable doubling back; the length-scaled, category-aware repeat penalty is
holding."*

---

## 2. Multiple valid routing components

The engine no longer assumes one town-wide graph.

- **Start snapping** goes to the nearest node in a component classified valid, not to
  the main component. A walker in the Corporate Research Center routes the CRC.
- **Candidate generation is scoped to the start's own component.** Work in another
  component is unreachable by definition and is never offered.
- **The router never invents a connection.** Separation is reported, not bridged.
- **Tiny islands are excluded from snapping** (`start_snap_allowed = False`), so a bad
  snap cannot strand a request on a two-node fragment.

### Components carrying required mileage

| # | Description | Req mi | HH | Public | Cycle | Sep. | Closed route? | Classification | In denominator |
|---|---|--:|--:|:-:|:-:|--:|:-:|---|:-:|
| 0 | Main Blacksburg network | 130.536 | 10,622 | ✅ | ✅ | — | ✅ all 5 bands | **VALID_INDEPENDENT_ROUTING_AREA** | ✅ |
| 3 | Research Center Dr area (Kraft, Pratt, Knollwood) | 2.044 | 288 | ✅ | ✅ | 0 m | ✅ 4 bands | **VALID_INDEPENDENT_ROUTING_AREA** | ✅ |
| 2 | Scenic Ridge Cir | 0.586 | 59 | ✅ | ✅ | 0 m | ✅ 4 bands | **VALID_INDEPENDENT_ROUTING_AREA** | ✅ |
| 77 | Davis St | 0.305 | 0 | ✅ | ✗ | 6.7 m | ✅ out-and-back, 0.61 mi | **VALID_INDEPENDENT_ROUTING_AREA** | ✅ |
| 16 | Apple Ln / Sandstone Rdg | 0.297 | 46 | ✅ | ✗ | 89 m | ✅ out-and-back, 0.59 mi | **VALID_INDEPENDENT_ROUTING_AREA** | ✅ |
| 28 | Georgia St / Bradley Ln | 0.292 | 8 | ✅ | ✗ | 11.8 m | ✅ out-and-back, 0.58 mi | **VALID_INDEPENDENT_ROUTING_AREA** | ✅ |
| 76 | Brush Mountain Rd | 0.080 | 0 | ✅ | ✗ | 59 m | ✗ 0.16 mi | DATA_ERROR_OR_REVIEW_REQUIRED | ✅ |
| 41 | Coal Bank Hollow Rd | 0.039 | 0 | ✅ | ✗ | 59 m | ✗ 0.08 mi | DATA_ERROR_OR_REVIEW_REQUIRED | ✅ |
| 86 / 46 / 12 | Shenandoah Trail Spur (3 fragments) | 0.051 | 1 | ✅ | ✗ | 0 m | ✗ | DATA_ERROR_OR_REVIEW_REQUIRED | ✅ |

**106 further components carry no required mileage → CONNECTOR_ONLY.**

| Classification | Components | Required mi | Households |
|---|--:|--:|--:|
| VALID_INDEPENDENT_ROUTING_AREA | **6** | **134.060** | 11,023 |
| DATA_ERROR_OR_REVIEW_REQUIRED | 5 | 0.170 | 1 |
| CONNECTOR_ONLY | 106 | 0 | 0 |
| INACCESSIBLE_OR_RESTRICTED | 0 | 0 | 0 |

**Nothing was removed from the denominator.** All 134.229 required miles remain in it —
the 0.170 mi in review-required fragments is still required street, we simply cannot
build an independent route to it yet.

`INACCESSIBLE_OR_RESTRICTED` is empty because the only member — the Smart Road — is now
handled upstream as an eligibility correction (§3) rather than as a routing exclusion.
That is the right place for it: it is not eligible, not merely unroutable.

### Two classification bugs found and fixed

- **Unknown ownership was being read as a prohibition.** The Paths layer leaves `Owner`
  blank on 83% of features, so three Shenandoah Trail Spur fragments were classified
  `INACCESSIBLE_OR_RESTRICTED`. Restricted now means `PRIVATE` or `GATED` — someone has
  actually said no.
- **Separation was measured in degrees.** Distances were multiplied by a constant
  instead of projected, which is why the CRC first reported a 6.4 m gap and then 0 m.
  Now computed in EPSG:6594.

---

## 3. Smart Road reclassified — network v1.1

**Gordon C Willis Smart Rd: REQUIRED → EXCLUDED.** 6 segments, **1.041 miles**.

The Virginia Smart Road is VTTI's controlled research facility — gated, instrumented,
closed to the public except on organised tours. Members of the public cannot lawfully
walk it. It carries `RD_MAINT = Blacksburg` in the town's 911 file because ambulances
must be routed there, which is exactly the failure mode the Phase 1 audit warned about:
**presence in a 911 road layer is not evidence of public access.**

Implemented as a **curation override** (`pipeline/build/curation.py`
→ `ROLE_OVERRIDES_BY_NAME`), applied after the automatic rules on every build, per
technical plan §2.4. Keyed on `normalized_name` so it survives a rebuild that renumbers
segments. It is not a hand-edit of pipeline output and it cannot be lost silently.

| | v1.0 | **v1.1** |
|---|--:|--:|
| Network id | `bbg-net-v1.0-b61d1067f9a57e32` | **`bbg-net-v1.1-3855ef9c4c15358a`** |
| Required mileage | 135.271 | **134.229** |
| — required street | 124.848 | 123.807 |
| — required trail | 10.423 | 10.423 |
| Completion denominator | 135.271 | **134.229** |
| Unreachable required mileage | 4.315 (incl. 0.621 Smart Road) | **0.170** |
| Routing segments | 2,496 | 2,490 |
| Households on required coverage | 11,029 | 11,024 |

**Unreachable required mileage fell from 4.315 mi to 0.170 mi** — 0.621 by excluding the
Smart Road, and the rest by recognising that the CRC, Scenic Ridge, Davis St, Apple Ln
and Georgia St are routable in their own right rather than "off the main component."

---

## 4. Corporate Research Center — retained as REQUIRED

**Verdict: public, walkable, locally routable. Kept as REQUIRED, classified
VALID_INDEPENDENT_ROUTING_AREA, added to the benchmark harness.**

| Question | Answer |
|---|---|
| Are its streets public and walkable? | **Yes.** Research Center Dr, SW Kraft Dr, Pratt Dr, N/S Knollwood Dr all carry `RD_MAINT = Blacksburg` and `access_type = PUBLIC`. |
| Can a user starting inside be snapped to it? | **Yes** — `snap()` now restricts to valid components, and (-80.4069, 37.2010) lands on component 3. |
| Can it generate useful closed loops? | **Yes.** 32 nodes, 34 edges — it contains cycles. Measured routes: 0.82 mi (Quick), 1.54 mi (Short), 3.56 mi (Medium+), collecting all 2.04 required miles and 288 households. |
| Is an excluded highway crossing being wrongly treated as necessary? | **The Phase 2b framing was wrong.** The CRC is not cut off by the US-460 bypass. It is separated by **at-grade crossings of Research Center Dr and SW Kraft Dr** that the connector classifier marked `CROSSING_REVIEW_REQUIRED` — 25–35 mph secondary roads. Those are ordinary street crossings that a human review will almost certainly approve, at which point the CRC merges into the main component. |
| Should it be a valid independent routing area? | **Yes**, and it is. |

Eight connectors touching the CRC are held out of the routing graph: Rimrock Dr →
Research Center Dr (8.6 m), Kraft Drive Trail → Research Center Dr (7.5 m), Research
Center Drive → Kraft Dr SW (6.6 m), and five more.

> **CORRECTED 2026-08-03 (Phase 3, docs/13 §1).** Two claims above are wrong.
>
> 1. **Reviewing these eight would NOT fold the CRC back into the main network.** Each
>    links the CRC to a *small isolated fragment*, not to the town graph. The review is
>    still worth doing for local CRC walkability, but whatever separates the CRC from
>    downtown is not in this list. Measured in
>    `review/crc-crossings.json → if_all_crc_crossings_were_promoted`.
> 2. **It is not the highest-value connector review available.** Under network v1.2
>    that is the campus↔town crossings, chiefly of Prices Fork Rd, worth 6.080 mi of
>    stranded required mileage.
> 3. One of the eight is `LIKELY_FALSE` and one `UNRESOLVED`; the sentence above
>    implied all eight were `CROSSING_REVIEW_REQUIRED`.
>
> The connector-attribution figures elsewhere in this document also understated
> connector-caused disconnection, because `attribute_disconnection` could never add a
> rejected connector back — see docs/13 §1, finding 2.

---

## 5. South Main household validation

**Root cause: the benchmark coordinate was wrong. The household methodology is correct
and unchanged.**

`(-80.4180, 37.2130)` is not on South Main Street — it is roughly 1.5 km west, and it
snapped to node 1181 on **Innovation Dr / Research Center Dr / Smoot Drive Trail**. The
routes it produced covered Innovation Dr and Research Center Dr, in the research-park
strip.

Evidence:

| Check | Result |
|---|---|
| Residential dwelling units within 250 m of the tested route | **0** |
| Within 150 m / 100 m / 75 m | 0 / 0 / 0 |
| Households on the covered required segments | 0 on all 6 |
| Units associated but on other segments | 0 |
| Units held for review nearby | 0 |

So the zero was **correct for where the route actually was**. Not a land-use error, not
a threshold artefact, not a held-units artefact, not a reporting bug.

**Correction applied:** the benchmark location moved to **(-80.4059, 37.2220)** — the
residential stretch of S Main St, with **305 dwelling units within 300 m**. South Main
now reports 137 households (Quick) to 845 (Extended).

S Main St as a whole carries **62 segments, 5.99 required miles, 183 households**
directly attached, distributed along the corridor from lat 37.1966 to 37.2286.

No change to `households.py`, the association cap, or the residential filter.

---

## 6. Late-opportunity response states

`api/routing/response.py`. Every band of every request returns a structured state
decided from **local** conditions — never from a town-wide completion percentage. A
town at 40% can have a finished neighbourhood; a town at 95% can have good walking left
in one corner.

| State | When | Carries |
|---|---|---|
| `ROUTE_AVAILABLE` | ≥0.25 new mi **and** ≥30% efficiency | new mi, efficiency, households, quality |
| `LIMITED_LOCAL_COVERAGE` | route exists but mostly approach or repeat | new mi, efficiency, approach mi, suggested longer band |
| `LONGER_ROUTE_REQUIRED` | this band cannot reach the work, a longer one can | nearest incomplete mi, which band works |
| `NO_USEFUL_ROUTE_NEAR_START` | nothing reachable at any band | nearest incomplete mi, reason |
| `SELECT_DIFFERENT_START_AREA` | nothing here and the work is >2.5 mi away | nearest incomplete mi |

Inputs: distance to nearest incomplete REQUIRED segment, approach distance, expected
new mileage, new-coverage efficiency, walk quality, and which bands the start's
component can support. **No band is ever padded with low-value mileage to avoid
returning a reason.**

Observed behaviour at 85% completion:

```
South Main   Quick    LONGER_ROUTE_REQUIRED   nearest un-walked street 2.6 mi away; Long works
             Short    LONGER_ROUTE_REQUIRED
             Medium   LONGER_ROUTE_REQUIRED
             Long     LIMITED_LOCAL_COVERAGE  4.80 mi, 0.04 new (1%)
             Extended LIMITED_LOCAL_COVERAGE  8.04 mi, 0.89 new (11%)

CRC          all five ROUTE_AVAILABLE         its own component is untouched
```

An interface has everything it needs for *"There are no remaining unprayed streets near
this starting point"*, *"The nearest unfinished area is approximately 2.6 miles away"*,
and *"Choose another starting point or view the nearest unfinished area."* No copy is
composed in the engine.

---

## 7. Integration candidate

| | |
|---|---|
| **Canonical network version** | **v1.1** — `bbg-net-v1.1-3855ef9c4c15358a` |
| Previous | v1.0 — `bbg-net-v1.0-b61d1067f9a57e32` |
| **Routing engine version** | **2.0.0** |
| Snapshot date | 2026-08-03 |
| **Required mileage** | **134.229 mi** (123.807 street + 10.423 trail) |
| **Valid routing components** | **6** |
| Required mi by component | 130.536 main · 2.044 CRC · 0.586 Scenic Ridge · 0.305 Davis · 0.297 Apple Ln · 0.292 Georgia St |
| **Smart Road excluded** | **1.041 mi** (6 segments) |
| **Remaining unresolved / inaccessible required mileage** | **0.170 mi** (5 fragments, all review-required, all still in the denominator) |
| Connector mileage | 68.903 authoritative + 0.871 derived |
| Households | 11,024 on required coverage · 6,284 held |
| Routing graph | 2,490 segments · 2,273 nodes |

### Benchmark summary

Fresh network, 40 location-variant pairs across 7 starts:

| Location | Medium mi | New mi | Households | Quality |
|---|--:|--:|--:|--:|
| Downtown Blacksburg | 3.75 | 2.82 | 481 | 60.9 |
| Virginia Tech campus | 3.77 | 2.71 | 1,077 | 66.3 |
| Hethwood | 3.73 | 2.44 | 216 | 56.1 |
| North Main | 3.58 | 3.03 | 1,336 | 71.5 |
| **South Main** *(corrected)* | 3.78 | 3.22 | **349** | 67.9 |
| Near town boundary (NW) | 3.52 | 1.76 | 38 | 53.0 |
| **Corporate Research Center** *(new)* | 3.56 | 2.04 | 288 | 65.3 |

Stress across completion states is materially better at every level than Phase 2b:
quality at 75% rose from 54.0 to ~65, at 90% from 52.8 to ~64.

### Performance

| Metric | Value |
|---|--:|
| Single route, median | **14.8 ms** |
| Single route, p90 | 135.2 ms |
| Single route, max | 235.9 ms |
| Five variants, median | **386.6 ms** |
| Five variants, max | 2,019.5 ms |
| Engine build (graph + component classification) | ~9 ms |

Unchanged from Phase 2b within noise (+1.6% in the A/B), despite the added component
classification and response assessment.

---

## 8. Known limitations

1. **Eight CRC connectors await review** (§4). Reviewing them merges 2.044 mi and 288
   households into the main component. Highest-value connector review available.
2. **0.170 mi in five review-required fragments** — Brush Mountain Rd, Coal Bank Hollow
   Rd, three Shenandoah Trail Spur pieces. In the denominator, not independently
   routable. Three of them touch the main network at 0 m and are pure noding gaps.
3. **Three valid components cannot support the Quick band** — Davis St, Apple Ln and
   Georgia St max out at ~0.6 mi out-and-back. `supports_bands` is empty for them and
   the interface must offer a shorter walk or explain.
4. **"Approved connector" is still a placeholder** — 761 connectors qualify as
   "OPTIONAL_CONNECTOR, walkable, authoritative source" because no human connector
   approval pass has run. Unchanged from Phase 2b.
5. **Cohesion is still a bounding-box proxy** (median 0.56). Do not raise its weight
   before replacing the measure.
6. **No elevation.** Source `Slope` is uniformly zero, so walk stress is speed- and
   class-based only.
7. **6,284 households held for review** — routes through complexes under review
   under-report their reach.
8. **Deterministic seed** — two walkers starting together get identical routes. Vary
   per participant at integration.
9. **Reservations implemented but untested** — no multi-walker scenario has been run.
10. **Component classification thresholds are unvalidated by a human.**
    `MIN_REQUIRED_MI = 0.25` decides whether Apple Ln is a routing area or a data error.
    Worth one look at a map.

---

## 9. Go / no-go for PWA integration

| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1 | Repeat traversal materially improved without severe coverage loss | ✅ **PASS** | Controlled A/B, 89 matched routes: avoidable repeat −14.2%, third-or-later passes −54.2%, U-turns −17.9%; new coverage **+0.4%**, households **+3.7%**, quality **+2.4%** |
| 2 | Smart Road correctly classified | ✅ **PASS** | 6 segments / 1.041 mi REQUIRED → EXCLUDED via curation override; absent from the routing graph |
| 3 | Valid independent components supported | ✅ **PASS** | 6 valid areas; snapping restricted to them; candidate generation scoped to the start's component |
| 4 | No legitimate public area excluded for not joining the main graph | ✅ **PASS** | 0 public components ≥0.25 mi classified anything but valid; **0 mi removed from the denominator** |
| 5 | South Main household result explained | ✅ **PASS** | Bad benchmark coordinate, 1.5 km off-corridor; 0 dwelling units within 250 m of where it landed. Methodology unchanged. |
| 6 | Late-opportunity response states defined | ✅ **PASS** | 5 states from local conditions only; no band padded to avoid a reason |
| 7 | Route-generation performance interactive | ✅ **PASS** | 14.8 ms median single route; 386.6 ms median for five variants |

# ✅ GO for PWA integration

Carry forward, none blocking:

1. **Review the eight CRC connectors** — ~~biggest single connectivity win available~~
   *(corrected in §4: it is neither the biggest win nor a route to the main network)*.
2. **Handle components that cannot support the Quick band** in the UI (§8.3).
3. **Vary the random seed per participant** before two people walk together.
4. **The five Phase 2a.1 rulings are still open** — D1b campus promotion (11.36 mi), D2
   confirmation, the 40 ownership conflicts. They change the denominator, not the
   engine.
5. **Licensing gate G1 still blocks public release**, unchanged since Phase 2a.

---

## 10. Files

```
api/routing/
  network.py      v1.1 load, checksum, routing-graph membership
  components.py   component discovery + four-way classification      [new]
  response.py     structured late-opportunity response states        [new]
  ab_repeat.py    controlled A/B for the repeat penalty              [new]
  freeze.py       integration-candidate manifest + gates             [new]
  graph.py · state.py · score.py · engine.py · bench.py · quality.py · viz.py
  results/
    integration-candidate-2.0.0.json   the freeze
    ab-repeat-penalty.json             controlled A/B, both weight sets
    benchmark.json · quality-review.json
    before/                            Phase 2b baselines, kept for comparison
    routes.html                        16 representative routes (gitignored)
pipeline/build/curation.py             ROLE_OVERRIDES_BY_NAME (Smart Road)
```

Reproduce:

```
python3 -m pipeline.build.run        # applies the Smart Road override -> v1.1
python3 -m api.routing.bench
python3 -m api.routing.quality
python3 -m api.routing.ab_repeat
python3 -m api.routing.freeze
python3 -m api.routing.viz
```
