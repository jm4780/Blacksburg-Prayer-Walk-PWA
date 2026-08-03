# Technical Plan — Blacksburg Prayer Walk PWA (V1)

**Date:** 2026-08-02
**Companion documents:** [`00-product-spec.md`](00-product-spec.md) (requirements, §
numbers referenced throughout) · [`01-data-audit.md`](01-data-audit.md) (Phase 1 data
audit) · [`04-schema-inspection.md`](04-schema-inspection.md) (Phase 2a, live data)

> **Amended 2026-08-03** after the Phase 2a schema inspection. Sections carrying a
> `> 📋 2026-08-03` note were written against assumptions the data has since corrected.
> The one that matters most: **the town's Roads, Address, and Building layers do not
> cover the Virginia Tech campus**, which leaves decision D1 without a road or household
> source. See §2.4a.

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

> 📋 **2026-08-03 — measured, not estimated.** The canonical build produced
> **2,998 segments / 253.53 miles**, of which **1,515 segments / 135.27 miles** are
> REQUIRED (124.85 mi street + 10.42 mi trail). **2,579 nodes.** Household layer:
> **17,963 estimated housing units** from 19,773 address points — larger than the
> ~14,000 assumed, because the address layer is unit-level (see §2.5).
>
> The graph is smaller than the 3,000–6,000 estimate and roughly **half** the
> 200–250 mi of required street the decision docs assumed. The router's job is easier
> than planned. See [`08-phase-2a-review-package.md`](08-phase-2a-review-package.md).

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

> 📋 **2026-08-03.** Those three hosts are now allowed and all respond — but **two of
> them are Hub sites, not data hosts**. Montgomery County's features are on
> `services5.arcgis.com` and VGIN's are on `vginmaps.vdem.virginia.gov`; both are still
> blocked, as are `hub.arcgis.com` (every Hub download redirects there) and
> `www.arcgis.com`. **Add those four** before 2b, or the VGIN cross-check and the
> parcel spatial join stay untestable.
>
> Two constraints for the fetchers:
> - The town's services advertise `capabilities = Query,Sync` — **no `Extract`** —
>   on every layer we need except Zoning. Use paged `query` + `resultOffset`; do not
>   depend on `f=geojson` bulk export or Hub Download. `maxRecordCount` is 8,000
>   (Address), 4,000 (Paths), 2,000 (Roads/Building/boundaries), 5,000 (Comp Plan).
> - The actual layer names are **not** what the audit guessed: Roads, Address and
>   Building are layers 1/0/2 of one service `Address_Road_Building`, and the boundary
>   is `Administrative_Reference_Boundaries/4 — Town Corporate Limits`.

**First task of Phase 2 is a schema inspection report** — dump field names and value
distributions for every ⚠️ item in the data audit (especially any road
ownership/class attribute), then update the audit with what's actually there. Several
decisions below are contingent on that report.

> ✅ **Done — 2026-08-03:** [`04-schema-inspection.md`](04-schema-inspection.md).

### 2.2 normalize

- Reproject everything to **~~EPSG:6595~~ EPSG:6594** (NAD83(2011) / Virginia South,
  **metres**) for all geometry math. Store in PostGIS as EPSG:4326 with a computed
  geography column, or store 6594 and transform on output — either is fine, but **all
  length and distance math happens in a projected CRS.** Degrees are not a unit of
  length.
  > 🔴 **2026-08-03 — this section had a bug and the build hit it.** **EPSG:6595 is
  > NAD83(2011) / Virginia South (ftUS)** — US survey feet. The metre-based code for
  > this zone is **EPSG:6594**. The first canonical build ran on 6595 and reported
  > **443 miles** of required network instead of 135: every length 3.28× too large, and
  > every tolerance silently shrunk to a third of its intended size (1 m endpoint
  > snapping became 0.3 m, the 75 m household cap became 23 m). It looked plausible.
  >
  > The pipeline now calls `geo.assert_metric()` at startup and refuses to run if the
  > configured CRS is not metre-based. Do not "fix" this back to 6595.
  > 📋 Source CRS is **EPSG:2284** (NAD83 / Virginia South, survey feet) on every town
  > layer. `Shape__Length` on Paths is in survey feet; Roads carries its own `MILES`.
- Normalize street names into two fields: `display_name` ("N Main St") and
  `normalized_name` (`main st n` — lowercased, USPS-style suffix and directional
  normalization, punctuation stripped). `normalized_name` is what groups segments
  into named streets for §12 and the partial-street bonus in §13.
