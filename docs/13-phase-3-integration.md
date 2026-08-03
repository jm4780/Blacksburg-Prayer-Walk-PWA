# Phase 3 — Functional PWA Integration

**Status:** complete. One end-to-end vertical slice, working on a mobile browser and
as an installed PWA.
**Canonical network:** `v1.2` / `bbg-net-v1.2-e1284e6001ff54f5` (was
`bbg-net-v1.1-3855ef9c4c15358a`)
**Routing engine:** `2.1.0` (was `2.0.0`)
**Recommendation:** **GO for a limited authenticated pilot. NO-GO for public
release** — licensing gate G1 is still unresolved.

---

## 1. Canonical network v1.2

The approved rulings are applied in the pipeline, not by hand-editing output, so a
rebuild reproduces them.

| Ruling | Where it lives | Result |
|---|---|---|
| Promote campus corridors to REQUIRED | `curation.CAMPUS_PROMOTE_CANONICAL_TO_REQUIRED`, applied in `build/run.py` after normalization | 73 segments, **11.360 mi** |
| Alternatives satisfy the obligation, no duplicates | `campus_normalize._link_alternatives` → `network.credited()` | 41 walkways, **2.044 mi** of duplicate obligation avoided |
| Deerfield + Shenandoah → REQUIRED | `curation.TRAIL_ROLES` | PROVISIONAL → **CONFIRMED** |
| `RD_MAINT` stays authoritative; conflicts preserved | `classify.classify_road` unchanged | 36 ownership conflicts still recorded and downgraded |
| Untrusted connectors stay out | `network.in_routing_graph` unchanged | 30 CROSSING_REVIEW_REQUIRED + 8 LIKELY_FALSE + 4 UNRESOLVED excluded |
| Smart Road stays EXCLUDED | `curation.ROLE_OVERRIDES_BY_NAME` | 6 segments / 1.041 mi |
| CRC crossings catalogued, not promoted | `pipeline/build/crc_review.py` → `review/crc-crossings.json` | **8 crossings**, 0 in the routing graph; CRC remains `VALID_INDEPENDENT_ROUTING_AREA` |

### Published figures

| | |
|---|---|
| Canonical network identifier | `bbg-net-v1.2-e1284e6001ff54f5` |
| Required mileage | **145.588 mi** |
| — street | 123.807 mi |
| — trail | 10.423 mi |
| — campus | 11.359 mi |
| Households associated with required coverage | **11,024** (6,284 held for review) |
| Valid routing components | **9** |
| Unresolved required mileage | **0.868 mi** across 12 review-required fragments |
| Excluded mileage | 49.320 mi |
| Routing graph | 2,490 segments / 2,273 nodes |

The three mileage buckets partition the required total exactly (123.807 + 10.423 +
11.359 = 145.589). An earlier version split on `segment_type` and double-counted the
4.471 mi of the campus obligation that the Paths layer types as `Trail`; a freeze gate
now asserts the partition.

### How "walking one side counts" was made operational

Promoting the canonical side of each campus corridor to REQUIRED creates a problem the
normalization exists to prevent: a walker who takes the north sidewalk of Drillfield
Drive would see the corridor still marked unprayed-for. So each ALTERNATIVE walkway
records the canonical segments it runs alongside **and what fraction of each it
covers**, and `Network.credited()` grants a canonical segment once the fractions of the
alternatives actually walked reach 0.6.

The first implementation credited all-or-nothing and left **28 of 41** alternatives
earning nothing at all, because canonical and alternative walkways are not split at the
same points and a 100 m walkway cannot cover 60 % of a 300 m canonical segment.
Proportional, additive credit fixed it: **41 of 41** now credit a canonical side, with
no dangling links.

### Three findings that contradict earlier documents

