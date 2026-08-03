# Phase 3.4 — Engineering review: mission planning

An assessment of the proposed realignment. No code has been changed.

**Headline:** the direction is right, and the engine is better positioned for it than
you'd expect — the start point is already a parameter, not an assumption. Dropping the
GPS-start requirement makes the *inner* routing problem meaningfully simpler, not
harder. But it moves a hard problem outward, and there is one consequence that has to
be designed for rather than discovered: **if everyone asks for the best walk, everyone
gets the same walk.**

---

## 1. How these ideas fit the current architecture

Better than I expected, for one structural reason: `Engine.best_route(start_node,
target_miles, state)` takes the start as an **argument**. Nothing inside the engine
believes the start came from a phone. Every assumption about "the user is standing
here" lives in the *caller* — the API layer and the UI.

That means most of this realignment is a change to who calls the engine and with what,
not a change to the engine.

### What "the engine picks the start" actually does to the routing problem

Today, five things depend on the start being fixed and externally imposed:

| Where | What it does | With an engine-chosen start |
|---|---|---|
| `snap()` | nearest node in a valid component | **gone** |
| `discover_clusters` | finds work, scores it by *distance from the walker* | simplifies — the walker is at the work |
| radius = budget/2 | only consider work you can reach and return from | **gone** |
| `_anchor_setup` | drops candidates whose round trip won't fit | simplifies — everything in the cluster is near |
| feasibility invariant | `used + cost + distance_home ≤ budget` | **unchanged, still needed** |

A large amount of the current engine exists to answer one question: *is this work worth
walking to from where you happen to be standing?* That question is what produces the
approach leg, the half-budget radius, `access_m`, `usable_m`, `nearest_incomplete_miles`
and four of the five late-opportunity states.

Remove the premise and that machinery goes with it. The route becomes: **a good closed
walk inside a cluster of remaining work.** That is a smaller, cleaner problem than the
one we're solving today.

### But the difficulty moves outward, and changes character

The new question — *which cluster, and where in it should the walk begin?* — is
formally harder. It's the same optimisation with an extra free variable, so the search
space is roughly the number of candidate start nodes times bigger.

It's harder in a way that doesn't matter, though, because it comes off the critical
path. Today a route must be found in the seconds a person will wait. A *mission* can be
computed overnight, or in the background whenever the town's completion state changes.

Rough cost, from measured performance (14.8 ms per route): a cluster has on the order of
20–80 plausible start nodes; trying all of them is 0.3–1.2 s per cluster; a full
town-wide slate across ~30–60 clusters is **tens of seconds**. That is a background job,
not an engineering problem. And you don't need to try every node — a high-degree
intersection near the cluster's centre is a good first guess.

**Net: the latency-critical part gets simpler; the new complexity lands somewhere that
can afford it.** That's a good trade and the strongest technical argument for the
change.

---

## 2. UI changes vs engine changes

| Idea | Where the work is | Size |
|---|---|---|
| Hide routing scores, walk quality, coverage gain | **UI only** | Hours. API keeps returning them. |
| Dashboard emphasises the three mission metrics | **UI only — already true** | None. See §3. |
| Time slider instead of distance bands | **Mostly UI**, plus one real engine question | Small–medium |
| Mission-style route descriptions | **UI + a naming source** | Medium — see §5 |
| Engine chooses the start | **Engine + new precompute layer** | The big one |
| Home screen answers "what's my next walk?" | **New service layer**, engine unchanged | Medium |

The important line: **only one of these six is really an engine change**, and even that
one is mostly *new code beside the engine* rather than surgery inside it.

---

## 3. What already supports this philosophy

More than I expected. In rough order of how much it helps:

1. **The start is a parameter.** `best_route(start_i, target_miles, state)`. Choosing
   `start_i` differently is a caller change.
