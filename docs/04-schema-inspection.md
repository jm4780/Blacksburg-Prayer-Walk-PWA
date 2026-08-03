# Phase 2a — Schema Inspection Report

**Project:** Blacksburg Prayer Walk PWA
**Date:** 2026-08-03
**Task:** [Technical plan §2.1](02-technical-plan.md) — first task of Phase 2
**Method:** live ArcGIS REST queries against each service root, layer metadata
(`?f=json`), full-dataset `groupByFieldsForStatistics` value distributions, complete
attribute pulls where the layer was small enough, and spatial probes (envelope and
boundary-polygon queries) for coverage questions.

This is **reconnaissance only**. No pipeline code, no application code.

Everything below was read from the live services on 2026-08-03 unless explicitly
marked otherwise. Where a source could not be reached from this environment, that is
stated plainly rather than filled in from documentation — which is the mistake
[`01-data-audit.md`](01-data-audit.md) made, and which this report corrects in several
places.

---

## 0. Answers to the six questions

### Q1 — Does Roads carry a usable ownership / maintenance / road-class attribute?

**Yes. Emphatically yes. This is the best possible outcome.**

`Town of Blacksburg → Address_Road_Building → layer 1 (Roads)` carries **two**
independent classification fields, both domain-backed, both populated on 100% of the
1,547 features:

| Field | Domain | Values present (full dataset) |
|---|---|---|
| `RD_MAINT` | `RoadMaintenance` | `Blacksburg` 1,215 · `Private` 232 · `State` 100 |
| `ROAD_CLASS` | `RoadClass` | `Local` 904 · `Private` 198 · `Secondary` 150 · `Collector` 116 · `Arterial` 94 · `Ramp` 49 · `Primary` 33 · `Service Drive` 3 |

There is also `STREETMAP_` (`Blacksburg` 1,308 / `Private` 235 / `VA TECH` 3), which
tracks `RD_MAINT` almost exactly and adds nothing, and `SpeedLimit` (populated on all
1,547 — 25 mph on 1,166 of them), which feeds `walk_stress` directly.

Cross-tab, with mileage from the layer's own `MILES` field:

| `RD_MAINT` | `ROAD_CLASS` | segments | miles |
|---|---|---:|---:|
| Blacksburg | Local | 866 | 86.03 |
| Private | **Private** | 198 | 17.65 |
| Blacksburg | Secondary | 148 | 17.97 |
| Blacksburg | Collector | 116 | 9.62 |
| Blacksburg | Arterial | 84 | 8.22 |
| State | Ramp | 48 | 8.70 |
| Private | **Local** | 34 | 2.92 |
| State | Primary | 33 | 14.88 |
| State | Arterial | 10 | 1.36 |
| State | Local | 4 | 0.57 |
| State | Service Drive | 3 | 1.04 |
| State | Secondary | 2 | 0.04 |
| Blacksburg | Ramp | 1 | 0.17 |
| | **total** | **1,547** | **169.16** |

**Consequence: public/private classification is mostly automatic, not mostly manual.**
`RD_MAINT = 'Private'` isolates 232 segments / 20.57 miles — 12.2% of the network — and
spot-checking (Q3) shows it is landing on exactly the right streets. The audit's §5.1
prediction that this would be "the single biggest curation task" is wrong. It becomes a
**verification** pass over ~232 flagged segments plus the 34 disagreement rows below,
not a from-scratch classification of 1,547.

Two caveats worth carrying into 2b:

1. **The two fields disagree on 34 segments** — all `RD_MAINT = Private` with
   `ROAD_CLASS = Local` (Foxridge's Copper Croft Run / Foxhunt Ln / Houndschase Ln /
   Heather Dr, Windsor Hills' Wellesley Ct, Hunters Mill Rd, Clover Valley Cir, and
   similar). Zero segments disagree the other way (`ROAD_CLASS = Private` always
   implies `RD_MAINT = Private`). **Treat `RD_MAINT` as authoritative** and put the 34
   on the human review list. `Heather Dr` appears as both `Blacksburg` and `Private` on
   different segments, which is the right behaviour for a street that transitions from
   public to private — evidence the attribute is genuinely maintained per-segment.
2. **`ROAD_CLASS` has domain drift.** The published coded-value domain lists
   `Alley, Bridle Path, Local, Other, Parking Lot, Primary, Private, Ramp, Secondary,
   Service Drive, Stairway, Trail, Vehicular Trail, Walkway` — but the data actually
   uses `Collector` (116) and `Arterial` (94), which **are not in the domain**, and
   uses none of `Alley / Parking Lot / Walkway / Stairway / Trail / Bridle Path /
   Vehicular Trail / Other`. The pipeline must validate against observed values, not
   the declared domain, and must not silently drop unrecognised codes.

Derived network sizes:

- **Public and plausibly walkable:** ~**124.9 mi** (Blacksburg + State, excluding
  `Ramp` 8.87 mi and `Primary` 14.88 mi — `Primary` is exclusively the US-460 bypass,
  17 WB + 16 EB segments).
- **Private:** 20.57 mi.
- **Limited-access, hard-exclude:** 49 ramp segments (8.87 mi) + 33 bypass segments
  (14.88 mi).

### Q2 — Are Address Points unit-level? Is there a stable key?

**Unit-level, and yes — there are two usable keys.**

19,773 address points. `unit` and `unit_designator` are real, populated fields:

| `unit_designator` | count |
|---|---:|
| (blank) | 8,576 |
| `APT` | 7,045 |
| `UNIT` | 2,591 |
| `STE` | 847 |
| `LOT` | 249 |
| `BLDG` | 15 |
| `GATE` | 1 |

**10,770 of 19,773 points (54%) carry a unit.** Apartment complexes are enumerated to
the individual unit: 1,728 points for Foxridge Apartments, 559 for Terrace View, 502
for Hub Blacksburg, 443 for The Union. The largest single street address is
`301 GIVENS LN` with **139** unit-level points under it.

Restricting to `LocalType = 'Residential'` (18,022 points): 9,855 carry a unit, and
they collapse to **9,060 distinct building-level street addresses**. So the layer is
simultaneously usable as a unit count and as a building count — no estimation needed
for the multi-unit case, which removes audit §3 step 3 almost entirely.

**Keys:**

- `ADDR` — the full formatted address string — is **unique across all 19,773 rows**
  (19,773 distinct, zero blanks).
- A normalized composite of `STNUM + STREET_PRE_DIR + STREET_NAME + STREET_TYPE +
  STREET_POST_DIR + unit_designator + unit` is **also unique across all 19,773 rows,
  zero collisions**.
