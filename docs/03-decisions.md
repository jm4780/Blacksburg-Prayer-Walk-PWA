# Decision Log

Decisions that shape data or product behavior, with the reasoning at the time. Open
items live at the bottom. Superseded decisions are struck through, never deleted —
route quality and metric changes need to be traceable to a decision.

---

## D1 — Virginia Tech campus: **INCLUDED** ✅

**Decided:** 2026-08-02 by Jacob.
**Decision:** Include the Virginia Tech campus in the coverage project. Count dorms
toward the household estimate using a documented estimate.

This supersedes the Phase 1 recommendation to treat campus as connector-only. The
ministry case is straightforward: praying for students is a core motivation, and
excluding ~10,000 residents living inside the town boundary would have been a strange
gap in a project whose stated goal is to pray over *every* eligible street and
household in Blacksburg.

Three implementation questions follow from it, answered below.

### D1a — Which campus geometry is REQUIRED?

Virginia Tech's main campus is **2,600 acres ≈ 4.1 sq mi**, against Blacksburg's
**19.77 sq mi** of land area. Campus is roughly **20% of the town by area** — so
"include campus" is not a rounding adjustment, it materially changes the denominator
of the headline metric.

But most of that acreage is agricultural research land, the airport, and the golf
course. Blanket inclusion would load the denominator with miles of farm service roads
that pass zero households, making "% of Blacksburg prayed for" crawl for no ministry
gain, and sending people on genuinely unpleasant walks past fields.

**Decision:** include the **developed campus core** — academic core, residential
quads, athletics precinct, and the named campus streets serving them. Exclude the
agricultural/research land, the airport, and the golf course, treating any roads
through them as `OPTIONAL_CONNECTOR` where they usefully link eligible areas.

This requires a **hand-drawn "campus core" polygon** as a Phase 2c curation artifact.
It is the boundary between "we prayed for campus" and "we walked past a soybean
trial." Drawing it is a 30-minute job on a map and should be done with Jacob present.

### D1b — Pedestrian paths on campus are REQUIRED, not connectors

This is the most consequential detail, and it inverts the rule used everywhere else in
town.

Off campus, sidewalks are absorbed into their parallel street and only genuine
shortcuts become `PEDESTRIAN_CONNECTOR` edges (see the technical plan, §2.3). **On
campus that rule fails.** The residential quads, the Drillfield perimeter, and the
paths threading between academic buildings and residence halls are not adjuncts to a
street network — they *are* the network. Students live along footpaths, not along
roads. A campus modeled from roads alone would route people around the outside of
the dorm quads and call campus complete, which would defeat the entire purpose of
including it.

**Decision:** inside the campus core polygon, major pedestrian ways carry
`segment_type = PEDESTRIAN_CONNECTOR` (or `TRAIL`) but `role = REQUIRED`. Minor
building-access spurs, service paths, and parking-lot connections stay
`OPTIONAL_CONNECTOR` or `EXCLUDED`.

Selecting "major" from "minor" here is curation work, not a rule. Rough guide: if it
is a path a student walks daily between where they sleep and where they study, it
counts.

### D1c — How dorms are counted as households

VT houses roughly **9,300–10,500 students in 47 residence halls** on campus.

| Method | Campus "households" | Share of town total | Verdict |
|---|---|---|---|
| One per residence hall | 47 | ~0.3% | Undercounts ~10,000 people to nearly nothing |
| One per **room** | **~4,700–5,300** | **~26%** | ✅ Chosen |
| One per bed | 9,300–10,500 | ~43% | A shared double is one door, not two homes |

**Decision: count rooms.** A dorm room is the closest analogue to a household — a
door, and a small group of people living behind it. Estimate as
`beds ÷ 2` per hall (typical double occupancy), refined per-hall where VT publishes
suite or single-room configurations.

Expected effect on the headline metric: town households ~13,800 + campus ~5,000 ≈
**18,800 estimated households**, with campus about a quarter of the total. That is a
big enough shift that Jacob should see and approve the actual computed number before
launch, not discover it afterward.

