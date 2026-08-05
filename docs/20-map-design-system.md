# The Prayer Walk Map Design System

The map is the product's primary visual instrument. Every screen that matters shows
one, and until now every one of them showed the same thing: OpenStreetMap's vector
tiles with our lines painted on top. It felt borrowed because it was.

This is the cartographic language that replaces it — written up here, defined in
`web/src/map/tokens.ts`, constructed in `web/src/map/style.ts`, and rendered live at
**`#/map-system`**, which is the specimen sheet and the authority when this document
and the code disagree.

---

## 1. The two rules

Everything else follows from these.

> **1. Prayer state owns colour. Road class owns width.**
>
> Prayer state — the subject, covered, remaining, held — is the only thing permitted
> hue, opacity and texture. Road class may only make a line slightly wider or
> narrower. An arterial nobody has walked therefore stays quieter than a cul-de-sac
> somebody has, because width can never out-shout tone.

> **2. Hierarchy is built from luminance, not hue.**
>
> The subject of the context is drawn in light. Everything else is grey. Saturated
> colour appears in exactly one place on the map — the start point — and never on a
> line.

The second rule was learned the expensive way. The first cut used saturated green for
covered ground and saturated orange for the assignment: two loud hues competing, and
the result read as a default map with brand colours applied. That is the thing this
system exists to stop being. The reference images make the point better than argument
does — in both, the route is near-white and is the brightest object on screen, the
base is monochrome and almost textureless, and colour survives only as a dot.

---

## 2. The basemap is ours

Not a vendor's tiles with our lines painted over them — that is the actual reason the
old map felt borrowed — but a single Protomaps `.pmtiles` archive we build, style and
serve ourselves. This is what `docs/02-technical-plan.md` §1.1 specified before a line
of code existed, and it is now what runs:

```
web/public/basemap/blacksburg.pmtiles    6.5 MB, one file, our origin
web/public/basemap/blacksburg.json       the style, in this system's palette
web/src/map/basemap.ts                   the pmtiles:// protocol handler
```

Getting here cost two corrections, both worth recording.

**The first cut drew only the 1,582 required segments and nothing else.** That is not a
quiet basemap, it is no basemap, and the result was a network diagram: the bypass, the
ramps, the campus service roads and the whole non-obligation street fabric simply
absent. You cannot orient yourself in a town whose landmarks have been deleted, and
**removing the world is not the same as letting the prayer data lead it.**

**The second cut drew the town's own roads, parks and boundary.** A real town — ending
at a hard line, floating in a void. Blacksburg is not an island, and a map that stops
at the town limit tells a walker nothing about which way Christiansburg is, where the
New River runs, or which ridge they are looking at. The town publishes the town, and
nothing beyond it, so no amount of styling was going to fix that.

The ground now carries a region: roughly 50 km in every direction, `-81.00,36.80` to
`-79.80,37.65`. Every road class from interstate to residential, the New River and its
tributaries, the two arms of Jefferson National Forest, the Norfolk Southern main line,
and the place names — Christiansburg, Radford, Salem, Riner, Brush Mountain — that let
somebody say *where* they are rather than only *what street*.

### Where the data comes from, and why it is not OpenStreetMap

The archive is built entirely from **US federal public-domain sources**: USGS The
National Map (Transportation and Hydrography), the USGS Small-scale collection
(federal lands, cities) and GNIS. There is no OpenStreetMap geometry in it, and the
attribution on the map says USGS because that is what is true.

That is not an accident of what happened to be reachable. `docs/01-data-audit.md` §2.4
already ruled that the canonical network is built **without OSM geometry**, so that
ODbL share-alike can never reach the town data. Building the basemap from the same
public-domain family keeps that clean: the archive carries no licence obligation of
its own, and unlike the town GIS it is not blocked behind release gate G1 — it is the
one piece of this map that could be published tomorrow.

### Layer stack

Prayer data is not baked into the archive. It is inserted into the basemap's own stack
at load time, in `MapView`:

```
bg-land, bg-forest, bg-water
  pw-parks                        <- town open space, under the roads and the plate
bg-stage                                           <- the plate. A SURFACE.
bg-waterway, bg-rail, bg-road-{minor..motorway}
bg-waterway-label, bg-road-shield, bg-place-*      <- basemap labels
bg-town-line, bg-town-edge                         <- the frame, all but invisible
bg-emphasis                                        <- the darkening. ATMOSPHERE.
  pw-remaining, pw-held, pw-covered, pw-assigned   <- above the entire basemap
  pw-labels, pw-hit
```

Parks slide in under the roads, because a park drawn over a street is a park that has
erased a street — and because that also puts them under the plate, so open space inside
the town is lifted with the ground it sits on. Everything else the mission owns goes on
top of the whole basemap, emphasis included; see "Nothing on the ground may reach the
mission" below for why that is not negotiable.

With the archive live, `pw-context` — the 1,102 town roads the previous cut used as a
stand-in basemap — is not drawn at all. The archive already carries them at the same
luminance ramp, and drawing both would double the ink on exactly the layer that has to
stay quietest. That layer is now the fallback, not the basemap.

### Emphasis — three levels

The archive is one corpus, drawn one way, everywhere. That is exactly what makes it
read as a real place, and it is also why it had no centre. Two rounds of fixing that
by darkening the region got the eye to stop wandering, but left the map with only two
levels: a quiet world and a bright overlay. Blacksburg itself had no level of its own —
only an absence around it, and **an absence is not a place.**

There are three now:

| | | |
|---|---|---|
| **03 — the prayer overlay** | untouched | every emphasis layer sits below it |
| **02 — the mission area** | **+10.5%** | the same archive, on a plate |
| **01 — the surrounding world** | **−40.6%** | the same archive, quieter |

Inside-to-outside went from 1.44 to **2.67**.

**One field, read in both directions.** `pipeline/basemap/emphasis.py` emits a
signed-distance field around the municipal line and hangs two values off every band:
`a`, how much the ground is darkened, and `l`, how much it is lifted. Two fill layers,
one geometry, and the crossing between them centred on the boundary rather than either
side of it.

**But the two layers do not live in the same place, and that is the whole thing.**

> **A plate is a surface, so it goes UNDER the linework.
> The darkening is atmosphere, so it goes OVER everything.**

Two rounds were spent on the wrong side of that. Drawn over the roads, a lift
brightens them too — so it is capped by how close the brightest road may come to the
dimmest prayer state, and held to what that ceiling allows the ground moved about
**two display levels**. Measured on the render: land went 13,17,19 inside the line to
13,17,19 immediately outside it. Two levels is not a plate; it is a rumour of one, and
no amount of tuning was going to fix a mechanism.

Drawn under them the roads never move at all, the invariant is untouchable, and the
surface is free to carry the whole effect — **about ten levels**, which is what two
surfaces meeting actually looks like. Road-against-land contrast inside the town falls,
and that is not a side effect to apologise for: ground rising toward the linework that
sits on it is exactly what "raised" means.

The ramps are deliberately different widths, and the town's own shape is why. It is
51 km² of sprawl, not a blob — erode it 2 km and 5 km² survives — so a lift that faded
over kilometres would be a gradient with no shape to it. The plate therefore falls away
over the last 600 m inside the line and is gone 150 m past it; the darkening starts at
the line and takes 3.2 km to arrive. **Short plate, long falloff.**

Both ramps begin exactly on the line, and that is a correction. An earlier cut started
the darkening 800 m inside, reasoning that a ramp beginning at the boundary would draw
a border. Measured, it cost the town's outer kilometre 8.6% — the streets nearest the
line were the dimmest part of the mission area, which is precisely backwards. Starting
on the line costs nothing, because smootherstep has zero slope at both ends: **the
boundary is the flattest point in the entire field**, the one place where nothing is
changing.

**The plate is green-leaning, and that is the difference between a lift and a wash.**
`#5F9B8A` at 2.4%. Lerping near-black ground toward a neutral grey raises it and
bleaches it at once — measured, a grey plate took 7–10% of the ground's own saturation
with it. A lift carrying more chroma than the ground it lands on leaves that alone.
Inside the town, saturation now goes *up* 2–3%. That is what "richer" has to mean if
it means anything.