1. **Promoting all eight CRC crossings would *not* connect the CRC to the main
   network.** Doc 12 §4 says it would ("at which point the CRC merges into the main
   component") and lists it as the highest-value connector review available. It is
   wrong. Each of the eight links the CRC to a *small isolated fragment*, not to the
   town graph. Reviewing them is still worth doing for local CRC walkability, but
   whatever separates the CRC from downtown is not in that list. Recorded in
   `review/crc-crossings.json → if_all_crc_crossings_were_promoted`.

2. **The connector attribution report was silently reporting zero.**
   `attribute_disconnection` tested "what if we allowed the rejected connectors" by
   adding their ids to a routable set — but the same function filtered on `walkable`
   first, and the build sets `walkable=false` on every rejected connector. So
   `caused_by_rejected_connectors` was structurally always `0.000`, and every stranded
   mile was blamed on missing source data. Fixed; the real split for v1.2 is **6.080 mi
   recoverable by connector review, 6.778 mi genuinely isolated**.

3. **The campus promotion strands 12.858 mi off the main component** (v1.1: 0.170 mi).
   Campus pedestrian geometry does not join the town street graph through any
   *trusted* connector, so promoting it created two new valid routing areas —
   Drillfield Dr / Perry St (5.620 mi) and Oak Lane Trl (2.555 mi) — that a walker
   downtown cannot reach in the default graph. This is the one **WARN** gate. It is
   carried as a quantified limitation rather than hidden, and §21 records what would
   close it.

---

## 2. Routing-engine stability

Engine **2.1.0**. Weights, bands, `EngineConfig` and the search are byte-identical to
2.0.0. The single change is the campus coverage credit in `score.compute`, which is the
network v1.2 ruling's coverage semantics, not scoring tuning — `new_required_miles` can
now include a corridor the walk earned without physically traversing it, and
`credited_required_miles` reports how much. **Nothing was modified during UI
integration.**

Measured before/after on the controlled A/B (97 matched routes, identical code and
locations, weights swapped): avoidable repeat −22.2 %, third-or-later passes −59.1 %,
U-turns −15.6 %, new coverage +0.8 %, walk quality +2.8 %. Performance: **14.2 ms**
median single route, 306.6 ms median for five variants.

Three defects were found by integration tests, each recorded, reproduced and fixed
separately:

1. **Reservation accumulation.** A participant could leave a walk ACTIVE on any error
   path, start another, and hold both sets of segments against everyone else for the
   full four-hour window. `/api/walks/select` now refuses to start a second walk while
   one is ACTIVE (409) while still replacing a PREVIEW freely — previewing is
   browsing, starting is a commitment. Found by test ordering, not by design.
   `test_cannot_start_a_second_walk_while_one_is_active`.
2. **Lost response states.** When *every* band failed, `Engine.variants` returned
   early without attaching response objects, so the API fell back to a blanket
   `NO_USEFUL_ROUTE_NEAR_START` and lost the `SELECT_DIFFERENT_START_AREA` and
   `LONGER_ROUTE_REQUIRED` distinctions — precisely when §10's structured states
   matter most. `test_no_useful_route_state_is_structured_not_padded`.
3. **Untappable streets.** Required streets render at 1.4 px and overlap; whichever
   path happened to be on top swallowed the tap, so selecting the street you meant
   during "Review and edit" was close to impossible on a phone. Fixed with an
   invisible 14 px hit layer above the drawing. This was a mobile usability defect the
   e2e test surfaced by being unable to click anything.

Scoring weights, bands and the search are untouched by all three.

---

## 3–17. The vertical slice

```
web/  React 18 + TypeScript + Vite + vite-plugin-pwa     (mobile-first, installable)
api/app/  FastAPI + SQLAlchemy                            (identity, routing, walks, admin)
api/routing/  the frozen engine, read-only                (untouched by the app layer)
pipeline/  the canonical network build                    (v1.2 rulings)
```

**The twelve steps, all working:** arrive → sign up → dashboard → generate → grant
location once → see five sizes → change size → preview → start → walk → confirm →
dashboard moves. Verified end to end on a Pixel 7 viewport by `web/e2e/slice.mjs`
(30 assertions, all passing) against the real API and the real network.

| § | Requirement | Implementation |
|---|---|---|
| 4 | Home dashboard | Three metrics, each with its definition behind a disclosure. Households always labelled *estimated*. |
| 5 | Lightweight identity | First/last/email; matched on lowercased-and-trimmed email; opaque 256-bit token in the browser, `hmac-sha256(pepper, token)` in the database. Returning walkers see **"Walking as [Name]"** with **"Not you? Switch person"** — this is a shared-phone situation as often as not. |
| 6 | One-time location | `getCurrentPosition`, never `watchPosition`. Purpose stated *before* the browser prompt. Map-start fallback is first-class. |
| 7 | Route-generation contract | Documented in `api/app/routers/routes.py`; every per-variant output in `schemas.VariantOut`. Coverage-area ID, completion-state version and active reservations are **resolved server-side**, not accepted from the browser — a client that could name its own coverage area could ask for a route in one it is not standing in. Both are echoed back and stored. |
| 8 | Size interface | Slider snapping to computed variants only. Unavailable sizes shown, disabled, with the reason. |
| 9 | Small components | An area with less required mileage than the Quick band **replaces** the slider with **"Complete this area"** — not a sixth size bolted onto a control whose other five do not apply. Davis St (0.305 mi), Apple Ln (0.297), Georgia St (0.292). |
| 10 | Late-opportunity states | Five states, each with its own copy, all decided from local conditions — never from town-wide completion. |
| 11 | Controlled diversity | Per-request random seed, stored. Same seed → identical routes; different seeds → different routes within a 40 % quality tolerance, asserted in tests. |
| 12 | Reservations | Created on preview, extended on start, auto-expiring, released on submit/discard. Applied as a **prize multiplier of 0.15**, never a graph edit. Two nearby simultaneous walkers both get useful routes. |
| 13 | Active walk | Static plan, fixed start/end marker, distance, time, households, and a collapsed turn list. No live-location indicator, no moving marker, no GPS or tracking language. Enforced three ways in the e2e test: a language guard, an assertion that the only marker is `data-kind="route-start-end"` and does not move, and instrumentation proving `getCurrentPosition` was called **once** and `watchPosition` **never**. |
| 14 | Post-walk confirmation | "Did you complete the route as shown?" → *Yes, mark it complete* / *Review and edit* / *I didn't complete it*. Editing starts pre-selected from the plan and lets a walker drop skipped obligations and add nearby ones in one pass, with the adjusted distance and contribution updating live. Segment selection, never freehand. `Walk.planned_segment_ids` is never rewritten. |
| 15 | Completion model | Unique `(walk_id, segment_id)`; a repeat submission records 0 and moves no metric. Stored: planned route, final confirmed obligations, manual additions, manual removals, planned distance, final distance, participant, network version, engine version, route seed, submission timestamp — plus a `walk_edits` row per change so an administrator sees the *diff*, not two opaque lists. |
| 16 | Public progress map | Completed and incomplete required obligations, required trails, town boundary, legend, live metrics. Canonical campus corridors only. No household points, addresses, per-segment counts, participant identity or raw source layers. |
| 17 | Administration | Eleven capabilities (see below). |

**The eleven administration capabilities**, matching §17 one for one:
view submitted walks · view manual route edits · correct a walk submission · correct
segment completion (reverse, or record one walked offline) · release or inspect
reservations · review participant duplicates · inspect route-generation failures ·
view network and engine versions · review the eight CRC crossings · export aggregate
pilot data · town-wide progress and deployment posture including the licensing gate.

Route-generation failures are stored with everything needed to reproduce them — seed,
start node, coverage area, completion-state version, engine and network version — so
"it gave me nothing" is a bug report, not an anecdote.

Deliberately absent: any way to read one *named* participant's routes. §16 forbids
tying routes to names, and an admin screen is exactly where that rule would leak.

### Two design decisions worth flagging

**No basemap.** The map is a self-contained SVG renderer, not MapLibre + tiles. Every
tile and imagery host is blocked in this environment; a Protomaps extract raises the
same redistribution question we have not answered; and an installed PWA has to work
offline. The trade is real: a walker sees the shape of their route but not the
buildings around it, and turn-by-turn text carries that weight instead. A basemap is
the obvious first upgrade once licensing is settled.

**SQLite by default.** The technical plan specifies PostgreSQL 16 + PostGIS. Nothing
here depends on SQLite — switching is `BPW_DATABASE_URL`. PostGIS is not needed at all:
all geometry lives in the frozen canonical network on disk, and the database stores
only ids, counts and timestamps. Schema changes are Alembic migrations
(`api/migrations/`), with the URL read from the environment so no credential is ever
written to the repository; `alembic check` is kept green so the migrations and the
models cannot drift apart.

**GIS data is an internal application dependency, not a redistributable asset.** The
pipeline fetches it, the application reads the frozen network it produces, and none of
it is committed. A deployment runs `pipeline.sources.fetch` and has what it needs; the
repository carries the code that reproduces it. The town boundary the progress map
draws is read from the snapshot at runtime for the same reason — if it is absent the
map simply draws without an outline.

---

## 18. Privacy and repository safeguards

Three rules are enforced by the *shape* of the schema, not by convention:

1. **No residential data is stored anywhere.** No address, no household coordinate, no
   household identifier. Households are only ever counted, through the segment they
   hang off in the canonical network, at read time.
2. **No participant location is stored.** A route request records the graph node the
   start snapped to — a public street intersection. The GPS fix is used once, in
   memory, to pick that node, and discarded. `test_no_gps_fix_is_ever_stored` asserts
   the table has no location column.
3. **The browser holds an opaque token**, stored server-side only as a peppered hash.

Excluded from version control, and asserted by a test: raw address-point files, source
snapshots, household coordinates, generated maps embedding them, participant data
(`*.db`), and secrets (`.env`). `.env.example` documents every variable with no values.

**The strongest privacy assertion** is in `tests/test_privacy.py`: it samples 400 real
residential addresses out of the canonical household file and proves none of them
appears in *any* API response — 15 endpoints including every admin route. That fails if
a future change leaks data through a field nobody thought to check, which a key-name
scan would not.

The browser-side equivalent runs in `e2e/slice.mjs`, which captures every network
response during a full walk and scans them all.

---

## 19. The licensing gate and the three deployment tiers

`BPW_TIER` selects the posture. The default is `pilot` — a deployment has to opt *into*
public exposure, never fall into it.

| | Private development | **Limited authenticated pilot** | Public release |
|---|---|---|---|
| Who can reach it | one operator | invited participants, signed up | anyone |
| Aggregate metrics | yes | yes | yes — no source geometry, no residential data |
| Route geometry | yes | yes, authenticated | **blocked** |
| Progress map | yes | yes, authenticated | **blocked** |
| Residential data exposed | none | none | none |
| Participant identity exposed | none | none | none |
| **G1 blocker** | not blocking | **not blocking** | **BLOCKING** |

**G1 remains unresolved.** No Town of Blacksburg dataset used by this project publishes
any reuse licence — `copyrightText` is empty on every layer. Serving geometry derived
from them to the general public is redistribution. It does **not** block a pilot: showing
a map to a signed-up participant is on the same footing as showing someone a map in a
meeting.

Mechanically, `deps.geometry_or_403` refuses geometry to anonymous callers unless
`BPW_PUBLIC_GEOMETRY_ENABLED` is explicitly set, and setting it produces a loud startup
warning naming G1. `/api/health` and the admin deployment screen both publish the gate.

---

## 20. Testing

| Matrix | File | Tests |
|---|---|---|
| Identity | `tests/test_identity.py` | first-time, returning, switch, duplicate normalized email, token rotation, hashing |
| Location + small components | `tests/test_location.py` | parking-lot start, multiple nearby components, inside the CRC, tiny component, complete-this-area, structured no-route state |
| Routing | `tests/test_routing_api.py` | five variants, unavailable variants, determinism from a stored seed, diversity within tolerance, nesting, component containment |
| Completion, reservations, metrics | `tests/test_completion.py` | as planned, remove skipped, add nearby, partial, did-not-complete, duplicate completion by two users, discarded, expired reservation, two simultaneous walkers, campus double-count, denominator |
| Privacy | `tests/test_privacy.py` | no addresses, no participant data on public endpoints, no stored GPS, no sensitive artifacts committed |
| UI components | `web/src/components/__tests__/ui.test.tsx` | 10 |
| End-to-end, mobile viewport | `web/e2e/slice.mjs` | 41 assertions |

**82 passed, 1 skipped** (household coordinates are stripped when `households.json` is
written, so there is nothing to test for), plus 10 frontend and 41 e2e. Run:

```bash
python3 -m pytest                                    # backend matrices
cd web && npm test                                   # component tests
cd web && npm run build && node e2e/slice.mjs        # full slice, needs the API running
```

---

## 21. Pilot readiness

**Recommendation: GO for a limited authenticated pilot. NO-GO for public release.**

Seven of eight freeze gates PASS; one WARNs.

### Deliverables

| # | Deliverable | Where |
|---|---|---|
| 1 | Mobile-first PWA vertical slice | `web/` |
| 2 | Backend/API integration | `api/app/` |
| 3 | Canonical network v1.2 manifest | `api/routing/results/integration-candidate-2.1.0.json` |
| 4 | Routing-engine integration contract | `api/app/routers/routes.py` docstring + `schemas.VariantOut` |
| 5 | Database schema and migrations | `api/app/models.py`, `api/migrations/` |
| 6 | Automated test results | §20 above — 82 backend, 10 component |
| 7 | Mobile browser test results | `web/e2e/slice.mjs`, Pixel 7 viewport, 41 assertions |
| 8 | PWA installation test | manifest, standalone display, service-worker registration — in the same run |
| 9 | Privacy and data-exposure audit | §18 above, `tests/test_privacy.py` |
| 10 | Licensing-dependent deployment matrix | §19 above |
| 11 | Known limitations | below |
| 12 | Pilot-readiness recommendation | this section |

### Ready

- The twelve-step slice works on a phone and as an installed PWA.
- 145.588 required miles across 9 valid routing areas; 11,024 households on required
  coverage.
- Routing is interactive (14.2 ms median) and reproducible from a stored seed.
- No residential data, no participant location and no participant identity crosses the
  wire, proven against real address data.
- Completion is idempotent; the plan survives a different-route report.

### Before a pilot — small, and yours to decide

1. **Set `BPW_TOKEN_PEPPER`** to a generated value, and `BPW_TIER=pilot`.
2. **Run `alembic upgrade head`** against the pilot database.
3. **Run `python3 -m pipeline.sources.fetch && python3 -m pipeline.build.run`** on the
   deployment host. The GIS data is an internal dependency and is not in the
   repository.
4. **Seed one administrator.** There is deliberately no API for granting admin — an
   application that can promote itself over HTTP is one request away from anyone else
   doing so. Promote the first account directly in the database.

Repository visibility is no longer treated as a blocker, per your instruction. The
exclusions still hold and are asserted by a test: no raw source datasets, no household
coordinates, no participant database, no secrets.

### Before public release — larger, and not all ours

5. **Resolve licensing gate G1.** The single blocker. Until the Town of Blacksburg
   grants a reuse right, the progress map and route geometry stay behind
   authentication. Ask for written permission covering redistribution of derived
   geometry; §19 lists exactly what each tier exposes.
6. **Review the 8 CRC crossings** — worth doing for local CRC walkability, but note the
   correction in §1: it will not connect the CRC to downtown.
7. **Review the campus↔town crossings.** This is now the highest-value connector
   review, not the CRC: 6.080 mi of stranded required mileage would be recovered,
   including the 5.620 mi Drillfield Dr / Perry St area, mostly via crossings of
   Prices Fork Rd. That is a real question for someone with local knowledge — those are
   arterial crossings, and the router will not invent them.
8. **Add a basemap** once licensing allows it.

### Known limitations, carried forward

- **12.858 mi of required mileage is off the main component** (WARN gate). 6.080 mi is
  recoverable by connector review; 6.778 mi is genuinely isolated or missing from the
  source. Introduced by the campus promotion, quantified rather than hidden.
- **Three valid components cannot support even the Quick band** and are offered as
  "Complete this area" instead.
- **6,284 housing units are held for review**, mostly in apartment complexes with no
  mapped internal walkway. They are excluded from the public number rather than
  assigned to a frontage street.
- **VGIN, Montgomery County parcels, VT GIS and OSM were never reachable** from this
  environment across all of Phases 2a–3. Every conclusion about campus geometry rests
  on the town's own Paths to the Future layer.
- **No aerial imagery has ever been consulted**, which is why connector classification
  is a review queue rather than a decision.
