# Phase 2a Review Package — Canonical Network Build

**Date:** 2026-08-03 · **Snapshot:** 2026-08-03 · **Build:** `pipeline/out/2026-08-03/`
**Read before:** implementing the router.

The first canonical Blacksburg walking network exists. This package is everything a
human needs to decide whether it is right, plus the proposed Phase 2b plan.

---

## 1. Build summary

```
fetch → normalize → split → connect → classify → households → identify → validate → report
```

Nine town layers pulled to dated snapshots with sidecars (2026-08-03). Everything
reprojected to **EPSG:6594** — NAD83(2011) / Virginia South, **metres**.

> ⚠️ **Correction to technical plan §2.2.** The plan specified **EPSG:6595**, which is
> the same zone in **US survey feet**. The first build ran on it and produced 443 miles
> of required network instead of 135 — every length 3.28× too large, and every
> tolerance (1 m snapping, 75 m household cap) silently shrunk to a third of its
> intended size. The metre code is **6594**. The pipeline now refuses to start if the
> configured CRS is not metre-based (`geo.assert_metric()`).

| Stage | Result |
|---|---|
| Input | 1,547 roads · 1,069 paths · 19,773 address points · 1 boundary · 112 zoning · 375 open space |
| Sidewalk absorption | 410 sidewalks + 53 bike facilities absorbed into parallel streets; 32 on-street features unmatched (logged) |
| Split at intersections | 2,551 inputs → 3,168 pieces (412 inputs split); **2,579 nodes**; 49 endpoint snaps over 0.3 m |
| Connect | **267 components → 65.** 426 synthetic connectors over 5 passes. 14 components unreachable within 25 m |
| Dedupe | 170 duplicate-geometry segments dropped (divided-roadway dual centerlines) |
| Output | **2,998 canonical segments** · `SEG-000001`… assigned in deterministic spatial order |

### The connect stage was not optional

Paths to the Future and Roads were digitised independently and **share no nodes** —
sidewalk geometry sits offset from road centerlines. Before this stage the pedestrian
network floated free of the streets: 267 disconnected components, and a router could
never have stepped from a street onto the Huckleberry Trail. Every connector is
synthetic, tagged `source.dataset = "DERIVED"`, and flagged `NEEDS_REVIEW` — each one
asserts a crossing that a human should confirm.

---

## 2. Counts and mileage

| Role · Type | Segments | Miles |
|---|---:|---:|
| **REQUIRED · STREET** | **1,456** | **124.85** |
| **REQUIRED · TRAIL** | **59** | **10.42** |
| **REQUIRED — total** | **1,515** | **135.27** |
| OPTIONAL_CONNECTOR · TRAIL | 369 | 34.43 |
| OPTIONAL_CONNECTOR · PEDESTRIAN_CONNECTOR | 650 | 31.33 |
| OPTIONAL_CONNECTOR · OUT_OF_AREA_CONNECTOR | 4 | 4.22 |
| OPTIONAL_CONNECTOR — total | 1,023 | 69.98 |
| EXCLUDED · STREET | 412 | 44.31 |
| EXCLUDED · TRAIL | 48 | 3.97 |
| EXCLUDED — total | 460 | 48.28 |
| **ALL** | **2,998** | **253.53** |

**Estimated total eligible mileage: 135.27 miles.**

Sanity check: `REQUIRED · STREET` at 124.85 mi matches the independent hand
calculation from the Phase 2a schema inspection (Blacksburg + State maintenance, less
ramps and the US-460 bypass) to two decimal places.

The Phase 1 plan guessed 200–250 miles of required street network. The real figure is
**about half that** — Blacksburg is smaller on the ground than the desk estimate. The
router's job just got easier, and the coverage denominator more achievable.

---

## 3. Map / inspectable export

**`pipeline/out/2026-08-03/network-map.html`** — self-contained, opens from disk, no
server and no network. Pan, zoom, hover any segment for id, name, type, role, status,
mileage and household count. Layers toggle independently; "Review only" isolates the
segments that need a ruling.

