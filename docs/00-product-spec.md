# Blacksburg Prayer Walk PWA — V1 Product and Routing Specification

> This is the authoritative product specification for V1, preserved in the repo so
> implementation decisions can be checked against it. Section numbers are stable and
> are referenced throughout the other docs.

## 1. Product summary

Build a mobile-first Progressive Web App for Blacksburg Church that helps people
systematically prayer-walk every eligible public street and major trail within the
Town of Blacksburg.

The app should:

1. Show collective progress across the town.
2. Generate a closed-loop walking route from the user's current location.
3. Prioritize streets that have not yet been prayed over.
4. Let the user adjust the general size of the recommended route.
5. Show route distance, estimated walking time, estimated households passed, and expected new coverage.
6. Let the user confirm or edit which streets they completed after the walk.
7. Update town-wide progress after a walk is submitted.
8. Avoid requiring traditional user accounts.

Core experience: **Open the app. Generate a route. Pray while walking. Confirm the
streets covered. Watch the town gradually fill in.**

## 2. V1 scope

- Organization: Blacksburg Church
- Coverage project: Blacksburg Town Prayer Walk
- Geographic scope: eligible streets and major trails within the Town of Blacksburg
- Primary use mode: walking
- Start point: the user's one-time current location
- End point: the same location

The backend must not hard-code Blacksburg as the only possible location. It should
carry basic multi-area infrastructure so future projects can include Montgomery
County, Christiansburg, house-church neighborhoods, other custom initiatives, and
additional organizations. **None of this appears in the V1 interface.**

## 3. Explicit V1 exclusions

Password accounts · social login · leaderboards · badges · social feeds · prayer
journals · street-specific prayer requests · live location tracking · GPS recording
during a walk · route-deviation detection · automatic rerouting · built-in
turn-by-turn navigation · team assignment · group walk coordination · push
notifications · multi-project selection in the public UI · county-wide routing ·
advanced participant profiles · AI-generated prayer content.

## 4. Core product rules

### 4.1 Location use

Location may be requested **only** when generating a route, and is used to determine
the start/end point, find nearby incomplete segments, and generate a closed loop.
No ongoing GPS access. No wording that implies the walk was recorded or verified.

Flow: tap Generate → one-time browser location request → snap raw coordinates to the
nearest appropriate public walking-network point → snapped point becomes start and
end → generate variants → no ongoing tracking. The start may differ slightly from the
raw location if the user is in a building or parking lot.

### 4.2 Street completion

A segment is complete when the user confirms they traveled it once in either
direction. Either direction counts; either sidewalk counts; once is enough; no GPS
verification; the user may add or remove segments in post-walk review. Completion is
tracked **by segment**, not by street name — a named street may be partially complete.

### 4.3 Eligible network

**Count as required coverage:** public streets within the Town of Blacksburg; major
public trails within the town intentionally included in the project.

**Allow as connectors:** public streets outside the boundary when needed for a
sensible route; public pedestrian connections needed to link eligible segments;
out-of-town roads that help the route return to its start.

**Do not count as required coverage:** private roads, gated roads, alleys,
parking-lot drive aisles, internal commercial drives, internal apartment-complex
drives (unless intentionally approved), and service roads that are not meaningful
public streets.

Every segment has exactly one project role: `REQUIRED`, `OPTIONAL_CONNECTOR`, or
`EXCLUDED`. A connector may appear in a route but never increases the completion
percentage.

## 5. User identity

No traditional accounts. Lightweight participant identity.

- **First use:** first name, last name, email. Create a participant record; store a
  device token / participant identifier in browser storage.
- **Returning use:** show "Walking as Jacob McKlarney" with a small "Not you?" /
  "Switch person" action. Do not re-ask for name and email when local identity exists.
- **Cross-device:** not required for V1. If the same email is entered on another
  device, associate it with the existing participant rather than duplicating. Email
  matching is case-insensitive and normalized. No password or account-management UI.

## 6. Public metrics

Dashboard shows: percentage of Blacksburg prayed for; total miles walked; estimated
households prayed for. Optional secondary: completed walks, participants, unique
eligible street miles completed.

- **6.1 Percentage prayed for** = completed REQUIRED mileage ÷ total REQUIRED mileage.
  Never by count of named streets. Public wording: "38% of Blacksburg prayed for."