- `GlobalID` is present and unique (19,773 distinct).

Recommendation: **derive the key** from the normalized composite rather than trusting
`ADDR` (which is a display string the town may reformat) or `GlobalID` (Esri-managed;
stable in practice but silently reassigned if the layer is ever republished from a new
source geodatabase). Store all three so the identity matcher has fallbacks.

Other useful fields discovered:

- `LocalType` — the residential filter, on the address layer itself:
  `Residential` 18,022 · `Office/Business` 610 · `Commercial` 490 · `Utility` 155 ·
  `Other` 97 · `University` 90 · `Industrial` 56 · `Religious` 53 · `Recreation` 45 ·
  `Government` 38 · `Parking` 27 · `School` 12 · `Mixed Use` 11 · `Out Building` 6 ·
  `Research` 4. (Same domain drift problem: `Office/Business`, `University`,
  `Religious` are used but are not in the declared `LocalAddrType` domain.)
- `PlaceName` — populated on 14,417 points with the **apartment complex or subdivision
  name** (`Foxridge Apartments`, `Terrace View Apartments`, `The Retreat at
  Blacksburg`, `Windsor Hills`, …). This is a gift: it groups units into complexes
  without any spatial work.
- `Placement` — how the point was sited: `Structure` 19,227 · `Parcel` 271 · `Site` 266
  · `Geocoding` 4 · `Property Access` 4. 97% are placed on the actual structure, so
  nearest-segment association will behave.
- `LandmkName` (2,913 populated) includes 139 points marked `Vacant` and several marked
  `demolished` / `construction site` — filter these or they inflate the count.
- `DateUpdate` populated on 11,654 points, ranging 2000-12-14 to **2026-03-30**.

**The Census reconciliation will not be clean.** 18,022 residential points against the
Census 2020 figure of ~13,800 households is a **+31% gap**. Part of that is real (unit-
level counting of apartments that census counts as occupied households; ~5 years of
construction since 2020; vacancy), but it is large enough that the technical plan's
"large gap means the residential filter is wrong" gate would fire on a *correct*
filter. See §7 for the recommended change.

### Q3 — Does Roads include private and apartment-complex drives?

**Yes — and they are correctly flagged. But coverage is uneven, and the gaps matter
more than the flags.**

Spatial probe: for each complex, take the bounding box of its own address points and
list every Roads feature intersecting it.

| Complex | addr pts | roads in extent | private drives present? |
|---|---:|---:|---|
| Foxridge Apartments | 1,728 | 43 (17 Private) | ✅ Copper Croft Run, Foxhunt Ln, Houndschase Ln, Heather Dr, Cardinal Ct, Chowning Pl, Richmond Ln, Colonial Dr, Heritage Ln, Blue Ridge Dr… |
| The Retreat at Blacksburg | 206 | 28 (20 Private) | ✅ Carpenter Blvd, Crisp Rd, Gustafson Ave, Redd Rd, Strock St, Tomko Rd, MacArthur St, Brightwood Manor Dr |
| Pheasant Run Townhomes | 165 | 12 (11 Private) | ✅ Pheasant Run Ct/Dr, Janie Ln, Redstone Ln, Princeton Rd NW, Yale Rd NW, Tech Ct |
| Maple Ridge Townhomes | 316 | 24 (17 Private) | ✅ Autumn Splendor Way, Turning Leaf Ln, Golden Harvest Cir, Hidden Nest Dr, October Glory Ct, Fallen Acorn Trl |
| Village at Toms Creek | 212 | 46 (13 Private) | ✅ — as **alleys**: Creekside Aly, Meadows Edge Aly, Plum Aly, Periwinkle Aly, Sycamore Aly, Quince Ct, Bluebell Ct |
| Windsor Hills | 303 | 12 (5 Private) | ✅ Ascot Ln, Buckingham Pl, Hampton Ct |
| Collegiate Suites | 211 | 11 (4 Private) | ✅ Henry Ln, Mary Jane Cir, Robinson St, University Ter |
| Alight Blacksburg | 290 | 15 (5 Private) | ✅ Christine Ct, Jennifer Dr, Laurence Ln |
| Chasewood Downs | 277 | 11 (1 Private) | ⚠️ only Appalachian Dr; the rest of the site is parking-lot circulation |
| Terrace View Apartments | 559 | 34 (8 Private) | ⚠️ **no internal drives** — only University Ter / Shenandoah Cir nearby |
| The Mill at Blacksburg | 164 | **1** | ❌ **nothing** — only Grayland St (public) |
| Hunters Ridge | 110 | **2** | ❌ **nothing** — only Seneca Dr (public) |

Two distinct patterns, and the pipeline needs to handle both:

1. **Named private drives (majority).** Present in Roads, flagged `RD_MAINT=Private`.
   Automatic `EXCLUDED` candidate; verify, done.
2. **Parking-lot circulation (The Mill, Hunters Ridge, Terrace View, most of
   Chasewood).** Not in Roads at all — the complex's internal movement is across
   surface lots, which a 911 street file does not model. **Those hundreds of households
   have no nearby segment other than the public street they front.** That is actually
   the behaviour we want (a walker prays for The Mill from Grayland St), but it means
   the 75 m association cap in technical plan §2.5 will fail for units at the back of a
   large site. The Mill's 164 units span well over 75 m from Grayland St.

The audit's warning that "presence in the Roads layer must not be treated as public
street" was right, but it under-anticipated the opposite problem: **absence from Roads
does not mean absence of households.**

### Q4 — What's actually in Paths to the Future?

`Paths_to_the_Future` has two layers. **Layer 1 (`Proposed`) is empty — 0 features.**
All content is in layer 0 (`Existing`): **1,069 features, 157.7 miles**.

Sidewalks, trails, and connectors are distinguished by a plain `Type` field:

| `Type` | features | miles |
|---|---:|---:|
| Sidewalk | 688 | 75.82 |
| **Trail** | 283 | 52.94 |
| Bike Lane | 66 | 19.68 |
| Sharrow | 16 | 6.95 |
| Alley | 7 | 1.47 |
| Trail Tunnel | 4 | 0.08 |
| Share the Road | 2 | 0.38 |
| Contra Flow Lane | 1 | 0.34 |
| Stairs | 1 | 0.01 |
| Bridge | 1 | 0.01 |

`Type` is populated on every feature — no blanks. Sidewalks carry a `Road` name on 648
of 688 features, plus `From_` / `To_` cross-street fields, which makes the technical
plan §2.3 "absorb sidewalks into the parallel street" step a **name join rather than a
geometric one**. That is a significant simplification.

**Named trails — yes, identifiable, with one naming trap:**