- Drop PII at import — parcel owner names in particular. We need land use and unit
  counts, not people's names.
  > 📋 **2026-08-03.** Montgomery County already excludes owner names from Parcels Open
  > Data — there is no owner field to drop. Still drop `DEEDBOOK`/`DEEDPAGE`/`SALE_*`
  > and the assessed-value fields; we don't need them. And note that the field the audit
  > expected to classify land use, `LANDUSE_VA`, is **a dollar amount**, not a code —
  > the real classifier is `EX_CLASSD`. Better still, use the town's own
  > `Comprehensive_Plan/8 — Current Land Use` (see §2.5).
- Normalise known source misspellings and domain drift, **logging every correction and
  never silently fixing**: `Aspahlt` → `Asphalt`, `Bilke Lane` → `Bike Lane`,
  `Bicenntennial` → `Bicentennial`, `Deerfield` → `Deerfield Trail`,
  `S MAIN STS` → `S MAIN ST`. Validate coded fields against **observed** values, not
  the declared ArcGIS domain — `ROAD_CLASS` uses `Collector` and `Arterial`, neither of
  which is in its domain, and `LocalType` uses `Office/Business`, `University` and
  `Religious`, none of which are in its domain.

### 2.3 split — building the graph

> 📋 **2026-08-03 — two of these steps got easier and one got smaller.**
> - **Step 1's boundary split is nearly a no-op.** The town layers are already clipped
>   to the corporate limits (Roads 1,546/1,547 intersect, Address 19,771/19,773,
>   Building 10,156/10,156, Paths 1,068/1,069). The real consequence runs the other
>   way: **out-of-town connectors don't exist in this data at all**, including the
>   Huckleberry south of the town line.
> - **Step 5's sidewalk absorption is a name join, not a geometry job.** 648 of 688
>   sidewalk features carry the parallel street's name in `Road`, plus `From_`/`To_`
>   cross-streets. Match on name first; reserve geometry for the 40 unnamed ones.
> - **Step 6's degree-2 merge will do real work.** Roads' median segment is 0.076 mi
>   (~400 ft), but 48 segments are under 53 ft and 105 under 0.02 mi — mostly
>   intersection stubs. The layer is already roughly intersection-to-intersection,
>   which is the unit we want, but the slivers need collapsing.

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

Automatic rules — **revised 2026-08-03 to use the fields that actually exist**:

| Signal | Action |
|---|---|
| `RD_MAINT = 'Private'` (232 segs, 20.57 mi) | `access_type = PRIVATE`, role `EXCLUDED` |
| `ROAD_CLASS = 'Ramp'` (49 segs, 8.87 mi) | role `EXCLUDED` — limited access |
| `ROAD_CLASS = 'Primary'` (33 segs, 14.88 mi — exclusively the US-460 bypass) | role `EXCLUDED` |
| `RD_MAINT ∈ {Blacksburg, State}` otherwise | `access_type = PUBLIC`, `STREET`, role `REQUIRED` (~124.9 mi) |
| `RD_MAINT` and `ROAD_CLASS` disagree (**34 segs**, all `Private`/`Local`) | flag for human review; **`RD_MAINT` wins by default** |
| Segment inside an `HOA Active` / `HOA Inactive` / `Privately Owned` polygon from `Parks_and_Open_Space/1` | flag as private candidate |
| `SpeedLimit` (populated on all 1,547) | seeds `walk_stress` directly |
| Curated trail list, keyed on Paths `Road` **as spelled in the data** | `TRAIL`, role `REQUIRED` |
| Paths `Type = Sidewalk` with a matching `Road` name | absorb into that street (§2.3) |
| Other Paths-to-the-Future geometry | `PEDESTRIAN_CONNECTOR`, role `OPTIONAL_CONNECTOR` |
| Paths `Owner = 'PRIV'` (27 features, 3.96 mi, all trails) | flag as private candidate |
| Inside **campus core polygon**: named campus streets | `STREET`, role `REQUIRED` — ⚠️ **no source, see §2.4a** |
| Inside campus core: curated major pedestrian ways | `PEDESTRIAN_CONNECTOR`, role **`REQUIRED`** (D1b) — ✅ sourced from Paths, `Owner = VT` |
| Inside campus core: service drives, lot connections | role `EXCLUDED` |
| VT land outside the campus core (farms, airport, golf) | role `OPTIONAL_CONNECTOR` |
| Everything else inside town | `STREET`, role `REQUIRED` |

