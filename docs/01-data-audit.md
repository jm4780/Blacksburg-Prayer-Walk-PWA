# Phase 1 — Geographic Data Audit

**Project:** Blacksburg Prayer Walk PWA
**Date:** 2026-08-02
**Status:** Complete (desk audit). Items marked ⚠️ *verify on download* need hands-on
confirmation when the datasets are pulled at the start of Phase 2 — the audit was
performed from documentation and catalog listings, and some portals (ArcGIS Hub)
were not directly reachable from the environment used for this audit.

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
| 4 | Public/private road status | Town Roads attributes (⚠️ verify) + **manual curation** | Montgomery County parcels; OSM `access=` tags; local knowledge |
| 5 | Major trails | Town of Blacksburg **Paths to the Future** dataset | OSM; town Parks & Rec pages |
| 6 | Pedestrian connections | Paths to the Future (sidewalks, connectors) | OSM footways |
| 7 | Crosswalk / crossing feasibility | OSM crossing nodes + manual flags | Deferred to curation (no authoritative dataset) |
| 8 | Residential address points | Town of Blacksburg **Address Points** (911 authority) | VGIN Virginia Address Points (public domain) |
| 9 | Parcel data | Montgomery County, VA GIS Open Data (**Parcels**, monthly) | — |
| 10 | Building footprints | Town of Blacksburg Building Footprints | VGIN statewide Building Footprints (quarterly) |
| 11 | Estimated housing units | Census 2020 DHC block-level housing counts + ACS 5-year | Used to calibrate, not as the primary layer |
| 12 | Street names | Town Roads dataset (911 naming authority) | VGIN RCL |
| 13 | Speed / road class (walking comfort) | VDOT functional classification via VGIN RCL | OSM `maxspeed`, `highway`, `lanes` |

**Headline conclusion:** Blacksburg is unusually well-served. The Town is its own
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
- **Known datasets relevant to us:**
  - **Roads** (road centerlines) — the town maintains these as the 911 addressing
    authority, used for call routing and emergency response. This is our primary
    street network.
  - **Address Points** — 911 address assignments. Primary household layer.
  - **Building Footprints** — supporting household estimation.
  - **Corporate limits / town boundary** — ⚠️ verify exact dataset name on the hub.
  - **Paths to the Future** — "all known and mapped multimodal trails, sidewalks,
    bike lanes, and other non-vehicular transportation infrastructure in Blacksburg."
    FeatureServer: `https://services1.arcgis.com/rAuQoDGA22NtJdmg/arcgis/rest/services/Paths_to_the_Future/FeatureServer`
  - Zoning / land use — useful secondary signal for residential vs. commercial
    segment context.
- **Format:** ArcGIS Hub standard exports (GeoJSON, Shapefile, CSV, KML) plus live
  FeatureServer query API (`f=geojson`).
- **License:** The town states public GIS data is "shared for free use and download."
  ⚠️ *Verify the exact license text per dataset on download.* ArcGIS Hub datasets
  typically carry an explicit license field; if none is stated, contact the town GIS
  office (Engineering & GIS department) for written confirmation before public
  redistribution. Storing and serving derived data inside our app is low-risk; we
  will record the license string per dataset in the import pipeline.
- **Update cadence:** Maintained continuously for 911 purposes; export freshness
  ⚠️ verify per dataset (`last updated` on hub pages).
- **Known gaps / caveats:**
  - Attribute schema (ownership, public/private flag, functional class) is not
    documented in the catalog listings — ⚠️ inspect fields on download. Because the
    layer exists for 911 dispatch, it almost certainly *includes* private streets,
    apartment-complex drives, and campus roads (ambulances go there), so **presence
    in the Roads layer must not be treated as "public street."** Expect a
    road-class or ownership attribute; if absent or unreliable, public/private
    becomes a curation task (see §5).
  - Roads layer likely extends to/past the town boundary; boundary intersection
    handling is a pipeline task, not a data gap.