**Measure the surface, not the ink.** Every measurement before this one averaged the
pixels *brighter* than bare ground — the roads — and threw the surface away. That is
the wrong instrument for a plate, and it is why two rounds of tuning kept reporting
healthy numbers for something nobody could see. The unit below is display levels of
bare land, because that is what a surface is made of.

| Surface, bare land | Bytes |
|---|---|
| inside the line | **23.0** |
| immediately outside | 13.0 |
| 1.5–3 km out | 11.3 |
| beyond 3 km | 11.0 |

The whole transition happens within 250 m either side of the line: about 50 px at map
scale, soft, and the two surfaces on either side of it are plainly different things.
The frame is down to a 14% hairline with a 5% companion, because with a step that size
the plate defines its own shape and the line has almost nothing left to do.

Measured on the same render, banded by signed distance from the line:

| Distance from the town line | Luminance | Saturation |
|---|---|---|
| inside, more than 2 km in | **+14.2%** | +2.9% |
| inside, 1–2 km | +10.3% | +2.9% |
| inside, 0–1 km | +9.2% | +1.9% |
| **the line** | | |
| outside, 0–1 km | +6.8% | −1.7% |
| outside, 1–2 km | −22.4% | −3.9% |
| outside, 2–3 km | −39.3% | −9.2% |
| outside, 3–4 km | **−43.7%** | −11.9% |

Isolated, the plate measures **exactly 0.0%** outside the line — no halo — and the
frame moves the town by +0.4% and the region by nothing at all. The +6.8% in the first
kilometre outside is the frame's own pixels inside a kilometre-wide band.

**The frame.** A 1.4 px hairline at 45% on the municipal line, plus a wide blurred
inward-offset companion at 10% that reads as the edge of the plate rather than as a
border. Neither is meant to be noticed; between them they are what stops the plate
looking like a smudge.

### Nothing on the ground may reach the mission

The plate and the darkening are the **last two layers of the basemap**, and every
prayer layer is added above them. `basemap.test.ts` fails the build if that is ever not
true, because it was not always true and the cost was not obvious.

The previous order put the basemap's labels above the prayer lines, so a street
somebody walked would never be drawn through CHRISTIANSBURG. But the emphasis has to
sit above the labels to dim them — which put it above the prayer data too. Measured, a
lift there costs the subject **3.7%** of its luminance and lifts remaining ground by
**7.6%**: the prayer scale squeezed from both ends, in the one place the mission
actually lives. A place name occasionally crossed by a street is a much smaller price.

That reordering also uncovered a bug worth recording. The darkening used to be drawn
**twice** — once over the ground, once over the labels, because the overlays were
inserted between them. Two passes of 0.22 is one pass of 0.39, so the number in the
file had never been the number on the screen. There is one pass now.

And the same round found the measurement flattering itself: it chose which pixels to
average separately for each image, so darkening quietly dropped the dimmest ones out of
the "after" set and inflated the survivors. That is why an earlier round reported −29.5%
for a region that had actually gone down 39.7%. **The mask is taken once, from the
reference image, and applied to both.** Neither bug changed what shipped; both changed
what was believed about it, which is worse.

The road ramp also came back down. Lifting it 7% globally was how the town was made to
read brighter before there was a plate to do it, and the cost was a lift the darkening
then had to cancel — which it could not do in the first kilometre outside the line,
where the darkening is deliberately near zero. That left a +12% ring of country around
the town: a halo, built by accident. One mechanism for inside, one for outside, and
neither fighting the other.

### Offline

One file, precached by the service worker, and one subtlety that is easy to get wrong.

PMTiles is normally read with HTTP range requests. A Workbox precache answers *any*
request for a precached URL with the whole file and status 200 — range header or not —
and pmtiles' own `FetchSource` treats that as a misconfigured host and throws. The
stock source therefore works online and fails the moment the app goes offline, which
is the one situation this app exists to survive.

`ArchiveSource` in `web/src/map/basemap.ts` reads that 200 as what it is: the entire
archive, delivered early. Online with a cold cache it uses ranges and pulls a few tens
of kilobytes; offline it takes the whole file once and never touches the network
again. `web/e2e/basemap.mjs` forces the 200 path and asserts the map still has tiles.