Dropped from the original table: *"Segment lies wholly within a single non-ROW parcel"*
and *"Segment inside a parcel with apartment/commercial land use"* — both were proxies
for an ownership attribute we assumed didn't exist. `RD_MAINT` does the job directly
and better, and neither proxy is worth a county-parcel spatial join we can't currently
test. *"Name matches alley/service patterns"* is also dropped: `TYPE = ALY` appears on
only 10 segments, and the Village at Toms Creek alleys it would catch are already
flagged `Private`.

Note the campus rows deliberately invert §2.3's rule that pedestrian geometry is
absorbed rather than required. On campus the footpath network *is* the network —
students live along paths, not roads — so a road-only campus model would route people
around the outside of the residential quads and declare campus finished. See
[decision D1](03-decisions.md#d1--virginia-tech-campus-included-) for the full
reasoning; the campus core polygon and the "major pedestrian way" selection are both
hand-curated Phase 2c artifacts.

Then: **a human review pass over every flagged segment plus a full visual sweep**, in
the admin curation tool, before launch. An hour of local knowledge here is worth more
than any amount of algorithm tuning, because a wrong REQUIRED segment means the town can
never reach 100%, and a wrong EXCLUDED segment means a street never gets prayed for.

> 📋 **2026-08-03 — this shrank a lot.** The audit predicted public/private
> classification would be "the single biggest curation task." It isn't. `RD_MAINT` is
> populated on 100% of features and spot-checks land correctly: Foxridge (Copper Croft
> Run, Foxhunt Ln, Houndschase Ln, Heather Dr…), The Retreat (Carpenter Blvd, Crisp Rd,
> Gustafson Ave…), Pheasant Run, Maple Ridge, Windsor Hills, Collegiate Suites and the
> Village at Toms Creek alleys are all correctly `Private`. **The review list is ~232
> auto-excluded segments to confirm plus 34 disagreements to adjudicate** — hours, not
> days. The full visual sweep still happens.
>
> ⚠️ **The opposite problem is real, though.** Several large complexes have **no
> internal drives in Roads at all** — The Mill at Blacksburg (164 units), Hunters Ridge
> (110), Terrace View (559), most of Chasewood Downs — because their circulation is
> surface parking, which a 911 street file doesn't model. Absence from Roads does not
> mean absence of households. That lands on §2.5, not here.

### 2.4a ⚠️ Campus streets have no data source (blocks D1)

**Decide this before starting 2b.** The schema inspection found that the town's Roads,
Address and Building layers **stop at the Virginia Tech campus line**:

- **Roads:** Drillfield Dr, Duck Pond Dr, Perry St, Old Turner St, Beamer Way, Spring Rd,
  Tech Center Dr and Oak Lane return **zero** features. W Campus Dr, Alumni Mall and
  Stanger St appear only as ~0.01-mile stubs at the town-street junction. The three
  features tagged `STREETMAP_ = 'VA TECH'` total **0.017 miles**.
- **Address:** no residence-hall addresses. The 90 points typed `LocalType='University'`
  are VT-leased offices *off* campus.
- **Building:** **zero** VT residence halls among all 10,156 footprints.
- **Paths to the Future:** ✅ **106 features / 20.5 mi in the campus core**, 79 tagged
  `Owner = VT`. Campus pedestrian infrastructure is well covered.

So **D1b is buildable now and the rest of D1 is not.** The classify table's campus-street
row has nothing to classify. Options, in the order I'd try them:

1. **VGIN RCL** — statewide, likely includes campus. Requires
   `vginmaps.vdem.virginia.gov` on the network allowlist (§2.1). Untested.
2. **VT Facilities GIS** — VT publishes an ArcGIS org; authoritative if reachable.
3. **Hand-digitise** — campus has perhaps 5 miles of drivable street. A one-afternoon
   job that keeps the canonical network licence-clean.
4. **OSM** — complete and accurate, but pulling OSM geometry into the canonical network
   makes it an ODbL derivative database, which audit §2.4 deliberately designed around.
   Last resort.

**Recommendation: try (1), fall back to (3).** The residence-hall table for D1c has the
same problem and the same answer.

One thing that got *easier*: the town's **`UNIV` zoning polygon (1.38 sq mi, single
feature)** is a usable first draft of D1a's hand-drawn campus core polygon. And D1's area
arithmetic was overstated — the in-town university footprint is **1.38–1.68 sq mi
(7–8% of the town)**, not the 4.1 sq mi / 20% the decision assumed, because most of VT's
2,600 acres is outside the corporate limits or zoned `RR-1`.

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

