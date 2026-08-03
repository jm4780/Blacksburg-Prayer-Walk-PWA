# Phase 3.1 — Pilot deployment and campus validation

**Canonical network:** `v1.2` / `bbg-net-v1.2-e1284e6001ff54f5` — **unchanged. There is
no v1.3.**
**Routing engine:** `2.1.1` (was `2.1.0`) — one defect fix, measured.
**Recommendation:** **GO for a three-to-five-person pilot**, with campus assigned as a
deliberate test rather than as ordinary walking.

Deployment steps, backups and rollback live in
[`docs/15-pilot-deployment.md`](15-pilot-deployment.md).

---

## 1. G1 is now deployment configuration

`BPW_ACCESS_MODE` takes `authenticated` (pilot default) · `invite` · `public`.
`api/app/deps.may_see_geometry` is the **only** place it is read, so moving to
lightweight public participant access is one environment variable and a restart — no
route handler, schema, client build or database change.

The identity model is identical in all three modes: first name, last name, email,
remembered device, opaque token. No password, no verification, no account system.
`invite` adds a shared code at sign-up and changes nothing else.

Raw source GIS, household coordinates, residential addresses, participant records and
secrets remain excluded from the repository and from every endpoint, in all three
modes — `test_public_access_mode_still_hides_residential_data` asserts that making
geometry public does not make anything else public.

---

## 2. Campus routing validation

`python3 -m api.routing.campus_validate` → `api/routing/results/campus-validation.json`

### The finding

**The campus components are near-trees, and they are not independently useful for the
walks this app offers.**

| Component | Required | Households | Nodes | Edges | Independent cycles |
|---|---|---|---|---|---|
| 0 — main Blacksburg | 132.730 mi | 10,617 | 1,737 | 2,059 | **323** |
| **1 — Drillfield / Perry / Stanger** | **5.620 mi** | **0** | 66 | 66 | **1** |
| **4 — Oak Lane / Duck Pond** | **2.555 mi** | **0** | 29 | 30 | **2** |
| 3 — Corporate Research Center | 2.044 mi | 288 | 32 | 34 | 3 |

One independent cycle across 5.6 miles is a tree with a loop attached. The routing
consequence is visible and unambiguous: every campus route sits at `loop_shape` exactly
**0.50** — each segment walked precisely twice — with **0.00 avoidable repeat**. The
router is not being lazy. On a tree, out-and-back is the only closed walk that exists.

### Per location

| Start | Snap | Component | Bands | Best route | New coverage | Households | Loop |
|---|---|---|---|---|---|---|---|
| The Drillfield | 27 m | 1 | 5 | 6.59 mi | 3.06 mi | **0** | out-and-back at every band |
| Duck Pond | 126 m | 4 | 5 | 3.90 mi | 1.89 mi | **0** | out-and-back at every band |
| Lane Stadium | 124 m | 1 | 5 | 5.10 mi | 2.01 mi | **0** | coherent at Short only |
| N Main St / Prices Fork Rd | 94 m | **0** | 5 | 8.09 mi | 6.24 mi | 2,173 | coherent at all five |
| Downtown, east campus edge | 42 m | **0** | 5 | 8.09 mi | 6.73 mi | 2,260 | coherent at 3 of 5 |
| Outside campus, Prices Fork entrance | 65 m | **0** | 5 | 8.26 mi | 6.66 mi | 1,468 | coherent at all five |
| *Downtown (control)* | 29 m | 0 | 5 | 8.10 mi | 7.32 mi | 2,138 | coherent at all five |
| *CRC (control)* | 130 m | 3 | 3 distinct | 3.56 mi | 2.04 mi | 288 | coherent at Quick only |

### What that means

- **No start failed.** All eight produced five offered bands and a returnable route.
  Nobody is stranded.
- **No invented crossings.** Structurally guaranteed: the router is scoped to the
  start's own component and never crosses between them.
- **Campus walks pass zero homes.** Not a rounding artefact — campus canonical
  corridors carry no associated dwelling units at all. A walker doing the Drillfield
  covers required mileage and prays for nobody's house.
- **Boundary starts fall town-side, which is right.** N Main/Prices Fork, the eastern
  campus edge and the Prices Fork pedestrian entrance all snapped into the main
  component, 42–94 m, and produced strong routes. There is no surprising component
  selection anywhere in the set.
- **No location reaches both campus and non-campus coverage**, because no component
  contains both. That is the whole finding, restated.

### Two surprises worth naming