2. **`discover_clusters` is already mission discovery.** It does union-find over
   incomplete required segments and scores each cluster by how much work it holds. That
   is exactly "where is there a worthwhile chunk of praying left to do." Today it's
   scoped to the walker's component and discounted by distance from them; both are
   parameters to relax, not logic to rewrite.
3. **The engine is stateless.** `CompletionState` is passed in per call. Precomputing
   hundreds of missions in parallel is safe by construction — there is no shared state
   to corrupt.
4. **`target_miles` is already a float.** The five bands are a constant list, not a
   structural assumption. Continuous time needs no engine change to *accept*.
5. **Reservations are already prize multipliers, not locks.** This is precisely the
   mechanism mission assignment needs — steer people apart softly rather than
   partitioning the town.
6. **The dashboard metrics are already the three you named.** Overall completion,
   estimated households, total miles. Nothing to add; the change is subtraction
   elsewhere.
7. **Component classification already knows** which areas are independently walkable,
   how much required mileage each holds, and which lengths they can support.
8. **Seeds and versions are stored on every route.** A precomputed mission stays
   reproducible and auditable — the feedback mechanism keeps working unchanged.
9. **Performance headroom is large.** 14.8 ms per route is what makes the precompute
   approach viable at all.

### One thing we already have and have never used

The Town's road data carries a **neighbourhood name on every street**: `NbrhdCom_L` /
`NbrhdCom_R`, populated on 1,528 of 1,547 records, 33 distinct values —
*Hethwood/Prices Fork*, *Tom's Creek*, *Downtown*, *Miller Southside*, *Kabrich
Crescent*, *Northside Park*.

This is the missing vocabulary for mission descriptions, and it is sitting in a file we
already download. It needs the same light cleaning the street names got in Phase 2a —
there are case duplicates (`TOMS CREEK` / `Tom's Creek`), a slash inconsistency
(`Kabrich/crescent`), and one typo (`MCBYDE`). Perhaps 22 real neighbourhoods after
normalisation.

**But a neighbourhood is not a mission.** Median neighbourhood is 4.45 miles — about 90
minutes — and the largest are five to six hours:

| | miles | at 3 mph |
|---|---|---|
| Tom's Creek | 18.30 | 6 hours |
| Hethwood/Prices Fork | 15.22 | 5 hours |
| Downtown | 4.45 | 89 min |
| Bennett Hill/Progress | 2.61 | 52 min |
| Murphy | 1.27 | 25 min |

So "Finish Hethwood" is a **season**, not a walk. That's not a problem — it's arguably a
better story than a single walk. Use neighbourhoods for *narrative and progress*
("Hethwood is 60% prayed for") and sub-clusters within them for *today's mission* ("the
north end of Hethwood, about 40 minutes"). Only the genuinely small neighbourhoods, and
small components like the Corporate Research Center, are finishable in one outing — and
those are exactly the cases where "Finish X" is truthful and satisfying.

---

## 4. Where the current implementation conflicts

Honest inventory, worst first.

1. **The five bands are load-bearing in the UI and the tests.** `VARIANTS`, the nesting
   guarantee in `variants()`, `SizeSlider`, `Component.supports_bands`,
   `complete_area_miles`. Roughly 54 assertions across five backend test files and 17 in
   the component tests reference band names or snapping. Continuous time doesn't break
   the engine; it breaks a lot of *tests and interface*.

2. **Four of the five late-opportunity states exist only because the start is imposed.**
   `NO_USEFUL_ROUTE_NEAR_START`, `SELECT_DIFFERENT_START_AREA`, `LONGER_ROUTE_REQUIRED`,
   `LIMITED_LOCAL_COVERAGE` are all answers to "you're standing in a bad spot." If the
   engine picks the spot, they mostly stop occurring. That's a *feature* — a large
   category of bad experience disappears — but `response.py` and its interface copy were
   built around them and would be substantially rewritten.

3. **Reservations were designed for spatially-dispersed walkers.** See §6, pushback 1.
   This is the one genuine architectural risk in the proposal.