Two safeguards:

1. **`household_estimate.household_type`** (`RESIDENTIAL` | `STUDENT_RESIDENCE`)
   so the split is always recoverable and the convention can be re-cut later without
   rebuilding the network.
2. **`confidence = LOW`** on all dorm estimates, with the per-hall bed counts and
   their source recorded. The public label stays "estimated," which is exactly what
   it is.

**Data source:** a curated residence-hall list (name, footprint, bed count, room
estimate) built from VT Housing & Residence Life published capacities joined to
building footprints. This is a **new Phase 2 curation artifact** — one table of ~47
rows, built by hand once. Off-campus student apartments (Foxridge, The Edge, Terrace
View, etc.) need none of this: they are ordinary address points and are already
counted as `RESIDENTIAL`.

**Greek housing:** Oak Lane on-campus houses get the same room-based treatment;
off-campus chapter houses are ordinary address points.

### D1d — Consequences to watch

- **The percentage will move more slowly.** A bigger denominator is the cost of a
  more honest goal. Worth saying plainly to the congregation at launch.
- **Campus is dense in households per mile**, so campus walks will show high
  household numbers relative to their distance. That is real, not a bug.
- **The router's cluster scoring will favor campus early** because of that density.
  If campus dominates the first weeks of routing at the expense of neighborhoods,
  turn it down with a per-zone priority nudge rather than by re-weighting households
  globally.
- **Football Saturdays and move-in week** make parts of campus unpleasant to walk. Not
  worth modeling in V1; mention it in the pilot notes.

---

## D2 — Which trails count: **Huckleberry confirmed**, rest recommended ⏳

**Decided (partial):** 2026-08-02. Huckleberry Trail confirmed by Jacob. The
recommendations below await a yes/no.

### The test

A trail earns `REQUIRED` if it **passes households** or **functions as a neighborhood
connector people walk for transportation**. Being pleasant woods is not sufficient.

Note what this test is *not* based on. For the campus (D1a) the argument against
blanket inclusion was denominator bloat. That argument is weak here: Blacksburg's
required street network will be on the order of 200–250 miles, so even six miles of
Huckleberry is ~3%, and a few extra trails would barely move the percentage. The real
reasons to keep wooded trails out are different and better:

1. **No households** — a wooded loop generates no ministry value under the project's
   own stated goal.
2. **Route quality** — a required dirt trail with serious elevation is a genuine
   router problem. Gateway Trail is 3.7 mi with **869 ft of gain**; as a REQUIRED
   segment it would sit incomplete indefinitely, and then the aging bonus (D-plan
   §4.3, Stage 3) would eventually force a mountain hike into somebody's "Extended"
   prayer walk. That is a bad experience produced by a correct algorithm.
3. **Practicality** — these are destination hikes, not the 30–60 minute walk from your
   front door that this app is built around.

### Recommendation

**`REQUIRED`:**

- **Huckleberry Trail**, in-town portion including **Huckleberry North** — confirmed.
  The town's spine: paved, passes neighborhoods and commercial areas, genuinely used
  for transportation.
- **Deerfield Trail** (Toms Creek Rd at Deerfield Dr) and **Shenandoah Bike Trail**
  (off Toms Creek Rd / Patrick Henry Dr) — short paved neighborhood trails embedded in
  residential areas north of town. These are effectively streets without cars, and
  they pass homes. ⚠️ *Verify against GIS: confirm length and that they front
  households rather than running behind fences.*

**`OPTIONAL_CONNECTOR`** (walkable, never counted, usable to close loops):

- **Heritage Community Park & Natural Area** paved walkways and **Gateway Park** paths
  — in town and worth walking, but park interiors with no adjacent homes. Valuable to
  the router for making loops; should not inflate the denominator.