Labels need SDF glyphs, which is the one thing a self-hosted vector map cannot fake.
`web/scripts/build-glyphs.mjs` renders Archivo into `public/fonts/Prayer Walk Regular/`
— two ranges, 76 KB, latin only, which is every character in a Blacksburg street name.
The map has no runtime dependency on anything outside our origin.

### What we still leave out

Buildings and land use. Buildings (10,156 polygons, 12.9 MB) and land use (11,398,
9.3 MB) stay out on both payload and philosophy — they are exactly the visual noise the
brief asks to remove, and neither is something anybody navigates by.

Water was the previous gap and is closed: NHD gives the New River, the reservoirs and
every named creek, drawn from the feature's own `visibility` scale so the water thins
out the way a cartographer would thin it rather than the way a tile budget would.

---

## 3. Ground

| Element | Value | Reasoning |
|---|---|---|
| Land | `#0D1113` | Near-black, very slightly cool. Darker than the app's card so the map reads as a surface you look *at*, not a panel of the interface. |
| Park | `#141B19` | Public open space only — 96 Town-owned polygons of 375; the rest are HOA and private, which are neither walkable nor ours to draw. A park should be felt, not read. |
| Town roads | `#252C2F` | Public roads outside the obligation. The fallback layer, drawn only when the archive cannot be reached. |
| Major roads | `#333C40`, ×1.9 width | Same, for US 460 and the ramps. |
| Boundary | `#242B2D`, 1.2 px, dashed | Not a border. The limit of what we claim. |

### The regional ramp

Five steps of luminance and nothing else — no hue, no texture, no casing. Defined in
`BASEMAP` in `tokens.ts`, duplicated in the style document, and held together by
`web/src/map/__tests__/basemap.test.ts`, which fails the build if the two drift or if
anything on the ground rises above the dimmest prayer state.

| Element | Value | Relative luminance |
|---|---|---|
| Forest | `#111713` | 0.0078 |
| Water | `#0E161B` | 0.0075 |
| Rail | `#1A1F22`, dashed | 0.0117 |
| Waterway | `#17222A` | 0.0144 |
| Road — minor / tertiary / link | `#20262A` | 0.0186 |
| Road — secondary | `#252C2F` | 0.0240 |
| Road — primary | `#2A3134` | 0.0294 |
| Road — trunk | `#2E3639` | 0.0352 |
| Road — motorway | `#333C40` | 0.0416 |
| *(the same, inside the town, on the plate)* | | *0.0210 – 0.0449* |
| *(the same, out in the region)* | | *0.0121 – 0.0270* |
| **`INK.remaining` — the dimmest prayer state** | `#4A5457` | **0.0849** |

The top of the ground ramp sits at about half the bottom of the prayer ramp — 2.0 to 1,
1.9 to 1 even on the plate, and 3.1 to 1 out in the region. A six-lane interstate crossing the frame can
therefore never out-rank a cul-de-sac somebody has prayed for, at any zoom, anywhere in
the region. `basemap.test.ts` asserts it rather than trusting it.

Basemap labels run on their own quieter scale — town `#6F7674` (0.176), hamlet
`#5C6362`, ridge `#4E5654`, shield `#5A6265` — all below `INK.covered` (0.249), so a
place name can never look more important than a mile that has been walked. They stop
at zoom 14: below that they orient, above it the walker is reading street names on
today's route and CHRISTIANSBURG is in the way.

Parks are simplified hard on the way out of the API — a background wash at town scale,
not a parcel boundary. 226 KB of source becomes 50 KB.

---

## 4. Road hierarchy

`road_class` and `path_type` now load onto `Segment` and reach the browser. They are
**cartography only** — the routing engine has never consulted road class and must not
start. Both sit outside the network checksum, exactly as `neighborhood` does, so
`bbg-net-v1.3-e1284e6001ff54f5` is unchanged and every stored route still replays.

| Class | Multiplier | Count |
|---|---|---|
| Arterial | ×1.25 | 108 |
| Secondary | ×1.15 | 173 |
| Collector | ×1.08 | 146 |
| Local | ×1.00 | 1,023 |
| Trail | ×0.85 | 419 |
| Sidewalk / Alley | ×0.70 | 388 |