*(Not committed — it embeds derived town geometry, see §9. Regenerate with
`python3 -m pipeline.build.map_export`, or ask for it to be sent directly.)*

Colour: dark green `REQUIRED · street` · teal `REQUIRED · trail` · olive
`OPTIONAL_CONNECTOR` · pink `Derived connector` · grey `EXCLUDED` · orange
**`Review · affects coverage`**.

That last layer is deliberately narrow — **112 segments, 9.22 miles**. It shows only
rulings that can move the coverage denominator (a `REQUIRED` or `EXCLUDED` segment
whose status is unsettled). The other ~1,000 review items are connector-versus-connector
questions that are real work but cannot make coverage wrong; highlighting them would
bury the 112 that matter.

Machine-readable equivalents: `segments.geojson` (2,998 features, full properties and
source lineage), `nodes.geojson`, `households.json`.

---

## 4. Unresolved and manually curated areas

| # | Area | Scale | Where |
|---|---|---|---|
| 1 | **Apartment complexes with no internal walkable network** | 58 complexes, **7,710 units held** | `review/apartment-complexes.json` |
| 2 | **Campus pedestrian ways awaiting the D1b ruling** | 114 segments, 13.40 mi | `review/vt-campus-coverage.json` |
| 3 | **Trails not on the D2 curated list** | 375 segments | `review/segments-needing-review.json` |
| 4 | **Sidewalks with no matching street** | 283 segments | same |
| 5 | **Synthetic connectors** | 262 segments, 1.08 mi | same; `source.dataset = DERIVED` |
| 6 | **Ownership conflicts** | 36 segments | `review/ownership-conflicts.json` |
| 7 | **Public streets inside HOA/private open space** | 4 segments | same file as 3 |
| 8 | **D2 provisional trails** (Deerfield, Shenandoah) | 24 segments | applied but unconfirmed |
| 9 | **Paths typed `Alley`** | 30 segments | no automatic rule |
| 10 | **14 components unreachable within 25 m** | — | `build-report.json` → `connect.unreachable` |
| 11 | **41 REQUIRED segments off the main component** | 41 | validation warning |
| 12 | **Campus core polygon is the raw `UNIV` zoning polygon** | 1.38 sq mi | D1a, DRAFT |
| 13 | **528 units beyond the 75 m association cap** | — | `review/unassociated-households.json` |

**Decisions needed from Jacob, in priority order:**

1. **D1b — promote campus paths to `REQUIRED`?** Unblocks campus coverage entirely and
   needs no new data. 114 segments listed with names and mileage.
2. **D2 — confirm Deerfield and Shenandoah.** Currently applied provisionally; 24
   segments, 10.42 mi of `REQUIRED · TRAIL` depends partly on this.
3. **The three named complexes** (§5) — the calibration case for the other 55.
4. **Whether to hold or estimate** the 7,710 units in unresolved complexes for the
   pilot.

---

## 5. Ownership-field conflicts

**36 segments** where `RD_MAINT` and `ROAD_CLASS` disagree. Every one is the same
shape: `RD_MAINT = Private`, `ROAD_CLASS = Local`. **Zero conflicts run the other
way** — `ROAD_CLASS = Private` always implies `RD_MAINT = Private`.

**Resolution rule applied: `RD_MAINT` wins**, per instruction. Each conflicting segment
was classified `PRIVATE` → `EXCLUDED`, and had its `role_status` downgraded from
`AUTOMATIC` to `NEEDS_REVIEW` so a conflict never rides through as a settled decision.

Affected streets (Foxridge, Windsor Hills and Hunters Ridge areas): Copper Croft Run ·
Foxhunt Ln · Houndschase Ln · Heather Dr · Cardinal Ct · Chowning Pl · Richmond Ln ·
Colonial Dr · Heritage Ln · Blue Ridge Dr · Wellesley Ct NW · Newton Ct NW · Chelsea Ct
· Yorkshire Ct · Sherwood Ct · Southampton Ct · Foxtrail Ln · Foxridge Ln · Lancelot Ct
· Camelot Ct · Nottingham Ct · Canterbury Ct · Brightwood Manor Dr · Quincy Ct ·
Hunters Mill Rd · Clover Valley Cir.

