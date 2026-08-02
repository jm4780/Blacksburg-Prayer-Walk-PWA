# Technical Plan — Blacksburg Prayer Walk PWA (V1)

**Date:** 2026-08-02
**Companion documents:** [`00-product-spec.md`](00-product-spec.md) (requirements, §
numbers referenced throughout) · [`01-data-audit.md`](01-data-audit.md) (Phase 1 data audit)

---

## 0. The one hard problem

Everything in this project is ordinary web work except one thing: **the router**.

This is an *arc-routing* problem — cover as many un-walked **edges** as possible and
return to where you started — not the point-to-point routing that Google Maps, OSRM,
Valhalla, GraphHopper, and Mapbox all solve. No off-the-shelf engine does this. That
single fact drives most of the technology choices below: pick a stack where writing a
custom graph algorithm is pleasant, and keep everything else boring.

The good news is that the problem is small. Blacksburg is ~20 square miles; expect
roughly **3,000–6,000 network segments** and **~14,000 household points**. The entire
graph fits comfortably in memory in a single process. We do not need distributed
anything, a tile server, or a routing cluster.

---

## 1. Architecture at a glance

```
┌─────────────────────────────────────────────────────────────┐
│  PWA  (React + TypeScript + Vite + MapLibre GL)             │
│  installable, service worker, no login, localStorage identity│
└───────────────┬─────────────────────────────────────────────┘
                │  HTTPS / JSON
┌───────────────▼─────────────────────────────────────────────┐
│  API  (Python 3.12 + FastAPI)                               │
│   ├── metrics, participants, walks, reservations, admin     │
│   └── router service ── in-memory graph, rebuilt on change  │
└───────────────┬─────────────────────────────────────────────┘
                │  SQL
┌───────────────▼─────────────────────────────────────────────┐
│  PostgreSQL 16 + PostGIS                                    │
│   canonical network · households · participants · walks     │
└───────────────▲─────────────────────────────────────────────┘
                │  offline, versioned, reproducible
┌───────────────┴─────────────────────────────────────────────┐
│  Network build pipeline (Python CLI, run by hand)           │
│   raw GIS snapshots → cleaned graph → stable IDs → DB       │
└─────────────────────────────────────────────────────────────┘
```

### 1.1 Stack and why

| Layer | Choice | Reason |
|---|---|---|
| Language (backend + pipeline) | **Python 3.12** | The geospatial and graph ecosystem (Shapely, GeoPandas, pyproj, NetworkX, SciPy, rtree) has no real competitor. Phases 2 and 3 are data-engineering work wearing a web-app hat. |
| API framework | **FastAPI** | Typed request/response models, automatic OpenAPI, async where useful, trivial to test. |
| Database | **PostgreSQL 16 + PostGIS** | Spatial indexing, `ST_` functions for the pipeline and admin queries, and one durable store for both geometry and app state. |
| Migrations | **Alembic** | The segment-identity migration process (§11 of the spec) needs real, reviewable migrations. |
| Router | **Custom Python module**, graph held in memory (adjacency lists + NumPy arrays; SciPy `csgraph` for bulk shortest paths) | Arc routing is bespoke. At this graph size a plain in-process implementation answers in well under a second. |
| Frontend | **React 18 + TypeScript + Vite**, `vite-plugin-pwa` | Standard, fast, good PWA story. |
| Map | **MapLibre GL JS** + **Protomaps `.pmtiles`** basemap served as a static file | No API keys, no per-tile billing, no vendor account for the church to manage, and a single tile file caches beautifully in a service worker. |
| Hosting | API + Postgres on **Fly.io** or **Render**; static PWA on **Cloudflare Pages** | Cheap (tens of dollars/month at most), simple, no ops burden. A managed Postgres with the PostGIS extension is the only real requirement. |
| Auth (admin only) | Single admin password → signed session cookie, or a magic-link email | §26.8 needs an admin surface; the public app deliberately has no accounts (§5). |

### 1.2 Repository layout (target)

```
/docs                    audit, plan, decisions, data-source records
/pipeline                Phase 2 network build (Python CLI)
  /sources               fetchers, one module per dataset
  /build                 split, clean, classify, associate, id-assign
  /snapshots             frozen raw GeoJSON pulls (git-lfs or object storage)
/api                     FastAPI app
  /routing               the router (Phase 3 prototype lands here first)
  /models                SQLAlchemy models + Pydantic schemas
  /migrations            Alembic
/web                     React PWA
/prototype               Phase 3 scratch: notebooks, fixture graphs, map dumps
```

