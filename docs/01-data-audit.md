# Phase 1 — Geographic Data Audit

**Project:** Blacksburg Prayer Walk PWA
**Date:** 2026-08-02 · **Verified against live data:** 2026-08-03
**Status:** Complete, and **substantially corrected** by the Phase 2a schema inspection
([`04-schema-inspection.md`](04-schema-inspection.md)).

This audit was written from documentation and catalogue listings, not from the data.
Several parts of it were wrong. Verified findings are marked **✅ VERIFIED**;
corrections are marked **❌ CORRECTED** and state plainly what the audit got wrong.
Items that still could not be checked — because the environment's network policy blocks
the hosts the data actually lives on — are marked **⏳ STILL UNVERIFIED**. Read the
schema inspection report for the evidence behind every one of these.

> **The three headline corrections:**
> 1. Roads carries a clean, fully-populated `RD_MAINT` ownership attribute
>    (Blacksburg / Private / State). Public/private classification is **mostly
>    automatic**, not "the single biggest curation task" this audit predicted.
> 2. **Virginia Tech's campus is absent from the town's Roads, Address, and Building
>    layers** — no campus streets, no dorm addresses, no dorm footprints. Decision D1
>    has no road or household source for campus. Campus *paths* are present.
> 3. The parcel field this audit expected to drive the residential filter
>    (`LANDUSE_VA`) is **a dollar amount, not a land-use code**. A better town-published
>    layer exists and should be used instead.

This document answers the spec's §32 requirements: for each data need, the best
available source, its license, update cadence, known gaps, required manual cleanup,
and whether the data can legally be stored and redistributed.

---

## 1. Summary of recommended sources

| # | Data need | Primary source | Backup / cross-check |
|---|-----------|----------------|----------------------|
| 1 | Town boundary | Town of Blacksburg GIS Open Data (corporate limits) | Census TIGER/Line place boundary |
| 2 | Public street centerlines | Town of Blacksburg **Roads** dataset | VGIN Virginia Road Centerlines (RCL); OpenStreetMap |
| 3 | Road access classification | Town Roads attributes + VGIN RCL | OSM `highway=` tags |
| 4 | Public/private road status | Town Roads **`RD_MAINT`** ✅ VERIFIED — mostly automatic | Open Space HOA polygons; local knowledge for the ~34 ambiguous segments |
| 5 | Major trails | Town of Blacksburg **Paths to the Future** dataset | OSM; town Parks & Rec pages |
| 6 | Pedestrian connections | Paths to the Future (sidewalks, connectors) | OSM footways |
| 7 | Crosswalk / crossing feasibility | OSM crossing nodes + manual flags | Deferred to curation (no authoritative dataset) |
| 8 | Residential address points | Town of Blacksburg **Address Points** (911 authority) | VGIN Virginia Address Points (public domain) |
| 9 | Residential land use | ❌ CORRECTED → Town **Current Land Use** (`Comprehensive_Plan/8`, 11,398 polys) + address `LocalType` | Montgomery County Parcels `EX_CLASSD` (cross-check only) |
| 10 | Building footprints | Town of Blacksburg Building Footprints | VGIN statewide Building Footprints (quarterly) |
| 11 | Estimated housing units | Census 2020 DHC block-level housing counts + ACS 5-year | Used to calibrate, not as the primary layer |
| 12 | Street names | Town Roads dataset (911 naming authority) | VGIN RCL |
| 13 | Speed / road class (walking comfort) | VDOT functional classification via VGIN RCL | OSM `maxspeed`, `highway`, `lanes` |

**Headline conclusion (holds, with one large exception):** Blacksburg is unusually
well-served — better than this audit guessed, on every count except one. The exception
is **Virginia Tech**, which the town's road, address, and building layers simply do not
cover. See §7 below.

The Town is its own
911 addressing authority and publishes roads, address points, and building
footprints on its own ArcGIS Open Data hub, and publishes a purpose-built
multimodal dataset ("Paths to the Future") covering trails, sidewalks, and bike
infrastructure. We should build the canonical network from **town data first**,
using OSM only for gap-filling walkability context — which also keeps us clear of
ODbL share-alike complexity (see §4).

---

## 2. Source-by-source detail

### 2.1 Town of Blacksburg GIS Open Data hub