- **6.2 Total miles walked** = combined length of all confirmed submitted routes,
  including repeats, connectors, return portions, dead-end backtracking, and
  out-of-town portions. This is participant walking distance, not unique coverage.
  Store unique completed mileage separately.
- **6.3 Estimated households prayed for** — source preference order: residential
  address points → residential parcels with address/occupancy data → residential
  building footprints → census/housing-unit estimates distributed spatially → a
  documented density estimate. Always labeled "estimated." Deduplicated town-wide.
  Record source and confidence internally.

## 7. Recommended route metrics

For every variant: total distance, estimated walking time, estimated households
passed, expected new eligible mileage, optionally the number of incomplete segments
included. Example:

```
Recommended Prayer Walk
2.6 miles
About 55 minutes
Estimated 184 households
1.9 miles of new coverage
```

These must update when the route-size control changes.

## 8. Route-size control

No exact duration or distance entry. Five levels: **Quick · Short · Medium · Long ·
Extended**. May look like a slider but snaps to a limited set of generated variants.

Guidance bands (not promises): Quick ≈ 0.5–1.0 mi · Short ≈ 1.0–1.75 · Medium ≈
1.75–2.75 · Long ≈ 2.75–4.0 · Extended ≈ 4.0–6.0. Always show the actual generated
distance and time.

**Route stability:** related sizes must stay geographically similar where practical.
Longer should *extend* shorter rather than replace it — shorter removes outer loops,
distant clusters, and inefficient branches; longer adds nearby incomplete streets,
loops, cul-de-sacs, or an adjacent cluster. Avoid regenerating an unrelated route per
slider position.

## 9. Routing problem definition

This is an **arc-routing** problem, not point-to-point navigation. The route must
begin and end at the snapped start point, stay walkable, prefer incomplete required
segments, use completed/connector roads when necessary, be coherent to a real walker,
avoid private and excluded roads, support eligible trails, respect active
reservations, and return geometry plus metrics. Maximize useful incomplete coverage
while preserving route quality.

## 10. Street-network model

A graph. **Nodes:** street and trail intersections, dead ends, trailheads,
significant pedestrian connectors, segment endpoints, boundary transition points.
**Edges** (walkable segments) carry: stable internal ID, geometry, length, normalized
name, display name, segment type, walkability, access classification, public/private
status, coverage-project role, town-boundary relationship, household associations,
completion status, optional zone membership.

Segment types: `STREET`, `TRAIL`, `PEDESTRIAN_CONNECTOR`, `OUT_OF_AREA_CONNECTOR`.

## 11. Stable segment IDs

Every physical segment gets a stable internal ID independent of any mutable external
provider ID (`SEG-000001`, …). External source IDs are metadata only; completion
history references the internal ID. This protects history across OSM ID churn, name
changes, data refreshes, better GIS data, and manual corrections. Material geometry
changes go through a migration process, never a silent identity swap.

## 12. Named streets

Track physical segment, normalized named street, and coverage status separately. A
named street contains many segments; the public map shows completed and incomplete
portions separately; never mark a whole named street complete because one segment was
traveled.

## 13. Initial route-scoring logic

Simple, inspectable, tunable.

**Reward:** new incomplete required mileage; fully completed segments; completing
partially completed named streets; completing dead ends/cul-de-sacs; completing
isolated leftovers; clearing a coherent neighborhood cluster; new households;
geographic continuity.

**Penalize:** repeated completed-road mileage; long access travel before new
coverage; excessive backtracking; unnecessary U-turns; repeated intersection
crossings; fragmented shape; tiny disconnected additions; overlap with active
reservations; unsafe or undesirable roads; excessive out-of-town travel; routes that
are efficient but unpleasant.

Illustrative starting formula:

```
Route score =
  100 × new incomplete miles
+  20 × completed segments
+  30 × completed normalized streets
+  20 × completed dead ends
+  15 × completed partial streets
+  neighborhood-coherence bonus
−  35 × repeated completed miles
−  10 × unnecessary U-turns
−   5 × excessive turns
−  active-route overlap penalty
−  route-awkwardness penalty
```

Starting weights only. Store score components for every generated route.

## 14. Primary optimization metric

Maximize **previously incomplete REQUIRED network mileage included in the route** —
not the number of street names or short segments.

Priority order: (1) new eligible physical coverage, (2) completing partial segments
or named streets, (3) dead ends and isolated leftovers, (4) connected neighborhood
clusters, (5) avoiding repeated travel, (6) a coherent, understandable walk.