---

## 2. Phase 2 — canonical network preparation

The pipeline is an **offline, deterministic, re-runnable CLI**, not a background job.
Each stage writes an intermediate artifact so a failure at stage 6 doesn't re-download
stage 1. Every run emits a build report (segment counts, total required mileage,
household totals, diffs vs. the previous build) that a human reads before promoting
the result.

```
fetch → snapshot → normalize → split → classify → connect → households → identify → load
```

### 2.1 fetch / snapshot

Pull each source from its ArcGIS FeatureServer (paged `f=geojson` queries) into
`/pipeline/snapshots/<dataset>/<YYYY-MM-DD>.geojson`, alongside a sidecar JSON
recording `{source, source_url, license_text, retrieved_at, source_updated_at, feature_count}`.

**Snapshots are the build input, never the live API.** Builds must be reproducible
months later, and route quality regressions must be attributable to either a code
change or a data change — never to "the town edited a road on Tuesday."

> ⚠️ The remote sandbox used for the Phase 1 audit blocks `*.arcgis.com`. Phase 2
> needs an environment that allows `services1.arcgis.com`,
> `data-montva-gis.opendata.arcgis.com`, and `vgin.vdem.virginia.gov`.

**First task of Phase 2 is a schema inspection report** — dump field names and value
distributions for every ⚠️ item in the data audit (especially any road
ownership/class attribute), then update the audit with what's actually there. Several
decisions below are contingent on that report.

### 2.2 normalize

- Reproject everything to **EPSG:6595** (NAD83(2011) / Virginia South, meters) for all
  geometry math. Store in PostGIS as EPSG:4326 with a computed geography column, or
  store 6595 and transform on output — either is fine, but **all length and distance
  math happens in a projected CRS.** Degrees are not a unit of length.
- Normalize street names into two fields: `display_name` ("N Main St") and
  `normalized_name` (`main st n` — lowercased, USPS-style suffix and directional
  normalization, punctuation stripped). `normalized_name` is what groups segments
  into named streets for §12 and the partial-street bonus in §13.
- Drop PII at import — parcel owner names in particular. We need land use and unit
  counts, not people's names.

### 2.3 split — building the graph

1. Node the network: split every line at every intersection with another line
   (planarize), and at the town boundary.
2. Snap endpoints within a small tolerance (~1 m) so near-misses become true nodes;
   log every snap over ~0.3 m for review.
3. **Do not** split at every geometry vertex — a segment runs intersection to
   intersection, which is the unit a walker understands and the unit we mark complete.
4. Collapse divided-roadway dual centerlines into a single walkable segment where the
   source data has them (Main St may be dual-carriageway). Walking one side counts
   (§4.2), so two parallel required edges would double-count mileage and make coverage
   permanently impossible to finish.
5. **Sidewalks are not separate required coverage.** Where Paths-to-the-Future
   sidewalk geometry parallels a street, it is absorbed into the street segment as a
   walkability attribute. Only sidewalks/paths that provide a *connection the street
   network doesn't have* become `PEDESTRIAN_CONNECTOR` edges.
6. Detect dead ends (degree-1 nodes) and mark their incident segments — the router
   needs this for §16, and it drives the "cul-de-sac" bonus.

