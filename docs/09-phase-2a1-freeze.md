# Phase 2a.1 — Review, Normalize, Freeze

**Date:** 2026-08-03 · **Candidate:** `candidate-network-v1` · **Snapshot:** 2026-08-03
**Verdict: GO for Phase 2b.** All six gates pass.

Everything below is produced by the pipeline and re-derivable:
`pipeline/out/2026-08-03/candidate-network-v1.json`.

---

## 1. Repository and licensing

| Item | State |
|---|---|
| Repository visibility | To be made **private** (currently public — verify before the next push) |
| Raw source snapshots | Excluded from version control (`.gitignore`) |
| Address-level data & household coordinates | Excluded — `households.json`, `unassociated-households.json` |
| Derived detailed geometry | Excluded — `segments.geojson`, `nodes.geojson`, map HTML |
| Licensing status | 🔴 **Release blocker, unchanged** |
| Permissions request | Preserved — [`05-licensing-status.md`](05-licensing-status.md) §2 |
| Source lineage | Preserved — every segment carries `source{dataset, source_id, GlobalID, layer URL, source_updated_at, retrieved_at, license_status}` |

No town dataset carries any licence text. `license_status = NONE_PUBLISHED` on all nine
layers, `DERIVED` on synthetic connectors. Gate G1 (written permission from Town
Engineering & GIS) still blocks public release and nothing else.

---

## 2. Synthetic connector review

426 connectors were proposed across five connect passes; **262 survive as distinct
segments** after duplicate-geometry dedup. All 262 are classified.

> **Basemap evidence: none.** Every imagery and tile host is denied by this
> environment's egress policy. Classification uses geometry, endpoint alignment, road
> class, speed limit, name agreement and crossing context only. Stated because the
> instruction asked for basemap evidence where available, and it was not available.

### 2.1 Counts by classification

| Class | Connectors | Miles | Routable by default |
|---|---:|---:|---|
| **HIGH_CONFIDENCE** | **220** | 0.871 | ✅ yes |
| CROSSING_REVIEW_REQUIRED | 30 | 0.137 | ❌ no |
| LIKELY_FALSE | 8 | 0.040 | ❌ no |
| UNRESOLVED | 4 | 0.029 | ❌ no |

Non-HIGH_CONFIDENCE connectors stay in the network with `routable_by_default = false`
and `walkable = false` — visible for review, unable to carry a route. Verified by gate
3: **0 non-HIGH_CONFIDENCE connectors are routable.**

**Rules.** `LIKELY_FALSE` fires on a connector that asserts access onto a limited-access
facility (`ROAD_CLASS ∈ {Ramp, Primary}`), crosses one mid-block, or reaches only an
`EXCLUDED` private drive. `HIGH_CONFIDENCE` fires on pedestrian-to-pedestrian joins,
name-agreement joins (a sidewalk offset from the street it belongs to), and short
(≤10 m) joins onto a ≤25 mph local street with no roadway crossed.
`CROSSING_REVIEW_REQUIRED` catches everything that steps into a trafficked roadway or
crosses a centerline, plus gaps over 15 m — too long to be a digitising offset.

The 8 `LIKELY_FALSE` are the sanity check that the rule works: three assert you can
walk onto the EB/WB 460 bypass or its ramps; five assert access onto private drives
(Henry Ln, Mary Jane Cir, Ridge Rd, Hunters Mill Rd).

### 2.2 Segments and mileage affected

| | Segments | Miles |
|---|---:|---:|
| Required segments whose reachability depends on a rejected connector | 6 | **0.310** |
| Required mileage unaffected either way | 1,509 | 134.961 |

### 2.3 Connectivity

Main component of the **default routing graph** (HIGH_CONFIDENCE only):

| | |
|---|---:|
| Nodes | **1,739** |
| Required mileage in main component | **130.958 mi** |
| Share of all required mileage | **96.81%** |
| Required mileage off main | 4.314 mi (45 segments) |

For comparison — the connectors matter far less to *required* reachability than
expected, because the town's Roads layer was already properly noded:

| Graph | Components | Main-component required mi | Share |
|---|---:|---:|---:|
| No connectors at all | 265 | 130.68 | 96.6% |
| HIGH_CONFIDENCE only *(the default)* | 118 | 130.96 | 96.8% |
| Every connector routable | 89 | 131.27 | 97.0% |

The connect stage buys **0.28 mi** of required reachability. Its real value is
pedestrian-network access — trails and sidewalks reaching the streets at all — not
required-mileage coverage.