4. **Walking speed is currently cosmetic and would become load-bearing.** `WALK_MPH =
   3.0` appears in two places and is used only to *display* an estimate. If time becomes
   the input, that constant decides how far someone actually walks. Being 20% wrong
   turns a 35-minute request into a 42-minute walk — a broken promise, on the one number
   the user gave us.

5. **The start-location plumbing is threaded through the stack** — `start_source`, the
   Blacksburg bounding-box guard, snapping restricted to valid components,
   `coverage_area_id` derivation, the one-time-location screen and its consent copy.
   None of it is wasted (see pushback 2), but it stops being the primary path.

6. **"Complete this area" for small components** is currently triggered by the walker
   happening to stand in one. Under mission planning it becomes something the engine
   *offers* — which is better, but it's a different code path.

---

## 5. Recommended sequence

Ordered so that each step ships independently, the engine is untouched until step 3,
and nothing is deleted before its replacement works.

**Step 0 — Calibrate walking speed. No code.**
The pilot already records `started_at` and `resolved_at` on every walk, and the planned
distance. Before making time the primary input, find out what a prayer-walking mile
actually costs. My expectation is that it's slower than 3.0 mph — people praying don't
walk like people commuting — but that's a guess and the pilot will replace it with a
number. *Zero risk, and it gates step 6.*

**Step 1 — Hide the engineering metrics. UI only.**
Remove walk quality, route score, efficiency and coverage-gain from the walker's
screens. Keep them in the API and the admin view. About a day, and the app immediately
reads more like a guide and less like a tool.

**Step 2 — Make the existing bands speak in time. UI only.**
"About 20 minutes" instead of "2.0 mi", still five stops. This gets the *language* right
before changing the *mechanism*, and it's reversible. It also surfaces any speed problem
early, cheaply.

**Step 3 — Mission discovery. New module, engine untouched.**
A new `api/routing/missions.py` that calls the existing `discover_clusters` town-wide
rather than scoped to a start, picks a sensible start node per cluster, and runs the
existing `best_route` from it. Output: a ranked slate of candidate missions. Nothing
existing changes; this is additive and independently testable against the current
engine's behaviour.

**Step 4 — Names. Canonical network v1.3.**
Add normalised neighbourhood names to the network from `NbrhdCom_L/R`. Missions become
"the north end of Tom's Creek" instead of "cluster 7". This is a pipeline change of the
kind already done twice, and it's a version bump, not a rewrite.

**Step 5 — Precompute, store and assign.**
Persist the mission slate, expire it when completion state changes, and assign missions
to participants so two people don't get the same one. This is where pushback 1 gets
solved. Home screen becomes "today's walk."

**Step 6 — Continuous time.**
Only now, with missions in place and speed calibrated, make the slider continuous by
regenerating the mission at the requested budget.

**Step 7 — Demote, don't delete, current location.**
See pushback 2.

The first two steps are worth doing regardless of whether the rest happens.

---

## 6. Pushback

### 1. "Best next walk" is a global optimum, and global optima collide — this is the real architectural risk

Today, route diversity is free: people are in different places, so they get different
walks. That is the *only* thing currently preventing collision at scale, and this
proposal removes it. If five people open the app on Saturday morning and each asks for
the best 45-minute walk, the honest answer for all five is the same walk.

Reservations damp this, but they were sized for incidental overlap, not for every
request converging on one place. The concentration is qualitatively different.

This is solvable, and the solution shapes step 5: precompute a **slate** of good
missions rather than a single best one, and assign deterministically per participant.
The user still sees one recommendation and makes one decision — they just don't all see
the *same* one. Reservations then handle the residual.

I'd want this designed before step 5, not discovered during it. It's the one place where
"the engine quietly decides" could produce a visibly worse experience than what we have
now.

### 2. Don't remove current location — move the decision to sign-up

I'd push back on making every walk start somewhere you drive to.

