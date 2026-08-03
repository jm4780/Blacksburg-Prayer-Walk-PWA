# Virginia Tech Campus Coverage Report

**Date:** 2026-08-03
**Bears on:** decision D1 (campus included), D1a (campus core polygon), D1b (campus
pedestrian ways REQUIRED), D1c (residence-hall capacity table)
**Data:** `pipeline/out/2026-08-03/review/vt-campus-coverage.json` ·
`pipeline/build/campus_report.py`

---

## 0. The headline, revised

Phase 2a's schema inspection concluded that campus was missing from the town's data
and that D1 therefore had no road source. That is still true for **street
centerlines**. But the canonical network build turned up something the earlier probe
missed:

> **Paths to the Future carries campus street *names* on its sidewalk features.**
> Drillfield Drive, Perry Street, Beamer Way, West Campus Drive, Duck Pond Drive,
> Stanger Street and Oak Lane all appear — as **pedestrian geometry running alongside
> the streets that are absent from Roads.**

For a prayer-walk application, that is most of what we needed. Nobody walks the
centerline of Drillfield Drive; they walk the path beside it. **16.7 miles of campus
pedestrian infrastructure is already in the canonical network**, correctly positioned,
with type and surface attributes.

What remains genuinely missing is narrower than it looked: **residence-hall locations
and capacities (D1c)**, and a human ruling on which of the 16.7 miles is `REQUIRED`
versus connector (D1b).

---

## 1. Source-priority evaluation — as instructed

| Rank | Source | Status | Why |
|---|---|---|---|
| **1** | **VGIN Virginia Road Centerlines (RCL)** | 🔴 **NOT EVALUATED** | Host `vginmaps.vdem.virginia.gov` denied by the build environment's egress policy — 403 at the gateway on every attempt, re-tested 2026-08-03 after authorization was granted in conversation. The Hub site `vgin.vdem.virginia.gov` *is* reachable, but publishes RCL only as a 112 MB File Geodatabase served from the blocked host. **No schema, no geometry, no field list.** Nothing about RCL's campus coverage is asserted anywhere in this document. |
| **2** | **Virginia Tech public GIS / campus map / building data** | 🔴 **NOT EVALUATED** | `gis.vt.edu` and `www.vt.edu` both denied by the egress policy. VT's ArcGIS organisation was never reached. |
| **3** | **OpenStreetMap** | 🔴 **NOT EVALUATED** | `overpass-api.de` denied by the egress policy. Independently, OSM would require the ODbL analysis in audit §2.4 before any geometry entered the canonical network — it stays a documented comparison option, not a merge candidate. |
| **4** | **Manual digitisation** | 🟡 **RECOMMENDED FALLBACK** | Only for what remains after 1–3 are evaluated. Given §0, the residual scope is small. |

**This is the single largest gap in Phase 2a**, and it is an environment problem, not a
data problem. The authorization granted in conversation did not change the sandbox's
network policy — that is configured on the environment itself. See §6.

---

## 2. Campus core polygon (D1a)

