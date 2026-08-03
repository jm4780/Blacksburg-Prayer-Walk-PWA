# Household Estimation Methodology

**Date:** 2026-08-03
**Implements:** spec §6.3, §20 · audit §3 · technical plan §2.5
**Code:** `pipeline/build/households.py`

> ⚠️ **Superseded in part by [`09-phase-2a1-freeze.md`](09-phase-2a1-freeze.md) §5.**
> Two things changed in Phase 2a.1: the occupancy model was **removed** (the public
> number is now a transparent count of residential units on REQUIRED coverage, not an
> occupancy-adjusted estimate), and the apartment-complex rule was **recalibrated** so
> holding is per-unit wherever a site is genuinely walked. The figures below —
> 9,044 occupied households, 7,710 units held, ~16,700 after resolution — are the
> pre-recalibration values. Current: **11,029 on required coverage, 6,279 held.**
> The deduplication rules, association rule and confidence discussion below still
> stand.

The public interface says **"Estimated households prayed for."** This document is the
full chain from an address point in the town's GIS to that number, and the places
where the chain is weak.

---

## 1. Three quantities, never conflated

The Phase 1 plan compared a single "household count" against the Census figure for
*occupied households*, which is the wrong benchmark for what the address layer
actually contains. Internally we now track three distinct things:

| Internal name | 2026-08-03 value | What it is |
|---|---:|---|
| `residential_address_points` | **18,022** | Address points where `LocalType = 'Residential'`. Raw. |
| `estimated_housing_units` | **17,963** | Dwelling units after removing non-dwellings and duplicate address keys. **This is what gets compared to census housing units.** |
| `estimated_occupied_households` | **9,044** | Housing units *that a walker on the eligible network would actually pass*, times the occupancy rate. **This is the public number.** |

The gap between 17,963 and 9,044 is not error — it is 8,238 units deliberately held
back (§5). It will close as complexes are reviewed.

### Validation benchmark — corrected

The gate now compares `estimated_housing_units` against **housing units**, not
occupied households:

```
[PASS] housing_units_plausible: 17,963 estimated housing units
       (plausible band 12,000–24,000; compared against housing units,
        not the ~13,800 occupied-household figure)
```

The old gate would have failed a correct pipeline: 17,963 units against ~13,800
occupied households is a +30% gap that is mostly *right*, because the town's address
layer is unit-level and because occupied households exclude vacant units by
definition.

---

## 2. The chain, step by step

```
19,773 address points  (town Address layer, unit-level)
  ├─ 1,751 non-residential            LocalType ≠ Residential
  ↓
18,022 residential address points
  ├─ 59 not a dwelling                LandmkName contains vacant/demolished/construction
  ├─ 0 duplicate address keys         composite key was unique across all rows
  ↓
17,963 ESTIMATED HOUSING UNITS        9,854 unit-level · 8,109 building-level · 9,002 distinct buildings
  ├─ 7,710 held in unresolved complexes   §5
  ├─   528 beyond the 75 m association cap
  ↓
 9,725 units associated to an eligible segment
  × 0.93 occupancy rate
  ↓
 9,044 ESTIMATED OCCUPIED HOUSEHOLDS  → "Estimated households prayed for"
```

### The occupancy rate is the weakest link

`OCCUPANCY_RATE = 0.93`, `confidence = LOW`. It is currently a **placeholder** and is
flagged as such in code and in the build report. Before launch it must be replaced
with the current ACS 5-year occupancy rate for Blacksburg town, and the source
recorded. A 5-point error here moves the headline number by ~450 households.

---

## 3. Double-counting: five defences

Each is enforced in code, not by convention.