> 📋 **2026-08-03 — four changes, one of them a bug that would have shipped.**
>
> 1. **Unit-count resolution is essentially free.** The address layer is genuinely
>    unit-level: **10,770 of 19,773 points carry a `unit`** (`APT` 7,045 · `UNIT` 2,591
>    · `STE` 847 · `LOT` 249 · …). Foxridge alone is 1,728 points; `301 GIVENS LN` is
>    139. Within `LocalType='Residential'` (18,022 points), 9,855 carry a unit and they
>    collapse to 9,060 building-level addresses — so the layer serves as both a unit
>    count and a building count. Drop the parcel/census-derived estimation path.
> 2. **Use the town's land use, not the county's.** Residential filter =
>    address-point `LocalType = 'Residential'` intersected with
>    `Comprehensive_Plan/8 — Current Land Use` (11,398 parcel-level polygons, edited
>    2026-01-29, PII-free, queryable). Montgomery Parcels drops to cross-check —
>    its `LANDUSE_VA` field is a dollar amount, not a land-use code, and its features
>    are on a host we currently can't reach. Also filter the 139 points whose
>    `LandmkName` is `Vacant`, plus the handful marked `demolished`/`construction`.
> 3. **Keys:** `ADDR` is unique across all 19,773 rows, and so is a normalized
>    composite of `STNUM + STREET_PRE_DIR + STREET_NAME + STREET_TYPE +
>    STREET_POST_DIR + unit_designator + unit`. `GlobalID` is unique too. **Derive the
>    key from the composite** (`ADDR` is a display string; `GlobalID` is Esri-managed
>    and reassignable on republish) and store all three for the identity matcher.
> 4. **⚠️ The 75 m association cap will orphan households.** The Mill at Blacksburg
>    (164 units), Hunters Ridge (110), Terrace View (559) and most of Chasewood Downs
>    have **no internal drives in Roads** — their circulation is surface parking. Units
>    at the back of those sites sit well beyond 75 m from any segment and would silently
>    vanish from the household count. **Fix:** raise the cap, and/or add a
>    `PlaceName`-keyed rule — `PlaceName` is populated on 14,417 points with the complex
>    or subdivision name — that associates every unit in a named complex to whichever
>    segment the complex's frontage resolves to. Log every household that finds no
>    segment; never let one disappear quietly.
>
> ✅ The street-name tie-break is confirmed sound: **19,605 of 19,773 points (99.2%)**
> match a Roads street name exactly with only case/whitespace normalization. The
> residual 168 span 18 street names and can be handled by hand. `Placement` shows
> 19,227 points sited on the actual structure, so distances will behave.
>
> ⚠️ `STUDENT_RESIDENCE` is blocked on the same problem as campus streets — there are
> **zero VT residence-hall footprints** in the town's Building layer. See §2.4a.

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

> 📋 **2026-08-03 — this gate, as written, fails on correct data.** The residential
> filter yields **18,022 points** against ~13,800 Census-2020 households: a **+31%
> gap**, and much of it is right. We count apartment units the census counts as
> occupied households, and five years of construction have landed since 2020. A gate
> that halts here would halt on a working pipeline.
>
> **Revised gate:** compare against total **housing units**, not households; allow a
> wide band; and print the composition — unit-level points vs building-level points,
> and the split by `LocalType` — so a human judges rather than a threshold. Keep the
> hard failure for the shapes that really are wrong: a residential total below the
> household count, or a sudden double-digit swing between builds.

### 2.5a connect — stitching the pedestrian layer onto the streets

> 📋 **Added 2026-08-03.** The stage list at the top of §2 names `connect` but no
> section described it. The build found out why it matters.

**Paths to the Future and Roads were digitised independently and share no nodes.**
Sidewalk and trail geometry sits offset from road centerlines, so after noding, the
pedestrian network floated free of the streets: **267 disconnected components**. A
router could never have stepped from a street onto the Huckleberry Trail.

The connect stage finds components disconnected from the main network and adds short
synthetic connector edges to the nearest reachable geometry:

- **Maximum reach 25 m.** Beyond that the gap is a genuine missing link in the source
  data, not a digitising offset, and inventing an edge would assert a crossing that may
  not exist.
- **Each pass joins only to a strictly larger component**, so two stranded fragments
  cannot pair off and stay stranded. Chains take several passes; iterate until the
  component count stops falling.
- **Every connector is synthetic and says so** — `source.dataset = "DERIVED"`,
  `role_status = NEEDS_REVIEW`, and a `derived_from` block naming what it stitched
  between. A human confirms the crossing each one implies.