**A 1.25 : 1 spread from arterial to residential.** On a driving map it would be six to
one. Here the residential street is where the households are and therefore where the
mission is, so arterials earn just enough width to orient by and no more. This is the
single most direct answer to "residential streets should receive more emphasis".

Trails are narrower than streets but never invisible: on foot they are often the only
way between two neighbourhoods.

---

## 5. Prayer hierarchy

| State | Ink | Weight | Texture | Opacity |
|---|---|---|---|---|
| **Subject** (whichever the context is about) | `#F2EFE9` | ×0.95 + halo | solid | 1.0 |
| Covered, when not the subject | `#7E8C86` | ×0.70 | solid | 0.85 |
| Assigned, when not the subject | `#9A8A76` | ×0.70 | solid | 0.85 |
| Remaining | `#4A5457` | ×0.55 | dash 2 / 2.4 | 0.9 |
| Held by another walker | `#6E6455` | ×0.60 | dot 0.6 / 1.8 | 0.7 |
| Dropped from a plan (editing) | `#4A5457` | ×0.72 | dash 1.2 / 1.6 | 0.7 |
| Start point | `#E4712C` | 5.5 px dot | — | 1.0 |

**The overlay weights were halved after the first cut.** A ×1.9 subject under a 3.4×
halo read as a thick white noodle laid across the town. Both references draw the route
as a thin, precise line and win attention through contrast against a quiet ground, not
through mass — a heavy stroke reads as emphasis at first glance and as clumsiness at
the second. The halo came down with it, 3.4× → 2.6× and α 0.10 → 0.07: it is there to
separate the line from the ground beneath, not to glow around it.

`remaining` moved the other way, `#414A4D` → `#4A5457`. Once real town roads sat under
the overlays, a street somebody is *obliged* to walk and a street that is merely there
were within a few points of each other. Obligation has to stay legible as obligation,
so remaining gets the light back that context roads never get.

Draw order **is** the hierarchy, made literal:

```
ground → parks → town roads → boundary → remaining → held
       → subject halo → subject → labels → tap targets
```

Nothing above can be obscured by anything below, so the most important thing on the map
is also structurally the last thing drawn.

**No state is distinguished by colour alone.** Every one differs in texture and weight
as well. A walker reads this in direct sunlight, roughly one man in twelve will not
separate two greys by hue, and the map should survive a greyscale screenshot pasted
into a message.

---

## 6. Labels

> A general map labels everything it can fit. This map labels only what the walker has
> been asked to do, and only when they are close enough to act on it.

- **Below z14.5: nothing.** The dashboard map is a picture of progress; 2,600 street
  names would bury it.
- **From z14.5:** streets that are part of the mission or already covered.
- **Never:** unwalked streets two neighbourhoods away. Naming them is noise wearing the
  costume of helpfulness.

Archivo, 10 → 13 px, `#C6C3BC` on a 1.4 px `#0D1113` halo, along the line, 34° max
angle.

---

## 7. Zoom philosophy — the six contexts

One cartography, six settings. Every screen gets its map from `CONTEXTS` in
`style.ts`, so this is one artefact with six configurations rather than six maps that
happen to resemble each other.

Every context draws the town roads: you always need to know where you are.

| Context | Screen | Subject | Labels | Emphasis | Obligation let through | Tap | Max z | Controls |
|---|---|---|---|---|---|---|---|---|
| `town` | Dashboard | covered | — | ×1.00 | α 0.45 | — | 15 | — |
| `briefing` | Mission assignment | assigned | ✓ | ×1.10 | α 0.30 | — | 16 | — |
| `walking` | Walking mode | assigned | ✓ | ×1.35 | α 0.22 | — | 17 | ✓ |
| `recording` | Recording | assigned | ✓ | ×1.20 | α 0.30 | — | 17 | ✓ |
| `editing` | Route editing | assigned | ✓ | ×1.15 | α 0.55 | 26 px | 17.5 | ✓ |
| `atlas` | Town progress, expanded | covered | — | ×1.00 | α 0.50 | — | 15 | ✓ |

The reasoning behind the two that are least obvious:

**`walking` lets the least context through (α 0.22) and is the loudest (×1.35).** On a
walk the only questions are "where am I going" and "have I turned yet". Everything that
is not the route is actively in the way, and the screen is being read at arm's length
in sunlight.