| Trail | how it appears | features | miles |
|---|---|---:|---:|
| Huckleberry Trail | `Road = 'Huckleberry Trail'` (+ `Huckleberry Trail Spur`, `Huckleberry Trail Underpass`, one `Bridge`, one `Stairs`) | 25 | 11.15 |
| **Deerfield Trail** | `Road = 'Deerfield'` — **not** "Deerfield Trail" | **1** | **0.76** |
| **Shenandoah Bike Trail** | `Road = 'Shenandoah Trail'` (2) + `Shenandoah Trail Spur` (12); `Type = Trail`, **not** `Bike Lane` | 14 | 2.18 |
| Hethwood Trail | `Hethwood Trail` / `Hethwood Trail Spur` | 37 | ~2.6 |
| Gateway Trail | `Gateway Trail` | 2 | 0.55 |

Others present and named: Fiddlers Green, CRC Trail, BHS Trail, Kipps Farm, Wong Park,
Echols Village, Bicenntennial *(sic — misspelled in the data)*, Midtown, The Glen,
Givens Lane, Duck Pond, Oak Lane, West Campus Drive, Smithfield Road, Prices Fork Road,
Kraft Drive, Innovation Drive, Research Center Drive.

So for **D2**: Deerfield and Shenandoah are both findable, but a curated list keyed on
exact `Road` strings must use the data's spelling, not the colloquial name. 38 trail
features have a **blank** `Road` and will need visual identification.

**Surface: present. Grade: absent.**

- `Material` (the surface attribute D2 asks for) is populated on 886 of 1,069:
  `Concrete` 572 · `Asphalt` 282 · `Brick` 13 · `Concrete/Asphalt` 5 · `Mix` 5 ·
  `Gravel` 4 · `Dirt` 2 · **`Aspahlt` 2 (misspelled)** · `Wood` 2 · `Review` 1 ·
  `Green Lane` 1. 180 features are blank/null. Normalisation needed, but usable.
- **`Slope` is populated on 1,026 features and every single value is `0`.** The field
  exists and is empty of information. **There is no grade data in this dataset.**
- `Width` is populated on **1 feature out of 1,069** (value 5). Effectively absent.
- `Level_` (difficulty) is populated on 12 features. Effectively absent.

**D2's "surface and grade gate trail eligibility" rule is half-executable.** Surface
yes; grade must come from a DEM (USGS 3DEP 1 m is available for Montgomery County) or
be dropped from the automatic rule and handled by curation. See §7.

Ownership on paths: `Owner` is blank on 886 features, and populated as `VT` 91 ·
`PRIV` 27 · `TOB` 24. `Maintenanc` mirrors it. So **path ownership is only ~17%
attributed** — much weaker than Roads. The 27 `PRIV` features are all `Type = Trail`
(3.96 mi) and are a good starting flag list, but this field cannot carry the same
weight `RD_MAINT` does.

### Q5 — License text and last-updated date per dataset

| Dataset | License text carried by the data | Last data edit |
|---|---|---|
| **All Town of Blacksburg layers** | **None.** `copyrightText` is empty at both service and layer level on every service inspected — Address_Road_Building, Administrative_Reference_Boundaries, Paths_to_the_Future, Comprehensive_Plan, Parks_and_Open_Space, Zoning_and_Landuse. The only town service carrying attribution is Brush_Mountain_Trails: *"Poverty Creek Trails Coalition, New River Land Trust, Town of Blacksburg"*. | see below |
| Montgomery County **Parcels Open Data** | Warranty disclaimer only: *"Information shown is for reference purposes only and is not to be construed or used as a legal or official determination… Data is believed to be accurate but is not guaranteed. The Montgomery County Board of Supervisors or Planning & GIS Services are not responsible for any inaccuracies herein contained…"* Plus, importantly: *"Owner names are excluded for privacy, however all other property value and related information is within."* Hub `license` field = `custom`. | 2026-03-05 (item), 45,565 records |
| **VGIN** RCL / Address Points / Building Footprints | Warranty disclaimer only, identical across all three: *"The Virginia Base Data layers are intended for cartographic use and spatial analysis only, and not for use as a legal description. Best efforts were undertaken to ensure the correctness of RCL, Address Points, Parcels, Administrative Boundaries, and Building Footprint data throughout the Commonwealth of Virginia, however, all warranties regarding the accuracy of the map data and any representation or inferences derived there from are hereby expressly disclaimed."* Hub `license` field = `custom`. | 2026-07-01 (all three) |

Town of Blacksburg per-layer edit dates (from `editingInfo`, live):

| Service | Layer | Features | Data last edited | Schema last edited |
|---|---|---:|---|---|
| Address_Road_Building | 0 · Address | 19,773 | 2026-04-07 | 2023-10-17 |
| Address_Road_Building | 1 · Roads | 1,547 | 2026-04-07 | 2025-02-04 |
| Address_Road_Building | 2 · Building | 10,156 | 2026-03-31 | 2023-10-17 |
| Administrative_Reference_Boundaries | 4 · Town Corporate Limits | 1 | 2026-01-31 | 2024-06-18 |
| Paths_to_the_Future | 0 · Existing | 1,069 | 2025-11-07 | 2025-11-07 |
| Paths_to_the_Future | 1 · Proposed | **0** | 2025-11-07 | 2025-11-07 |
| Zoning_and_Landuse | 9 · Town Zoning | 112 | **2023-01-09** | 2023-01-09 |
| Comprehensive_Plan | 8 · Current Land Use | 11,398 | 2026-01-29 | 2023-05-04 |
| Comprehensive_Plan | 7 · Future Land Use | 151 | 2026-04-02 | 2023-05-04 |
| Parks_and_Open_Space | 0 · Parks | 44 | 2026-03-14 | 2023-05-02 |
| Parks_and_Open_Space | 1 · Open Space | 375 | 2026-03-14 | 2023-05-02 |
| Brush_Mountain_Trails | 0 | 18 | 2026-03-06 | 2026-03-06 |

Roads and Address were both edited **2026-04-07**; `CHGDATE` inside Roads runs from
2004-08-09 to **2026-03-20**. This data is live and current.

**Nothing in any town dataset grants a redistribution licence.** The audit recorded
"free use and download" from the town's website; that text is *not attached to the
data*, and the town's Hub site and blacksburg.gov are both unreachable from this
environment, so it could not be re-verified. See §7 — this needs a written answer from
the town before anything derived from it is published.

### Q6 — Do Parcels have land-use codes, and owner names to drop?

**Owner names: there are none to drop. The publisher already removed them.**