### 2.4 Ten largest remaining disconnected components

| # | Segments | Miles | Required mi | Sample |
|---|---:|---:|---:|---|
| 1 | 66 | 6.490 | 0.000 | (pedestrian only) |
| 2 | 34 | 3.252 | 0.586 | Scenic Ridge Cir |
| 3 | 34 | 3.014 | 2.044 | N Knollwood Dr, Pratt Dr, Research Center Dr |
| 4 | 30 | 2.919 | 0.000 | (pedestrian only) |
| 5 | 12 | 0.241 | 0.000 | — |
| 6 | 8 | 0.734 | 0.000 | — |
| 7 | 8 | 0.457 | 0.000 | — |
| 8 | 8 | 1.019 | 0.000 | — |
| 9 | 7 | 0.160 | 0.000 | — |
| 10 | 6 | 0.429 | 0.000 | — |

**Only two disconnected components carry required mileage at all.**

### 2.5 Cause of disconnected required mileage

| Cause | Miles | Share |
|---|---:|---:|
| **Legitimate isolation or missing source data** | **4.004** | 92.8% |
| Rejected connectors | 0.310 | 7.2% |

The stranded required mileage, by street: Research Center Dr 0.65 · Gordon C Willis
Smart Rd 0.62 · SW Kraft Dr 0.59 · Scenic Ridge Cir 0.59 · Pratt Dr 0.42 · Davis St
0.31 · N/S Knollwood Dr 0.39 · Apple Ln 0.18 · others <0.2.

Two clusters explain most of it, and both are **real isolation, not a data defect**:

- **Corporate Research Center** (Research Center Dr, Kraft Dr, Pratt Dr — 1.66 mi) sits
  across the US-460 bypass. The only connections run along the bypass, which is
  correctly `EXCLUDED`. Even routing every connector does not reach it.
- **Gordon C Willis Smart Road** (0.62 mi) is VTTI's closed test facility. It is
  arguably misclassified: it should probably be `EXCLUDED`, not `REQUIRED`. Flagged in
  the decision table.

**Nothing here is caused by the connector policy.** Trusting the 42 rejected connectors
would recover 0.31 mi and add invented crossings of Prices Fork Rd.

---

## 3. Coverage-affecting decision table

**112 segments in 5 groups.** The ~1,000 connector-catalogue entries are deliberately
excluded: connector-versus-connector questions are real work but cannot make coverage
wrong. Full data: `review/coverage-decision-table.json`.

| Group | Segs | Miles | Recommended ruling | Why |
|---|---:|---:|---|---|
| **Provisional trails** | 24 | 2.175 | **CONFIRM as REQUIRED** | D2 recommended Deerfield and Shenandoah; both are short paved neighbourhood trails that pass homes, which is exactly the D2 test. Confirming changes nothing in the build; declining removes 2.18 mi from the denominator. |
| **Required-street conflicts** | 40 | 3.085 | **UPHOLD `RD_MAINT`** | 36 segments where `RD_MAINT`=Private and `ROAD_CLASS`=Local, plus 4 public streets whose midpoint falls inside an HOA/private open-space polygon. `RD_MAINT` is the maintenance authority's own field and **zero conflicts run the other way**. Uphold it; spot-check the 4 HOA cases (Wakefield Dr, Stradford Ln, Honeysuckle Dr) on a map. |
| **Campus path decisions (D1b)** | 73 | 11.359 | **PROMOTE canonical corridors to REQUIRED** | After normalization each corridor carries exactly one obligation, so promoting these adds campus coverage without demanding a walker cover the same street twice. Parallel walkways are already `ALTERNATIVE` and stay connectors. |
| **Derived connections affecting accessibility** | 42 | 0.206 | **KEEP OUT of the default graph; review the 30 crossing cases** | 8 `LIKELY_FALSE` assert access onto the 460 bypass, its ramps, or private drives — reject outright. 30 `CROSSING_REVIEW_REQUIRED` + 4 `UNRESOLVED` need a human. Only 0.31 mi of required mileage depends on any of them. |
| **Other consequential cases** | 48 | 3.965 | **REVIEW individually** | Trails `EXCLUDED` on a Paths `Owner=PRIV` tag, and off-main required stubs — notably **Gordon C Willis Smart Rd**, a closed research facility that is probably `EXCLUDED` rather than `REQUIRED`. |

---

## 4. Campus network normalization

