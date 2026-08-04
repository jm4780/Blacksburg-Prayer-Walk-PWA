# Mission control — the Dashboard, rebuilt from the approved design

The landing screen now implements design **"01 — Mission control"** from the approved
Claude Design direction (`Prayer Walk PWA full`). Dashboard only; no other screen was
touched.

To see it: `./go`, then open the app. To regenerate screenshots locally —
`node web/e2e/screenshots.mjs /tmp/shots`. They are not committed, for the same reason
the progress-map screenshots were left out of docs/18: they are full rasters of the
required street network, and this repository does not publish geometry derived from
Town of Blacksburg GIS data while gate G1 is open.

---

## 1. What the screen does now

One story, top to bottom, in the order the design fixes:

| | Element | Source |
|---|---|---|
| 1 | `PRAYER WALK` · `BLACKSBURG, VA` | static |
| 2 | **The mission** — "Pray for every household in Blacksburg, one street at a time." | static |
| 3 | Percentage prayed through, at 96px, with a dashed progress rule | `percent_prayed_for` |
| 4 | **The town map**, filling the remaining height, with `Explore ↗` | `/api/progress/map` |
| 5 | Households · Streets · Miles | `estimated_households_prayed_for`, `required_segments_complete`, `total_miles_walked` |
| 6 | "Counted for the whole town, not for you." | static |
| 7 | **Begin today's walk →** | → `/mission` |

The layout is a fixed-height flex column, not a scrolling page. Everything above and
below the map is `flex: none`; the map is `flex: 1 1 auto` and takes what is left. That
is what makes it read as one surface rather than a page with a map embedded in it.

## 2. The requirements, one by one

| # | Requirement | How |
|---|---|---|
| 1 | Map integrated into the Dashboard | `MapView` renders inline, filling the panel |
| 2 | One unified experience | Single fixed-height column; no card around the map; it bleeds to both edges with hairline rules |
| 3 | Remove "See Progress Map" | Gone — and so is the **Progress button in the top bar**, which led to the same place |
| 4 | Obviously town-wide, not personal | Stated in words under the metrics, and the mission line is about the town |
| 5 | Four metrics preserved | All four, from the existing endpoint. No API change |
| 6 | Households prominent | First in the row, and named in the mission statement above — the design's own two-part answer |
| 7 | Primary action dominant | 64px, full width, `#E4712C` against a near-black screen. The only saturated element |
| 8 | Communication order | Exactly as listed in §1 |
| 9 | No separate Progress destination | Route removed; `#/progress` redirects to `/` so pilot links still work |
| 10 | Expand in place | `Explore ↗` opens a full-screen overlay. No route change, no history entry |

## 3. Deliberate departures from the design

Three, all small, all reversible in a line.

**"street segments", not "streets".** The design reads "418 of 1,204 streets". Our
number is `required_segments_complete` — **1,582 street *segments***, not 1,582 streets.
One street is usually many segments. Given how much of this project rests on numbers
being defensible, the subhead says "street segments". The compact metric label still
reads "Streets" because the design's 10px uppercase treatment has no room for more, and
the definition panel spells out the difference. Say the word and it matches the design
exactly.

**A "Walk in progress" bar.** Not in the design. Somebody with an unfinished walk needs
to get back to it, and burying that under a full-height map to preserve fidelity would
be a regression. It appears only when a walk is open, above everything else.

**The metric row opens a definitions panel.** Phase 3 committed to every number carrying
its own definition — the percentage is a claim about a denominator two phases of work
went into settling. The design has no room for three separate disclosures, so tapping
any metric opens one panel covering all four, plus what the map excludes. The
commitment survives; only its packaging changed.

## 4. Map treatment

`MapView` gained a `theme` prop. `dark` gives the design's palette: `#5E9B7E` for
covered ground, `#6E7676` for what is left.