- **Gateway Trail** (Jefferson NF, 3.7 mi, dirt, 869 ft gain) and onward to Poverty
  Creek / Pandapas Pond — see reason 2 above.

**Out of the coverage area entirely** (available as `OUT_OF_AREA_CONNECTOR`):

- **Coal Mining Heritage Park loop** (1.5 mi, county park at 751 Merrimac Rd) and the
  **Huckleberry south of the town line** — outside Blacksburg, so out of scope for the
  town project. Natural candidates for a future Montgomery County coverage area.

### Two implementation notes

- **Surface and grade gate trail eligibility.** Spec §17 already asks trails to carry
  surface and accessibility attributes; the classifier should use them, so "paved and
  flat enough to pray on" is a data property rather than a case-by-case judgment.
- **Walking the full Huckleberry to Christiansburg already works correctly.** Only the
  in-town portion counts toward coverage, but spec §6.2 counts the whole walked
  distance — including out-of-town portions — toward "total miles walked." Someone who
  walks the full 15 miles gets credit for 15 miles walked and coverage for the ~6
  in-town. No special handling needed; worth explaining in the UI once.

---

## Open decisions
- **D3 — Out-of-town connector allowance.** How far past the boundary may a route
  wander to close a loop? Suggested default: 0.5 mi, penalized.
- **D4 — Data refresh cadence.** Suggested: quarterly plus on demand, each refresh a
  human-reviewed build promotion, never automatic.
- **D5 — Admin access.** How many admins; password vs. magic link.
- **D6 — Hosting budget.** Confirms Fly.io/Render + Cloudflare Pages, roughly
  $20–40/month.
- **D7 — GitHub write access.** The session's GitHub integration is read-only, so
  Phase 1 work is committed locally but unpushed. See the session notes.

## Sources

- [VT Housing & Residential Experience](https://housing.vt.edu/) · [VT Housing overview](https://www.vt.edu/campus-life/housing.html) · [Facts About Virginia Tech](https://www.vt.edu/about/facts-about-virginia-tech.html) · [Campus of Virginia Tech](https://en.wikipedia.org/wiki/Campus_of_Virginia_Tech) · [BOV housing expansion (2026)](https://news.vt.edu/articles/2026/06/cm-bov-housing.html)
- [Census QuickFacts — Blacksburg town](https://www.census.gov/quickfacts/fact/table/blacksburgtownvirginia/PST045224)


---

## Rulings applied at Phase 3 (2026-08-03) — canonical network v1.2

| Decision | Was | Now | Where |
|---|---|---|---|
| **D1b** — which campus ways are REQUIRED | `OPTIONAL_CONNECTOR` / `NEEDS_REVIEW` | **One coverage obligation per campus corridor.** The canonical side is `REQUIRED` (73 segments, 11.360 mi); the parallel walkway stays a connector and *satisfies* the same obligation rather than creating a second one. | `curation.CAMPUS_PROMOTE_CANONICAL_TO_REQUIRED`, `campus_normalize._link_alternatives`, `network.credited()` |
| **D2** — Deerfield Trail | `REQUIRED` / PROVISIONAL | `REQUIRED` / **CONFIRMED** | `curation.TRAIL_ROLES` |
| **D2** — Shenandoah Trail | `REQUIRED` / PROVISIONAL | `REQUIRED` / **CONFIRMED** | `curation.TRAIL_ROLES` |

The D1b ruling is a *selection*, as D1b asked for — but the selection is made by rule
rather than by naming streets: one obligation per corridor. Promoting all 114 campus
pedestrian segments would have demanded 13.403 mi of walking to cover 11.359 mi of
distinct ground, and Drillfield Drive would not have counted as done until someone had
walked both sides of it. Spec §4.2 already says walking one side counts.

Consequence, recorded rather than hidden: campus pedestrian geometry does not join the
town street graph through any *trusted* connector, so the promotion stranded 12.858 mi
of required mileage off the main component and created two new valid routing areas.
See docs/13 §1 and §21.