**The problem:** the pedestrian layer represents each campus street with whatever
walkways exist beside it — often two (one per side), sometimes three (sidewalk plus a
parallel shared-use trail). Promoting all of them would demand a walker cover
Drillfield Drive two or three times before it counted as done. Spec §4.2 already says
walking one side counts.

**The method:** group campus pedestrian geometry by corridor name (stripping
Trail/Spur/Underpass/Tunnel suffixes *before* normalizing), then split each corridor
into one obligation set plus parallel alternatives. A walkway is an alternative only if
**≥70% of its length runs within 45 m of geometry already in the obligation** — pure
distance clustering was tried first and got it wrong, treating a disconnected stretch
700 m further down Prices Fork Rd as a "second side."

### 4.1 Per-corridor

| Corridor | Features | Pedestrian mi | **Canonical obligation** | Duplicate removed | Ratio |
|---|---:|---:|---:|---:|---:|
| West Campus Dr | 9 | 0.853 | **0.375** | 0.478 | 2.27× |
| Oak Lane Trl | 1 | 0.770 | **0.770** | 0.000 | 1.00× |
| Prices Fork Road Trl | 8 | 0.716 | **0.670** | 0.046 | 1.07× |
| Perry St | 6 | 0.607 | **0.306** | 0.301 | 1.98× |
| Drillfield Dr | 5 | 0.586 | **0.576** | 0.010 | 1.02× |
| Smithfield Road Trl | 6 | 0.487 | **0.385** | 0.102 | 1.27× |
| Duck Pond Drive Trl | 7 | 0.486 | **0.371** | 0.115 | 1.31× |
| Duck Pond Trl | 2 | 0.393 | **0.393** | 0.000 | 1.00× |
| Beamer Way | 1 | 0.357 | **0.357** | 0.000 | 1.00× |
| Stanger St | 5 | 0.339 | **0.339** | 0.001 | 1.00× |
| Turner St | 1 | 0.281 | **0.281** | 0.000 | 1.00× |
| Southgate Dr | 1 | 0.225 | **0.225** | 0.000 | 1.00× |
| Washington St | 3 | 0.202 | **0.129** | 0.073 | 1.57× |
| Life Science Cir | 1 | 0.153 | **0.153** | 0.000 | 1.00× |

**Alternative sides satisfy the same obligation.** Each is stamped
`campus_obligation = "ALTERNATIVE"` with the corridor it belongs to, so a walker on
either side completes it. West Campus Drive at 2.27× and Perry Street at 1.98× are the
clearest cases — both sides plus, for West Campus, a parallel trail.

### 4.2 Revised campus mileage

| | Miles |
|---|---:|
| Total campus pedestrian geometry | 13.403 |
| — named corridors | 6.457 |
| — unnamed (interior quad mesh) | 6.946 |
| **Duplicate obligations removed** | **2.044** |
| — from named corridors | 1.126 |
| — unnamed walkways parallel to a named corridor | 0.918 |
| **Revised campus required mileage** | **11.359** |

Unnamed campus geometry was tested the same way: 42 segments / 6.028 mi are distinct
coverage (the interior quad mesh — genuinely new ground), 16 segments / 0.918 mi run
parallel to a named corridor and are now alternatives.

### 4.3 Campus roads with no adequate pedestrian representation

| Street | Status | Canonical mi |
|---|---|---:|
| Drillfield Drive | ✅ REPRESENTED | 0.576 |
| Oak Lane | ✅ REPRESENTED | 0.770 |
| West Campus Drive | ✅ REPRESENTED | 0.375 |
| Duck Pond Drive | ✅ REPRESENTED | 0.371 |
| Beamer Way | ✅ REPRESENTED | 0.357 |
| Stanger Street | ✅ REPRESENTED | 0.339 |
| Perry Street | ✅ REPRESENTED | 0.306 |
| Life Science Circle | ✅ REPRESENTED | 0.153 |
| **Old Turner Street** | ❌ **NO REPRESENTATION** | 0 |
| **Tech Center Drive** | ❌ **NO REPRESENTATION** | 0 |
| **Stadium Drive** | ❌ **NO REPRESENTATION** | 0 |
| **Coliseum Drive** | ❌ **NO REPRESENTATION** | 0 |
| **Alumni Mall** | ❌ **NO REPRESENTATION** | 0 |

Five campus corridors have neither a street centerline nor a named walkway. Some may be
covered by the unnamed interior mesh; that cannot be confirmed without a second source.
These are the specific candidates for manual digitisation — and the specific thing to
look for first if VGIN or VT GIS become reachable.