Result: **267 components → 65** over 5 passes, using **426 connectors** (262 surviving
dedup, 1.08 mi total). 14 components have nothing within 25 m in a larger component and
are reported rather than force-joined.

**The router must treat `DERIVED` edges as provisional** — either exclude them from
prototype routes or surface them in the output, and never silently route between
disconnected components.

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
| 2a | Schema inspection report; resolve ⚠️ items | ✅ done ([`04`](04-schema-inspection.md)) |
| 2a | **Canonical network build** — pipeline, 2,998 segments, 135.27 mi required | ✅ done ([`08`](08-phase-2a-review-package.md)) |
| 2a′ | **Blocked/pending:** network policy for VGIN + VT GIS; licence answer from Town GIS; D1b + D2 rulings; residence-hall table | blocks parts of 2b and all of release |
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
| Private/apartment drives misclassified as REQUIRED → town can never hit 100% | **Largely retired 2026-08-03** — `RD_MAINT` classifies all 1,547 road segments and spot-checks land correctly. Residual: 34 disagreements + a confirm pass over 232 auto-excluded segments, then the 2c visual sweep |
| **Campus streets and dorm footprints have no data source** (§2.4a) — D1 is half-buildable | Resolve in 2a′: VGIN RCL → VT Facilities GIS → hand-digitise (~5 mi). Campus *paths* are already sourced, so D1b proceeds regardless |
| **Households in complexes with no internal roads silently vanish** at the 75 m association cap (The Mill, Hunters Ridge, Terrace View — 800+ units) | Raise the cap; add a `PlaceName`-keyed complex→frontage rule; log every unassociated household and fail the build on a nonzero count |
| Census calibration gate halts a *correct* pipeline (18,022 residential points vs ~13,800 households) | Compare against housing units, widen the band, print composition for human judgment (§2.5) |
| No town dataset carries any licence text | Written confirmation from Town Engineering & GIS before publishing derived data; start the ask now, it has latency |
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
  capacity table.
  > 📋 **2026-08-03 — D1 needs a follow-up decision.** The town publishes no campus
  > streets, addresses, or building footprints (§2.4a), so **D1's road layer and D1c's
  > residence-hall table have no source**; D1b's pedestrian ways do. Also, the in-town
  > campus footprint is **1.38–1.68 sq mi (7–8% of the town)**, not the 4.1 sq mi / 20%
  > D1 assumed — most of VT's 2,600 acres lies outside the corporate limits. The
  > headline-metric effect D1 reasons about is roughly a third of what was estimated.
  > On the plus side, the town's single `UNIV` zoning polygon is a ready first draft of
  > D1a's campus core polygon.
- **D2 — Which trails count (§17). ✅ Huckleberry confirmed**; Deerfield and
  Shenandoah recommended as REQUIRED, park interiors and Gateway Trail as
  connector-only, Coal Mining Heritage and the Huckleberry south of the town line out
  of area. Awaiting a yes/no on the recommendations. Trail eligibility should key off
  surface and grade attributes rather than case-by-case judgment.
  > 📋 **2026-08-03 — half of D2's eligibility rule is unbuildable as written.**
  > Surface exists: Paths `Material` is populated on 889 of 1,069 features
  > (`Concrete` 572 · `Asphalt` 282 · `Gravel` 4 · `Dirt` 2 · …). **Grade does not** —
  > `Slope` is populated on 1,026 features and *every value is 0*. `Width` is populated
  > on 1. Either derive grade from a DEM (USGS 3DEP 1 m covers Montgomery County) or
  > drop grade from the automatic rule and make it a curation note.
  >
  > Naming, for the curated list: Deerfield Trail appears as **`Deerfield`**
  > (1 feature, 0.76 mi) and the Shenandoah *Bike* Trail as **`Shenandoah Trail`** with
  > `Type = Trail` (2 features + 12 spur, 2.18 mi). In-town Huckleberry is 25 features /
  > 11.15 mi. 38 trail features have a blank `Road` and need visual identification.
  > The Huckleberry south of the town line isn't in the data at all, so "out of area"
  > costs nothing to implement. Brush Mountain Park's 18 singletrack trails are a
  > separate service D2 doesn't currently mention and should explicitly exclude.
- **D3–D6** — out-of-town connector allowance, refresh cadence, admin access, hosting
  budget. All have workable defaults; none block Phase 2.
- **D7 — GitHub write access.** Open; blocks pushing work, not doing it.