Full records with source ids: `review/ownership-conflicts.json`.

Separately, **4 segments are `PUBLIC` per `RD_MAINT` but fall inside an HOA or
privately-owned open-space polygon** — corroborating evidence pointing the other way.
Flagged, not reclassified: Wakefield Dr, Stradford Ln, Honeysuckle Dr, and one more.

---

## 6. Virginia Tech coverage

Full report: **[`07-vt-campus-coverage.md`](07-vt-campus-coverage.md)**. Summary:

- **Source ranks 1–3 could not be evaluated.** VGIN (`vginmaps.vdem.virginia.gov`), VT
  GIS (`gis.vt.edu`), and OSM (`overpass-api.de`) are all still denied by the
  environment's egress policy. Authorization in conversation did not reach the gateway.
  **Nothing is asserted about RCL's campus coverage.**
- **Campus streets remain absent** from the town's Roads layer — Drillfield, Duck Pond,
  Perry, Old Turner, Beamer, Tech Center, Oak Lane, West Campus all return zero
  features; Alumni Mall, Stanger and W Campus Dr are sub-100 m stubs. Total genuine
  campus street in Roads: **0.021 miles**.
- **But campus pedestrian infrastructure is present and good** — 97 features / 16.72 mi
  in Paths to the Future, 79 tagged `Owner = VT`, carrying the *names of the missing
  streets*: West Campus Drive (1.15 mi), Stanger Street (0.93), Oak Lane Trail (0.77),
  Perry Street (0.61), Drillfield Drive (0.59), Beamer Way (0.36). **13.40 mi of it is
  in the canonical network today**, as `OPTIONAL_CONNECTOR` / `NEEDS_REVIEW`.
- **Campus is 1.38 sq mi / 7.0% of the town**, not the 4.1 sq mi / 20% D1 assumed.
- **D1c is the real gap:** zero VT residence-hall footprints in the town Building layer.

**Recommendation: do not digitise campus streets yet.** D1b already holds that on
campus the footpath network *is* the network, and we have that network. Rule on D1b
first; revisit centerlines only if the review finds walkable campus roads with no
parallel path.

---

## 7. Apartment-complex household association

Full method: **[`06-household-methodology.md`](06-household-methodology.md)**.

103 complexes profiled (≥25 units sharing a `PlaceName`). **58 unresolved, 7,710 units
held out of the estimate.**

| Trigger | Complexes |
|---|---:|
| `AUTOMATIC` — no internal network, and/or >25% of units beyond the cap | 55 |
| `INSTRUCTION_AND_AUTOMATIC` | 1 — The Mill at Blacksburg |
| `INSTRUCTION_ONLY` — named for review, heuristic cleared it | 2 — Terrace View, Hunters Ridge |

| Recommended disposition | Complexes |
|---|---:|
| `ADD_AUTHORITATIVE_PEDESTRIAN_NETWORK` (≥100 units) | 23 |
| `ASSOCIATE_WITH_FRONTAGE_STREETS` | 5 |
| `TREAT_AS_UNRESOLVED` | 30 |
| *interim for all three:* `EXCLUDE_FROM_ESTIMATE` | 58 |

**No complex is bulk-assigned to its nearest public entrance segment.** Doing so would
claim that a walker who passed Foxridge's entrance had prayed for 1,719 homes they
never saw.

> **The calibration case.** Terrace View (558 units) and Hunters Ridge (108) were named
> for review but the automatic test clears them — Terrace View shows 2,194 m of internal
> network and only 13% of units beyond cap. Part of that is the convex-hull footprint
> swallowing adjacent public streets. **Look at these two first**: whichever way they
> go tells us whether the heuristic or the instinct is better calibrated for the other
> 55.

---

## 8. Estimated total household figure