1. **The bands are not really bands on campus.** Duck Pond returns the same 3.90-mile
   route for Long *and* Extended: the component runs out of ground before the budget
   does. The size control is honest about it (both remain available and both are that
   route), but a campus walker choosing "Extended" gets Long.
2. **Snap distances are larger on campus** — 124–126 m at Lane Stadium and the Duck
   Pond versus 27–42 m downtown. Campus pedestrian geometry is sparser than the street
   grid, so a walker standing in a car park or on a lawn has further to go to reach a
   mapped way. Nothing broke; it is worth knowing when a participant says "it started
   me somewhere odd".

---

## 3. High-value connector review

`python3 -m pipeline.build.connector_candidates` →
`pipeline/out/2026-08-03/review/connector-candidates.json`, and the **Connectors** tab
in the admin interface.

29 component-joining candidates, prioritised by required mileage recovered, components
joined, likely start frequency (households within 500 m) and evidence strength.

### Evidence available, and its ceiling

No aerial or street-level imagery host is reachable from this environment. So the
signals are geometric:

- **opposed pedestrian termini** — a way ends at the kerb and another begins opposite.
  Two digitisers stopping at the same place is meaningful.
- **forms a street junction** — the connector links two differently-named streets,
  which is where crosswalks are. Campus corridors count as streets here, because the
  town Roads layer contains no campus streets at all.
- **road class and speed** — supporting, never deciding.

### The result: nothing meets the bar

**0 of 29 promoted. No canonical network v1.3.**

The finding that decides it is uncomfortable and clean:

> **The highest-value candidate has the weakest evidence, and the best-evidenced
> candidates recover almost nothing.**

| Segment | Recovers | Road | Crossing | Recommendation | Confidence |
|---|---|---|---|---|---|
| **SEG-001679** | **5.620 mi** | Prices Fork Rd, Secondary, 25 mph | mid-block | DO NOT PROMOTE WITHOUT EVIDENCE | LOW |
| SEG-002576 | 0.292 mi | Georgia St, Local, 25 mph | mid-block | DO NOT PROMOTE WITHOUT EVIDENCE | LOW |
| SEG-001647 | 0.108 mi | Prices Fork Rd, Secondary, 25 mph | at intersection | REVIEW ON SITE | MEDIUM |
| SEG-001774 | 0.042 mi | Prices Fork Rd, Secondary, 25 mph | at intersection | REVIEW ON SITE | MEDIUM |
| SEG-001517 | 0.000 mi | N Main St, Arterial, 20 mph | at intersection | REVIEW ON SITE | MEDIUM |

**SEG-001679 is the whole game.** 6.2 m long — kerb-to-kerb width — at
`37.23184, -80.42800`, and it alone would fold the entire 5.620-mile Drillfield
component into the main network, turning the campus from a tree into part of a graph
with 323 cycles. Everything above hangs on it.

And the evidence against it is real: no pedestrian way terminates opposite, and it does
not form a junction between two named streets. I initially convinced myself this was
"West Campus Drive meeting Prices Fork Road" — a main campus entrance, obviously
crossable. It is not. That name comes from the *stranded component's* label; the
segment on the campus side is an **unnamed** walkway. I corrected the classifier for a
real blind spot it had (it could not see campus street junctions at all), re-ran, and
SEG-001679 still came back mid-block. My original classification was right and my
correction was chasing a story I had built from the wrong field.

