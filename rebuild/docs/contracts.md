# Interface contracts

Agreed before any component was written. Anything not written down here is a
component's private business; anything written here may not change without
changing this file first.

Everything below is already true and running: Postgres 16 + PostGIS 3.4 on
`localhost:5432`, database `bbg`, 1,553 segments / 156.54 mi loaded.

---

## 0. Shared vocabulary

| term | meaning |
|---|---|
| **segment** | One named street between two junctions. The unit a walker confirms and the unit the town map fills in. Never subdivided at runtime. |
| **coverable** | A segment that counts toward the town total. Everything in the `segment` table is coverable; non-coverable ways were dropped at build time. |
| **covered** | A segment that appears in the `coverage` table. Permanent, and set by the first walk to claim it. |
| **confirmed** | A walker has explicitly said "yes, I walked this" on the confirm screen. Nothing reaches `coverage` any other way. |

---

## 1. Data layer → everyone  *(built, frozen)*

`segment` table, and the identical `rebuild/data/out/network.geojson`:

```
seg_id    integer   stable across a build, not across rebuilds
name      text      never null, never empty  e.g. "Progress St"
ref       text|null e.g. "US 460 Bus"
class     text      motorway | minor  (link/ramp never appears)
length_m  float     metres, clipped to the town limit
node_a    text      junction id, "gx_gy" on the z13/4096 grid
node_b    text      junction id
homes     int|null  ALWAYS NULL in this build. See §6.
carriageway int|null both sides of a divided road carry the same value, which
                    is the seg_id of the pair's representative. Null (the
                    ordinary case) means the segment stands alone. See §7.
geom      LineString, EPSG:4326
```

Two segments are topologically adjacent iff they share a node id. That is the
only adjacency rule; do not infer adjacency from proximity.

Counts, in the two sizes that matter:

| | |
|---|---|
| segments | 1,598 — routing and matching work in these |
| countable units | 1,489 — coverage and percentages work in these |
| drawn length | 156.54 mi |
| countable length | 149.20 mi |

---

## 2. Coverage engine

**Owns:** deciding which segments a recorded walk actually covered.
**Must not:** write to the database, or commit anything.

```python
propose(trace, network, *, now=None) -> list[Proposal]

trace    : list[Fix]  Fix = {lat, lon, accuracy_m, t (epoch seconds)}
network  : the segment set (loaded once)

Proposal = {
    seg_id: int,
    name: str,
    confidence: float,      # 0.0-1.0
    matched_m: float,       # metres of this segment the trace covers
    reason: str,            # human-readable, shown to no one but the tests
}
```

Rules, in priority order:

1. **A wrong match is worse than a missing match.** Downtown parallel streets sit
   ~60 m apart and consumer GPS drifts further than that. When the evidence does
   not clearly separate two candidates, return neither, or return the one the
   walker was topologically able to reach and mark it low confidence.
2. Matching is **topological**, not nearest-line. A candidate segment must be
   reachable from the previously matched segment through shared node ids.
   Teleporting to a parallel street is thereby structurally impossible.
3. Use heading. A trace running north cannot match an east-west street.
4. Weight each fix by its own `accuracy_m`. A 65 m fix votes far more weakly
   than an 8 m fix.
5. A gap in `t` longer than 90 s is a **dropout**: end the current chain and
   start a new one. Never interpolate across a dropout.
6. Return `confidence < 0.5` for anything the confirm screen should show
   unticked. The walker ticks it on if they really walked it.

**Never** does this engine decide coverage on its own. Its output is a
*proposal* for a human to accept.

---

## 3. Route engine

**Owns:** generating a walk.
**Must not:** read `coverage` directly. Uncovered set is passed in.

```python
generate(start_lonlat, target_m, network, covered: set[int], *, seed=None) -> Route

Route = {
    seg_ids: list[int],       # in walking order, may repeat (deadheading)
    new_seg_ids: list[int],   # the uncovered ones this walk would claim
    geometry: LineString,     # for drawing
    length_m: float,
    new_m: float,
}
```