> ⚠️ **Campus coverage is not complete.** The normalization above has not been reviewed
> by a human, the campus core polygon is still the raw `UNIV` zoning polygon (DRAFT),
> and D1c (residence halls) remains unmodelled. Campus corridors are `NEEDS_REVIEW`
> pending the D1b ruling in §3.

---

## 5. Household methodology

### 5.1 Reconciliation of every figure

| # | Figure | Value | What it is |
|---|---|---:|---|
| 1 | Address points, all | 19,773 | Every point in the town's 911 Address layer |
| 2 | — non-residential | −1,751 | `LocalType ≠ Residential` (commercial, office, utility, university offices…) |
| 3 | **Residential address points** | **18,022** | `LocalType = Residential`. **A count of points, not of households.** |
| 4 | — not a dwelling | −59 | `LandmkName` contains vacant / demolished / construction |
| 5 | — duplicate address keys | −0 | Normalized composite key collisions (there were none) |
| 6 | **Estimated housing units** | **17,963** | Distinct residential dwelling units. **This is what gets compared to census *housing units*.** |
| 7 | — held for review | −6,279 | 5,624 in complexes a walker cannot pass + 655 beyond the 75 m cap |
| 8 | — associated to a connector only | −655 | Reached only by an `OPTIONAL_CONNECTOR`, which carries no coverage obligation |
| 9 | **Units associated to REQUIRED coverage** | **11,029** | **The public number.** Dwelling units attached to a segment a walker can complete |

`11,029 + 655 + 6,279 = 17,963` ✓ (gate 4 checks this every build)

**On the earlier ~16,700 figure:** that was a projection of what the number *would*
be if every held complex resolved and an occupancy multiplier were applied. It is not
a measured quantity and it is retired. The comparable projection now is: if all 6,279
held units resolved onto required coverage, the public number would approach **~17,300**
— but that is a ceiling, not a forecast, and it is not published anywhere.

**Naming discipline:** "occupied households" is no longer used anywhere. The three
quantities are *residential address points*, *estimated housing units*, and *units
associated to required coverage*. The public label "Estimated households prayed for"
maps to the third.

### 5.2 Recommended V1 method

**`RESIDENTIAL_UNITS_ON_REQUIRED_COVERAGE`** — a transparent count, no occupancy model.

```
residential address points (LocalType = Residential)
  → drop non-dwellings: vacant / demolished / under construction
  → drop duplicate normalized address keys
  = estimated housing units
  → associate each unit one-to-one with the nearest REQUIRED segment within 75 m
    (name-match tie-break; REQUIRED outranks connectors outright)
    holding units in complexes a walker cannot pass
  = units associated to REQUIRED coverage
  = "Estimated households prayed for"
```

**Why no occupancy model.** The previous version multiplied by an assumed 0.93
occupancy rate to produce "estimated occupied households." That rate was a placeholder
with no cited source, it moved the headline by ~800 units, and nobody could audit it.
A count of dwelling units associated with segments a walker can actually complete is
defensible line by line. Being auditable matters more here than being closer to a true
occupied-household figure we cannot measure. `occupancy_model_applied: false` is
asserted in the build report and checked by gate 4.

### 5.3 Deduplication rules

| Risk | Defence |
|---|---|
| **Apartment units** | Each address point is exactly one dwelling unit. Unit keys and building keys are computed separately; the unit key identifies the household. |
| **Duplicate address representations** | Normalized composite key; collisions dropped and logged. Verified unique across all 17,963. |
| **Corner properties** | Exactly one `primary_segment_id` per household. Up to three secondary associations recorded for admin inspection, never counted. |
| **Buildings on multiple segments** | Association is one-to-one from the household side. |
| **Repeated route segments** | Totals sum distinct household keys, not per-segment counts. |

### 5.4 Vacant units

Excluded at source: 59 points whose `LandmkName` marks them vacant, demolished, or
under construction. **No blanket vacancy rate is applied** — that was the occupancy
model, and it is gone. Structural vacancy is therefore *not* modelled: the public
number counts dwelling units that exist, whether or not someone lives in one tonight.
For a prayer walk that is arguably the right unit anyway — you pray for the home.

### 5.5 Dorms

**Not modelled. Zero units.** The town's Building layer contains no VT residence hall
footprints and the Address layer has no dorm addresses, so D1c has nothing to build
from. When it is built, dorms enter as a separate `STUDENT_RESIDENCE` household type
with `confidence = LOW`, reported separately and never folded into the residential
figure. Expected scale ~4,700–5,300 units.