The unwalked network is drawn **dashed as well as grey**. The design distinguishes the
two states by colour alone; dashing costs nothing and survives greyscale printing,
screenshots, and the ~8% of men who will not reliably separate those two hues. The
legend shows a solid rule and a dashed rule, matching.

Two fixes fell out of building this:

- **Every map instance independently waited six seconds** to discover the basemap was
  unreachable. Tapping `Explore` on a blocked network showed an empty rectangle for the
  whole six seconds. A module-level flag now records the first failure, and later maps
  start on the fallback immediately.
- **`window.__bpwMap`** (the end-to-end test handle) was not cleared on unmount, so a
  probe after navigation quietly queried a dead map's empty sources instead of failing.

## 5. Typography

Archivo and IBM Plex Mono, **self-hosted** via `@fontsource`, latin subsets only — 7
files, 112 KB. The design loads them from Google Fonts; a PWA that precaches its shell
should not need a third-party CDN to render text, and this app is used outdoors on
whatever signal a phone has. The unscoped `@fontsource` imports pull Vietnamese,
Cyrillic and Greek as well, which tripled the precache for glyphs this app will never
draw; the imports are pinned to `latin-*`.

## 6. Files changed

```
web/src/screens/Dashboard.tsx      rewritten as Mission control
web/src/screens/Progress.tsx       deleted — no longer a destination
web/src/App.tsx                    /progress redirects; top-bar Progress removed;
                                   the dashboard renders full-bleed without shared chrome
web/src/components/MapView.tsx     `theme` prop; dashed unwalked lines; basemap-failure
                                   memo; test handle cleared on unmount
web/src/main.tsx                   self-hosted fonts
web/src/styles.css                 `.dash` block (scoped dark theme)
web/package.json                   @fontsource/archivo, @fontsource/ibm-plex-mono
web/e2e/slice.mjs                  rewritten for the unified dashboard
web/e2e/screenshots.mjs            ditto, plus an expanded-map shot
```

Nothing under `api/`, `pipeline/` or the database changed. Mission generation and
routing are untouched.

## 7. Follow-ups — not implemented

**The map payload is 1.25 MB and the server does not compress it.** Measured:
1,254,073 bytes raw, byte-identical with `Accept-Encoding: gzip`. That cost used to be
paid only by people who chose to visit the progress map; it is now paid on every first
visit to the landing screen, including anonymous visitors who never walk. GeoJSON
compresses roughly 5–8×. One line of `GZipMiddleware` would take it to ~150–250 KB.
Left alone because this task forbade backend changes. **This is the single highest-value
follow-up.**

**The dashboard is dark; every other screen is light.** The approved direction has all
fourteen screens dark, so this is the first step of a migration rather than a permanent
inconsistency — but until the rest follows, tapping "Begin today's walk" moves from a
near-black screen to a cream one. Worth doing next, and worth doing as one deliberate
piece rather than screen by screen.

**Geometry gating is now on the landing screen.** `/api/progress/map` sits behind the
G1 gate. Under today's `open_read` default this is invisible. Under
`BPW_ACCESS_MODE=authenticated` — recommended for any real pilot — an anonymous
visitor gets a 403 where the centrepiece should be. The dashboard handles it with a
"not public yet" panel, but the screen is materially weaker in that mode, which sharpens
the case for resolving G1.

**The build badge overlaps the fine print** at the bottom of the dashboard. It is
temporary scaffolding for verifying previews on real phones and should be removed once
that stops being a live question.

## 8. Tests

| Suite | Result |
|---|---|
| `e2e/slice.mjs` | 95 checks, all passing |
| `e2e/verify-build.mjs` | 13 checks, all passing |
| `web` unit tests | 16 passing |
| `pytest` | unchanged — no backend code was touched |

New assertions cover the requirements that could regress silently: the map is embedded
rather than linked, no progress destination is offered anywhere, `Explore` changes no
route, `#/progress` still redirects, households leads the metric row, the numbers are
declared as the town's, and the definitions remain reachable.