### 2.2 VGIN (Virginia Geographic Information Network) statewide layers

- **Portal:** https://vgin.vdem.virginia.gov/ (Virginia GIS Clearinghouse downloads:
  https://vgin.vdem.virginia.gov/pages/cl-data-download)
- **Virginia Road Centerlines (RCL):** statewide, built to a Commonwealth data
  standard (OTH 703-00) which specifies naming, geometry, and attribute
  conventions. Useful attributes per the standard: route names, address ranges,
  and road classification fields. Good cross-check and a fallback if town data
  attributes disappoint. https://vgin.vdem.virginia.gov/datasets/VGIN::virginia-road-centerlines-rcl
- **Virginia Address Points:** statewide aggregation of local 911 address points.
  **Geometry and attributes are public domain as of January 1, 2012** — the
  cleanest license in the whole audit. The state standard includes unit-level
  addressing, which matters for apartment complexes. https://vgin.vdem.virginia.gov/datasets/8105f26377d2495f8eb8aeed0794fe7c
- **Virginia Building Footprints:** statewide aggregation of locally submitted
  footprints, **updated quarterly**; carries no addressing/ownership/resident
  attributes. https://vgin.vdem.virginia.gov/datasets/virginia-building-footprints/about
- **License:** Address points are public domain; other Clearinghouse layers are
  distributed with "as is" disclaimers rather than formal open licenses —
  effectively open for use, ⚠️ record the exact disclaimer text on download.
- **Role for us:** cross-check + fallback; the town layers should be fresher and
  are locally authoritative.

### 2.3 Montgomery County, VA GIS Open Data

- **Portal:** https://data-montva-gis.opendata.arcgis.com/ (county GIS dept:
  https://montva.com/1/departments-services/GIS)
- **Parcels:** public parcels dataset, **updated monthly**, includes building
  footprints and subdivisions. Parcel ownership + land-use codes are our best
  signal for (a) residential vs. non-residential classification of address
  points, (b) private-road detection (roads crossing a single private parcel with
  no public right-of-way), and (c) HOA/common-area identification.
- **License:** ArcGIS open data terms — ⚠️ verify per dataset. County data is
  standard public-record GIS; storage and internal derivation are low-risk.
- **Role for us:** household estimation support and private-road curation evidence.
  Not a network source.

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
- **Critical caveat:** Blacksburg is a university town. Virginia Tech dormitories
  are **group quarters**, not households — census household counts already exclude
  them, but address-point and building-footprint layers include dorms. Household
  estimation must exclude group-quarters buildings or the "households prayed for"
  metric will be inflated on and near campus.
- **Role for us:** calibration target ("do our deduplicated address-point-derived
  household counts, summed town-wide, land near ~13.8k?") and a distribution
  fallback where unit-level address data is weak.

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

- **No authoritative government dataset identified.** Paths to the Future may
  include crossing features (⚠️ verify); OSM has crossing nodes of uneven
  completeness.
- **Decision:** do not model crossings as first-class data in V1. Instead: (a) a
  soft penalty for routes crossing high-stress arterials mid-block, derived from
  road class; (b) an admin curation flag `unsafe_crossing` on specific nodes/edges
  as issues are discovered during the pilot (§33 of the spec already requires this
  admin capability).

---

## 3. Household estimation approach (selected)

Per spec §6.3's preference order, we can start at **option 1 — residential address
points** — the best case:

1. **Base layer:** Town of Blacksburg Address Points (fallback: VGIN statewide,
   public domain). Each point gets a stable internal household-estimate ID keyed to
   the source's address key (⚠️ verify a stable key field exists; else derive one
   from normalized full address).
2. **Residential filter:** classify points as residential using Montgomery County
   parcel land-use codes (spatial join point→parcel), assisted by town zoning and
   building footprints. Exclude commercial, institutional, and **group-quarters
   (VT dorms, Greek housing, care facilities)** — maintain an explicit exclusion
   list for the campus area.