## 15. Route quality rules

Reject or strongly penalize: excessive zigzagging; frequent U-turns; repeated use of
the same intersection; one-block excursions with immediate reversals unless required;
long travel on completed streets before new coverage; unsafe or non-walkable
crossings; excessive high-stress roads; disconnected-looking additions; unnecessary
out-and-back behavior; implausible connections; poorly matched start/end geometry.

A route with slightly less new coverage may be preferable if it is significantly more
coherent. Maintain both a **coverage score** and a **walk-quality score**; routes must
meet a minimum walk-quality threshold.

## 16. Dead ends and cul-de-sacs

Inward traversal may complete the segment; the return contributes to route mileage;
households count once; the router gets a completion bonus; nearby dead ends should be
grouped; dead-end priority rises over time so they are not indefinitely avoided. Near
town-wide completion, isolated dead ends and leftovers get strong priority even when
inefficient.

## 17. Trails

Major public trails inside the town may count when intentionally included. Trail
segments are manually curated. Store trail name, surface, accessibility, public
access, seasonal limitations, connection points, whether it counts toward completion,
and whether it is connector-only. Do not assume every mapped footpath counts.

## 18. Route generation process

1. **Snap start point** — nearest appropriate public walkable point; avoid private
   roads and parking-lot geometry; return a clear start marker.
2. **Load candidate network** — incomplete required segments and usable connectors
   within the max route-size search area.
3. **Identify promising clusters** — by connectivity, proximity, incomplete mileage,
   household coverage, access cost, ease of return, and active reservations.
4. **Build a core route** — a coherent medium closed loop over a high-value cluster.
5. **Generate related variants** — add/remove outer loops, adjacent segments, nearby
   dead ends, or a secondary cluster; preserve route identity.
6. **Optimize** — remove repetition, reduce awkward turns, improve the return path,
   prefer incomplete streets on the return, validate walkability, confirm closure.
7. **Calculate metrics** — distance, time, households, new required mileage, segment
   IDs, route score, walk-quality score.

## 19. Walking-time estimate

No pace question in V1. Documented default: base walking speed ≈ 2.7–3.0 mph plus a
modest adjustment for turns, crossings, and complexity. Public wording is approximate
("About 55 minutes"). Refine later from feedback, without GPS.

## 20. Household estimation

Stable internal ID per household/residential unit where possible. Associate
households with nearby required segments using the best available method. Avoid
double-counting corner properties, buildings near multiple segments, repeated
segments, overlapping segments, and apartment buildings represented in multiple
datasets.

- Route preview: unique associated household IDs across the route's unique relevant
  segments.
- Public progress: unique associated household IDs whose linked required segments are
  confirmed complete.

Where units within multi-family buildings cannot be distinguished, use the best
estimate and keep the word "estimated."

## 21. Route reservations

Soft and temporary, because users are not tracked.

- **Preview reservation:** on route generation, soft-reserve targeted incomplete
  segments for ~10–15 minutes.
- **Active reservation:** on "Start Prayer Walk," extend to estimated route time plus
  buffer (a 50-minute walk ≈ 75–90 minutes).

Reservations expire automatically, are released on submission or discard, act as
routing **penalties** rather than locks, and never block another user when no
reasonable alternative exists. Completion operations are idempotent.

## 22. Walk lifecycle

Open app → see progress → tap Generate → resolve identity → one-time location → snap
→ generate variants → adjust size → metrics update → Start Prayer Walk → reservation
extended → walk the static route untracked → return → choose *completed as planned* /
*review and edit* / *did not complete* → confirm final segments → store total
distance → mark required segments complete → update household estimate → release
reservations → show updated town-wide progress.

## 23. Post-walk confirmation

Prompt: "Did you complete the route as shown?" — **Yes, mark it complete** /
**Review and edit** / **I didn't complete it**.

- *Yes:* mark planned required segments complete; submit the full planned distance.
- *Review and edit:* show the planned route split into selectable segments; allow
  removing skipped segments, adding nearby connected segments, confirming part of the
  route, and reviewing the revised distance and household contribution. Prefer
  segment selection over freehand drawing.
- *Didn't complete:* mark nothing complete, release reservations. No complicated
  unfinished-walk workflow in V1.

## 24. Manual editing and audit trail