**`editing` lets the most through (α 0.55) and has the widest tap target.** You cannot
choose a street you cannot see. This is the one context where unwalked ground is
promoted rather than suppressed, because selecting it is the task.

The dashboard's framing rule — point the map at the progress, then pull back until it
is a minority of the view — is separate, and documented in
`web/src/screens/progressFrame.ts`.

---

## 8. Controls

Translucent, blurred, hairline, and mono-uppercase — the same treatment as the metric
labels, so a map control reads as part of the interface rather than as map furniture.

```
background  rgba(13, 17, 19, .55) + 6px backdrop blur
border      1px rgba(247, 245, 241, .12)
ink         #9AA0A0, #F7F5F1 when pressed
height      32px, fully rounded
type        500 10px/1 IBM Plex Mono, .12em tracking, uppercase
```

**Contexts that are read rather than navigated get no controls at all.** The dashboard
map has no zoom buttons: a +/− box there reads as a GIS application parked on a mission
briefing. Contexts that are genuinely navigated keep them, quietly.

---

## 9. Motion

> Motion reports state. It never celebrates.

| Event | Duration | Behaviour |
|---|---|---|
| Route appears | 700 ms | Draws in along its length |
| Coverage updates | 900 ms | Settles from assigned into covered |
| Camera | 650 ms | Eased out, never bounces |
| Reduced motion | 0 ms | Everything is instant |

A route drawing itself in says "this is yours now". A completed walk settling into the
covered tone says "it is recorded". Neither is a reward — **the walk was the point, and
an app that congratulates somebody for praying has misunderstood what it is for.**

---

## 10. Status

**Implemented and rendering:** the ground, the prayer hierarchy, the road ramp, the
draw order, parks, boundary, glyphs, controls, the six contexts, and the specimen
sheet. The Dashboard (`town`) and its expanded map (`atlas`) are on the system.

**Designed, not yet wired into their screens:** `briefing`, `walking`, `recording` and
`editing` exist and render on the specimen sheet against live data, but Mission,
ActiveWalk and Confirm still use the pre-system rendering. Migrating them is
mechanical — one `context` prop each — and was deliberately left out of this pass
because the brief said not to redesign application screens.

**Known gaps:**

1. **The archive is a checked-in build artifact.** `pipeline/basemap/build.sh`
   rebuilds it from public USGS downloads in a few minutes, but nothing runs it
   automatically and nothing notices when the sources move on. Six months from now,
   somebody has to remember.
2. **Motion is specified but not implemented.** The tokens are in place; the
   line-dasharray animation for route draw-in is not written.
3. **The payload is fixed.** `GZipMiddleware` is in — flagged as the top follow-up in
   docs/18, docs/19 and the first cut of this document, and now done. The bare network
   went from 1.36 MB uncompressed to **375 KB**, which is what made the geographic
   context affordable: with roads and parks the response is 1.9 MB raw but **437 KB on
   the wire**, still a third of what the network alone used to cost.
4. **A silent-failure trap worth knowing about.** MapLibre rejects a `['zoom']`
   expression nested inside another operator — and rejects it through the map's error
   event rather than by throwing, so the layer simply never appears. Four of the nine
   layers were invisible for exactly this reason. Zoom interpolation must always be the
   outermost expression; the class multiplier lives inside each stop.

---

## 11. Where this lives

```
web/src/map/tokens.ts        the system. Colours, weights, textures, motion, controls
web/src/map/style.ts         construction: contexts, layer order, expressions
web/src/map/basemap.ts       the pmtiles:// protocol and its offline-safe source
web/public/basemap/          the archive, its style document, the emphasis falloff
pipeline/basemap/build.sh    how to rebuild the archive from USGS
pipeline/basemap/emphasis.py the falloff — boundary, distances, alpha, easing
web/src/screens/MapSystem.tsx  the specimen sheet, at #/map-system
web/scripts/build-glyphs.mjs  Archivo → SDF glyph ranges, into our own origin
api/routing/network.py        road_class + path_type on Segment (cartography only)
api/app/routers/progress.py   public open space, simplified
```