### 5.6 Assisted-living and institutional residences

Excluded from the residential layer by `LocalType`: care facilities, group quarters and
institutional residences are typed `Other`, `Government` or `School`, not `Residential`,
so they never enter the count. This is correct for V1 — address points represent them
poorly (one point for a facility with dozens of residents). They are not separately
modelled and their residents are not counted.

⚠️ Not individually audited. A facility mistyped `Residential` in the source would be
counted as one dwelling unit — an undercount, not an overcount, and small.

### 5.7 Confidence limitations

| Limitation | Effect |
|---|---|
| 6,279 units held for review | Public number is a **floor**. Rises as complexes are dispositioned. |
| Dorms unmodelled | ~4,700–5,300 units missing entirely from every figure. |
| No vacancy adjustment | Counts dwelling units, not occupied homes. Deliberate; stated. |
| Association confidence | HIGH 6,697 · MEDIUM 1,787 · LOW 1,241 (of 11,684 links). |
| 75 m cap | Only 78.8% of units are within it; median 32.8 m, p90 113.5 m. |
| Institutional residents | Not counted at all. |

**Present it as "11,029 households currently associated to walkable required
coverage," never as "Blacksburg has 11,029 households."** The held count travels with
it in the build report.

---

## 6. Apartment-complex calibration

Three complexes were named for review. They produced **three different answers**, which
is exactly what a calibration set should do. Focused map: `complex-review-map.html`.

| | **Terrace View** | **Hunters Ridge** | **The Mill** |
|---|---|---|---|
| Residential units | 558 | 108 | 162 |
| Site footprint | 50.85 acres | 4.78 acres | 7.97 acres |
| Road geometry inside | 0.834 mi public (Broce Dr, Hunt Club Rd, NW Progress St) | 0.091 mi public (Seneca Dr) | **none** |
| Pedestrian geometry inside | 0.533 mi (Progress St walkways) | none | **none** |
| Private geometry inside | 0.201 mi (University Ter, `EXCLUDED`) | none | none |
| Public/private status | Mixed — public frontage + private internal | Public only | n/a |
| Units within 25 m | 121 / 558 | 7 / 108 | 10 / 162 |
| Units within 75 m (cap) | 486 / 558 | 105 / 108 | 97 / 162 |
| Distance median / p90 / max | 38.1 / 77.9 / 108.6 m | 41.1 / 65.4 / 79.4 m | **71.8** / 88.4 / 100.3 m |
| Units beyond cap | 72 (13%) | 3 (3%) | **65 (40%)** |
| **Units associated** | **486** | **105** | **0** |
| **Units held** | **72** | **0** | **162** |
| **Recommended treatment** | **ASSOCIATE_WITH_FRONTAGE_STREETS** | **ACCEPT_AUTOMATIC_ASSOCIATION** | **ADD_AUTHORITATIVE_PEDESTRIAN_NETWORK** |
| Interim | PARTIAL_COUNT | COUNT | EXCLUDE_FROM_ESTIMATE |

**Terrace View** — the site has 1.37 mi of real internal walkable network and 87% of
units are within the cap. Holding all 558 was over-caution. Associate the 486,
hand-assign the 72-unit tail to frontage.

**Hunters Ridge** — 4.8 acres with one public street through it and 97% of units within
the cap. A walker on Seneca Dr genuinely passes this site. Count it.

**The Mill** — zero walkable network inside, 40% beyond the cap, and a *median* distance
of 71.8 m (the typical unit is nearly at the cap, not the tail). A walker on Grayland St
passes nothing. Hold all 162 until internal walkways are sourced.

### 6.1 Recalibration of the automatic rule

The v1 rule held every unit in any complex it flagged, and flagged on "no internal
network" alone. The three cases show both halves were wrong — Hunters Ridge has almost
no internal network but is small enough that frontage serves it.

**Rule v2 — reach decides, and holding is per-unit wherever the site is genuinely
walked:**

| Tier | Condition | Disposition | Hold |
|---|---|---|---|
| **A** | ≤10% of units beyond cap | `ACCEPT_AUTOMATIC_ASSOCIATION` | none |
| **B** | 10–35% beyond cap, with internal network | `ASSOCIATE_WITH_FRONTAGE_STREETS` | beyond-cap units only |
| **C** | >35% beyond cap, **or** no internal network + >10% beyond + >6 acres | `ADD_AUTHORITATIVE_PEDESTRIAN_NETWORK` | all units |

