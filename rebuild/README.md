# Blacksburg Prayer Walk — rebuild

A second build, from scratch, alongside the existing one so the two can be
compared. Nothing here reads or depends on the code outside `rebuild/`, with two
exceptions that are data, not code: the committed town boundary polygon and the
committed basemap archive.

Open the app and see prayed against unprayed streets on the town's own map. Say
how long you have. Get a loop that starts and ends where you are and takes in
streets nobody has covered. Walk it. Confirm what you actually walked. The town
map moves.

## Run it

```bash
# database (Postgres 16 + PostGIS 3.4)
python3 rebuild/data/pipeline/extract_network.py     # build the network
python3 rebuild/db/load_network.py                   # schema + load

# api
cd rebuild && python3 -m uvicorn api.main:app --port 8000

# app
cd rebuild/web && npm install && npm run dev         # :5173, proxies /api
```

Tests:

```bash
python3 -m pytest rebuild/tests/            # 47: 32 route, 15 coverage
cd rebuild/web && npm test                  # 26
python3 rebuild/tests/five_routes.py        # renders five walks for inspection
```

## What is here

```
data/pipeline/   extract_network.py     the network, from the committed basemap
                 fetch_authoritative.py the same network from Town GIS, unrun
db/              schema.sql             coverage, walks, carriageways
engine/          coverage.py            which streets a walk actually covered
                 route.py               which streets to walk next
api/                                    FastAPI over the above
web/                                    React PWA, mobile first
docs/            contracts.md           the interfaces, agreed before any code
                 data-provenance.md     where the streets came from, and the error
tests/           five_routes.py         the final check, rendered for a human
```

## Read this before trusting a number

**The street network is provisional and about 9.5% too big.** No geodata host is
reachable from the build environment, so the network is rebuilt from the
committed Protomaps basemap rather than fetched from the Town. That archive
carries real geometry and real names but only a three-value road class, so it
cannot tell a public street from an apartment drive. 149.20 countable miles
against a known-good 136.21. The whole story, with every heuristic and its
residual risk, is in [`docs/data-provenance.md`](docs/data-provenance.md).

`data/pipeline/fetch_authoritative.py` closes that gap from the Town's own
ownership fields and writes the identical artefact, so the swap is two commands.
**It has never been executed**, because nothing here can reach those endpoints.

**There is no home count, and the app shows none.** No address source is
reachable, so `segment.homes` is null on all 1,598 rows and the interface renders
nothing where the count would go. Never a zero: a zero is a claim that nobody
lives on that street. The counter is otherwise built, and populating that one
column lights it.

## The decisions worth knowing

**A wrong match is worse than a missing one.** GPS drifts further than the 60 m
between parallel downtown streets, and a wrong match silently corrupts a shared
map that nobody can audit. So matching is topological rather than nearest-line:
a candidate must be reachable through shared junctions, which makes jumping to a
parallel street impossible rather than unlikely. Measured false-positive rate
across 8,687 proposals: **0.00%**. Recall is deliberately 0% at 40 m accuracy,
because at that accuracy the answer is not knowable.

**Nothing reaches the town map without a tap.** The matcher proposes; a person
confirms. Anything the matcher is unsure of renders unticked.

**Every street counts once, ever.** Enforced by primary key, not by convention.
Two walkers covering the same street move the total once.

**A divided road is one road.** Dual carriageways are drawn as two parallel
lines; 109 pairs here. Both stay in the graph for routing, but coverage and the
denominator count the pair once. Otherwise the town could never reach 100%,
because nobody can walk the far side of a median.

**No location data is ever stored.** Not a trace, not a fix, not a coordinate.
There is no table one could go in. A walk records which streets a person
confirmed, and nothing else. Street matching during a walk runs on the phone,
against the street file the phone already holds.

**Location is optional.** Declining it changes nothing structural. Streets are
picked by hand, as stretches named by their corners.

## What is not done

- **Nobody has opened this on a phone.** It has been driven in headless
  Chromium at 390×844 and every screen rendered, but a real device is a
  different thing and the wake lock has never held a real screen awake.
- **The service worker leaves the 4.4 MB basemap uncached**, because range
  requests cannot be cached correctly through the Cache API. A first-ever launch
  in airplane mode has no basemap, though the streets, the walk and the queue
  all still work.
- **The network is provisional**, as above. That is the largest open item, and
  the fix is written and waiting on a host with network access.