This is a rural postman problem on the uncovered subgraph. Solve it as one.

Optimise, in this order:

1. **Closes the loop.** Ends within 100 m of where it started. A walk that
   strands someone a mile from their car is a failed walk.
2. **`length_m` within ±15% of `target_m`.** Someone with 30 minutes has 30
   minutes.
3. **Maximise `new_m`.** Uncovered street captured is the whole point.
4. **Contiguity.** Prefer one connected neighbourhood over scattered spurs, so
   the town map fills in as regions. Measure it and report it.
5. **Safety.** Never route a walker along `class = motorway` unless
   `ref = 'US 460 Bus'`. Prefer segments that share junctions with many others
   (a grid) over long isolated stretches.

---

## 4. API

FastAPI on `:8000`. JSON everywhere. No auth; a device id is a claim, not a
credential, and nothing in the schema can be damaged by a forged one.

```
GET  /api/network              -> {segments: [{seg_id,name,length_m,geometry}]}
GET  /api/progress             -> {segments_covered, segments_total,
                                   covered_m, total_m, percent,
                                   homes_covered|null, homes_total|null}
GET  /api/coverage             -> {covered: [seg_id, ...]}
POST /api/route                -> body {lon, lat, minutes} -> Route (§3)
POST /api/walk                 -> body {device_id, client_walk_id,
                                        display_name?, started_at?,
                                        seg_ids: [int]}
                                  -> {walk_id, newly_covered: [int]}
POST /api/match                -> body {trace: [Fix]} -> {proposals: [Proposal]}
```

`POST /api/walk` is **idempotent on `(device_id, client_walk_id)`**. The client
mints `client_walk_id` before the walk starts and reuses it on every retry
forever. This is what makes airplane mode safe.

---

## 5. App shell

**Owns:** everything the walker sees, the offline queue, the wake lock.

Hard requirements:

- Works with location permission **denied**. Full manual street selection.
- A walk in progress survives a reload, a suspend, and a kill. Persist to
  IndexedDB on every change, never only in memory.
- The offline queue retries forever with the same `client_walk_id`.
- **Nothing commits without an explicit confirm tap.**
- No raw coordinate is ever sent to the server outside `POST /api/match`, and
  `/api/match` stores nothing.

---

## 6. Homes: built, and dark

`segment.homes` is null for every row, on purpose. No address-point source is
reachable from this build environment, so there is no honest number to show.

Every layer must handle null by **showing nothing at all** rather than showing
zero. A zero is a claim that no one lives on that street. The API returns
`homes_covered: null`, and the interface renders no home line. When a real
address source is wired in, populating `segment.homes` lights the counter with
no other change anywhere.

---

## 7. Divided roads

A dual carriageway is drawn as two parallel lines. Prices Fork Rd, US 460 Bus
and Alumni Mall are the big ones here: 109 pairs, 7.34 mi of duplicate.

Left alone that breaks the central promise twice. The denominator counts the
road twice, so the town can never reach 100%. And a walker who walks Prices Fork
Rd covers one line while the other stays unprayed for ever, because there is no
way to walk the far side of a median and no reason to ask anyone to.

So both lines stay in the graph, since routing needs the real topology, and they
share a `carriageway`. Two rules follow, and every component must obey them:

- **Coverage is per carriageway.** `commit_walk` marks every segment sharing a
  carriageway with anything walked. Walk one side, the road is prayed for.
- **The denominator is per carriageway.** The `street_unit` view takes the
  longer of the two lines, never their sum.

Pairing is mutual-best and therefore always exactly two segments. Transitive
grouping was tried and is wrong: along Prices Fork Rd the north line of one
block lies within tolerance of the south line of the next, so a union-find walks
the length of the road and ends up claiming two miles are prayed for because
somebody walked one block.