Montgomery County `Parcels_Open_Data` — 45,565 parcels countywide, 11,358 with
`JURISDICTI = 'BLACKSBURG'`. Full field list: `PARCEL_ID, TAX_MAP_ID, SITE_ADD1,
SITE_ADD2, ACRES, LEGAL1, LEGAL2, SUBD_NAME, SUBD_LOT, SUBD_BLK, PLATBK_PG, DEEDBOOK,
DEEDPAGE, TAXDIST, ZONING, NEIGHBORHD, LAND_VALUE, BLDG_VALUE, TOTAL_VALU, LANDUSE_VA,
SALE_DATE, SALE_PRICE, STORIES, YEARBLT, ROOMS, BEDROOMS, FULLBATHS, HALFBATHS, MGFA,
SFLA, COMMYRBLT, BUS_NAME, EX_CLASSD, JURISDICTI, NACRES, NLAND_VALU, NBLDG_VALU,
NTOTAL_VAL, NLANDUSE, NSALE_PRIC, GlobalID`.

There is **no owner-name field of any kind**. The dataset description says so
explicitly: *"Owner names are excluded for privacy."* `BUS_NAME` is a business/site
name (`FOXRIDGE APTS`, `TERRACE VIEW`, `6 UNIT APARTMENTS`, `BBURG PRESBYTERIAN
CHURCH`) — blank on 43,181 of 45,565 — not a person. It is still worth dropping
`DEEDBOOK` / `DEEDPAGE` / `SALE_DATE` / `SALE_PRICE` / the four value fields at import
since we don't need them, but the PII risk the audit flagged does not exist here.

**Land-use codes: yes — but not the field the audit assumed.**

⚠️ **`LANDUSE_VA` is not a land-use code.** It is a dollar amount — the Virginia
land-use *deferral* assessment value. 43,283 of 45,565 rows are `'$0.00'`; the
remainder are values like `'$303,100.00'`. Its numeric twin `NLANDUSE` has mean
$6,918, max $3,617,400. Anything keying a residential filter on "the parcel land use
code" will get garbage.

The field that actually classifies property use is **`EX_CLASSD`**:

| `EX_CLASSD` | parcels (countywide) |
|---|---:|
| Single Family Urban | 19,178 |
| Single Family Sub-Urban | 16,386 |
| Commercial & Industrial | 3,447 |
| Agricultural (undeveloped) 20–99 acres | 2,230 |
| **Multi-Family Apt/Townhouses** | 928 |
| Common Area | 672 |
| Agricultural (undeveloped) over 99 acres | 604 |
| Exempt/Local Government | 490 |
| Exempt/Other | 477 |
| Exempt/Religious | 420 |
| Exempt/Educational | 396 |
| Exempt/State Government | 119 |
| Exempt/Regional Government | 89 |
| Exempt/Charitable | 74 |
| Exempt/Federal Government | 32 |
| Mineral Land | 8 |
| Exempt/Multiple Government | 1 |

`ZONING` is also populated (`A1` 16,196 · `R1` 4,367 · `R3` 4,066 · `R2` 3,945 ·
`R-4` 3,824 · `PR` 2,172 … `UNIV` 153), mixing county and town district codes.
`BEDROOMS` (populated on 30,534), `ROOMS`, `STORIES`, and `YEARBLT` are present and
would support unit estimation — though after Q2 we barely need them.

**However — we probably don't need Parcels at all.** See §5: the Town publishes a
`Current Land Use` layer with 11,398 parcel-level polygons carrying a clean `Land_Use`
classification, no owner data, and a 2026-01-29 edit date. It is a better fit, it comes
from a source we can actually query, and it needs no PII handling.

⚠️ **Montgomery County parcel *features* could not be pulled.** The dataset lives on
`services5.arcgis.com`, which this environment's network policy blocks (403 at the
proxy). Everything above comes from the ArcGIS Hub v3 metadata + statistics API on the
allowed host `data-montva-gis.opendata.arcgis.com`, which returns the full field list
and full-dataset string-value frequencies but no geometry and no row-level data. **The
schema and distributions are real; the spatial join has not been tested.**

---

## 1. Environment / network reality

Network access works — the check in the task brief succeeded. But the allowlist is
**exactly three hosts**, and two of the three sources actually live somewhere else:

| Host | Status | What's on it |
|---|---|---|
| `services1.arcgis.com` | ✅ 200 | All Town of Blacksburg layers. Fully queryable. |
| `data-montva-gis.opendata.arcgis.com` | ✅ 200 | Montgomery County **Hub site only** — DCAT catalogue + v3 metadata/statistics API. |
| `vgin.vdem.virginia.gov` | ✅ 200 | VGIN **Hub site only** — DCAT catalogue + item metadata. |
| `services5.arcgis.com` | ❌ 403 | Montgomery County's actual **feature services** (Parcels, Zoning, Hiking Trails). |
| `maps.montva.com` | ❌ 403 | Montgomery County's ArcGIS Server (Parcels_Public MapServer). |
| `vginmaps.vdem.virginia.gov` | ❌ 403 | VGIN's actual **feature services** (VBMP RCL, VA Address Points). |
| `hub.arcgis.com` | ❌ 403 | Hub download redirect target — all `/api/download/…` calls 302 here and die. |
| `www.arcgis.com` | ❌ 403 | AGOL item pages / sharing REST. |
| `town-of-blacksburg-gis-data-blacksburg-va.hub.arcgis.com` | ❌ 403 | Town Hub site (where the licence statement would be). |
| `www.blacksburg.gov`, `data.virginia.gov` | ❌ 403 | Town GIS page, state catalogue. |

**To finish the VGIN cross-check and test the parcel spatial join, add
`services5.arcgis.com`, `vginmaps.vdem.virginia.gov`, and `hub.arcgis.com` to the
policy.** Adding `www.arcgis.com` and the town Hub host would also let us capture the
licence text the town publishes on its Hub pages.

One more constraint that matters for the pipeline: the town's services advertise
`capabilities = Query,Sync` — **not `Extract`** — on Address_Road_Building,
Paths_to_the_Future, Administrative_Reference_Boundaries, Comprehensive_Plan and
Parks_and_Open_Space. Only Zoning_and_Landuse offers `Extract`. Paged `query`
harvesting works fine (that is how the full tables below were pulled), so this is not a
blocker — but Hub "Download" buttons and `f=geojson` bulk exports may not be available,
and the pipeline should not depend on them. `maxRecordCount` is 8,000 for
Address_Road_Building, 4,000 for Paths, 2,000–5,000 elsewhere.

---

## 2. Town of Blacksburg — service inventory