Your example — *Finish the Corporate Research Center* — is a place you'd drive to. But
Hethwood is a place people **live**. For a church whose members live in the town they're
praying for, "near me" is frequently the *right* answer, not a compromise. A system that
routinely answers "drive across town" has added a car journey to a prayer walk, and will
quietly lose the Tuesday-evening-after-dinner walk, which is probably the most repeatable
kind.

But you're right that asking every time is a decision too many. So: **ask once, at
sign-up.** "Which part of town are you closest to?" — a list of the ~22 neighbourhoods.
The engine then biases toward missions near home, and overrides that only when there's a
genuinely better one elsewhere, saying so ("this one's a short drive, and it finishes the
Research Center").

That keeps the one-decision promise per walk, keeps the app useful for people who just
want to step out of their front door, and preserves the location plumbing we already
built and tested rather than deleting it.

### 3. Greedy "best next walk" is not the best way to finish a town

This is the deepest point, and it's an argument *for* your framing rather than against
it — mission planning is a genuinely more interesting problem than route generation, and
worth doing properly.

Always assigning the densest remaining cluster is locally optimal and globally poor. It
harvests the easy, high-household areas first and leaves a scattered tail of awkward
fragments — precisely the endgame the Phase 2b stress tests explored, where at 98%
completion the only work left is isolated dead ends and route quality collapses.

A real mission planner should sometimes assign a *less* impressive walk to avoid
fragmenting coverage — finish the edge of a neighbourhood rather than start a new one.
The objective changes from "best walk today" to "best sequence of walks over a year," and
those genuinely differ.

I'd not build this in step 3. But I'd design the mission scorer so a completion-shape
term can be added later without restructuring, and I'd avoid shipping copy that promises
optimality we haven't implemented.

### 4. Keep the metrics in the API; only hide them in the UI

Small but worth stating explicitly. Walk quality, score components and coverage gain
should stop appearing on the walker's screens — agreed. They should keep flowing through
the API, because pilot feedback reproducibility, admin diagnosis and any future tuning
all depend on them. Hiding is a one-line UI change; deleting is unrecoverable and would
undo the reproducibility work from Phase 3.1.

### 5. "Continuous" should be continuous to the eye, quantised underneath

A slider that reads "37 minutes" implies a precision the engine cannot honour —
individual walking-pace variation swamps a one-minute difference, and two adjacent
positions would return visibly different routes for no reason the user can perceive.

Recommend: slider feels continuous, snaps to 5-minute steps internally, labels itself
"about 35 minutes." Same feel, no false precision, and route caching stays practical.

### 6. Mission framing raises the stakes on honest labelling

"Finish the Corporate Research Center — about 50 minutes, approximately 280 households"
is a good, motivating sentence. The risk is that the same sentence generator will happily
produce **"Finish the Drillfield — about 55 minutes, approximately 0 households"**.

Phase 3.1 established that campus routes pass zero homes and are forced out-and-backs on
a near-tree. Today the interface presents those neutrally, as a route. A mission framing
presents them as an *objective*, which makes a weak walk look like a worthwhile one.

Not a reason to avoid mission framing — a reason for the mission scorer to be honest
about which missions are worth assigning, and for the description to say what a walk
genuinely is: "campus paths, no homes on this one."

### 7. Minor: be careful with the word "best"

"Your best next walk" is a claim the walker can falsify by walking it. "Today's walk"
or "suggested for you" is just as confident and doesn't set up a promise about
optimality that the greedy planner in step 3 won't be keeping yet.

---

## Summary

- The engine is well-placed: the start is already a parameter, the engine is stateless,
  and clusters are already discovered and scored.
- Removing the GPS start makes the **inner** problem simpler and deletes a whole class of
  bad experiences. It makes the **outer** problem harder, but that part can be
  precomputed, and performance headroom is ample.
- Five of the six ideas are UI or additive-service work. One is a real engine change,
  and even that is mostly new code beside the engine.
- The main risk is collision, not correctness. Design the mission slate before building
  it.
- The main product risk is making people drive. Ask for a home neighbourhood once at
  sign-up rather than removing "near me" altogether.
- Steps 1 and 2 are worth doing whatever else you decide.

---

## 7. Keeping the routing engine reusable

Added in response to the constraint about future reuse for other coverage problems
(running every street, canvassing, inspections). Assessed, not implemented.

**Good news: the engine is already almost entirely domain-free, and the layering you
want already exists.** `api/routing/` is the engine; `api/app/` is the prayer-walking
application. The application layer owns "prayed for", "walks", "estimated households
prayed for", and all the mission language. The engine layer talks about segments,
coverage, components, completion state and routes.

I audited it rather than assuming. Prayer-specific language inside the engine amounts
to **five occurrences, four of them cosmetic**:

| Where | What | Verdict |
|---|---|---|
| `network.py:134` | a code comment ("unprayed-for") | harmless |
| `state.py:106` | a code comment ("congregations work outward") | harmless |
| `viz.py` ×2 | HTML title of a development-only visualisation | harmless |
| **`response.py:123`** | **a user-facing string: "mi of streets not yet prayed for"** | **a real leak** |

That last one is worth noting because it violates a rule the file already states in its
own docstring — *"Every state carries the numbers an interface needs to write its own
sentence. No copy is composed here."* One line slipped through. Steps 3 and 5 of the
sequence above will rewrite `response.py` anyway, so the fix is free at that point.

### The one genuinely domain-named concept: `households`

`Segment.households`, `Weights.household`, `RouteScore.households`,
`Component.households`. The *concept* is generic — "how much value sits on this
segment" — and every coverage application has one: households for canvassing, assets
for inspections, nothing at all for running every street. Only the name is
prayer-adjacent.

Renaming it (`segment_value`, or `weight`) is about six identifiers. **I would not do it
now**, for a reason worth recording:

> `score_components` is **persisted as JSON** on every stored walk, and `rescore()`
> reads those keys back to re-evaluate historical routes under new weights. Renaming the
> Python identifiers without versioning the stored keys would silently break rescoring
> of every walk recorded before the change.

So if this is ever done, it's a rename *plus* a stored-key compatibility shim — not the
one-line change it looks like. Best done opportunistically, when mission work is already
touching `score.py`, and with the stored keys either kept stable or explicitly versioned.

### On "Projects"

There is no `Project` concept today, and I would not add one. A `project_id` column that
only ever holds one value is carrying cost for a payoff that may never arrive.

What matters is only that nothing *precludes* it, and nothing does: the network is
already loaded by an explicit snapshot identifier rather than a hard-coded global, and
the engine holds no module-level state about which town it is serving. When the mission
store is built in step 5, the thing to avoid is caching missions in a module-level
global that assumes a single network — a per-network key costs nothing and keeps the
door open.

### How this changes the recommendations above

Very little, which is the point. Two small adjustments:

1. **Mission naming and description belong in `api/app/`, not `api/routing/`.** The
   engine should return a cluster with its segments, its neighbourhood names and its
   metrics. Turning that into *"Finish the north end of Tom's Creek — about 40 minutes,
   roughly 180 households"* is application work. This is the right split anyway: the
   sentence is a product decision that will be revised often, and it has no business
   living next to the search algorithm.

2. **Mission *discovery* is engine work; mission *assignment* is application work.**
   "Which clusters of remaining coverage are worth a visit, and what's a good closed walk
   in each" is generic across every coverage problem. "Who gets which one, and what do we
   call it" is specific to a church running a prayer campaign. Step 3 should land in
   `api/routing/`; step 5 should land in `api/app/`.

Neither of those makes today's application more complicated — if anything the split is
the one I'd have picked regardless, because it keeps the part that changes weekly (copy,
assignment policy) away from the part that must stay stable and tested (search,
scoring).