Never overwrite the original route definition. Store the planned route, planned
segment IDs, user additions, user removals, final confirmed segment IDs, planned
distance, final submitted distance, participant, and submission timestamp.
Distinguish: planned-and-confirmed, planned-but-removed, manually added, and
previously completed before the walk. Manual additions far from the planned route
require extra confirmation or an admin review flag, but are not prohibited.

## 25. Total route distance after editing

Confirmed as planned → add the planned distance. Edited → recalculate the best
available estimate from the selected segment sequence and connectors; if traversal
order can't be reconstructed, use a documented approximation. Never sum only newly
completed segments (that undercounts returns and connectors). V1 may preserve the
full planned distance unless the walk is marked partially complete, in which case
present a reasonable adjusted estimate before submission.

## 26. Core screens

- **26.1 Home** — title, percentage prayed for, total miles walked, estimated
  households, primary "Generate a Prayer Walk," "View Progress Map."
- **26.2 Participant identity** — first use: name + email; returning: "Walking as
  [Name]" + "Not you?"
- **26.3 Route generation** — one-time location request, loading state, denial
  handling, optional manual map-start fallback.
- **26.4 Route preview** — map, start/end marker, route-size control, distance, time,
  households, new coverage, Start, Regenerate.
- **26.5 Active route** — static route map, summary, clear route line and start/end
  point, optional written turn list, "Finish Walk," no claim of live tracking.
- **26.6 Post-walk review** — confirm as planned, review/edit, discard, segment
  selection map, updated contribution summary.
- **26.7 Progress map** — completed and incomplete required segments, major trails,
  town boundary, simple legend, public metrics.
- **26.8 Minimal admin** — review walks and manual edits, correct segment completion,
  edit segment eligibility, inspect household associations, view route-generation
  logs and reservations, correct participant duplicates, export basic data. No large
  analytics platform.

## 27. Suggested map states

Completed required segment · incomplete required segment · current planned route ·
connector-only segment · selected during editing · deselected during editing ·
manually added segment · start/end marker. **Meaning must not depend on color alone** —
use line patterns, contrast, or labels.

## 28. Future-proof backend structure

Hierarchy: Organization → Coverage Project/Area → optional Zones → Canonical Network
Segments → Area Memberships → Participants → Walks → Contributions.

Minimum future-facing fields: `organization_id`, `coverage_area_id`,
`parent_coverage_area_id`, `segment_role`, optional `zone_id`. V1 contains one
organization, one coverage area, no visible zones, and no multi-tenant admin or
project-switching UI.

## 29. Suggested data entities

**Organization** — id, name, created_at.

**CoverageArea** — id, organization_id, parent_coverage_area_id (nullable), name,
type (`TOWN` | `COUNTY` | `NEIGHBORHOOD` | `HOUSE_CHURCH_AREA` | `CUSTOM`),
boundary_geometry, active, created_at.

**NetworkSegment** — id, geometry, length_meters, normalized_name, display_name,
segment_type, access_type, walkable, stable_source_metadata, created_at, updated_at.

**CoverageAreaSegment** — coverage_area_id, segment_id, role, priority,
completion_status, first_completed_at, first_completed_by_walk_id,
estimated_household_count (cached if useful).

**HouseholdEstimate** — id, geometry/centroid, source, estimated_units, confidence,
primary_segment_id (nullable), source_updated_at.

**SegmentHousehold** — segment_id, household_estimate_id, relationship_type,
confidence.

**Participant** — id, organization_id, first_name, last_name, normalized_email,
created_at, last_seen_at.

**ParticipantDevice** — id, participant_id, local_token_hash, created_at,
last_seen_at.

**Walk** — id, participant_id, coverage_area_id, start_point, snapped_start_node_id,
selected_route_size, planned_route_geometry, planned_distance_meters,
final_distance_meters, estimated_time_minutes, planned_household_estimate, status
(`PREVIEW` | `STARTED` | `SUBMITTED` | `DISCARDED` | `EXPIRED`), started_at,
submitted_at, discarded_at.

**WalkSegment** — walk_id, segment_id, planned, confirmed, manually_added,
manually_removed, traversal_order (nullable).

**RouteReservation** — id, walk_id, segment_id, reservation_type (`PREVIEW` |
`ACTIVE`), expires_at.

