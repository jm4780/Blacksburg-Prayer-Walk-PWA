# Where the street network came from, and how far off it is

Read this before trusting a number this app shows.

## The constraint

The build environment cannot reach a single geodata host. Every one of these is
refused at the egress proxy, verified by probing about forty hosts:

| host | purpose | result |
|---|---|---|
| `overpass-api.de`, `download.geofabrik.de`, `planet.openstreetmap.org` | OpenStreetMap | refused |
| `services1.arcgis.com` | Town of Blacksburg GIS | refused |
| `services5.arcgis.com` | Montgomery County parcels | refused |
| `vginmaps.vdem.virginia.gov` | Virginia road centrelines and address points | refused |
| `www2.census.gov`, `tigerweb.geo.census.gov` | Census TIGER | refused |
| `supabase.com` | shared backend | refused |

Reachable: npm, PyPI, GitHub, Ubuntu apt. That is all.

The original plan called for OpenStreetMap clipped to the town boundary. That is
not possible here, and no substitute road source is reachable either.

## What was used instead

Two real assets already committed to this repository:

- `pipeline/basemap/blacksburg-limits.json` — the Town corporate limits polygon,
  1,757 vertices. Authoritative, used unchanged.
- `web/public/basemap/blacksburg.pmtiles` — a self-hosted Protomaps archive,
  z6–13, built from public-domain USGS data.

`rebuild/data/pipeline/extract_network.py` reads the roads layer out of that
archive and rebuilds a routable network from it.

Geometry is reassembled at the **edge** level, not the feature level. Vector
tiles clip features at tile borders and repeat them into neighbouring tiles'
buffers, so a "feature" is not a stable object. An edge is. The z13/4096
quantisation grid aligns exactly across tile boundaries, so the same physical
edge lands on identical integer coordinates in every tile carrying it, and a set
keyed on the endpoint pair deduplicates it exactly. 5,015 tile features collapse
to 12,228 distinct edges, which chain into 1,598 segments (1,489 countable
units once divided roads are paired).

Coordinate precision is about 0.95 m at z13. That is fine for street centrelines.

## What the archive does not carry

This is the part that matters.

The tile schema collapses road classification to three values: `motorway`,
`link`, `minor`. There is no ownership field, no access field, no surface, no
service type, and no footway or path layer at all. So `minor` is 205 miles that
contains Progress Street and an apartment parking aisle with nothing to tell
them apart.

Classification is therefore a documented heuristic. Each rule and its residual
risk:

| rule | miles | risk |
|---|---|---|
| `link` → excluded (ramps) | 7.49 | low |
| `motorway` → excluded, **except** `ref = US 460 Bus` | 16.30 | low. US 460 is the limited-access bypass. US 460 Business is Main Street downtown and is one of the most walked streets in town, so excluding it on class alone would be plainly wrong. |
| unnamed `minor` → excluded | 46.76 | **highest risk in the build.** In this archive an unnamed minor way is a parking aisle, driveway or service spur, and real residential streets are named. Some genuine streets are certainly lost here. |
| name ruled private by the previous build | 5.95 | low, and evidence-based |
| named `minor` → coverable | 146.54 | over-inclusive |

The private-name rulings are harvested from review artefacts that survive in git
even though the previous build's geometry does not. Those were real decisions
made against real Town ownership attributes, so they beat anything inferable
from tiles. Only 31 names survive that way, because the committed file is the
review *queue*, not the full decision set.

## Measured error

| | miles |
|---|---|
| drawn by this provisional network | 156.54 |
| **countable, each carriageway once** | **149.20** |
| previous authoritative build, required street + campus | **136.21** |
| difference | **+12.99 (+9.5%)** |

The gap between drawn and countable is divided roads. A dual carriageway is two
parallel lines in the source, and 109 of them are paired here, 7.34 mi of
duplicate. Counting both sides would mean the town could never reach 100%, since
nobody can walk the far side of a median separately. Both lines stay in the
graph for routing; coverage and the denominator count the pair once. See
contracts.md §7.

Found by the coverage engine, which kept matching a walk to two rows of the same
pavement and refused to tick either.

The excess is apartment and private drives that carry ordinary-looking street
names and that no reachable data distinguishes from public streets.

Tuning stopped here deliberately. Pushing the heuristics until the totals matched
would be fitting noise, not improving accuracy, and would produce a number that
looks right for the wrong reason.

## What this means for the app

- Percent-complete is a percentage **of this network**, not of the legal town
  street inventory. It is internally consistent, so the map fills in correctly
  and no street is ever counted twice, but the denominator is about 9.5% too big.
- Some streets on the map should not be walked. Roughly 13 miles of what the app
  calls coverable is private.
- Some real streets are missing, mostly short unnamed ones.

## The fix, already written

`rebuild/data/pipeline/fetch_authoritative.py` pulls roads, boundary and address
points straight from the Town of Blacksburg ArcGIS services, classifies from the
Town's own ownership and class fields instead of guessing, and writes the
identical artefact so nothing downstream changes:

```bash
python3 rebuild/data/pipeline/fetch_authoritative.py
python3 rebuild/db/load_network.py
```

It fails **closed**: an unrecognised ownership value excludes the street rather
than including it, because over-excluding costs somebody a manual tick while
over-including puts a private drive on the shared map permanently. It also
refuses to write at all if the resulting mileage falls outside a sanity envelope,
so a silent schema change upstream cannot corrupt the map.

**That script has never been executed.** No host reachable from this environment
serves those endpoints. The URLs and field semantics come from the previous
build's verified registry, but the first real run should be treated as a test
run: read the reconciliation table it prints before trusting the output.

## Homes

There is no home count, and the app shows none.

No address-point source is reachable: not Town GIS, not county parcels, not
VGIN, not TIGER, not OpenStreetMap. `segment.homes` is null on every one of the
1,598 rows, the API returns null, and the interface renders nothing where the
count would go.

It renders **nothing**, never a zero. A zero is a claim that nobody lives on that
street, and that claim would be false on almost every row.

The counter is otherwise fully built. `fetch_authoritative.py` populates
`segment.homes` from the Town address layer, assigning each address point to
exactly one segment, the nearest within 75 m, so no home is ever counted twice.
Populating that column is the only change needed to light the counter.