3. **Multi-unit handling:** if address points are unit-level (the state 911
   standard supports it — ⚠️ verify locally), count points. Where a single point
   represents a multi-unit building, use `estimated_units` from parcel data or
   census block calibration; record `confidence` accordingly.
4. **Segment association:** associate each household point with its nearest
   REQUIRED network segment (perpendicular distance, capped ~75 m, with tie-break
   on the segment matching the point's street name — address points carry the
   street name, which makes corner-lot assignment much more reliable than pure
   geometry). Store as `SegmentHousehold` rows with `relationship_type` and
   `confidence`; households are deduplicated town-wide by household ID, satisfying
   §20.
5. **Calibration:** compare town-wide totals against Census 2020 (~13.8k
   households) and document the delta and chosen adjustment in the pipeline output.

All public displays say "estimated," per spec.

---

## 4. Licensing summary

| Source | License | Store? | Redistribute derived data? |
|--------|---------|--------|---------------------------|
| Town of Blacksburg open data | "Free use and download" — ⚠️ capture exact per-dataset text | Yes | Expected yes; confirm in writing if we ever publish raw extracts |
| VGIN Address Points | **Public domain** (since 2012-01-01) | Yes | Yes |
| VGIN RCL / Building Footprints | Open access, "as is" disclaimer | Yes | Yes, with source note |
| Montgomery County parcels | County open data terms — ⚠️ verify | Yes | Internal derivation yes; avoid republishing owner names (we don't need them — drop PII fields at import) |
| OpenStreetMap | ODbL 1.0 | Only in isolated layers | Attribution required; share-alike if derived — avoided by design (§2.4) |
| Census / TIGER | Public domain | Yes | Yes |

Two standing rules for the import pipeline:

1. Record `{source, source_url, license_text, retrieved_at, source_updated_at}` for
   every imported dataset (the spec's `stable_source_metadata` / `HouseholdEstimate.source`
   fields).
2. Drop fields we don't need at import time — especially parcel owner names and any
   other PII. We need geometry, land use, and unit counts, not people's names.

---

## 5. Known gaps and required manual curation

These are the places where data alone won't be good enough, in expected order of
effort:

1. **Public/private street classification** — the single biggest curation task.
   Blacksburg has a large stock of apartment complexes and townhome communities
   (student housing) with internal drives that will appear in the 911 Roads layer.
   Strategy: seed classification from town road-class attributes → flag suspects
   (segments inside a single parcel, name patterns like "Dr/Ln" inside apartment
   parcels, dead-end stubs into commercial parcels) → human review pass over a map
   (Jacob + local knowledge) before launch. Spec §4.3 roles (`REQUIRED` /
   `OPTIONAL_CONNECTOR` / `EXCLUDED`) are assigned here.
2. **Virginia Tech campus** — a policy decision, not just a data one. Campus roads
   and paths are state (VT) property inside town limits; dorms are group quarters.
   **Recommendation:** mark campus internal roads/paths `OPTIONAL_CONNECTOR`
   (walkable, never required, never counted), and exclude campus buildings from
   household estimates. Flagged as an open decision in the technical plan.
3. **Trail curation** — per spec §17, hand-pick which Paths-to-the-Future features
   count as REQUIRED trails (Huckleberry Trail inside town limits is the obvious
   anchor) vs. connector-only sidewalk/path geometry. Sidewalks parallel to streets
   must be *collapsed into* the street segment, not modeled as separate required
   coverage (spec §4.2: either sidewalk counts).
4. **Boundary edge cases** — segments straddling the town line need splitting at
   the boundary with the outside portion marked `OUT_OF_AREA_CONNECTOR`.
5. **Group-quarters exclusion list** — enumerate VT dorms/Greek houses from
   footprints + campus map; exclude from household counts.
6. **Unsafe crossings / unpleasant arterials** — seeded from road class, refined
   from pilot feedback via admin flags.
7. **Missing pedestrian connectors** — cul-de-sac cut-throughs and neighborhood
   paths that make loops possible; Paths to the Future should cover most, OSM
   cross-check + pilot feedback covers the rest. Admin tool must support adding
   connector edges (spec §33).

---

## 6. Data-acquisition notes for Phase 2

- All ArcGIS Hub sources support scripted pulls from their FeatureServer endpoints
  (`.../FeatureServer/<layer>/query?where=1%3D1&outFields=*&f=geojson`, paged).
  The import pipeline should pull from the REST API (reproducible, cadenced)
  rather than one-off manual exports, but keep the raw pulled GeoJSON committed or
  archived so every network build is reproducible from a frozen snapshot.
- **Environment note:** the remote sandbox used for this audit has a network
  policy that blocks `*.arcgis.com`; the actual downloads in Phase 2 must run
  either locally or in an environment with those domains allowed. This is a
  session-configuration fix (allow `services1.arcgis.com`,
  `data-montva-gis.opendata.arcgis.com`, `vgin.vdem.virginia.gov`), not a blocker.
- First Phase 2 task is a **schema inspection report**: pull one page of each
  dataset, dump field lists and value distributions for the ⚠️ items above, and
  update this audit with findings.

## Sources

- [Town of Blacksburg GIS Open Data hub](https://town-of-blacksburg-gis-data-blacksburg-va.hub.arcgis.com/) · [Roads dataset](https://town-of-blacksburg-gis-data-blacksburg-va.hub.arcgis.com/datasets/Blacksburg-VA::roads) · [Town GIS data page](https://www.blacksburg.gov/departments/departments-a-k/engineering-and-gis/gis-data)
- [Town of Blacksburg on the Virginia Open Data Portal](https://data.virginia.gov/organization/town-of-blacksburg-gis-data) · [Paths to the Future](https://data.virginia.gov/dataset/paths-to-the-future/resource/5dc12247-6ebc-4f57-b4a1-55283e0ecda7)
- [VGIN Clearinghouse downloads](https://vgin.vdem.virginia.gov/pages/cl-data-download) · [Virginia Road Centerlines](https://vgin.vdem.virginia.gov/datasets/VGIN::virginia-road-centerlines-rcl) · [Virginia Address Points](https://vgin.vdem.virginia.gov/datasets/8105f26377d2495f8eb8aeed0794fe7c) · [Virginia Building Footprints](https://vgin.vdem.virginia.gov/datasets/virginia-building-footprints/about) · [RCL data standard (OTH 703-00)](https://www.vita.virginia.gov/media/vitavirginiagov/it-governance/psgs/pdf/VirginiaRCLDataStandardOTH70300.pdf) · [Address point standard](https://vginmaps.vdem.virginia.gov/download/standards/VAOTH704_VirginiaAddressPointsStandardOTH704.pdf)
- [Montgomery County, VA GIS Open Data](https://data-montva-gis.opendata.arcgis.com/) · [County GIS department](https://montva.com/1/departments-services/GIS) · [Parcels Open Data](https://data-montva-gis.opendata.arcgis.com/datasets/MontVA-GIS::parcels-open-data-1/about)
- [Census QuickFacts — Blacksburg town](https://www.census.gov/quickfacts/fact/table/blacksburgtownvirginia/PST045224) · [Blacksburg, Virginia (Wikipedia)](https://en.wikipedia.org/wiki/Blacksburg,_Virginia) · [Huckleberry Trail (Wikipedia)](https://en.wikipedia.org/wiki/Huckleberry_Trail) · [Town Huckleberry Trail page](https://www.blacksburg.gov/Home/Components/FacilityDirectory/FacilityDirectory/88/566)
- [OSM Open Database License](https://wiki.openstreetmap.org/wiki/Open_Database_License) · [OSMF Collective Database Guideline](https://osmfoundation.org/wiki/License/Community_Guidelines/Collective_Database_Guideline_Guideline) · [OSMF Licence & Legal FAQ](https://osmfoundation.org/wiki/Licence/Licence_and_Legal_FAQ) · [VirginiaRoads](https://www.virginiaroads.org/)