| Risk | Defence | Where |
|---|---|---|
| **Apartment units** counted twice — once as a unit, once as the parent building | Each address point is exactly one dwelling unit. Building-level and unit-level points are distinct rows in the source; a building address that has unit children is itself a separate point only where the source says so. Unit and building keys are computed separately and the unit key is what identifies a household. | `address_key` / `building_key` |
| **Duplicate address representations** | Households are keyed on a normalized composite (`number + pre-dir + street + type + post-dir + unit-designator + unit`). Collisions are dropped and logged. Verified unique across all 17,963. | `build_households` |
| **Corner properties** attaching to two streets | A household has exactly **one** `primary_segment_id`. Up to three `secondary_segment_ids` are recorded for admin inspection and are never counted. | `associate` |
| **Buildings linked to multiple road segments** | Association is one-to-one *from the household side*, so a building fronting two streets contributes to one segment only. | `associate` |
| **Repeated route segments** | Route and town-wide totals sum **distinct household keys**, not per-segment counts. Walking a segment twice, or two segments that share a household, cannot inflate the number. | `per_segment` uses a `set`; validation gate `one_primary_segment_per_household` |

Validation confirms it: `9,725 links, 9,725 distinct households`.

---

## 4. Association rule

Nearest eligible segment within **75 m**, tie-broken by street-name match.

- Name match is worth a **12 m equivalent bonus** — enough to win a corner lot, not
  enough to drag a household across a block to a same-named street.
- Confidence: `HIGH` (name match and ≤40 m) 6,697 · `MEDIUM` 1,787 · `LOW` 1,241.
- Eligible = `REQUIRED` or `OPTIONAL_CONNECTOR`, and walkable. `EXCLUDED` segments
  never receive households — a private drive cannot be someone's prayer-walk frontage.

Distance to the nearest eligible segment, across all 17,963 units:

| within | units | share |
|---|---:|---:|
| 25 m | 5,718 | 31.8% |
| 50 m | 12,107 | 67.4% |
| **75 m (the cap)** | **14,149** | **78.8%** |
| 100 m | 15,682 | 87.3% |
| 150 m | 17,106 | 95.2% |
| 300 m | 17,903 | 99.7% |

Median 32.8 m, p90 113.5 m, max 803 m. The tail is real, not an artefact — it is
apartment complexes whose internal circulation no town layer models.

---

## 5. Complexes held for review

**The rule that matters: units in a large complex are never bulk-assigned to the
complex's nearest public entrance segment.** Doing so would claim a walker who passed
the entrance had prayed for 1,700 homes they never saw.

A complex (≥25 units sharing a `PlaceName`) is marked `UNRESOLVED` when either:

- **no internal walkable network** — under 25 m of eligible segment inside the site
  footprint; or
- **poor reach** — more than 25% of its units sit beyond the 75 m cap from anything
  eligible.

Deliberately *not* a metres-of-road-per-unit density test: dense complexes legitimately
have very little road per unit, and that is not evidence of anything. An earlier
version used density and over-flagged badly.

Plus an override: complexes a human named for review are reviewed **regardless of what
the heuristic says**. `The Mill`, `Hunters Ridge`, and `Terrace View` are on that list.

### Result: 58 of 103 complexes unresolved, 7,710 units held

| Trigger | Complexes |
|---|---:|
| `AUTOMATIC` — failed one or both tests | 55 |
| `INSTRUCTION_AND_AUTOMATIC` — named *and* failed | 1 (The Mill at Blacksburg) |
| `INSTRUCTION_ONLY` — named, heuristic cleared it | 2 (Terrace View, Hunters Ridge) |

The two `INSTRUCTION_ONLY` cases are worth noting honestly: Terrace View shows 2,194 m
of internal network and 13% of units beyond cap; Hunters Ridge shows 149 m and 3%.
Both look fine to the automatic test. They are held anyway because a human named them,
and because the "internal network" figure for a sprawling site is partly an artefact
of the convex-hull footprint swallowing adjacent public streets. **A reviewer should
look at these two specifically to decide whether the heuristic or the instinct was
right** — it calibrates the test for everything else.

### Recommended disposition per complex

Every unresolved complex carries one of the four dispositions, with an interim of
`EXCLUDE_FROM_ESTIMATE` in all cases:

| Recommendation | Complexes | Applies when |
|---|---:|---|
| `ADD_AUTHORITATIVE_PEDESTRIAN_NETWORK` | 23 | ≥100 units. Source or digitise the internal walkways before counting these units. |
| `ASSOCIATE_WITH_FRONTAGE_STREETS` | 5 | Site spans more than the cap but is moderate. Assign buildings to the street they actually face, by hand. |
| `TREAT_AS_UNRESOLVED` | 30 | Small footprint; likely resolvable by raising the cap after review. |

The ten largest:

| Complex | Units | Trigger | Recommendation |
|---|---:|---|---|
| Foxridge Apartments | 1,719 | AUTOMATIC | ADD_AUTHORITATIVE_PEDESTRIAN_NETWORK |
| Terrace View Apartments | 558 | INSTRUCTION_ONLY | ADD_AUTHORITATIVE_PEDESTRIAN_NETWORK |
| The Union | 440 | AUTOMATIC | ADD_AUTHORITATIVE_PEDESTRIAN_NETWORK |
| Maple Ridge Townhomes | 314 | AUTOMATIC | ADD_AUTHORITATIVE_PEDESTRIAN_NETWORK |
| Windsor Hills | 300 | AUTOMATIC | ADD_AUTHORITATIVE_PEDESTRIAN_NETWORK |
| Smith's Landing Apartments | 284 | AUTOMATIC | ADD_AUTHORITATIVE_PEDESTRIAN_NETWORK |
| Collegiate Suites | 210 | AUTOMATIC | ADD_AUTHORITATIVE_PEDESTRIAN_NETWORK |
| The Vue at CRC | 206 | AUTOMATIC | ADD_AUTHORITATIVE_PEDESTRIAN_NETWORK |
| Pheasant Run Townhomes | 165 | AUTOMATIC | ADD_AUTHORITATIVE_PEDESTRIAN_NETWORK |
| The Mill at Blacksburg | 162 | INSTRUCTION_AND_AUTOMATIC | ADD_AUTHORITATIVE_PEDESTRIAN_NETWORK |

Full list with per-complex numbers and reasons:
`pipeline/out/<date>/review/apartment-complexes.json`.

---

## 6. Confidence limits on the public number

**9,044 is a floor, not an estimate of the truth.** Three separate reasons it is low,
and one reason it could be high:

| Direction | Cause | Magnitude |
|---|---|---|
| ↓ **Understates** | 7,710 units held in unresolved complexes | Up to +7,170 households if all resolve |
| ↓ **Understates** | 528 units beyond the association cap | Up to +490 |
| ↓ **Understates** | VT residence halls entirely absent from town data (D1c) | ~4,700–5,300 units, not yet modelled |
| ↑ **Overstates** | Occupancy rate is a placeholder | ±450 for a 5-point error |

If every complex resolved and the cap issue were fixed, the residential figure would
land near **16,700 occupied households** — which sits sensibly above the ~13,800
Census-2020 occupied-household count for a town that has built steadily since 2020 and
whose address layer counts apartment units individually.

**Recommended presentation until the complexes are reviewed:** show the number, and
show that it is provisional. Do not present 9,044 as "Blacksburg has 9,044 households."
It is "9,044 households currently associated to walkable segments," and the build
report carries the held count alongside it so the two are never separated.

---

## 7. What is not yet modelled

- **`STUDENT_RESIDENCE` (D1c)** — not implemented. The town's Building layer contains
  zero VT residence halls, so there is nothing to seed the ~47-row capacity table
  from. See `07-vt-campus-coverage.md`.
- **Group quarters other than dorms** — care facilities are excluded from
  `RESIDENTIAL` via `LocalType` and are not separately modelled. Correct for V1.
- **Mobile home parks** — `Meadowbrook Mobile Home Park` (98 units) is in the
  unresolved list; lot-level address points exist (`LOT` designator, 249 town-wide) but
  internal circulation is not in Roads.