| Quantity | Value |
|---|---:|
| Residential address points | 18,022 |
| **Estimated housing units** | **17,963** |
| — unit-level points | 9,854 |
| — building-level points | 8,109 |
| — distinct buildings | 9,002 |
| Units associated to the network | 9,725 |
| Occupancy rate (placeholder, `LOW` confidence) | 0.93 |
| **Estimated occupied households → "Estimated households prayed for"** | **9,044** |

Association confidence: `HIGH` 6,697 · `MEDIUM` 1,787 · `LOW` 1,241.

### Confidence limits

**9,044 is a floor, not a best estimate.**

| Direction | Cause | Magnitude |
|---|---|---|
| ↓ understates | 7,710 units held in unresolved complexes | up to +7,170 |
| ↓ understates | 528 units beyond the association cap | up to +490 |
| ↓ understates | VT residence halls unmodelled (D1c) | ~4,700–5,300 units |
| ↑ overstates | occupancy rate is a placeholder | ±450 per 5 points |

Fully resolved, the residential figure would land near **16,700 occupied households** —
sensibly above the ~13,800 Census-2020 count for a town that counts apartment units
individually and has built steadily since 2020.

**Do not present 9,044 as "Blacksburg has 9,044 households."** It is *"9,044 households
currently associated to walkable segments,"* and the held count travels with it.

---

## 9. Source lineage and licensing status

Every segment carries `source`: dataset, source id, GlobalID, layer URL,
`source_updated_at`, `retrieved_at`, and `license_status`. Synthetic connectors carry
`dataset = "DERIVED"` with a `derived_from` block. Nothing in the network is
untraceable.

| Source | Layers | `license_status` | Data edited |
|---|---|---|---|
| Town of Blacksburg | Roads, Address, Building, Boundary, Paths, Land Use, Zoning, Parks, Open Space | 🔴 `NONE_PUBLISHED` | 2023-01-09 → 2026-04-07 |
| Derived | 262 connectors | `DERIVED` | this build |
| Montgomery County | *(not retrieved — host blocked)* | `DISCLAIMER_ONLY` | — |
| VGIN | *(not retrieved — host blocked)* | `DISCLAIMER_ONLY` | — |

🔴 **Release blocker.** Full detail and the permissions list:
**[`05-licensing-status.md`](05-licensing-status.md)**.

**No town dataset carries any licence text at all** — `copyrightText` is empty on every
service and layer. Silence is not permission. Written confirmation from Town
Engineering & GIS covering download/store, transform/combine, display derived geometry,
produce routes, publish aggregate statistics, and retain in the application database is
needed before anything ships publicly. **Send that email now** — it has weeks of
latency and nothing downstream can start earlier.

> 🔴 **This repository is public** (verified 2026-08-03 via the GitHub API). Raw
> snapshots, derived geometry, and the two address-level files are therefore
> `.gitignore`d — publishing them would be redistribution the town has not authorised,
> and `households.json` holds ~18,000 individual street addresses. Committed instead:
> pipeline code, snapshot sidecars, build report, aggregate review files. **Recommend
> making the repository private until G1 clears.**

---

## 10. Automated validation results

```
[PASS] no_zero_length_segments          0 segments <= 5 cm
[PASS] segment_ids_unique               2,998 ids, 2,998 distinct
[PASS] household_keys_unique            17,963 households, 17,963 distinct keys
[PASS] one_primary_segment_per_household 9,725 links, 9,725 distinct households
[WARN] required_segments_connected      41 REQUIRED segments off the main component
                                        (65 components total)
[PASS] housing_units_plausible          17,963 estimated housing units
                                        (band 12,000–24,000; compared against housing
                                        units, not the ~13,800 occupied-household figure)
[WARN] association_rate                 45.9% of housing units unassociated
```

Both warnings are understood, not mysteries:

- **41 stranded REQUIRED segments.** After five connect passes, 14 components have
  nothing within 25 m in a larger component. Widening the tolerance would invent
  crossings that may not exist. These need eyes on a map — several are probably genuine
  gaps in the source data worth reporting back to the town.
- **45.9% unassociated** is 7,710 held complex units + 528 beyond-cap units. Both are
  deliberate holds, not failures. This warning should fall below 20% once the complexes
  are dispositioned.

