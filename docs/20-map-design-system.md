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

Blacksburg is drawn from the town's own data. There are no vector tiles, no tile host,
no third-party style — but there **is** a basemap, and getting that wrong is the one
correction this system has already had to make.

The first cut drew only the 1,582 required segments and nothing else. That is not a
quiet basemap, it is no basemap, and the result was a network diagram: the bypass, the
ramps, the campus service roads and the whole non-obligation street fabric simply
absent. You cannot orient yourself in a town whose landmarks have been deleted, and
**removing the world is not the same as letting the prayer data lead it.** The prayer
data has to be the hero through contrast and hierarchy, against a world that is
present and quiet.

The ground now carries 1,102 public roads outside the obligation — including US 460
and its ramps, which is what anybody in Blacksburg actually navigates by — plus 96
public parks and the town boundary, all drawn dark enough to sit under the mission
without competing with it.

Private drives stay out: 224 of them, plus everything marked PRIVATE or GATED. They
lead to individual houses, nobody navigates by them, and drawing them would put
residential specificity on a public map to no purpose.

Consequences of owning the basemap, all of them deliberate:

- **The prayer data leads by contrast, not by subtraction.** The town is underneath it,
  drawn at a luminance that cannot compete: the brightest context road is darker than
  the dimmest prayer state, at every zoom, by construction.
- **It renders identically offline.** This is a tool used outdoors on whatever signal a
  phone has, and the map is now part of the app rather than something the app fetches.
- **No third party can change how this product looks**, or take it away.
- **Nobody else's map looks like this**, because nobody else has this dataset. That is
  the recognisability the brief asks for, and it is earned structurally rather than
  applied as a skin.

Labels need SDF glyphs, which is the one thing a self-hosted vector map cannot fake.
`web/scripts/build-glyphs.mjs` renders Archivo into `public/fonts/Prayer Walk Regular/`
— two ranges, 76 KB, latin only, which is every character in a Blacksburg street name.
The map has no runtime dependency on anything outside our origin.

### What we give up

Buildings, land use and water.

Buildings (10,156 polygons, 12.9 MB) and land use (11,398, 9.3 MB) stay out on both
payload and philosophy — they are exactly the visual noise the brief asks to remove,
and neither is something anybody navigates by.

**Water is a genuine loss, and it is recorded as one rather than dressed up.** Water is
how people orient in unfamiliar ground, and both references keep it. The town publishes
no hydrography among the datasets we fetch — landuse has no water class, and
Blacksburg's water is creeks rather than anything that would read at town scale. Roads,
parks and the boundary carry the orientation load instead. If a pilot walker says they
cannot place themselves, water is the first thing to go looking for.

---

## 3. Ground

| Element | Value | Reasoning |
|---|---|---|
| Land | `#0D1113` | Near-black, very slightly cool. Darker than the app's card so the map reads as a surface you look *at*, not a panel of the interface. |
| Park | `#141B19` | Public open space only — 96 Town-owned polygons of 375; the rest are HOA and private, which are neither walkable nor ours to draw. A park should be felt, not read. |
| Town roads | `#252C2F` | Public roads outside the obligation. Present so the town is recognisable, dark enough never to compete. |
| Major roads | `#333C40`, ×1.9 width | US 460, the ramps, the arterials. A little more light, because these are what somebody orients by. |
| Boundary | `#242B2D`, 1.2 px, dashed | Not a border. The limit of what we claim. |

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

1. **No water.** §2 above. The first thing to add if orientation is a pilot complaint.
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
web/src/screens/MapSystem.tsx  the specimen sheet, at #/map-system
web/scripts/build-glyphs.mjs  Archivo → SDF glyph ranges, into our own origin
api/routing/network.py        road_class + path_type on Segment (cartography only)
api/app/routers/progress.py   public open space, simplified
```