- **Portal:** https://town-of-blacksburg-gis-data-blacksburg-va.hub.arcgis.com/
  (also catalogued on the Virginia Open Data Portal:
  https://data.virginia.gov/organization/town-of-blacksburg-gis-data and linked from
  https://www.blacksburg.gov/departments/departments-a-k/engineering-and-gis/gis-data)
- **ArcGIS REST services root:** `https://services1.arcgis.com/rAuQoDGA22NtJdmg/arcgis/rest/services`
  ✅ VERIFIED reachable; serves **30 FeatureServers**.
- **Datasets relevant to us** — ❌ CORRECTED: the audit's guessed dataset names were
  wrong. There is no service named "Roads", "Address Points", or "Building Footprints";
  all three are layers of one service:
  - **`Address_Road_Building/FeatureServer/1` — Roads** · 1,547 features · 169.16 mi ·
    data last edited 2026-04-07. Our primary street network.
  - **`Address_Road_Building/FeatureServer/0` — Address** · 19,773 points ·
    edited 2026-04-07. Primary household layer.
  - **`Address_Road_Building/FeatureServer/2` — Building** · 10,156 footprints ·
    edited 2026-03-31.
  - **`Administrative_Reference_Boundaries/FeatureServer/4` — Town Corporate Limits** ·
    1 polygon · 19.8227 sq mi / 12,686.5 acres. ✅ That is the actual layer name.
  - **`Paths_to_the_Future/FeatureServer/0` — Existing** · 1,069 features · 157.69 mi ·
    edited 2025-11-07. Layer 1 (`Proposed`) exists but is **empty — 0 features**.
  - **`Comprehensive_Plan/FeatureServer/8` — Current Land Use** · 11,398 parcel-level
    polygons · edited 2026-01-29. ⭐ Not known to this audit; it is the right
    residential-filter source (see §3).
  - **`Zoning_and_Landuse/FeatureServer/9` — Town Zoning** · 112 polygons · **data last
    edited 2023-01-09**, the stalest layer in the catalogue. Contains a single
    **`UNIV` polygon (1.38 sq mi)** — a usable first draft of D1's campus core polygon.
  - **`Parks_and_Open_Space/FeatureServer/1` — Open Space** · 375 polygons typed
    `HOA Active` / `HOA Inactive` / `Privately Owned` / `Town Developed` / `Town
    Undeveloped`. A strong second signal for private-drive detection.
- **Format:** ✅ live FeatureServer query API, paged. ⚠️ **CAVEAT:** the town's services
  advertise `capabilities = Query,Sync` — **not `Extract`** — on Address_Road_Building,
  Paths_to_the_Future, Administrative_Reference_Boundaries, Comprehensive_Plan and
  Parks_and_Open_Space. Paged `query` harvesting works (that is how the inspection was
  done), but Hub bulk-download and `f=geojson` exports may not be. The pipeline must
  not depend on them.
- **License:** ❌ CORRECTED — **there is no licence text in the data at all.**
  `copyrightText` is empty at both service and layer level on every town service
  inspected. The "free use and download" line came from blacksburg.gov, which is not
  attached to the data and could not be re-reached (host blocked). The only town service
  carrying attribution is Brush_Mountain_Trails. **⏳ ACTION: get a one-line written
  confirmation from Blacksburg Engineering & GIS before publishing anything derived
  from this data.** Start now — it has latency.
- **Update cadence:** ✅ VERIFIED live and current. Roads and Address both last edited
  2026-04-07; `CHGDATE` inside Roads runs to 2026-03-20. Full per-layer table in the
  schema inspection report §Q5.
- **Attribute schema:** ✅ VERIFIED — and much better than expected. Roads carries
  **`RD_MAINT`** (domain `RoadMaintenance`: `Blacksburg` 1,215 · `Private` 232 ·
  `State` 100) **and** `ROAD_CLASS` (`Local` 904 · `Private` 198 · `Secondary` 150 ·
  `Collector` 116 · `Arterial` 94 · `Ramp` 49 · `Primary` 33 · `Service Drive` 3), both
  populated on 100% of features, plus `SpeedLimit` on all 1,547.
  - The audit's warning that presence in Roads ≠ public street was correct, and
    `RD_MAINT` resolves it directly. **34 segments** disagree between the two fields
    (all `RD_MAINT=Private` / `ROAD_CLASS=Local`); treat `RD_MAINT` as authoritative.
  - ⚠️ `ROAD_CLASS` has **domain drift**: `Collector` and `Arterial` are used in the
    data but absent from the declared domain, and eight declared codes are unused.
    Validate against observed values, not the domain.
- ❌ CORRECTED — **the layers do not extend past the town boundary.** Tested against the
  corporate-limits polygon: Roads 1,546/1,547 intersect, Address 19,771/19,773,
  Building 10,156/10,156, Paths 1,068/1,069. Boundary splitting is nearly a no-op — but
  the flip side is that **out-of-town connectors do not exist in this data**, including
  the Huckleberry Trail south of the town line.
- ⚠️ Note: the service root also publishes four **Tucson, Arizona police-incident
  services**. Almost certainly a training artefact. Don't assume every service in this
  org is authoritative.

### 2.2 VGIN (Virginia Geographic Information Network) statewide layers

- **Portal:** https://vgin.vdem.virginia.gov/ (Virginia GIS Clearinghouse downloads:
  https://vgin.vdem.virginia.gov/pages/cl-data-download)
- **Virginia Road Centerlines (RCL):** statewide, built to a Commonwealth data
  standard (OTH 703-00) which specifies naming, geometry, and attribute
  conventions. Useful attributes per the standard: route names, address ranges,
  and road classification fields. Good cross-check and a fallback if town data
  attributes disappoint. https://vgin.vdem.virginia.gov/datasets/VGIN::virginia-road-centerlines-rcl
- **Virginia Address Points:** statewide aggregation of local 911 address points.
  https://vgin.vdem.virginia.gov/datasets/8105f26377d2495f8eb8aeed0794fe7c
- **Virginia Building Footprints:** statewide aggregation of locally submitted
  footprints. https://vgin.vdem.virginia.gov/datasets/virginia-building-footprints/about

**⏳ STILL UNVERIFIED — the VGIN cross-check could not be performed.** All three layers
are published on the Hub site only as **File Geodatabase downloads** (RCL 112 MB,
Address Points 176 MB, all three updated **2026-07-01**). Their queryable REST endpoints
live on `vginmaps.vdem.virginia.gov`, which this environment's network policy blocks.
No field list, no value distributions — and specifically **no answer to the question
that now matters most: does VGIN RCL contain the VT campus streets the town's file
omits?** See §7.

- **License:** ❌ CORRECTED — **the "public domain as of January 1, 2012" claim is not
  supported by the data.** The only licence text VGIN attaches to RCL, Address Points,
  and Building Footprints is an identical **warranty disclaimer**: *"The Virginia Base
  Data layers are intended for cartographic use and spatial analysis only, and not for
  use as a legal description… all warranties regarding the accuracy of the map data and
  any representation or inferences derived there from are hereby expressly
  disclaimed."* The Hub `license` field is `custom` on all three. The public-domain
  statement this audit cited comes from the address-point *standard document*, not from
  the dataset. Treat VGIN as "open access, no warranty" — **not** as the cleanest
  licence in the audit — and confirm in writing if we ever redistribute it.
- **Role for us:** cross-check + fallback, plus the **campus-street fallback** created
  by §7. The town layers are fresher and locally authoritative for everything the town
  actually covers.

### 2.3 Montgomery County, VA GIS Open Data

- **Portal:** https://data-montva-gis.opendata.arcgis.com/ (county GIS dept:
  https://montva.com/1/departments-services/GIS)
- **Parcels Open Data:** 45,565 parcels countywide, **11,358 in Blacksburg**, item last
  modified 2026-03-05.
- **Owner names:** ✅ VERIFIED — **there are none.** The publisher already removed them:
  *"Owner names are excluded for privacy, however all other property value and related
  information is within."* There is no owner-name field in the schema at all. `BUS_NAME`
  is a business/site name (blank on 43,181 of 45,565), not a person. The PII risk this
  audit flagged **does not exist here** — though we should still drop
  `DEEDBOOK`/`DEEDPAGE`/`SALE_*`/value fields at import because we don't need them.
- **Land-use codes:** ❌ CORRECTED — **`LANDUSE_VA` is not a land-use code.** It is a
  dollar amount (the Virginia land-use *deferral* assessment value); 43,283 of 45,565
  rows are `'$0.00'`. Keying a residential filter on it would produce silent garbage.
  The field that actually classifies property use is **`EX_CLASSD`**: `Single Family
  Urban` 19,178 · `Single Family Sub-Urban` 16,386 · `Commercial & Industrial` 3,447 ·
  `Multi-Family Apt/Townhouses` 928 · `Common Area` 672 · `Exempt/*` ~1,600 · etc.
  `ZONING`, `BEDROOMS`, `ROOMS`, `STORIES` and `YEARBLT` are also populated.
- **License:** ✅ VERIFIED — warranty disclaimer only (*"Information shown is for
  reference purposes only… not responsible for any inaccuracies herein contained…"*);
  Hub `license` field = `custom`. No explicit grant, no explicit restriction.
- **⏳ STILL UNVERIFIED:** parcel *features* could not be pulled — the service lives on
  `services5.arcgis.com`, blocked by this environment's network policy. Schema and
  full-dataset value distributions came from the ArcGIS Hub metadata API on the allowed
  host. **The point-in-parcel spatial join has not been tested.**
- **Role for us:** ❌ DEMOTED to cross-check. The Town's own **Current Land Use** layer
  (11,398 polygons, edited 2026-01-29, PII-free, queryable) is a better residential
  filter on every axis. Keep Parcels for a second opinion on unit counts.

### 2.4 OpenStreetMap

- **Access:** Geofabrik Virginia extract or Overpass API clipped to a Blacksburg
  bounding box.
- **Strengths for us:** pedestrian detail no government layer has — footpaths,
  informal connectors, crossing nodes (`highway=crossing`), sidewalk tags, trail
  surfaces, `access=private` tags, and the Huckleberry Trail mapped end-to-end.
- **License:** **ODbL 1.0** (share-alike for *derivative databases* + attribution).
  Implications, per the OSMF Collective Database Guideline:
  - If we mix OSM geometry into our canonical network, the network becomes a
    derivative database and must be redistributable under ODbL on request. That is
    survivable but annoying.
  - If we keep layers separated by type/region (all our streets from town data,
    OSM used only for distinct layers such as crossing hints), the combination is
    a *collective database* and share-alike applies only to the OSM-sourced layer.
  - Our participant, walk, and household data must never be blended into an
    OSM-derived table.
- **Decision:** Build the canonical network **without OSM geometry**. Use OSM only
  as (a) a visual cross-check during curation, and (b) optionally a separate,
  clearly-labeled "crossing hints" layer kept in its own table with OSM attribution.
  Base-map tiles (if we use OSM-based tiles) require "© OpenStreetMap contributors"
  attribution on the map UI regardless.

### 2.5 U.S. Census Bureau

- **2020 Census (DHC) block-level housing-unit counts** and **ACS 5-year** town
  profile. Public domain.
- **Blacksburg context numbers** (for sanity-checking our household estimates):
  ~44,800 population (2020), ~13,800 households, 19.77 sq mi land area.
- **Critical caveat:** Blacksburg is a university town. Virginia Tech dormitories are
  **group quarters**, so the ~13,800 census household figure *excludes* roughly
  10,000 on-campus students. Per **decision D1**, campus is in scope and dorms are
  counted via a separate room-based estimate — so the census figure calibrates the
  off-campus layer only, and campus households are added on top from a curated
  residence-hall table. Do not calibrate the combined total against 13,800.
- **Role for us:** calibration target for `household_type = RESIDENTIAL` ("do our
  deduplicated address-point-derived household counts, summed town-wide, land near
  ~13.8k?") and a distribution fallback where unit-level address data is weak.

### 2.6 VDOT / road classification

- VDOT functional classification and road inventory data are available through
  VGIN RCL attributes and https://www.virginiaroads.org/. Blacksburg maintains its
  own streets (it is an incorporated town), so VDOT data matters mainly for
  walking-comfort scoring on arterials (e.g., US 460 Business / Main St, Prices
  Fork Rd) and for the out-of-town connector edges.
- **Role for us:** derive a per-segment "walk stress" hint from functional class +
  speed. OSM `maxspeed`/`lanes` can supplement. Low precision is acceptable — this
  feeds a soft penalty, not eligibility.

### 2.7 Crosswalks / crossing feasibility

- **No authoritative government dataset identified.** ✅ VERIFIED — Paths to the Future
  does **not** include crossing features. Its `Type` values are `Sidewalk` 688 ·
  `Trail` 283 · `Bike Lane` 66 · `Sharrow` 16 · `Alley` 7 · `Trail Tunnel` 4 ·
  `Share the Road` 2 · `Contra Flow Lane` 1 · `Stairs` 1 · `Bridge` 1 — no crossings.
  OSM has crossing nodes of uneven completeness.
- **Decision:** do not model crossings as first-class data in V1. Instead: (a) a
  soft penalty for routes crossing high-stress arterials mid-block, derived from
  road class; (b) an admin curation flag `unsafe_crossing` on specific nodes/edges
  as issues are discovered during the pilot (§33 of the spec already requires this
  admin capability).

---

## 3. Household estimation approach (selected)

Per spec §6.3's preference order, we can start at **option 1 — residential address
points** — the best case:

1. **Base layer:** Town of Blacksburg Address Points — **19,773 points**.
   ✅ VERIFIED: a stable key exists, twice over. `ADDR` (the formatted address string)
   is unique across all 19,773 rows, and a normalized composite of
   `STNUM + STREET_PRE_DIR + STREET_NAME + STREET_TYPE + STREET_POST_DIR +
   unit_designator + unit` is **also unique with zero collisions**. `GlobalID` is
   present and unique too. **Recommendation: derive the key** from the normalized
   composite (`ADDR` is a display string; `GlobalID` is Esri-managed and can be
   reassigned on republish), storing all three for the identity matcher.
2. **Residential filter:** ❌ CORRECTED — use the Town's **Current Land Use** layer
   (`Comprehensive_Plan/8`) plus the address layer's own **`LocalType`** field, not
   Montgomery County parcel codes. `LocalType` alone gives: `Residential` 18,022 ·
   `Office/Business` 610 · `Commercial` 490 · `Utility` 155 · `Other` 97 ·
   `University` 90 · `Industrial` 56 · `Religious` 53 · `Recreation` 45 ·
   `Government` 38 · `Parking` 27 · `School` 12 · `Mixed Use` 11 · `Out Building` 6 ·
   `Research` 4. (⚠️ `Office/Business`, `University` and `Religious` are used but are
   not in the declared `LocalAddrType` domain — same drift as Roads.) Also filter the
   139 points whose `LandmkName` is `Vacant` and the handful marked `demolished` /
   `construction site`. Group quarters
   (VT residence halls, Oak Lane, care facilities) are excluded *from this layer*
   because address points represent them poorly — one point per building for
   hundreds of residents — and are instead handled by step 2b.
2b. **Student residences (per D1):** a curated table of ~47 VT residence halls —
   name, building footprint, published bed count, estimated rooms (`beds ÷ 2`,
   refined per hall where suite/single configurations are published). Each hall
   contributes `estimated_units = rooms` as `household_type = STUDENT_RESIDENCE`
   with `confidence = LOW`. Expect ~4,700–5,300 units. Off-campus student apartments
   are ordinary address points and need none of this.
   - ❌ CORRECTED — **this cannot be seeded from town building footprints.** There are
     **zero VT residence halls** in the town's Building layer; searching all 10,156
     footprints for `COMMON_NAME LIKE '%HALL%'` returns *Town Hall Annex* and *St Lukes
     & Oddfellows Hall*. Only 4 footprints are typed `University`. The table must be
     built from VT's own GIS or hand-digitised. See §7.
3. **Multi-unit handling:** ✅ VERIFIED — **the address points are unit-level.**
   `unit` and `unit_designator` are real, populated fields: **10,770 of 19,773 points
   (54%) carry a unit** (`APT` 7,045 · `UNIT` 2,591 · `STE` 847 · `LOT` 249 ·
   `BLDG` 15 · `GATE` 1). Apartment complexes are fully enumerated — 1,728 points for
   Foxridge, 559 for Terrace View, 502 for Hub Blacksburg, 443 for The Union; the
   largest single street address (`301 GIVENS LN`) carries **139** unit-level points.
   Within `LocalType = Residential`, 9,855 points carry a unit and they collapse to
   **9,060 distinct building-level addresses** — so the layer is usable as *both* a
   unit count and a building count. **This step is essentially eliminated.** No
   parcel-derived or census-derived unit estimation is needed for ordinary housing.
   Bonus: **`PlaceName` is populated on 14,417 points with the complex or subdivision
   name**, which groups units into complexes with no spatial work at all.
4. **Segment association:** ✅ VERIFIED that the street-name tie-break will work —
   **19,605 of 19,773 address points (99.2%) match a Roads street name exactly** with
   nothing more than case and whitespace normalization. Only 168 points across 18 names
   don't (`TRAVIS TRL` 30, `COUNTRY CLUB DR` 23, `JENNELLE RD` 21, `FAIN DR` 20 …, plus
   one `S MAIN STS` typo). `Placement` shows 19,227 of 19,773 points sited on the actual
   structure, so distances will behave.
   - ⚠️ **NEW PROBLEM: the ~75 m cap will orphan households.** Several large complexes
     have **no internal drives in Roads at all** — The Mill at Blacksburg (164 units,
     nearest road is Grayland St), Hunters Ridge (110 units, Seneca Dr), Terrace View
     (559 units), most of Chasewood Downs. Their circulation is surface parking, which
     a 911 street file doesn't model. Units at the back of those sites sit well beyond
     75 m from any segment. **Recommendation:** raise the cap, or add a
     `PlaceName`-keyed rule that associates every unit in a named complex to whichever
     segment the complex's frontage resolves to.
5. **Calibration:** ⚠️ **the proposed gate would fail on correct data.** 18,022
   residential points against the Census-2020 figure of ~13,800 households is a
   **+31% gap** — and much of that gap is *right*, because we are counting apartment
   units the census counts as households, plus five years of construction since 2020.
   Compare against total **housing units**, not households, allow a wide band, and print
   the composition (unit-level vs building-level) so a human can judge.
   `STUDENT_RESIDENCE` is reported separately and reviewed against VT's published
   on-campus population (~9,300–10,500 students) rather than against the census.

All public displays say "estimated," per spec.

---

## 4. Licensing summary

Rewritten 2026-08-03 from the licence text the datasets actually carry. The original
table was more confident than the evidence supports.

| Source | License text the data actually carries | Store? | Redistribute derived data? |
|--------|---------|--------|---------------------------|
| Town of Blacksburg open data | ❌ **None. `copyrightText` is empty on every service and layer.** The "free use and download" line lives on blacksburg.gov, not on the data. | Yes (low risk) | ⏳ **Not until we have written confirmation from Town Engineering & GIS.** |
| VGIN Address Points | ❌ **Not public domain per the dataset.** Warranty disclaimer only ("intended for cartographic use and spatial analysis only… all warranties… expressly disclaimed"), Hub `license` = `custom`. | Yes | Probably, with source note — confirm before publishing |
| VGIN RCL / Building Footprints | Identical warranty disclaimer; `license` = `custom` | Yes | Probably, with source note |
| Montgomery County parcels | Warranty disclaimer only; `license` = `custom`. ✅ **Owner names already excluded by the publisher** — no PII to drop. | Yes | Internal derivation yes |
| OpenStreetMap | ODbL 1.0 | Only in isolated layers | Attribution required; share-alike if derived — avoided by design (§2.4) |
| Census / TIGER | Public domain | Yes | Yes |

Two standing rules for the import pipeline:

1. Record `{source, source_url, license_text, retrieved_at, source_updated_at}` for
   every imported dataset (the spec's `stable_source_metadata` / `HouseholdEstimate.source`
   fields).
2. Drop fields we don't need at import time. The specific PII worry — parcel owner
   names — turned out to be moot (Montgomery County already excludes them), but the
   rule stands: drop deed books, sale prices, and assessed values at import. We need
   geometry, land use, and unit counts.

---

## 5. Known gaps and required manual curation

These are the places where data alone won't be good enough, in expected order of
effort:

*Reordered 2026-08-03. Item 1 shrank dramatically; a new item 0 took its place.*

0. **⚠️ NEW — Virginia Tech campus network and residence halls.** The town publishes no
   campus streets, no campus addresses, and no campus building footprints. Everything
   D1 needs except the pedestrian paths has to be sourced or built by hand. **This is
   now the largest open item in Phase 2.** See §7.

1. **Public/private street classification** — ❌ CORRECTED: **not the biggest curation
   task.** `RD_MAINT` does the work. Seed `access_type` from it (`Private` → `PRIVATE`,
   `Blacksburg`/`State` → `PUBLIC`), auto-`EXCLUDED` the 232 private segments
   (20.57 mi), hard-`EXCLUDED` the 49 ramps (8.87 mi) and 33 US-460 bypass segments
   (14.88 mi), then human-review only:
   - the **34** segments where `RD_MAINT` and `ROAD_CLASS` disagree, and
   - any segment falling inside an `HOA Active` / `HOA Inactive` / `Privately Owned`
     polygon from `Parks_and_Open_Space/1`.

   ✅ Spot-checks confirm `RD_MAINT` lands correctly: Foxridge (Copper Croft Run,
   Foxhunt Ln, Houndschase Ln…), The Retreat (Carpenter Blvd, Crisp Rd, Gustafson
   Ave…), Pheasant Run, Maple Ridge, Windsor Hills, Collegiate Suites and the Village
   at Toms Creek alleys are all flagged `Private`. Budget hours, not days.
   Spec §4.3 roles are still assigned here.
2. **Virginia Tech campus** — **resolved: campus is included** (decision D1). The
   curation work this creates: (a) hand-draw a **campus core polygon** — ✅ the town's
   single `UNIV` zoning polygon (1.38 sq mi) is a usable first draft, so this is nearly
   done; (b) select which campus **pedestrian ways** are REQUIRED — ✅ well supported:
   106 path features / 20.5 mi in the campus core, 79 tagged `Owner = VT`, including
   Drillfield Dr, West Campus Dr, Duck Pond Dr, Perry St, Stanger St, Oak Lane Trail;
   (c) build the ~47-row residence-hall capacity table — ❌ **blocked, no footprint
   source** (§7).
   - ❌ CORRECTED — **campus is not ~20% of the town by area.** The 2,600-acre / 4.1 sq
     mi figure in D1 is VT's *total* holdings, much of which (Kentland Farm, the
     airport, agricultural research land) is outside the corporate limits or zoned
     `RR-1`. The town's own layers put the in-town university footprint at
     **1.38 sq mi** (`UNIV` zoning) to **1.68 sq mi** (`Current Land Use = University`)
     — **7–8% of the town.** D1's impact on the headline metric is materially smaller
     than estimated, which lowers the cost of including campus rather than raising it.
3. **Trail curation** — per spec §17, hand-pick which Paths-to-the-Future features
   count as REQUIRED trails vs. connector-only geometry. ✅ Much easier than expected:
   `Type` is populated on all 1,069 features (`Sidewalk` 688 / `Trail` 283 /
   `Bike Lane` 66 / `Sharrow` 16 / `Alley` 7 / `Trail Tunnel` 4 / …), and named trails
   are identifiable via the `Road` field. In-town Huckleberry = 25 features / 11.15 mi.
   - ⚠️ **Naming traps for D2:** Deerfield Trail appears as **`Deerfield`** (1 feature,
     0.76 mi), and the Shenandoah *Bike* Trail appears as **`Shenandoah Trail`** with
     `Type = Trail`, not `Bike Lane` (2 features + 12 `Shenandoah Trail Spur`,
     2.18 mi total). Curated lists must use the data's spelling. 38 trail features have
     a **blank** `Road` and need visual identification.
   - ⚠️ **Grade data does not exist.** `Slope` is populated on 1,026 features and
     **every value is 0**. `Width` is populated on 1 feature. D2's "surface and grade
     gate eligibility" rule is only half-executable — surface (`Material`) is fine
     (`Concrete` 572 / `Asphalt` 282 / `Gravel` 4 / `Dirt` 2 / …, 180 blank), grade must
     come from a DEM (USGS 3DEP 1 m) or be dropped from the automatic rule.
   - ✅ **Sidewalk absorption is a name join, not a geometry job**: 648 of 688 sidewalk
     features carry the parallel street's name in `Road`, plus `From_`/`To_`
     cross-streets. Geometry is needed only for the 40 unnamed ones.
4. **Boundary edge cases** — ❌ CORRECTED: **nearly a no-op.** The town layers are
   already clipped to the corporate limits (Roads 1,546/1,547 intersect, Address
   19,771/19,773, Building 10,156/10,156, Paths 1,068/1,069). The real consequence is
   the opposite of what was expected: **out-of-town connectors don't exist in this data
   at all**, including the Huckleberry south of the town line. If we ever want them,
   they come from another source.
5. **Residence-hall capacity table** — ⚠️ **no footprint source.** See item 0 and §7:
   the town's Building layer contains zero VT residence halls. Care facilities and other
   true group quarters are still excluded from household counts.
6. **Unsafe crossings / unpleasant arterials** — seeded from road class, refined
   from pilot feedback via admin flags.
7. **Missing pedestrian connectors** — cul-de-sac cut-throughs and neighborhood
   paths that make loops possible; Paths to the Future should cover most, OSM
   cross-check + pilot feedback covers the rest. Admin tool must support adding
   connector edges (spec §33).

---

## 6. Data-acquisition notes for Phase 2

- ✅ Scripted paged pulls from the FeatureServer `query` endpoint work and are how the
  schema inspection was performed. The import pipeline should pull from the REST API
  (reproducible, cadenced) rather than one-off manual exports, and keep the raw pulled
  GeoJSON archived so every network build is reproducible from a frozen snapshot.
  - ⚠️ **Do not depend on `f=geojson` bulk export or Hub "Download".** The town's
    services advertise `capabilities = Query,Sync` — **no `Extract`** — on every layer
    we need except Zoning. Paged `query` with `resultOffset` is the reliable path.
    `maxRecordCount` is 8,000 (Address), 4,000 (Paths), 2,000 (Roads, Building,
    boundaries), 5,000 (Comprehensive_Plan).
- **Environment note** — ✅ partially resolved, ⏳ partially not. The three hosts named
  here were allowed and all three respond. But **two of the three sources don't live on
  the host their portal advertises**:
  - `services1.arcgis.com` ✅ — all Town of Blacksburg data, fully queryable.
  - `data-montva-gis.opendata.arcgis.com` ✅ — but this is the **Hub site only**.
    Montgomery County's actual features are on `services5.arcgis.com` ❌ **blocked**.
  - `vgin.vdem.virginia.gov` ✅ — again the **Hub site only**. VGIN's actual features
    are on `vginmaps.vdem.virginia.gov` ❌ **blocked**.
  - Also blocked: `hub.arcgis.com` (every Hub download 302s here), `www.arcgis.com`,
    the town's own Hub site, `www.blacksburg.gov`, `data.virginia.gov`.

  **To finish the VGIN cross-check and test the parcel spatial join, add
  `services5.arcgis.com`, `vginmaps.vdem.virginia.gov` and `hub.arcgis.com` to the
  network policy.** Adding `www.arcgis.com` and the town Hub host would also let us
  capture the licence text the town publishes on its Hub pages.
- ✅ **The schema inspection report is done** — see
  [`04-schema-inspection.md`](04-schema-inspection.md). This audit has been updated
  from it.
- **Source CRS:** all town layers publish in **EPSG:2284** (NAD83 / Virginia South,
  **survey feet**), not the EPSG:6595 the technical plan chose. Reproject on ingest, and
  note that `Shape__Length` on Paths is in feet while Roads carries its own `MILES`.
- **Revised network size:** 1,547 road segments (169.16 mi total; ~124.9 mi public and
  plausibly walkable) + 289 trail-family path features (53.0 mi). After planarizing,
  expect **~2,000–3,000 segments**, not the 3,000–6,000 the technical plan assumed.

---

## 7. ⚠️ The finding that changes the most: Virginia Tech is missing from the town's data

Added 2026-08-03. This is the largest single correction to this audit and it lands on
decision **D1**.

**Campus roads are not in Roads.** Drillfield Dr, Duck Pond Dr, Perry St, Old Turner St,
Beamer Way, Spring Rd, Tech Center Dr, Oak Lane, and the stadium/coliseum drives return
**zero** features. W Campus Dr, Alumni Mall and Stanger St appear only as ~0.01-mile
stubs where they touch a town street. The three features tagged `STREETMAP_ = 'VA TECH'`
total **0.017 miles**.

**Campus addresses are not in Address.** `COMMUNITY = 'VIRGINIA TECH'` appears on 8 of
19,773 points. The 90 points typed `LocalType = 'University'` are VT-*leased offices off
campus* (902 Prices Fork Rd, Kraft Dr, the Corporate Research Center, VTTI). A spatial
sweep of the campus core returns 40 points — Panda Express, Residence Inn, Truist Bank,
the Gateway Center, Smithfield Plantation. **Not one residence hall.**

**Campus buildings are not in Building.** The same sweep returns 23 footprints, 8 of them
Smithfield Plantation. Zero VT residence halls in all 10,156.

**But campus *paths* are in Paths to the Future** — 106 features / 20.5 mi in the campus
core, 79 of them `Owner = VT`, covering Drillfield Dr, West Campus Dr (+ Trail), Duck
Pond Dr (+ Trail), Perry St, Stanger St, Washington St, Smithfield Road Trail (+
underpass), Oak Lane Trail, and the Huckleberry's campus stretch.

**What this means:**

| D1 sub-decision | Status |
|---|---|
| D1a — campus core polygon | ✅ Easier than expected. The `UNIV` zoning polygon (1.38 sq mi) is a first draft. |
| D1b — campus pedestrian ways REQUIRED | ✅ Well supported. Real data, with types and materials. |
| **D1 — campus streets REQUIRED** | ❌ **No source.** Must come from VT Facilities GIS, VGIN RCL, OSM (ODbL contamination), or be hand-digitised. |
| **D1c — residence-hall table** | ❌ **No footprint source.** Must come from VT or be hand-digitised. |
| D1 area estimate | ❌ 1.38–1.68 sq mi in-town, not 4.1. See §5 item 2. |

**Recommendation:** try VGIN RCL first (requires the network-policy change above), and
fall back to hand-digitising. Campus has perhaps 5 miles of drivable street — a
one-afternoon job that keeps the canonical network licence-clean, which is exactly what
§2.4 was designed to protect.

## Sources

**Primary evidence for the 2026-08-03 revisions:**
[`04-schema-inspection.md`](04-schema-inspection.md) — live ArcGIS REST queries against
every endpoint listed there, including full attribute pulls of Roads (1,547), Address
(19,773) and Paths (1,069), full-dataset value distributions via
`groupByFieldsForStatistics`, and boundary-polygon containment tests.

**Original desk-audit sources (retained; several were superseded above):**

- [Town of Blacksburg GIS Open Data hub](https://town-of-blacksburg-gis-data-blacksburg-va.hub.arcgis.com/) · [Roads dataset](https://town-of-blacksburg-gis-data-blacksburg-va.hub.arcgis.com/datasets/Blacksburg-VA::roads) · [Town GIS data page](https://www.blacksburg.gov/departments/departments-a-k/engineering-and-gis/gis-data)
- [Town of Blacksburg on the Virginia Open Data Portal](https://data.virginia.gov/organization/town-of-blacksburg-gis-data) · [Paths to the Future](https://data.virginia.gov/dataset/paths-to-the-future/resource/5dc12247-6ebc-4f57-b4a1-55283e0ecda7)
- [VGIN Clearinghouse downloads](https://vgin.vdem.virginia.gov/pages/cl-data-download) · [Virginia Road Centerlines](https://vgin.vdem.virginia.gov/datasets/VGIN::virginia-road-centerlines-rcl) · [Virginia Address Points](https://vgin.vdem.virginia.gov/datasets/8105f26377d2495f8eb8aeed0794fe7c) · [Virginia Building Footprints](https://vgin.vdem.virginia.gov/datasets/virginia-building-footprints/about) · [RCL data standard (OTH 703-00)](https://www.vita.virginia.gov/media/vitavirginiagov/it-governance/psgs/pdf/VirginiaRCLDataStandardOTH70300.pdf) · [Address point standard](https://vginmaps.vdem.virginia.gov/download/standards/VAOTH704_VirginiaAddressPointsStandardOTH704.pdf)
- [Montgomery County, VA GIS Open Data](https://data-montva-gis.opendata.arcgis.com/) · [County GIS department](https://montva.com/1/departments-services/GIS) · [Parcels Open Data](https://data-montva-gis.opendata.arcgis.com/datasets/MontVA-GIS::parcels-open-data-1/about)
- [Census QuickFacts — Blacksburg town](https://www.census.gov/quickfacts/fact/table/blacksburgtownvirginia/PST045224) · [Blacksburg, Virginia (Wikipedia)](https://en.wikipedia.org/wiki/Blacksburg,_Virginia) · [Huckleberry Trail (Wikipedia)](https://en.wikipedia.org/wiki/Huckleberry_Trail) · [Town Huckleberry Trail page](https://www.blacksburg.gov/Home/Components/FacilityDirectory/FacilityDirectory/88/566)
- [OSM Open Database License](https://wiki.openstreetmap.org/wiki/Open_Database_License) · [OSMF Collective Database Guideline](https://osmfoundation.org/wiki/License/Community_Guidelines/Collective_Database_Guideline_Guideline) · [OSMF Licence & Legal FAQ](https://osmfoundation.org/wiki/Licence/Licence_and_Legal_FAQ) · [VirginiaRoads](https://www.virginiaroads.org/)