Corrections logged this build: 24 name fixes, 2 value fixes (`Aspahlt` → `Asphalt`), 32
anomalies. Nothing corrected silently — `review/corrections.json`.

---

## 11. Proposed Phase 2b — routing prototype plan

The network is ready enough to prototype against. Phase 2b is the router, and it stays
offline: no PWA, no polished UI.

### 2b.0 Preconditions (days, mostly other people's time)

| | Blocks | Owner |
|---|---|---|
| Send the Town of Blacksburg licence request | public release, not prototyping | Jacob |
| Widen the environment network policy | VGIN/VT/OSM evaluation | Jacob |
| **D1b ruling** on 114 campus segments | campus coverage | Jacob |
| **D2 confirmation** on Deerfield + Shenandoah | 24 segments | Jacob |
| Look at Terrace View / Hunters Ridge / The Mill | calibrates 55 more complexes | Jacob |

None of these block starting 2b.1.

### 2b.1 Load into PostGIS (2–3 days)

Alembic migrations for the schema in technical plan §3. Load `segments.geojson`,
`nodes.geojson`, `households.json`. Add the `curation_override` table and apply
overrides *after* the automatic rules on every build, so human judgment survives a data
refresh. Wire the build report into a promotion step a human approves.

### 2b.2 Graph and cost model (2–3 days)

In-memory adjacency from `network_segment` + `network_node`. ~3,000 edges and ~2,600
nodes fits trivially. Edge cost = length × walk-stress multiplier, with the dead-end
and cul-de-sac handling from technical plan §4. Validate against hand-measured routes
before trusting it.

### 2b.3 Arc-routing prototype (1.5–2 weeks — the long pole)

The Extended-route construction from technical plan §4.3, then prune to the five
variants. Target: sub-second for a 3–5 mile route on this graph.

Two properties of the real network that the prototype must respect and that the plan
did not know:

- **262 synthetic connectors carry the pedestrian network.** Any route crossing one is
  asserting a crossing nobody has confirmed. Either exclude `DERIVED` edges from
  prototype routes, or surface them in the output so the harness makes them visible.
- **65 connected components.** The router must not silently produce a route that
  teleports between them. Fail loudly instead.

### 2b.4 Scenario harness (3–4 days)

The 18 scenarios from technical plan §7, rendered as static maps for visual review.
Seed from real starting points: a downtown address, a Foxridge address, a campus-edge
address, a cul-de-sac in Hethwood.

### 2b.5 Second build, for the identity matcher (2 days)

Re-fetch a fresh snapshot and run the §2.6 matcher against the 2026-08-03 build.
Nothing exercises stable-ID logic like a real second build, and it is far cheaper to
find the problems now than after walk history exists.

**Estimate: 3.5–4.5 weeks**, dominated by 2b.3. Deliverable: a router that produces
five nested route variants from an arbitrary Blacksburg start point, with a visual
harness, and no UI.

---

## 12. Files

```
pipeline/
  sources/registry.py, fetch.py         source registry + snapshot fetcher
  build/geo.py                          reprojection, noding, snapping, dedup
       names.py                         street/trail name normalization
       classify.py                      eligibility rules
       connect.py                       stitch pedestrian layer onto streets
       households.py                    dedup, complex profiling, association
       curation.py                      D1/D2 decisions as data
       run.py                           orchestrator + validation + report
       campus_report.py                 VT coverage analysis
       map_export.py                    self-contained review map
  snapshots/<layer>/2026-08-03.geojson  frozen inputs + .meta.json sidecars
  out/2026-08-03/
    segments.geojson  nodes.geojson  households.json
    build-report.json  network-map.html
    review/  ownership-conflicts · apartment-complexes · vt-campus-coverage
             segments-needing-review · unassociated-households · corrections
             node-snaps · duplicate-geometry
```

Reproduce: `python3 -m pipeline.sources.fetch && python3 -m pipeline.build.run &&
python3 -m pipeline.build.campus_report && python3 -m pipeline.build.map_export`