The service root is `https://services1.arcgis.com/rAuQoDGA22NtJdmg/arcgis/rest/services`
and it lists **30 FeatureServers**. The audit's guessed dataset names were close but
not right — **there is no service called "Roads", "Address Points", or "Building
Footprints".** They are three layers of one service:

```
Address_Road_Building/FeatureServer
  0  Address    (point)     19,773
  1  Roads      (polyline)   1,547
  2  Building   (polygon)   10,156

Administrative_Reference_Boundaries/FeatureServer
  0  Neighborhoods · 1 Service Quadrants · 2 16 Squares · 3 Historic District
  4  Town Corporate Limits  (polygon)  1     ← the boundary layer, actual name

Paths_to_the_Future/FeatureServer
  0  Existing   (polyline)   1,069
  1  Proposed   (polyline)       0     ← empty

Zoning_and_Landuse/FeatureServer      (11 layers; 9 = Town Zoning, 112 polys)
TownZoningLayers/FeatureServer        (older duplicate of the above)
Comprehensive_Plan/FeatureServer      (9 layers; 8 = Current Land Use, 7 = Future Land Use)
Parks_and_Open_Space/FeatureServer    (0 Parks 44, 1 Open Space 375)
Brush_Mountain_Trails/FeatureServer   (18 trails)
Blacksburg_Transit · Hydrology · Impervious_Surface · Midtown_Parcels ·
Brush_Mountain_Properties · Routes · LandingZones · Frog_Points ·
Historic_and_Wayfinding_Signs_public_view · Utility_Undergrounding_Priorities_public_view ·
Town_of_Blacksburg_Water_Service_Extent · 6× survey123_* forms · Bike_to_work_day_feedback
```

🤨 **Oddity worth a mention:** the root also serves four Tucson, Arizona police-incident
services (`Tucson_Police_Incidents_2024`, `Tucson_AZ_Police_Incidents_2024`,
`Tucson_Police_Part_I_Incidents2024`, `Tucson_Police_Incidents___2024___Open_Data`) and
a `PDI_(Police_Data_Initiative)_Crime_Incidents…` service. Almost certainly a training
artefact left in the org. Harmless, but it is a small signal about how tightly this
org's published content is curated — don't assume every service here is authoritative.

All layers are published in **EPSG:2284** (NAD83 / Virginia South, ftUS — reported as
`wkid 102747 / latestWkid 2284`), not the EPSG:6595 the technical plan §2.2 chose.
That's fine — reproject on ingest — but note the source unit is **survey feet**, so
`Shape__Length` on Paths is in feet, and Roads carries its own `MILES` field.

**All four core layers are already clipped to the town boundary.** Tested against the
Town Corporate Limits polygon:

| Layer | total | intersecting town boundary |
|---|---:|---:|
| Roads | 1,547 | 1,546 |
| Address | 19,773 | 19,771 |
| Building | 10,156 | 10,156 |
| Paths (Existing) | 1,069 | 1,068 |

This contradicts the audit's expectation that the Roads layer "likely extends to/past
the town boundary." It doesn't — the boundary-splitting work in technical plan §2.3 is
nearly a no-op, but the flip side is that **out-of-town connectors don't exist in this
data at all**, including the Huckleberry Trail south of the town line (see §4).

Town Corporate Limits reports **19.8227 sq mi / 12,686.5 acres** — consistent with the
audit's 19.77 figure.

---

## 3. Roads (Address_Road_Building/1) — full field list

1,547 features · polyline · EPSG:2284 · `maxRecordCount` 2,000 · data last edited
2026-04-07.

| Field | Type | Domain | Notes |
|---|---|---|---|
| `OBJECTID` | OID | | |
| `PRE_TYPE` | String(20) | | |
| `PREMOD` | String(15) | | |
| `PREDIR` | String(10) | LegacyStreetNameDirectional | E/N/NE/NW/S/SE/SW/W |
| `NAME` | String(35) | | street name, no type/dir |
| `TYPE` | String(10) | LegacyStreetNameType | `DR` 394 · `ST` 371 · `RD` 255 · `LN` 169 · blank 92 · `CT` 66 · `AVE` 58 · `CIR` 55 · `WAY` 20 · `BLVD` 15 · `ALY` 10 · `TER` 8 · `PL` 7 · `XING` 5 · `RUN`/`TRL` 3 · `MALL`/`PASS`/`RDG` 2 · `PLZ`/`SQ` 1 |
| `SUFFIX` | String(10) | LegacyStreetNameDirectional | post-directional |
| `ESN_L` / `ESN_R` | Double | | 911 emergency service number |
| `COMM_L` / `COMM_R` | String(25) | | `BLACKSBURG` 1,546 · `VIRGINIA TECH` 1 |
| `L_F_ADD` `L_T_ADD` `R_F_ADD` `R_T_ADD` | Double | | address ranges — **1,362 of 1,547 have a nonzero range** |
| `MSAG_L` / `MSAG_R` | String(25) | | |
| `ROUTE` | String(15) | | blank 1,531 · `PRIVATE` 3 · `314` 2 |
| `CHGDATE` | Date | | 2004-08-09 → **2026-03-20** |
| `ALTNAME` | String(18) | | mostly blank; `STATE ROUTE 685` 25 · `3A` 36 · `SMART RD` 1 · **`TO BE VACATED` 1** |
| `SOURCE` | String(5) | | `BB` 1,537 · `VDOT` 5 |
| **`RD_MAINT`** | String(15) | **RoadMaintenance** | **`Blacksburg` 1,215 · `Private` 232 · `State` 100** |
| `MILES` | Double | | min 0.0036 · median 0.076 · max 1.406 · **sum 169.16** |
| `LABEL` | String(50) | | full display name; **511 distinct** |
| `BLOCK_RANG` | String(15) | | |
| `STREETMAP_` | String(20) | | `Blacksburg` 1,308 · `Private` 235 · `VA TECH` 3 |
| `ONE_WAY` | String(2) | OneWay | `B` 1,329 · `FT` 166 · `TF` 52 |
| **`ROAD_CLASS`** | String(15) | **RoadClass** | see Q1 |
| `SHAPE_LENG` | Double | | |
| `GlobalID` | GlobalID | | |
| `postal_code_left` / `_right` | String(7) | PostalCode | |
| `Parity_L` / `Parity_R` | String(255) | Parity | |
| `State_L` `State_R` `County_L` `County_R` | String(255) | | |
| `NbrhdCom_L` / `NbrhdCom_R` | String(255) | | |
| **`SpeedLimit`** | SmallInteger | SpeedLimit | 25 → 1,166 · 15 → 141 · 35 → 90 · 20 → 73 · 40 → 26 · 65 → 25 · 45 → 11 · 55 → 8 · 30 → 7 |
| `Shape__Length` | Double | | survey feet |

