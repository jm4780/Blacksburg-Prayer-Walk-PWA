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

## Open decisions

- **D2 — Which trails count (spec §17).** Recommendation: Huckleberry Trail inside
  town limits is REQUIRED; everything else in Paths-to-the-Future is connector-only
  until specifically added. **Needs a reviewed list.** Blocks the Phase 2c curation pass.
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