Named complexes still carry a `NAMED_FOR_REVIEW` flag, but the flag drives *review*, not
*holding* — an instruction to look at something is not an instruction to exclude it.

### 6.2 Effect across all 103 complexes

| | v1 | **v2** |
|---|---:|---:|
| Accepted outright | 45 | **58** |
| Partial hold (tail only) | 0 | **13** |
| Full hold | 58 | **32** |
| Units held | 7,710 | **6,279** |
| Units on required coverage | 9,725* | **11,029** |

*v1 figure includes connector-only associations, which v2 separates out.

**26 complexes changed disposition.** No complex is bulk-assigned to a single entrance
segment under either rule.

---

## 7. Candidate network `v1` — frozen metrics

| Metric | Value |
|---|---:|
| **Required mileage** | **135.271 mi** |
| — required street | 124.848 mi |
| — required trail | 10.423 mi |
| Connector mileage | 69.980 mi |
| Excluded mileage | 48.278 mi |
| Campus corridor mileage (canonical) | 11.359 mi |
| Campus duplicate obligations removed | 2.044 mi |
| Total network | 253.529 mi |
| **Main-component coverage** | **96.81%** (130.958 mi, 1,739 nodes) |
| **Unresolved required mileage** | **4.314 mi** (45 segments) |
| Segments | 2,998 (1,515 required · 1,023 connector · 460 excluded · 262 derived) |
| **Estimated households associated** | **11,029** |
| **Estimated households held for review** | **6,279** |

---

## 8. Go / no-go

| # | Gate | Status | Evidence |
|---|---|---|---|
| 1 | No silent non-metric CRS | ✅ **PASS** | Build CRS `EPSG:6594`, units `metre`. `assert_metric()` guard present and called at build start; the build refuses to run otherwise. |
| 2 | No known unit mismatch | ✅ **PASS** | Street mileage 173.13 mi vs the town's own `MILES` field total 169.16 mi — ratio **1.023**. Not the 3.28 survey-foot ratio. |
| 3 | No unresolved connector class routed by default | ✅ **PASS** | **0** non-HIGH_CONFIDENCE connectors routable. 220 HIGH_CONFIDENCE in; 42 out. |
| 4 | Household methodology internally consistent | ✅ **PASS** | 11,029 + 655 + 6,279 = 17,963 = housing units. Public label maps to `units_associated_to_required_coverage`. `occupancy_model_applied: false`. |
| 5 | Campus duplicate obligations removed | ✅ **PASS** | 14 corridors normalized, 2.044 mi marked `ALTERNATIVE`, **0** campus segments unstamped. |
| 6 | Overwhelming majority of required mileage reachable | ✅ **PASS** | **96.81%** in the main routing component; target 95%. |

# ✅ GO for Phase 2b

Conditions to carry forward, none of which block starting:

1. **The five rulings in §3** should land before the router's cost model is tuned. The
   biggest is D1b (11.36 mi of campus).
2. **Route only `routable_by_default = true` edges.** Gate 3 holds today; the router
   must not quietly widen it.
3. **Expect 96.8%, not 100%.** The router must fail loudly rather than route between
   components. 4.31 mi is genuinely unreachable, most of it the Corporate Research
   Center across the 460 bypass.
4. **Licensing (G1) still blocks release, not development.**
5. **Make the repository private** before the next push.

---

## 9. Files

```
pipeline/out/2026-08-03/
  candidate-network-v1.json          frozen metrics + gate results + decision table
  build-report.json                  full build record
  segments.geojson                   2,998 segments (gitignored)
  network-map.html                   full review map (gitignored)
  complex-review-map.html            three-panel calibration map (gitignored)
  review/
    connector-classification.json    262 connectors, classes, connectivity analysis
    campus-normalization.json        corridors, canonical vs alternative
    complex-calibration.json         the three calibration complexes
    coverage-decision-table.json     the 112 coverage-affecting segments
    apartment-complexes.json         all 103 complexes, v1 vs v2 disposition
    ownership-conflicts.json         36 RD_MAINT / ROAD_CLASS conflicts
    vt-campus-coverage.json          campus source-priority evaluation
    segments-needing-review.json · corrections.json · node-snaps.json
```

Reproduce:

```
python3 -m pipeline.sources.fetch
python3 -m pipeline.build.run
python3 -m pipeline.build.freeze
python3 -m pipeline.build.connector_review
python3 -m pipeline.build.campus_normalize
python3 -m pipeline.build.complex_review
python3 -m pipeline.build.campus_report
python3 -m pipeline.build.map_export
```