**Segmentation:** median segment 0.076 mi (~400 ft), p25 0.049, p75 0.130, max 1.406.
48 segments are under 0.01 mi (53 ft) and 105 under 0.02 mi. This is **already roughly
intersection-to-intersection**, which is the unit technical plan §2.3 wants. The
sub-50-ft slivers are mostly intersection stubs and will need the §2.3 degree-2 merge
rule; expect that rule to do real work.

**Graph size revision:** the technical plan §0 estimates 3,000–6,000 network segments.
Actual inputs are 1,547 roads + 289 trail-family paths. After planarizing and adding
pedestrian connectors, expect **roughly 2,000–3,000 segments** — smaller than planned,
which is good news for the router.

### Address-point ↔ street-name join

The technical plan §2.5 tie-break relies on matching an address point's street name to
a segment's `normalized_name`. Tested with a naive normalization (`PREDIR + NAME + TYPE
+ SUFFIX` vs `STREET_PRE_DIR + STREET_NAME + STREET_TYPE + STREET_POST_DIR`, uppercased,
whitespace-collapsed):

- 511 distinct road street keys · 481 distinct address street keys.
- **19,605 of 19,773 address points (99.2%) match a road street key exactly**, with no
  normalization beyond case and whitespace.
- 168 points (0.8%) across 18 street names don't: `TRAVIS TRL` 30, `COUNTRY CLUB DR` 23,
  `JENNELLE RD` 21, `FAIN DR` 20, `OAKLAND SQ` 13, `GARST ALY` 12, `SELLERS ST` 11,
  `PERRY ST` 5 (campus — see §6), `S MAIN STS` 1 (typo in the address layer), and others.
- 48 road street names have no address points — bypass ramps, `ALUMNI MALL`,
  `BRUSH MOUNTAIN RD`, `GORDON C WILLIS SMART RD`, industrial stubs.

**The tie-break will work.** The residual 0.8% is small enough to handle by hand.

---

## 4. Paths to the Future (Existing) — full field list

1,069 features · polyline · 157.69 mi · data last edited 2025-11-07.

| Field | Type | Populated | Values |
|---|---|---|---|
| `Id` | Integer | | source id |
| **`Road`** | String(50) | 1,000+ | street name for sidewalks; trail name for trails |
| `From_` / `To_` | String(50) | partial | cross-street endpoints |
| **`Type`** | String(50) | **1,069 / 1,069** | see Q4 table |
| `Route` | String(50) | 104 | bike-route colours (`Orange` 25, `Lime` 18, `Purple` 17…) + `Huckleberry Trail` |
| `F5ftReg` | String(50) | 2 | effectively empty |
| `Status` | String(50) | 1,069 | all `Existing` |
| `Level_` | String(50) | **12** | `Intermediate` 7 · `Advanced` 3 · `Beginner` 1 · `Virginia Tech Trail` 1 |
| `Width` | Single | **1** | effectively empty |
| **`Material`** | String(20) | **889** | `Concrete` 572 · `Asphalt` 282 · `Brick` 13 · `Concrete/Asphalt` 5 · `Mix` 5 · `Gravel` 4 · `Dirt` 2 · `Aspahlt` 2 *(sic)* · `Wood` 2 · `Review` 1 · `Green Lane` 1 |
| **`Slope`** | Single | 1,026 | **every value is 0 — no information** |
| `Maintenanc` | String(12) | 52 | `Private` 27 · `TOB` 25 |
| `Alt_Type_1` / `Alt_Type_2` | String(30) | 6 / 1 | `Trail` 4, `Sharrow` 1, `Bilke Lane` 1 *(sic)* |
| `Priority` | String(25) | 10 | all `High` |
| **`Owner`** | String(5) | **142** | `VT` 91 · `PRIV` 27 · `TOB` 24 |
| `Subtype` | String(50) | 2 | `Conventional` |
| `Notes` | String(255) | 3 | one records a Huckleberry bridge split; one *"owned by VT but maintained by PW"* |
| `Shape__Length` | Double | 1,069 | **survey feet** |

The three `Notes` entries are worth reading during curation — one documents that a
Huckleberry segment was split out to model a bridge over Stroubles Creek, which is
exactly the kind of thing that will confuse a naive geometry matcher.

---

## 5. Layers the audit didn't know about (and one it should use instead of Parcels)

Enumerating the service root turned up several layers that change the plan for the
better:

### `Comprehensive_Plan / 8 — Current Land Use` ⭐

**11,398 parcel-level polygons, edited 2026-01-29, no owner data, on a host we can
actually query.** Fields: `ST_Level_1`, `ST_Level_2`, `ST_Level_3` (hierarchical
LBCS-style codes) and a plain-English `Land_Use`:

| `Land_Use` | polygons | sq mi |
|---|---:|---:|
| Low Density Residential | 5,804 | 4.33 |
| Undeveloped | 435 | 3.80 |
| Very Low Density Residential / Agricultural | 43 | 2.66 |
| Research & Development / Light Industry | 265 | 1.71 |
| **University** | 150 | 1.68 |
| Park Land / Open Space | 316 | 1.33 |
| Civic | 305 | 0.95 |
| High Density Residential | 1,306 | 0.92 |
| Medium Density Residential | 2,056 | 0.64 |
| Industrial | 25 | 0.38 |
| Commercial | 206 | 0.26 |
| Professional Office | 213 | 0.11 |
| Mixed Use | 229 | 0.10 |
| Transportation, Roads, Parking | 45 | 0.04 |

This replaces Montgomery County Parcels for the residential-filter role: it's town-
scoped, current, PII-free, queryable, and its classes map straight onto what we need.
Keep Parcels as a cross-check only (and for `EX_CLASSD` / `BEDROOMS` if unit estimation
ever needs a second opinion).

### `Zoning_and_Landuse / 9 — Town Zoning`

112 polygons covering 19.81 of the town's 19.82 sq mi. **Data last edited 2023-01-09 —
by far the stalest layer in the town's catalogue.** Districts by area:
`RR-1` 8.27 · `R-4` 3.24 · `PR` 2.29 · **`UNIV` 1.38** · `RD` 1.33 · `R-5` 0.58 ·
`IN` 0.54 · `GC` 0.52 · `O` 0.51 · `RM-48` 0.41 · `RM-27` 0.26 · `DC` 0.15 · rest <0.1.

The single **`UNIV` polygon (1.38 sq mi)** is a ready-made starting point for D1's
hand-drawn campus core polygon — see §6.

### `Parks_and_Open_Space / 1 — Open Space`

375 polygons typed `HOA Active` 142 · `Town Developed` 79 · `Privately Owned` 76 ·
`HOA Inactive` 61 · `Town Undeveloped` 17. **The HOA and Privately-Owned polygons are a
strong second signal for private-drive detection** — a road segment inside an HOA
common-area polygon is a private-drive candidate even if `RD_MAINT` says otherwise.

### `Parks_and_Open_Space / 0 — Parks`

44 parks with `Name`, `Address`, `acreage`, `Status` (`Developed` 35 / `Undeveloped` 9).
Includes **"Deerfield Bike Trail"** (1200 Deerfield Dr) and "Heritage Community Park &
Natural Area" as named park features — useful for D2 naming and for route endpoints.

### `Address_Road_Building / 2 — Building`

10,156 footprints with a `PlaceType` domain: `Residential` 6,679 · `Out Building` 2,331
· `Commercial` 235 · `Industrial` 22 · … `University` 4. `height_ft` populated on 7,541,
`COMMON_NAME` on 899, plus `CO_DATE` (certificate of occupancy). Good for household
sanity checks; **note only 4 buildings are typed `University`** — see §6.

### `Brush_Mountain_Trails / 0`

18 named trails with `Difficulty` (`Beginner` 7 / `Intermediate` 5 / `Advanced` 4),
`Property` (`McDonald Hollow` 7 · `Stonecutters` 7 · `Property 3` 4), `Status` (all
`Open`), and the only real attribution string in the town's catalogue. These are
mountain-bike/hiking singletrack, almost certainly `EXCLUDED` for prayer-walk purposes,
but D2 should say so explicitly rather than leave them unaddressed.

---

## 6. The finding that changes the most: **VT campus is missing from the town's road, address, and building layers**

This is the biggest surprise in the report and it lands squarely on **decision D1**.

**Campus roads are not in Roads.** Probing by name across all 1,547 features:

| Campus street | In Roads? |
|---|---|
| Drillfield Dr | ❌ none |
| Duck Pond Dr | ❌ none |
| Perry St | ❌ none |
| Old Turner St | ❌ none |
| Beamer Way | ❌ none |
| Spring Rd | ❌ none |
| Tech Center Dr | ❌ none |
| Stadium / Coliseum drives | ❌ none |
| Oak Lane | ❌ none |
| W Campus Dr | ⚠️ **1 segment, 0.01 mi** |
| Alumni Mall | ⚠️ **2 segments, 0.01 mi total** |
| Stanger St | ⚠️ **1 segment, 0.01 mi** |
| Burruss Dr | ⚠️ 1 segment, 0.21 mi |
| McBryde Dr / McBryde Ln | ⚠️ 12 segments, 0.74 mi |

The three `STREETMAP_ = 'VA TECH'` features total **0.017 miles**. They are the stubs
where a campus road touches a town street — the town's file stops at the campus line.

**Campus addresses are not in Address.** `COMMUNITY = 'VIRGINIA TECH'` appears on 8 of
19,773 points. The 90 points typed `LocalType = 'University'` are VT-*leased offices
off campus* — 902 Prices Fork Rd, Kraft Dr, University City Blvd, the Corporate
Research Center, VTTI on Transportation Research Plz. A spatial sweep of the campus core
returns 40 address points, of which the named ones are Panda Express, Residence Inn,
Truist Bank, the Gateway Center, and Smithfield Plantation. **Not one residence hall.**

**Campus buildings are not in Building.** The same spatial sweep returns 23 footprints —
8 of them Smithfield Plantation, plus Hardees and University City Mall. Searching all
10,156 footprints for `COMMON_NAME LIKE '%HALL%'` returns exactly two: *Town Hall Annex*
and *St Lukes & Oddfellows Hall*. There are **zero** VT residence halls.

**But campus pedestrian infrastructure *is* in Paths to the Future.** A spatial sweep of
the campus core returns **106 path features, 20.5 miles** — 79 of them `Owner = VT` —
including Drillfield Drive, West Campus Drive (+ Trail), Duck Pond Drive (+ Trail),
Perry Street, Stanger Street, Washington Street, Smithfield Road Trail (+ Underpass),
Oak Lane Trail, and the Huckleberry's campus stretch. Statewide across the layer,
`Owner = VT` totals 91 features / 16.15 mi.

**Consequences for D1, in order of severity:**

1. **D1b is already well served.** "Make campus pedestrian ways REQUIRED" has a real
   data source, with types and materials. This part of D1 is buildable now.
2. **D1's campus *street* network has no source.** If campus roads are to be REQUIRED
   segments, they must come from somewhere else: VT's own GIS (Facilities publishes an
   ArcGIS org), VGIN RCL (statewide, likely includes them — untestable from here, see
   §1), or OSM (which would drag ODbL into the canonical network, the exact thing audit
   §2.4 designed around). **This needs a decision before 2b.**
3. **D1c's residence-hall table cannot be seeded from town footprints.** The audit
   assumed VT dorms could be located from Building Footprints and joined to published
   bed counts. There are no dorm footprints. The ~47-row table must be built from VT's
   own data or hand-digitised.
4. **D1's area arithmetic is off.** The decision doc says campus is "2,600 acres ≈ 4.1
   sq mi… roughly 20% of the town by area." The town's own layers put the in-town
   university footprint at **1.38 sq mi** (`UNIV` zoning, one polygon) to **1.68 sq mi**
   (`Current Land Use = University`, 150 polygons) — **7–8% of the town**, not 20%. The
   2,600-acre figure is VT's total holdings, much of which (Kentland Farm, the airport,
   agricultural research land) sits outside the corporate limits or is zoned `RR-1`.
   D1's headline-metric impact is therefore materially smaller than estimated — which
   *strengthens* the case for including campus, since the cost is lower.
5. **Silver lining:** the `UNIV` zoning polygon is a usable first draft of D1a's
   hand-drawn campus core polygon. That's a curation task nearly done.

---

## 7. What this changes — recommendations for Phase 2b

Ordered by how much they change the plan.

1. **Public/private classification is largely solved.** Seed `access_type` from
   `RD_MAINT` (`Private` → `PRIVATE`, `Blacksburg`/`State` → `PUBLIC`), auto-`EXCLUDED`
   the 232 private segments, hard-`EXCLUDED` the 49 ramps and 33 bypass segments, and
   send the 34 `RD_MAINT`/`ROAD_CLASS` disagreement rows plus any segment inside an
   `HOA Active` / `Privately Owned` open-space polygon to human review. Budget hours,
   not days.
2. **Decide the campus road source before building anything** (§6.2). Options: VT
   Facilities GIS · VGIN RCL · OSM-with-ODbL-consequences · hand-digitise the ~15
   campus streets. My recommendation: try VGIN RCL first (needs the network policy
   change in §1), fall back to hand-digitising — campus has maybe 5 miles of drivable
   street and it is a one-afternoon job that keeps the canonical network licence-clean.
3. **Swap the residential filter to town `Current Land Use` + address `LocalType`** and
   demote Montgomery Parcels to cross-check. Both town fields are current, PII-free,
   and queryable; `LANDUSE_VA` is a dollar amount and would have silently produced
   nonsense.
4. **Loosen the Census calibration gate.** 18,022 unit-level residential points vs
   ~13,800 Census-2020 households is a +31% gap that a *correct* filter produces. The
   gate should compare against total **housing units** (not households), allow a wide
   band, and print the composition (units-with-designator vs building-level points) so
   a human can judge. As written, the gate fails on good data.
5. **Grade data does not exist** — `Slope` is uniformly zero. Either derive grade from a
   DEM (USGS 3DEP 1 m covers Montgomery County) or drop grade from D2's automatic
   eligibility rule and make it a curation note. Surface (`Material`) is fine and should
   still gate.
6. **Handle "households with no adjacent segment."** The Mill (164 units), Hunters Ridge
   (110), Terrace View (559) and similar sites have no internal drives in Roads. The
   75 m association cap will orphan units at the back of these sites. Recommend: raise
   the cap, or add a `PlaceName`-based rule that associates every unit in a named
   complex to the same segment the complex's frontage point resolves to. `PlaceName` is
   populated on 14,417 points and makes this easy.
7. **Sidewalk absorption is a name join, not a geometry job.** 648 of 688 sidewalk
   features carry the parallel street's name in `Road`, plus `From_`/`To_` cross-streets.
   Match on name first, use geometry only for the 40 unnamed ones.
8. **Get the licence question answered in writing.** No town dataset carries any licence
   text at all. Before publishing anything derived from town data, ask Blacksburg
   Engineering & GIS for a one-line written confirmation. Record whatever they say in
   the per-dataset sidecar. This is a person-to-person task, not a data task, and it
   should start now because it has latency.
9. **Revise the expected graph size** in technical plan §0 from 3,000–6,000 segments to
   ~2,000–3,000, and the expected required mileage to roughly **125 mi of public street +
   ~11 mi of in-town Huckleberry + whatever else D2 admits**.
10. **Normalise the misspellings and drift** in the pipeline: `Aspahlt` → `Asphalt`,
    `Bilke Lane` → `Bike Lane`, `Bicenntennial` → `Bicentennial`, `Deerfield` →
    `Deerfield Trail`, `S MAIN STS` → `S MAIN ST`. Log every correction; never silently
    fix.

## 8. Things I could not answer

- **VGIN RCL and VGIN Address Points field schemas — unknown.** Both are published only
  as File Geodatabase downloads (112 MB and 176 MB, both updated 2026-07-01) on the Hub
  site; the queryable REST endpoints are on `vginmaps.vdem.virginia.gov`, which is
  blocked. **The cross-check the task asked for could not be performed.** No field list,
  no value distributions, and specifically no answer to "does VGIN RCL contain the VT
  campus streets the town's file omits" — which is now the most valuable thing VGIN
  could tell us.
- **Montgomery Parcels geometry and the point-in-parcel join — untested.** Schema and
  full-dataset value distributions were obtained via the Hub metadata API; no features
  were retrieved.
- **Town of Blacksburg licence text — does not exist in the data**, and every host that
  might carry the town's published statement is blocked.
- **`Slope` on paths** — the field is present and uniformly zero. Whether the town
  intends to populate it is unknown; the schema was last edited 2025-11-07, same as the
  data.
- **Whether the 34 `RD_MAINT`/`ROAD_CLASS` disagreements are data errors or genuine
  public-street-becomes-private transitions** — needs local eyes on a map, not more
  queries.

---

## Appendix — endpoints used

```
# Town of Blacksburg (all reachable)
https://services1.arcgis.com/rAuQoDGA22NtJdmg/arcgis/rest/services?f=json
  .../Address_Road_Building/FeatureServer/{0,1,2}
  .../Administrative_Reference_Boundaries/FeatureServer/4      (Town Corporate Limits)
  .../Paths_to_the_Future/FeatureServer/{0,1}
  .../Zoning_and_Landuse/FeatureServer/9                       (Town Zoning)
  .../Comprehensive_Plan/FeatureServer/{7,8}                   (Future / Current Land Use)
  .../Parks_and_Open_Space/FeatureServer/{0,1}
  .../Brush_Mountain_Trails/FeatureServer/0