**What one person could settle in ten minutes:** stand at
[`37.23184, -80.42800`](https://www.openstreetmap.org/#map=19/37.23184/-80.42800) and
answer one question — *is there a marked pedestrian crossing of Prices Fork Road here?*
Yes unlocks 5.620 miles and makes campus loops possible. That is the single
highest-value unresolved question in the project.

**Component 4 (Oak Lane / Duck Pond, 2.555 mi) has no candidate connector at all.**
Not a rejected one — none exists. Nothing in the source data would join it even if we
allowed everything. That is a data gap, not a review item, and no site visit fixes it.

---

## 4. Engine 2.1.1 — one defect, found by the loop check

`Route.node_sequence` seeded from `start_node`, a compact **graph index**, and compared
it against `Segment.u`, a canonical **node id**. The comparison was essentially always
false, so the first step fell through and the entire visited-node sequence came out
shifted by one position.

Consequences, both silent since Phase 2b:
- every turn angle in `turn_stats` was measured at the junction *before* the one where
  the turn happens, so `Weights.turn` and `Weights.uturn` were scoring the wrong
  geometry;
- every route reported as not closing.

Nothing failed loudly — a shifted list of node ids is still a plausible list of node
ids. It surfaced only when §2's loop-coherence check returned "does not close" for the
known-good downtown control.

Measured over 56 matched routes, weights untouched:

| | before | after | delta |
|---|---|---|---|
| turns / mile | 3.679 | 3.556 | **−3.3 %** |
| U-turns / mile | 0.227 | 0.200 | **−12.2 %** |
| walk quality | 67.50 | 67.90 | +0.6 % |
| **route score** | 413.50 | 413.79 | **+0.1 %** |
| routes closing | — | **56 / 56** | — |

Route *selection* is essentially unchanged, which is the expected shape for a
measurement fix rather than a tuning change.

---

## 5. Pilot feedback

Available from the active-walk screen (**"Report a problem with this route"** — so a
missing crossing can be reported standing at it) and after submission.

Five structured answers and a comment: overall rating, easy to follow, time felt
accurate, walked as planned, and *did it send you somewhere unsafe, inaccessible or
non-existent* with a detail box. One row per walk; a second answer replaces the first.

Every row stores the reproduction key — network id and version, engine version, seed,
coverage area, start node, band. `test_stored_seed_actually_regenerates_the_route`
does not merely assert the fields exist: it replays the stored seed and checks the
regenerated route is segment-for-segment identical to the one that was walked. A
complaint is a command someone can run.

---

## 6–7. Pilot admin summary and the capability audit

New **Pilot** tab: participants, walks submitted, completion rate, discarded, manual
edits, average rating, routes flagged unsafe, route-generation failures with their
seeds, late-opportunity states served, and a breakdown by routing component.

Starting areas are reported as **components, never coordinates** — a component is
hundreds of acres; a start point is somebody's front door.
`test_pilot_summary_never_names_a_walker_against_a_route` asserts no email, name or
coordinate appears anywhere in it.

### §7 audit — what is usable, and what is not

The honest answer for the Phase 3 admin interface was that nine of eleven capabilities
were a `<pre>` of raw JSON: usable by an engineer, not by an administrator. Rebuilt.

| Capability | State |
|---|---|
| Review submitted walks | ✅ table |
| Review manual route edits | ✅ table, shown as a diff (added / removed) |
| Inspect and release reservations | ✅ table |
| Review participant duplicates | ✅ table, with why nothing is auto-merged |
| Inspect route failures | ✅ table with reproduction keys, grouped by reason and area |
| View network and engine versions | ✅ manifest + component table |
| Review connector candidates | ✅ table with evidence and map links |
| Export aggregate pilot data | ✅ endpoint |
| Review pilot route feedback | ✅ table, flagged rows highlighted |
| **Correct a walk submission** | ⚠️ **API only** |
| **Correct segment completion** | ⚠️ **API only** |

Two defects were found by actually opening the interface rather than by testing the
endpoints behind it:

1. **The admin app white-screened on every tab switch.** Tab state and payload state
   were separate, so React rendered the newly-selected tab against the *previous*
   tab's data for one frame — clearing it inside the effect is too late — and
   Connectors received the pilot summary, crashing on `d.rows.map`. Now the payload is
   stored with the tab it belongs to, which makes the mismatch unrepresentable, and a
   late response from an abandoned tab can no longer overwrite the current one.
2. **The pilot screen reported a 200% feedback response rate.** Feedback can be left
   from the active-walk screen before a walk is submitted, so dividing all feedback by
   submitted walks exceeded 100%. A rate above 100% discredits every number beside it.
   The denominator is now submitted walks that have feedback, with mid-walk responses
   reported separately.

`node e2e/admin.mjs <admin-token>` is committed and checks that all eleven tabs render
with no page errors.

The two gaps are deliberate and recorded in code (`ADMIN_CAPABILITY_NOTES` in
`web/src/screens/Admin.tsx`). Both need map-based segment selection — the same
interface the walker gets — and building a second, worse copy of it for an action
nobody has needed yet was not worth the pilot's time. Both require a written reason and
are audited. If a pilot participant needs a correction, an administrator can call them;
if that happens more than once, build the screen.

---

## 8. Pilot plan — three to five participants

Two weeks. Each participant walks **at least twice**, and gives feedback each time.
No participant is identified in any report; scenarios are named, people are not.

### P1 — Downtown *(the control)*
- **Start:** anywhere near Main St / Draper Rd.
- **Testing:** the ordinary case. Dense grid, all five sizes, real households.
- **Feedback that matters:** is the estimated time about right? Did the turn list match
  what you saw?
- **Success:** completes as planned, rating ≥ 4, no flagged connection.
- **Failure:** any flagged crossing downtown — the street grid is the best-mapped part
  of the network, and a bad connection here means a systemic problem.

### P2 — Virginia Tech campus *(the deliberate stress test)*
- **Start:** the Drillfield.
- **Testing:** whether an out-and-back on a tree is acceptable to a real walker.
- **Tell them in advance:** this route will retrace itself, and it will not pass any
  houses. We want to know whether it is still worth walking.
- **Feedback that matters:** did the retracing bother you? Did walking a route with no
  homes on it feel meaningful?
- **Success:** they would do it again knowing what it is.
- **Failure:** "I would not walk this" — which would mean campus should be presented
  differently, or the Prices Fork crossing becomes urgent rather than valuable.

### P3 — Residential neighbourhood
- **Start:** Hethwood, or their own street.
- **Testing:** the household estimate against reality, and cul-de-sac handling.
- **Feedback that matters:** did the household count look plausible for what you
  walked? Did the dead-end returns feel unavoidable or silly?
- **Success:** completes, rating ≥ 4, household estimate not obviously wrong.
- **Failure:** the count is off by more than about a third by eye.

### P4 — Small isolated component
- **Start:** Scenic Ridge Cir (0.586 mi, 59 households) — the smallest area that is
  genuinely worth a walk.
- **Testing:** the "Complete this area" path instead of the size slider.
- **Feedback that matters:** was it clear this was a whole small area rather than a
  broken short route?
- **Success:** they understand what they were offered without it being explained.
- **Failure:** confusion about why there were no sizes.

### P5 — Corporate Research Center *(if practical)*
- **Start:** Research Center Dr.
- **Testing:** an independent component with real households (288), and the same
  out-and-back shape at longer bands.
- **Feedback that matters:** at Quick it is a coherent loop; at Medium and above it
  retraces. Is the difference noticeable?
- **Success:** the Quick route reads as a proper loop.
- **Note:** weekday daytime is best — it is a business park.

### Cross-cutting, every participant
- Install the PWA to the home screen. Report anything that breaks when opened that way.
- At least one walk started by **tapping the map** rather than using location.
- Anyone who declines the location prompt should still be able to plan a walk.

### Stop conditions
Pause the pilot and fix before continuing if any of these occur:
- a route sends someone into traffic with no crossing;
- the town-wide percentage moves when it should not, or fails to move when it should;
- two participants get identical routes from nearby starts on the same day;
- any residential address or another participant's identity appears anywhere in the app.

---

## 9. Known limitations carried into the pilot

- **12.858 mi of required mileage is off the main component** (campus 8.175, CRC 2.044,
  fragments the rest). 6.080 mi is recoverable by connector review — nearly all of it
  by the one Prices Fork crossing; 6.778 mi is isolated in the source data.
- **Campus walks pass zero households** and are out-and-back at every band.
- **Component 4 cannot be connected** by anything in the source data.
- **Extended and Long collapse to the same route** on small components.
- **6,284 housing units are held for review**, mostly in apartment complexes with no
  mapped internal walkway.
- **No aerial imagery has ever been consulted**, in any phase. Connector classification
  is a review queue for that reason.
- **VGIN, Montgomery County parcels, VT GIS and OSM were never reachable** from this
  environment. Every campus conclusion rests on the town's own Paths to the Future
  layer.
- **Correcting a walk or a completion is API-only** (§7 above).
- **G1 is unresolved**, so the progress map stays behind authentication.

---

## 10. Go / no-go

**GO for a three-to-five-person pilot.**

The flow works end to end on a real phone and as an installed PWA, on real data. Route
problems are reportable from inside a walk and reproducible from a stored seed.
Nothing about a participant or a resident leaves the server. Deployment, backup and
rollback are written down and checkable.

Two conditions, neither blocking:

1. **Assign campus as a deliberate test, not as ordinary walking.** P2 should be told
   what they are getting. Sending someone to the Drillfield expecting a neighbourhood
   loop would be a bad first impression of a system that is working correctly.
2. **Answer the Prices Fork question.** Ten minutes at
   `37.23184, -80.42800` decides whether 5.620 miles joins the network. It does not
   block the pilot; it is the highest-value thing anyone can do for the project.

**NO-GO for public release**, unchanged: licensing gate G1.