Validation gates (build fails loudly, doesn't silently proceed):

- No REQUIRED segment is isolated from the main connected component.
- No zero-length or duplicate-geometry segments.
- Total required mileage is within a plausible band (a first-run human sanity check;
  thereafter, within ±3% of the previous build unless explicitly overridden).
- Degree-2 nodes with the same street name on both sides are merged (avoids
  meaningless micro-segments that would let the router game §14).

### 2.4 classify — the eligibility pass

This assigns each segment its `segment_type`, `access_type`, and per-area `role`
(`REQUIRED` / `OPTIONAL_CONNECTOR` / `EXCLUDED`) per §4.3. It is **rules + human
review**, and the human review is not optional.

Automatic rules (first pass):

| Signal | Action |
|---|---|
| Outside town boundary | `OUT_OF_AREA_CONNECTOR`, role `OPTIONAL_CONNECTOR` |
| Town road-class attribute says private / service / driveway | role `EXCLUDED` (candidate) |
| Segment lies wholly within a single non-ROW parcel | flag as private candidate |
| Segment inside a parcel with apartment/commercial land use | flag as internal drive candidate |
| Name matches alley/service patterns | flag |
| Curated trail list | `TRAIL`, role `REQUIRED` |
| Other Paths-to-the-Future geometry | `PEDESTRIAN_CONNECTOR`, role `OPTIONAL_CONNECTOR` |
| Inside **campus core polygon**: named campus streets | `STREET`, role `REQUIRED` |
| Inside campus core: curated major pedestrian ways | `PEDESTRIAN_CONNECTOR`, role **`REQUIRED`** (D1b) |
| Inside campus core: service drives, lot connections | role `EXCLUDED` |
| VT land outside the campus core (farms, airport, golf) | role `OPTIONAL_CONNECTOR` |
| Everything else inside town | `STREET`, role `REQUIRED` |

Note the campus rows deliberately invert §2.3's rule that pedestrian geometry is
absorbed rather than required. On campus the footpath network *is* the network —
students live along paths, not roads — so a road-only campus model would route people
around the outside of the residential quads and declare campus finished. See
[decision D1](03-decisions.md#d1--virginia-tech-campus-included-) for the full
reasoning; the campus core polygon and the "major pedestrian way" selection are both
hand-curated Phase 2c artifacts.

Then: **a human review pass over every flagged segment plus a full visual sweep**, in
the admin curation tool, before launch. The audit expects a meaningful number of
student-housing internal drives that look exactly like public streets in a 911 layer.
Budget real hours for this — an hour of local knowledge here is worth more than any
amount of algorithm tuning, because a wrong REQUIRED segment means the town can never
reach 100%, and a wrong EXCLUDED segment means a street never gets prayed for.

Curation decisions live in a **`curation_overrides` table keyed by stable segment ID**,
applied *after* the automatic rules on every build. Human judgment must survive data
refreshes; it must never be a hand-edit of pipeline output.

### 2.5 households

Implements audit §3 and spec §20. Two layers:

- **`RESIDENTIAL`** — address points → residential filter (parcel land use + zoning)
  → unit-count resolution → nearest-required-segment association within ~75 m,
  tie-broken by street-name match against `normalized_name`.
- **`STUDENT_RESIDENCE`** — a curated ~47-row residence-hall table (name, footprint,
  published beds, estimated rooms) contributing `estimated_units = rooms` at
  `confidence = LOW`, associated to the nearest REQUIRED segment (frequently a
  pedestrian way, per D1b). Address points represent dorms poorly — one point for
  hundreds of residents — so they are excluded from the first layer and handled here.

Corner-lot double-counting is prevented structurally: **a household has exactly one
`primary_segment_id`** and only that link counts toward metrics. `SegmentHousehold`
may hold secondary associations with a `relationship_type` for admin inspection and
future refinement, but town-wide and per-route counts always dedupe by household ID.

Calibration gate: the `RESIDENTIAL` total should land near the Census 2020 figure
(~13,800). The build report prints the delta; a large gap means the residential
filter is wrong and must be fixed before proceeding. `STUDENT_RESIDENCE` is reported
separately and checked against VT's published on-campus population — it must **not**
be folded into the census comparison, since census households exclude group quarters
by definition. Expected combined total ≈ 18,800.

### 2.6 identify — stable IDs and the migration process (spec §11)

First build: assign `SEG-000001…` in a deterministic spatial order.

Every subsequent build runs a **matcher** before assigning any new ID:

1. Candidate pairs: previous-build segments whose buffered geometry overlaps a
   new-build segment.
2. Match score from symmetric buffer overlap (Hausdorff-style), length ratio, and
   `normalized_name` equality.
3. Above a high threshold, 1:1 → **carry the ID forward**.
4. One old → many new (a **split**): the new pieces get new IDs; a `segment_lineage`
   row records `parent → children`; **if the parent was complete, all children inherit
   complete.**
5. Many old → one new (a **merge**): new ID; the merged segment is complete only if
   *all* parents were complete (conservative — we would rather ask someone to walk a
   block again than falsely claim it was prayed for).
6. No match, old side → **retire** with a tombstone (never delete; walk history
   references it).
7. No match, new side → new ID.
8. Anything ambiguous → **halt and require human adjudication.** Never guess at
   identity; the completion history is the one irreplaceable asset in this system.

The matcher's output is a reviewable diff in the build report. Promotion to production
is a deliberate human action.

---

## 3. Data model

Follows spec §§28–29. Notes on the parts where implementation detail matters.

```sql
-- Multi-area scaffolding, single row each in V1, no UI (§28)
organization(id, name, created_at)
coverage_area(id, organization_id, parent_coverage_area_id NULL, name,
              type, boundary_geometry, active, created_at)

-- Canonical, area-independent physical network (§10)
network_segment(
  id TEXT PRIMARY KEY,                 -- 'SEG-000001', stable across refreshes (§11)
  geometry geometry(LineString,4326),
  length_meters DOUBLE PRECISION,
  normalized_name TEXT,                -- groups segments into named streets (§12)
  display_name TEXT,
  segment_type TEXT,                   -- STREET|TRAIL|PEDESTRIAN_CONNECTOR|OUT_OF_AREA_CONNECTOR
  access_type TEXT,                    -- PUBLIC|PRIVATE|GATED|SERVICE|UNKNOWN
  walkable BOOLEAN,
  walk_stress SMALLINT,                -- 1..5, from road class/speed; feeds §15
  is_dead_end BOOLEAN,
  start_node_id BIGINT, end_node_id BIGINT,
  stable_source_metadata JSONB,        -- source ids, license, retrieved_at (§32)
  retired_at TIMESTAMPTZ NULL,         -- tombstone, never hard-delete
  created_at, updated_at
)
network_node(id, geometry geometry(Point,4326), node_type, degree)
segment_lineage(parent_segment_id, child_segment_id, relation, build_id, created_at)

-- Per-project role + completion; the join that makes multi-area work (§28)
coverage_area_segment(
  coverage_area_id, segment_id,
  role,                                -- REQUIRED|OPTIONAL_CONNECTOR|EXCLUDED (§4.3)
  priority DOUBLE PRECISION,           -- curated nudge + aging (§16)
  completion_status,                   -- INCOMPLETE|COMPLETE
  first_completed_at, first_completed_by_walk_id,
  estimated_household_count,           -- cached
  zone_id NULL,
  PRIMARY KEY (coverage_area_id, segment_id)
)
curation_override(coverage_area_id, segment_id, field, value, reason,
                  set_by, set_at)      -- survives rebuilds (§2.4, spec §33)

household_estimate(id, centroid geometry(Point,4326), source, estimated_units,
                   household_type,      -- RESIDENTIAL|STUDENT_RESIDENCE (D1c)
                   confidence, primary_segment_id NULL, source_updated_at)
segment_household(segment_id, household_estimate_id, relationship_type, confidence)

participant(id, organization_id, first_name, last_name, normalized_email UNIQUE,
            created_at, last_seen_at)
participant_device(id, participant_id, local_token_hash, created_at, last_seen_at)

walk(id, participant_id, coverage_area_id, start_point, snapped_start_node_id,
     selected_route_size, planned_route_geometry, planned_distance_meters,
     final_distance_meters, estimated_time_minutes, planned_household_estimate,
     status,                           -- PREVIEW|STARTED|SUBMITTED|DISCARDED|EXPIRED
     started_at, submitted_at, discarded_at)
walk_segment(walk_id, segment_id, planned, confirmed, manually_added,
             manually_removed, traversal_order NULL, was_complete_before BOOLEAN)
route_reservation(id, walk_id, segment_id, reservation_type, expires_at)
route_generation_log(id, coverage_area_id, start_point, route_size, generated_route,
                     included_segment_ids, score_components JSONB, total_score,
                     walk_quality_score, generation_duration_ms, created_at)
```

Three deliberate details:

- **`walk_segment.was_complete_before`** captures spec §24's "previously completed
  before the walk" state at submission time. Recomputing it later is impossible once
  someone else completes the segment.
- **Completion lives on `coverage_area_segment`, not `network_segment`.** The same
  physical street can be REQUIRED for the town project and merely a connector for a
  future house-church area, with independent completion. This is the whole reason the
  join table exists.
- **`network_segment.id` is a human-readable TEXT key.** Admin work, bug reports, and
  curation spreadsheets all involve humans reading and typing segment IDs.
  `SEG-004217` is a better artifact than a UUID.
- **`household_estimate.household_type`** keeps the campus/off-campus split
  recoverable. Dorm counting is a judgment call (D1c chose rooms over beds); storing
  the type means the convention can be re-cut later with a query instead of a
  network rebuild.

### 3.1 Identity handling (§5)

Device holds an opaque random token in `localStorage`; the server stores only
`sha256(token)`. On first use the client posts name + email; the server normalizes the
email (trim, lowercase, strip `.`/`+tag` for gmail-class domains only) and does an
**upsert by `normalized_email`** — same person on a new device attaches a new
`participant_device` row rather than creating a duplicate participant. "Not you?"
clears the local token and starts the first-use flow again. No password, ever, in any
form.

Names and emails are the only personal data we hold; the privacy note in the UI should
say plainly what they are for (identifying contributions and letting the church know
who is participating) and nothing more.

---

## 4. Phase 3 — the router

Deliverable: a standalone module + CLI (`prototype/route.py --lat --lon --size`) that
takes start coordinates, route-size level, completion state, and reservation state,
and returns geometry, ordered segment IDs, distance, time, households, new coverage,
score breakdown, and walk-quality score (spec §31). It runs against a fixture graph
before it ever runs behind an HTTP endpoint.

### 4.1 The formulation

A **prize-collecting Rural Postman Problem with a distance budget**: find a closed
walk from the start node that maximizes collected prize (new required mileage,
weighted by the §13 bonuses) subject to a length budget, on a graph where traversal
cost is length × a walk-stress multiplier.

### 4.2 Generating all five variants: build big, then prune

Spec §8 requires that longer routes *extend* shorter ones rather than replacing them.
Solving five budgets independently would violate that constantly. So we don't.

**Construct one nested family:**

1. Solve once at the **Extended** budget.
2. Decompose the solution into a **core loop** plus a list of **excursions** —
   detachable branches (a cul-de-sac, an outer block, a secondary cluster), each with
   a value (new required mileage + bonuses) and a cost (added distance).
3. Order excursions by value density (value ÷ marginal cost).
4. **Each shorter variant is the Extended route with the lowest-density excursions
   removed and the loop re-closed** via the shortest path between the cut points.
5. Re-optimize each variant lightly (§4.5) and recompute metrics.

Nesting is then true *by construction*, not by luck: Quick ⊆ Short ⊆ Medium ⊆ Long ⊆
Extended. Sliding the control adds or removes recognizable pieces of the same walk.
One API call returns all five (spec §30), so slider movement is instant with no
network round-trip.

If pruning cannot land a variant inside its band (e.g. the nearest cluster is 0.9 mi
away, so no 0.5-mile route exists), return the closest achievable route **with a
warning** rather than a bad route or an error. The bands are guidance, not promises
(§8), and the UI shows actual distance.

### 4.3 Building the Extended route

```
Stage 1  snap start
Stage 2  load candidate network
Stage 3  cluster
Stage 4  select + grow the target set
Stage 5  build the closed walk (RPP heuristic)
Stage 6  improve
Stage 7  score + metrics
```

**Stage 1 — snap (§18).** Nearest point on any *walkable, non-excluded* edge, using a
PostGIS/rtree spatial index. Never snap to `EXCLUDED` geometry — a user standing in a
Kroger parking lot should start on the public street at the lot's mouth, not on a
drive aisle. If the nearest walkable edge is beyond ~250 m, return a "we can't find a
walkable street near you" state with the manual map-pick fallback (§26.3). Snapping
splits the start edge temporarily in the in-memory graph so the loop can genuinely
begin and end mid-block.

**Stage 2 — candidate network.** Take the subgraph within a network-distance radius of
roughly `0.6 × max_budget` from the start (Dijkstra-limited). This is the search
universe; everything after is local and fast.

**Stage 3 — clusters (§18.3).** Connected components of the *incomplete required*
subgraph, merged when within a short network distance of each other. Score each
cluster:

```
cluster_value = incomplete_miles
              + household_weight × new_households
              + dead_end_bonus × dead_end_count
              + aging_bonus(oldest_incomplete_at)
cluster_cost  = network_distance(start → cluster entry) × 2 (access, out and back)
cluster_rank  = cluster_value / (cluster_cost + ε) − reservation_overlap_penalty
```

The aging term is what implements §16's "dead ends should gain priority over time" and
the endgame behavior in §14/§16: a segment's priority grows slowly with how long it
has been incomplete, so isolated leftovers stop being permanently skipped as the town
fills in. Near total completion this term dominates naturally, without a special
endgame mode.

**Stage 4 — grow the target set.** Start from the top-ranked cluster's entry point,
then greedily add required edges (best marginal value density) and re-solve Stage 5
until the tour length reaches the Extended budget. This is the prize-collecting loop;
it is what keeps the router from trying to cover a whole cluster that's twice too big.

**Stage 5 — closed walk over the target set (Frederickson's RPP heuristic).**

1. Take the target required edges as a subgraph; find its connected components.
2. Build a complete graph over `{start} ∪ components` using shortest-path distances;
   take a minimum spanning tree; add those connecting paths as traversal edges.
3. Find odd-degree vertices in the resulting multigraph; add a minimum-weight perfect
   matching over them (greedy matching is adequate at our scale, and cheap).
4. The multigraph is now connected and even-degree → extract an **Eulerian circuit**
   (Hierholzer) starting and ending at the start node.

This is a well-understood heuristic with a good approximation ratio, and — importantly
— it produces a walk that *naturally* covers required edges once and uses connectors
sparingly, which is exactly the §14 objective.

**Stage 6 — improve (§18.6, §15).** The raw Eulerian circuit is optimal-ish in length
and often unpleasant to walk, because Hierholzer doesn't care about turns. Fixes, in
order:

- **Preference-guided Hierholzer:** at each node, among available edges prefer (a)
  incomplete required, (b) smallest turn angle (go straight), (c) not the edge we just
  came in on. Removes most gratuitous zigzag at zero cost.
- **Or-opt on excursions:** relocate detachable branches to a better position in the
  sequence.
- **2-opt on the connector paths only** (required edges stay covered).
- **Return-path preference:** where two equal-cost returns exist, take the one with
  incomplete coverage.
- **Final validation:** every edge walkable and non-excluded; first node == last node;
  no duplicate consecutive edge unless it's a genuine dead-end return.

**Stage 7 — metrics.**

```python
NEW_COVERAGE_W        = 100   # per mile of newly covered required network
SEGMENT_COMPLETE_W    =  20   # per segment newly completed
STREET_COMPLETE_W     =  30   # per normalized named street newly finished (§12)
DEAD_END_W            =  20   # per dead end cleared (§16)
PARTIAL_STREET_W      =  15   # per partially-complete street advanced
COHERENCE_W           =  ...  # neighborhood-cluster bonus
REPEAT_MILE_W         = -35   # per mile of already-completed road re-walked
U_TURN_W              = -10
EXCESS_TURN_W         =  -5
RESERVATION_W         =  ...  # overlap with active reservations
AWKWARDNESS_W         =  ...  # from the walk-quality score below
```

Straight from spec §13, and every component is persisted per route in
`route_generation_log.score_components` so route behavior can be inspected and tuned
during the pilot rather than argued about.

### 4.4 Walk-quality score (§15)

Kept **separate** from the coverage score, as the spec requires, and computed from
observable route properties:

| Component | Measure |
|---|---|
| Turn density | turns per mile (>12/mi starts costing) |
| U-turns | immediate reversals not justified by a dead end |
| Repeat fraction | repeated distance ÷ total distance |
| Intersection revisits | max visits to any single node |
| Access fraction | distance before first new coverage ÷ total |
| Compactness | route area vs. perimeter; penalizes stringy shapes |
| Stress exposure | fraction of distance on `walk_stress ≥ 4` |
| Fragmentation | count of disconnected coverage additions |

Normalized to 0–100. **Any variant below a floor (start at 55, tune in the pilot) is
rejected and the next-best candidate is used** — spec §15's minimum threshold. Keeping
this score independent is what lets us honor "a route with slightly less new coverage
may be preferable if it is significantly more coherent" as an explicit tradeoff
instead of a hidden weight.

### 4.5 Time estimate (§19)

```
minutes = (distance_miles / 2.85) × 60
        + 0.07 × turn_count            # ~4 s per turn
        + 0.25 × major_crossing_count  # ~15 s per arterial crossing
```

Documented, defaulted, never asked for. Displayed rounded to the nearest 5 minutes
("About 55 minutes"), never as an exact figure. The constants live in one config
module so the pilot can tune them from feedback without touching routing logic.

### 4.6 Reservations (§21)

Soft penalties, never locks. On preview, `PREVIEW` reservations on the targeted
incomplete segments for 15 minutes; on start, upgraded to `ACTIVE` for
`estimated_time × 1.5 + 15 min`. The router applies a value discount (not an
exclusion) to reserved segments, so a second walker starting in the same
neighborhood gets steered elsewhere when possible but is never told "no routes
available." Expiry is by `expires_at` comparison at query time plus a periodic sweep —
never a background job we depend on for correctness.

### 4.7 Performance

Target < 800 ms for a full five-variant generation. At this graph size that is
comfortable in pure Python with SciPy for the shortest-path work; the graph is loaded
once at process start and invalidated on completion writes. If a hot spot appears it
will be all-pairs shortest paths inside Stage 5 — cache node-pair distances per
request. **No premature optimization**; measure during Phase 3.

---

## 5. Phase 4 — backend API

```
GET    /api/metrics                    → §6 dashboard numbers (cached, 60 s)
GET    /api/progress-map               → simplified segment geometry + status (§26.7)
POST   /api/participants               → upsert by normalized email → participant + token
GET    /api/participants/me            → resolve device token
POST   /api/routes/generate            → §30 contract; returns all 5 variants + preview reservations
POST   /api/walks/{id}/start           → PREVIEW → STARTED; upgrade reservations
POST   /api/walks/{id}/submit          → confirmed segment IDs + final distance
POST   /api/walks/{id}/discard         → release reservations
GET    /api/walks/{id}/nearby-segments → candidates for post-walk "add a street" (§23)
/api/admin/*                           → §26.8
```

**Submission is idempotent and concurrency-safe** (§21, §34). Marking a segment
complete is an upsert guarded by `WHERE completion_status = 'INCOMPLETE'` inside the
walk's transaction — `first_completed_at` and `first_completed_by_walk_id` are set by
whoever genuinely got there first, and a second submission of the same segment is a
no-op that still records the walk's own participation via `walk_segment`. Test
scenario §35.16 ("submits segments another person completed first") is a normal path,
not an error path.

Metrics are computed from `coverage_area_segment` (percentage, unique mileage) and
summed `walk.final_distance_meters` (total miles walked), cached briefly. Households
prayed for is a distinct count over `household_estimate` joined through completed
required segments — deduplicated by construction (§3, §20).

Distance after editing (§25): confirmed-as-planned submits the planned distance; an
edited walk recomputes distance by walking the planned traversal order, keeping
confirmed segments and the connectors between them, and re-closing gaps with shortest
paths. The recomputed figure is **shown to the user before submission**, per §25.

---

## 6. Phase 5 — PWA

Screens exactly as §26. Implementation notes worth fixing now:

- **Offline.** The service worker precaches the app shell, the basemap `.pmtiles`, and
  — critically — **the active route**. Someone will lose signal mid-walk in a
  neighborhood; the route must still render. The active-route screen is read-only
  static data (§26.5), so this is easy and it should not be skipped.
- **Location.** Requested once, at generation, with a plain-language explanation
  *before* the browser prompt (§4.1). Denial is a supported path, not an error state:
  fall back to picking a start point on the map.
- **Map accessibility (§27).** Every state gets a distinct **line pattern and width**
  as well as a color — completed solid, incomplete dashed, planned route heavy
  overlay, connectors thin dotted, manually added distinct pattern. Verified against
  a color-blindness simulator. The legend spells out the patterns in words.
- **Copy.** No wording anywhere may imply tracking or verification (§34). No "we
  tracked your walk," no "verified," no "recorded route." Public-facing strings should
  go through the church's brand voice pass before launch — this app speaks for
  Blacksburg Church, and the difference between "38% of Blacksburg prayed for" and
  "38% complete" matters. Keep all user-visible strings in one module to make that
  review possible.
- **The household number always reads "estimated."** Not in a tooltip — in the label.

---

## 7. Testing

- **Pipeline:** golden-file tests on a small fixture area (a few dozen segments) for
  split/classify/associate; property tests for the ID matcher (splits inherit
  completion, merges are conservative, ambiguity halts).
- **Router:** a hand-built fixture graph (grid + cul-de-sacs + a trail + a boundary +
  an excluded private loop) with asserted invariants on **every** generated route —
  closed, walkable, no excluded edges, all five variants nested, all five return to
  the same start. Then the 18 scenarios of spec §35 as a **scenario harness** run
  against the real Blacksburg graph, each dumping a GeoJSON map for human eyeballing.
  Route quality cannot be fully asserted in code; the harness exists so a person can
  review 18 maps in ten minutes after every routing change.
- **API:** the concurrency cases explicitly — two simultaneous generations near each
  other (§35.10), double submission of the same segment (§35.16), submit-after-expiry.
- **Acceptance:** spec §34 turned into a literal checklist, run before the pilot.

---

## 8. Build sequence and rough effort

| Phase | Work | Est. |
|---|---|---|
| 1 | Data audit + this plan | ✅ done |
| 2a | Schema inspection report; resolve ⚠️ items | 1–2 days |
| 2b | Pipeline: fetch → split → classify → households → IDs → load | 1.5–2 weeks |
| 2c | **Human curation pass** (public/private, trails, campus core polygon, campus paths, residence-hall table) | 2–3 days of Jacob's time + tooling |
| 3 | Router prototype + scenario harness + tuning | 2–3 weeks |
| 4 | Backend API, admin, metrics | 1–1.5 weeks |
| 5 | PWA | 2–3 weeks |
| 6 | Pilot, tuning, data corrections | 2–4 weeks calendar |

Phase 3 is the long pole and the one most likely to overrun. It is also the phase
where the project either feels magical or feels broken, so it gets the time.

A useful early milestone: **finish 2b and stand up the progress map with everything
incomplete.** Seeing the whole town outlined and empty, before any routing exists, is
both a strong data-quality check and the moment the project becomes real to people.

---

## 9. Risks

| Risk | Mitigation |
|---|---|
| Private/apartment drives misclassified as REQUIRED → town can never hit 100% | Human curation pass (2c); admin can reclassify any segment at any time and metrics recompute |
| Routes are technically good but unpleasant → people stop using it | Separate walk-quality score with a hard floor; 18-scenario visual harness; pilot tuning |
| Dorm household estimate distorts the headline number (campus ≈ 26% of the total) | `household_type` split, `confidence = LOW`, separate calibration against VT capacity; Jacob approves the computed number before launch (D1c) |
| Campus modeled from roads only → dorm quads never actually prayed for | Campus pedestrian ways are REQUIRED, not connectors (D1b) |
| Blanket campus inclusion loads the denominator with farm roads | Hand-drawn campus core polygon; agricultural land, airport, golf course stay out (D1a) |
| Data refresh silently breaks completion history | Snapshot-based builds, ID matcher with lineage, halt-on-ambiguity, human-reviewed build diff |
| Two walkers get the same streets | Soft reservations; deliberately not hard locks (§21) — a duplicate prayer walk is a far smaller failure than "no routes available" |
| Nesting requirement makes variants low-quality at the extremes | Prune-from-Extended construction; per-variant re-optimization; warn rather than force a band |
| Scope creep into the §3 exclusion list | Apply the §37 test: does this help someone prayer-walk another street today? |

---

## 10. Open decisions

Tracked in [`03-decisions.md`](03-decisions.md). Summary of current state:

- **D1 — Virginia Tech campus. ✅ Resolved: included**, with dorms counted as rooms
  (~5,000 estimated households). Creates three Phase 2c curation artifacts: the
  campus core polygon, the required-pedestrian-way selection, and the residence-hall
  capacity table. See D1 for reasoning and the expected metric effects.
- **D2 — Which trails count (§17). ✅ Huckleberry confirmed**; Deerfield and
  Shenandoah recommended as REQUIRED, park interiors and Gateway Trail as
  connector-only, Coal Mining Heritage and the Huckleberry south of the town line out
  of area. Awaiting a yes/no on the recommendations. Trail eligibility should key off
  surface and grade attributes rather than case-by-case judgment.
- **D3–D6** — out-of-town connector allowance, refresh cadence, admin access, hosting
  budget. All have workable defaults; none block Phase 2.
- **D7 — GitHub write access.** Open; blocks pushing work, not doing it.