# Montgomery County (metadata only — feature host blocked)
https://data-montva-gis.opendata.arcgis.com/api/feed/dcat-us/1.1.json
https://data-montva-gis.opendata.arcgis.com/api/v3/datasets/53573a7164a6443ab934a916cb041dc2_0
  → real service (BLOCKED): https://services5.arcgis.com/IZ8QFYP84iubFqmi/arcgis/rest/services/Parcels_Open_Data/FeatureServer/0

# VGIN (metadata only — feature host blocked)
https://vgin.vdem.virginia.gov/api/feed/dcat-us/1.1.json
https://vgin.vdem.virginia.gov/api/v3/datasets/cd9bed71346d4476a0a08d3685cb36ae   (RCL)
https://vgin.vdem.virginia.gov/api/v3/datasets/8105f26377d2495f8eb8aeed0794fe7c   (Address Points)
  → real services (BLOCKED): https://vginmaps.vdem.virginia.gov/arcgis/rest/services/VA_Base_Layers/{VBMP_RCL,VA_Address_Points}/FeatureServer
```

Useful query patterns for the Phase 2b fetchers:

```
# full-dataset value distribution without downloading features
.../FeatureServer/1/query?where=1%3D1&f=json
  &groupByFieldsForStatistics=RD_MAINT,ROAD_CLASS
  &outStatistics=[{"statisticType":"count","onStatisticField":"OBJECTID","outStatisticFieldName":"n"}]

# paged attribute pull (maxRecordCount 8000 on Address)
.../FeatureServer/0/query?where=1%3D1&outFields=*&returnGeometry=false
  &resultRecordCount=8000&resultOffset=N&orderByFields=OBJECTID&f=json

# boundary-clip test — POST, the polygon is too long for a GET URL
POST .../FeatureServer/1/query   geometry=<rings>&geometryType=esriGeometryPolygon
  &inSR=4326&spatialRel=esriSpatialRelIntersects&returnCountOnly=true&f=json
```