| | |
|---|---|
| Source | Town Zoning, `Labels = 'UNIV'` — a **single polygon** |
| Area | **1.384 sq mi** (7.0% of the town's 19.82 sq mi) |
| Status | **DRAFT** — usable starting point, not a curated boundary |

D1 estimated campus at 4.1 sq mi / ~20% of the town. That figure is VT's *total*
holdings; most of it (Kentland Farm, the airport, agricultural research land) lies
outside the corporate limits or is zoned `RR-1`. The in-town university footprint is
**1.38 sq mi** by zoning, **1.68 sq mi** by Current Land Use.

**Consequence for D1:** the denominator effect that D1a worried about is roughly a
third of what was assumed. Blanket campus inclusion is a much cheaper decision than the
decision doc reasoned about.

The polygon has not been reviewed feature by feature. It should be, but it is close
enough to build on today.

---

## 3. What the town's Roads layer has inside the campus polygon

**30 features, 3.76 miles** — and almost none of it is campus:

| Road | Miles | What it actually is |
|---|---:|---|
| WB 460 BYPASS | 1.508 | Highway clipping the polygon |
| PRICES FORK RD | 1.413 | Town arterial on the campus edge |
| WB 460 BYPASS RAMP | 0.433 | Highway ramp |
| KENT ST | 0.093 | Town street |
| COLLEGE AVE | 0.093 | Town street |
| TURNER ST NW | 0.091 | Town street |
| N MAIN ST | 0.078 | Town street |
| **ALUMNI MALL** | **0.011** | **campus — stub only** |
| MCBRYDE LN | 0.008 | stub |
| UNIVERSITY CITY BLVD | 0.008 | stub |
| TOMS CREEK RD | 0.007 | stub |
| WOODLAND DR | 0.007 | stub |
| **STANGER ST** | **0.006** | **campus — stub only** |
| **W CAMPUS DR** | **0.004** | **campus — stub only** |

The three genuine campus entries total **0.021 miles**. The town's file stops at the
campus line.

### Name probes across all 1,547 road features

**ABSENT entirely:** Drillfield · Duck Pond · Perry · Old Turner · Beamer · Tech Center
· Stadium · Coliseum · Oak Lane · West Campus

**STUB ONLY (<100 m):** W Campus Dr (0.005 mi) · Alumni Mall (0.011 mi) · Stanger St
(0.006 mi)

**PRESENT (these are town streets that touch campus, not campus streets):** Burruss Dr
0.214 mi · McBryde Dr/Ln 0.739 · Washington St 0.813 · Southgate Dr 0.386 · Kent St
1.010 · Turner St 1.153 · Prices Fork Rd 6.024

---

## 4. What *is* present: campus pedestrian infrastructure

**97 features, 16.72 miles** inside the campus polygon, from Paths to the Future.

| Type | Features | Miles |
|---|---:|---:|
| Sidewalk | 60 | 9.152 |
| Trail | 28 | 5.076 |
| Bike Lane | 7 | 2.098 |
| Share the Road | 1 | 0.365 |
| Trail Tunnel | 1 | 0.026 |

| Owner | Features | Miles |
|---|---:|---:|
| `VT` | 79 | 14.018 |
| *(blank)* | 18 | 2.699 |

### Named campus walkable features — the recoverable street alignments

These are pedestrian features whose `Road` name is a campus street that does **not**
exist in the Roads layer. This is the alignment we were told we had no source for:

| Feature name | Miles | Street centerline in Roads? |
|---|---:|---|
| Prices Fork Road | 1.216 | yes (town arterial) |
| **West Campus Drive** | **1.146** | ❌ absent |
| **Stanger Street** | **0.927** | stub only |
| **Oak Lane Trail** | **0.770** | ❌ absent |
| Prices Fork Road Trail | 0.660 | — |
| Turner Street | 0.646 | yes |
| **Perry Street** | **0.607** | ❌ absent |
| **Drillfield Drive** | **0.586** | ❌ absent |
| Smithfield Road Trail | 0.480 | — |
| West Campus Drive Trail | 0.477 | — |
| Duck Pond Trail | 0.393 | — |
| Duck Pond Drive Trail | 0.388 | — |
| **Beamer Way** | **0.357** | ❌ absent |
| Southgate Drive | 0.228 | yes |
| Washington Street | 0.202 | yes |
| Life Science Circle | 0.153 | ❌ absent |
| **Duck Pond Drive** | **0.098** | ❌ absent |
| Kent Street | 0.088 | yes |

---

## 5. The three lists the instruction asked for

### 5a. Missing from Town of Blacksburg street data

Campus streets with no usable centerline in Roads:

Drillfield Drive · Duck Pond Drive · Perry Street · Old Turner Street · Beamer Way ·
Tech Center Drive · Oak Lane · West Campus Drive · Life Science Circle · stadium and
coliseum drives · Alumni Mall (stub only) · Stanger Street (stub only) · W Campus Drive
(stub only)

### 5b. Present in an authoritative alternative source

**Paths to the Future** (Town of Blacksburg — authoritative, already in the build)
covers the walkable alignment of most of 5a:

| Campus street | Pedestrian coverage | Miles | In canonical network |
|---|---|---:|---|
| West Campus Drive | sidewalk + trail | 1.623 | ✅ `OPTIONAL_CONNECTOR`, NEEDS_REVIEW |
| Stanger Street | sidewalk | 0.927 | ✅ same |
| Oak Lane | Oak Lane Trail | 0.770 | ✅ same |
| Perry Street | sidewalk | 0.607 | ✅ same |
| Drillfield Drive | sidewalk | 0.586 | ✅ same |
| Duck Pond Drive | sidewalk + 2 trails | 0.879 | ✅ same |
| Beamer Way | sidewalk | 0.357 | ✅ same |
| Life Science Circle | sidewalk | 0.153 | ✅ same |

In the canonical network today, campus contributes **114 segments / 13.40 miles**:
75 `PEDESTRIAN_CONNECTOR` (8.32 mi) and 39 `TRAIL` (5.08 mi), all
`OPTIONAL_CONNECTOR` with `role_status = NEEDS_REVIEW`.

*(13.40 mi in the network vs 16.72 mi in the source: the difference is on-street bike
lanes and sidewalks absorbed into parallel town streets, per technical plan §2.3.5.)*

### 5c. Still missing, likely to require manual curation

| Item | Why it can't be sourced from what we have | Recommended action |
|---|---|---|
| **VT residence halls — locations** | Zero dorm footprints in the town Building layer (searching all 10,156 for `%HALL%` returns *Town Hall Annex* and *St Lukes & Oddfellows Hall*). | Evaluate VT GIS first; digitise ~47 footprints from the public campus map if unavailable. |
| **VT residence halls — capacities (D1c)** | Not GIS data at all; comes from VT Housing publications. | Manual table regardless of source availability. |
| **Interior quad footpaths** | Paths to the Future follows named streets; the pedestrian mesh between residence halls may be under-represented. Cannot be confirmed without a second source. | Compare against VT GIS / OSM once reachable. |
| **Campus street centerlines proper** | Absent. | **Probably not needed.** See §7. |
| **Campus service drives / lot connections** | Absent, and D1 wants them `EXCLUDED` anyway. | No action. |

---

## 6. Blocker: the network policy did not change

Every host needed for source-priority ranks 1–3 is still denied:

```
services5.arcgis.com          403  Montgomery County feature services
vginmaps.vdem.virginia.gov    403  VGIN RCL + Address Points  ← rank 1
hub.arcgis.com                403  ArcGIS Hub downloads
www.arcgis.com                403  AGOL item / sharing REST
maps.montva.com               403  Montgomery County ArcGIS Server
gis.vt.edu                    403  Virginia Tech GIS          ← rank 2
www.vt.edu                    403  Virginia Tech
overpass-api.de               403  OpenStreetMap Overpass     ← rank 3
```

Reported by the egress gateway as *"gateway answered 403 to CONNECT (policy denial)"*.
Authorization given in conversation does not reach the gateway — **the environment's
network policy is set on the environment itself**, in the Claude Code environment
settings, and has to be widened there (or the pipeline run somewhere with open egress).

Until then, ranks 1–3 stay `NOT_EVALUATED` and nothing in this document claims
otherwise.

---

## 7. Recommendation

**Do not digitise campus street centerlines yet, and do not treat the campus gap as
blocking Phase 2b.**

The reasoning: D1b already says campus pedestrian ways should be `REQUIRED` because *on
campus the footpath network is the network*. We have 13.4 miles of that footpath
network, correctly aligned, from an authoritative town source. Adding campus street
centerlines would mostly duplicate geometry we already have — and per technical plan
§2.3.5, parallel sidewalk and street are supposed to collapse into one walkable edge,
not two.

Ordered next steps:

1. **Widen the network policy** (§6), then evaluate VGIN RCL and VT GIS properly. This
   is cheap and it settles rank 1 and 2 definitively.
2. **D1b ruling** — a human promotes campus paths from `OPTIONAL_CONNECTOR` to
   `REQUIRED`. 114 segments, listed with names and mileages in
   `review/vt-campus-coverage.json`. This is the decision that actually unblocks campus
   coverage, and it needs no new data.
3. **D1c residence halls** — the real remaining gap. ~47 halls, ~4,700–5,300 units.
   Try VT GIS; fall back to digitising footprints from the public campus map and
   joining published bed counts.
4. **Campus street centerlines** — only if step 2 reveals walkable campus roads with no
   parallel path. Judge that after the D1b review, not before.

---

## 8. Effect on D1's stated numbers

| D1 claim | Measured | Note |
|---|---|---|
| Campus ≈ 4.1 sq mi, ~20% of town | **1.38 sq mi, 7.0%** | D1's figure is VT's total holdings, not the in-town footprint |
| Campus ≈ 26% of total households | **not yet measurable** | D1c unmodelled; residential campus units are 0 in this build |
| Campus paths REQUIRED (D1b) | **13.40 mi available, 0 promoted** | awaiting the ruling in §7.2 |
| Campus streets REQUIRED | **0.02 mi exists in town data** | see §7 — probably moot |