**RouteGenerationLog** — id, coverage_area_id, start_point, route_size,
generated_route, included_segment_ids, score_components, total_score,
walk_quality_score, generation_duration, created_at.

## 30. Routing API contract

**Input:** start latitude, start longitude, coverage area ID, participant ID,
requested route-size level, optional excluded segment IDs, optional regenerate seed.

**Output:** snapped start point, route variant ID, route geometry, ordered network
edges, required segment IDs included, connector segment IDs included, total distance,
estimated time, estimated households, new required mileage, expected completed
segment count, route score, walk-quality score, warnings, reservation expiration.

Ideally one request returns all five related variants so slider movement is immediate.

## 31. Route prototype deliverable

Before the polished app, build a routing prototype taking start lat/lon, route-size
level, current completion state, and current reservation state; returning closed-loop
geometry, ordered segment IDs, total distance, estimated time, estimated households,
new coverage mileage, score breakdown, and walk-quality score. Test from multiple
starting points across Blacksburg before integrating.

## 32. Data audit requirements

Determine the best available sources for: town boundary, public street centerlines,
road access classification, public/private road status, major trails, pedestrian
connections, crosswalk/crossing feasibility, residential address points, parcel data,
building footprints, estimated housing units, street names, and speed/road-class
information useful for walking comfort.

Document for each: source, license, last updated, known gaps, required manual
cleanup, and whether the data can legally be stored and redistributed. Do not assume
OpenStreetMap alone contains all necessary household or private-road information.

## 33. Manual data curation

Provide a basic process or admin tool for: marking roads private; excluding incorrect
geometry; adding missing pedestrian connectors; adding/removing major trails;
changing a segment from REQUIRED to CONNECTOR; correcting street names; adjusting
household associations; splitting/merging segments; flagging unsafe crossings.

## 34. Acceptance criteria

**Route basics** — starts and ends at the same snapped point; follows walkable public
geometry; uses no excluded roads; may use approved out-of-town connectors;
prioritizes incomplete required segments; returns valid distance and time; displays
estimated households.

**Slider behavior** — five sizes available; metrics update on change; longer variants
are generally extensions of shorter ones; small changes don't cause arbitrary
geographic jumps unless necessary; all variants return to the same start.

**Completion behavior** — confirm as planned; remove skipped segments; add nearby
segments; confirmed segments update progress; re-completing a completed segment
causes no corruption; reservations released after submission or expiration.

**Identity behavior** — first-time user supplies name and email; returning user
remembered on device; user can switch identity; matching normalized email does not
create unnecessary duplicates.

**Metrics** — percentage = completed required mileage ÷ total required mileage; total
miles walked = total confirmed route length across submitted walks; households
labeled estimated; households deduplicated town-wide; preview metrics change with
variants.

**Privacy and language** — no continuous location tracking; no wording claiming the
user was tracked; location use clearly explained; the user actively confirms streets.

## 35. Initial test scenarios

1. Dense area with many incomplete streets.
2. Area where most nearby streets are complete.
3. Near the town boundary.
4. Outside the town but near an eligible area.
5. Inside a parking lot.
6. Near a private road.
7. Near a major trail.
8. Route containing multiple cul-de-sacs.
9. Route requiring out-of-town connector travel.
10. Two users generating routes simultaneously nearby.
11. Generates but never starts a route.
12. Starts but never submits.
13. Completes route as planned.
14. Removes half the planned route.
15. Adds nearby streets.
16. Submits segments another person completed first.
17. Route-size slider across all five levels.
18. Area near total completion with only isolated streets left.

## 36. Implementation sequence

1. **Geographic data audit** — sources, licensing, quality, household approach, cleanup needs.
2. **Canonical network preparation** — build graph, split at intersections, stable IDs, eligibility roles, trails and connectors, household associations.
3. **Routing prototype** — closed loops, coverage scoring, variants, metrics, scoring logs, multi-location testing.
4. **Minimal backend** — participants, walks, segment completion, reservations, metrics, admin corrections.
5. **PWA interface** — home, identity, location request, route preview, size control, static active route, post-walk confirmation, progress map.
6. **Pilot** — small group, route-quality review, tune time estimates and weights, correct geography, simplify flows.

## 37. Product principle

> Does this make it easier for someone to prayer-walk another street today?

If not, it goes in the future-feature backlog. The architecture should support
expansion; the V1 interface stays focused on one task: help people collectively pray
over every eligible street and household in Blacksburg.
