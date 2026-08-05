/**
 * The regional basemap is a static style document — `public/basemap/blacksburg.json`
 * — because `VITE_BASEMAP_STYLE` has to be able to point somewhere else, and a URL
 * cannot point at a TypeScript object. That means the palette exists twice.
 *
 * These tests are what stops the two copies drifting. They also state the one rule
 * the whole map system rests on, in a form that fails the build rather than fading
 * into a comment: NOTHING ON THE GROUND MAY BE BRIGHTER THAN THE DIMMEST PRAYER
 * STATE. Get that wrong and an interstate outranks a street somebody prayed for.
 */
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import { BASEMAP, GROUND, INK, INK_OPACITY, STATE_WEIGHT, WIDTH_STOPS } from '../tokens'
import { CONTEXTS } from '../style'

// Read, not imported: `public/` is served verbatim by Vite and must never end up in
// the bundle. Resolved from the vitest root, which is `web/`.
const style = JSON.parse(
  readFileSync(resolve(process.cwd(), 'public/basemap/blacksburg.json'), 'utf8'))

const layer = (id: string) => {
  const found = style.layers.find((l: any) => l.id === id)
  expect(found, `style has no layer ${id}`).toBeTruthy()
  return found
}

/** WCAG relative luminance. The single number this design system argues about. */
function luminance(hex: string): number {
  const ch = [1, 3, 5].map((i) => {
    const v = parseInt(hex.slice(i, i + 2), 16) / 255
    return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4
  })
  return 0.2126 * ch[0] + 0.7152 * ch[1] + 0.0722 * ch[2]
}

describe('regional basemap style', () => {
  it('paints the design system land colour', () => {
    expect(layer('bg-land').paint['background-color']).toBe(GROUND.land)
  })

  it('uses the token palette for every ground layer', () => {
    expect(layer('bg-forest').paint['fill-color']).toBe(BASEMAP.forest)
    expect(layer('bg-water').paint['fill-color']).toBe(BASEMAP.water)
    expect(layer('bg-waterway').paint['line-color']).toBe(BASEMAP.waterway)
    expect(layer('bg-rail').paint['line-color']).toBe(BASEMAP.rail)
    expect(layer('bg-road-minor').paint['line-color']).toBe(BASEMAP.road.minor)
    expect(layer('bg-road-secondary').paint['line-color']).toBe(BASEMAP.road.secondary)
    expect(layer('bg-road-primary').paint['line-color']).toBe(BASEMAP.road.primary)
    expect(layer('bg-road-trunk').paint['line-color']).toBe(BASEMAP.road.trunk)
    expect(layer('bg-road-motorway').paint['line-color']).toBe(BASEMAP.road.motorway)
  })

  it('keeps the road ramp monotonic in luminance', () => {
    const ramp = [BASEMAP.road.minor, BASEMAP.road.secondary, BASEMAP.road.primary,
                  BASEMAP.road.trunk, BASEMAP.road.motorway].map(luminance)
    for (let i = 1; i < ramp.length; i++) expect(ramp[i]).toBeGreaterThan(ramp[i - 1])
  })

  it('keeps every ground colour below the dimmest prayer state', () => {
    // Remaining ground is the floor of the prayer scale. It carries opacity, so the
    // fair comparison is what actually reaches the eye over land.
    const land = luminance(GROUND.land)
    const floor = land + (luminance(INK.remaining) - land) * INK_OPACITY.remaining
    const ground = [
      GROUND.land, GROUND.park, GROUND.boundary, GROUND.context, GROUND.contextMajor,
      BASEMAP.forest, BASEMAP.water, BASEMAP.waterway, BASEMAP.rail,
      ...Object.values(BASEMAP.road),
    ]
    for (const hex of ground) expect(luminance(hex)).toBeLessThan(floor)
    // And with real headroom, not by a rounding error.
    expect(floor / luminance(BASEMAP.road.motorway)).toBeGreaterThan(1.5)
  })

  it('keeps basemap labels below the mission, and above nothing else', () => {
    // A place name must be readable and must never compete with a street name on
    // today's walk. Covered ground is the ceiling: CHRISTIANSBURG cannot look more
    // important than a mile somebody has prayed for.
    const ceiling = luminance(INK.covered)
    for (const [name, hex] of Object.entries(BASEMAP.label)) {
      if (name === 'halo') continue
      expect(luminance(hex), name).toBeLessThan(ceiling)
    }
  })

  it('serves its own glyphs and its own archive', () => {
    expect(style.glyphs).toBe('/fonts/{fontstack}/{range}.pbf')
    expect(style.sources['bpw-base'].url).toBe('pmtiles:///basemap/blacksburg.pmtiles')
    // No third-party runtime dependency, anywhere in the document.
    expect(JSON.stringify(style)).not.toMatch(/https?:\/\/(?!www\.usgs\.gov)/)
  })

  it('credits the source of the data it actually contains', () => {
    // USGS, not OpenStreetMap. The archive is built from The National Map and GNIS;
    // crediting OSM for data that contains no OSM would be a false attribution, and
    // it is the reason this basemap carries no share-alike obligation at all.
    expect(style.sources['bpw-base'].attribution).toMatch(/USGS/)
    expect(JSON.stringify(style.sources)).not.toMatch(/OpenStreetMap/i)
  })

  it('draws the ground, then the linework, then the names', () => {
    const ids = style.layers.map((l: any) => l.id)
    expect(ids[0]).toBe('bg-land')
    // Nothing is drawn after the last name. The basemap's job finishes where the
    // mission's begins, and MapView appends the prayer layers on top of all of it.
    expect(style.layers[style.layers.length - 1].type).toBe('symbol')
  })

  // ---------------------------------------------------- no effects, anywhere
  describe('the region', () => {
    const ids = style.layers.map((l: any) => l.id)

    /**
     * THIS TEST IS A TOMBSTONE, AND IT IS THE MOST IMPORTANT ONE IN THE FILE.
     *
     * Three separate rounds of work put an emphasis field on this map: a near-black
     * wash feathered outward from the town to darken the county, and a tinted plate
     * under the linework to lift the ground inside it. Each round measured well — the
     * last one moved the surface ten display levels at the municipal line, which is a
     * real, defensible number — and each round looked, on screen, like a soft green
     * cloud with an edge you could find.
     *
     * The lesson was not "tune it further". It was that the town does not need to be
     * pointed at. All 1,868 prayer segments are inside the municipal limits and none
     * of the fifty kilometres around it has one, so the moment the overlay is drawn at
     * a weight the display can render, Blacksburg is the only lit thing in frame. The
     * field existed to compensate for a mission network that was being drawn at half a
     * pixel. Fix the half pixel and there is nothing left to compensate for.
     *
     * So: no fill on this basemap may be anything but a thing that is actually there.
     * Land, forest and water are places. A gradient around the town is a gesture.
     */
    it('carries no wash, no plate, no vignette — only what is on the ground', () => {
      for (const l of style.layers) {
        if (l.type !== 'fill' && l.type !== 'background') continue
        expect(['bg-land', 'bg-forest', 'bg-water'], `unexpected fill ${l.id}`)
          .toContain(l.id)
      }
      // And no data-driven alpha anywhere, which is the shape every version of the
      // field took: one geometry carrying a per-feature opacity ramp.
      expect(JSON.stringify(style.layers)).not.toMatch(/\["get","[al]"\]/)
    })

    it('is one corpus drawn one way everywhere', () => {
      // Every layer that renders the region reads the archive. The only exception is
      // the municipal line, which is a boundary rather than a feature of the ground.
      for (const l of style.layers) {
        if (!l.source) continue
        expect(l.source, l.id).toBe(l.id === 'bg-town-line' ? 'bpw-boundary' : 'bpw-base')
      }
    })
  })

  // ---------------------------------------------------- the municipal limits
  describe('the town line', () => {
    const ids = style.layers.map((l: any) => l.id)
    const line = () => layer('bg-town-line')

    it('is the tokens, and is drawn as a jurisdictional boundary', () => {
      expect(line().paint['line-color']).toBe(BASEMAP.line)
      expect(line().paint['line-opacity']).toBe(BASEMAP.lineOpacity)
      // Dashed. It is what a municipal limit is drawn as on every map that has ever
      // had one, and it carries the shape for a fraction of a solid line's ink.
      expect(line().paint['line-dasharray'].length).toBe(2)
    })

    it('stays under the mission it encloses', () => {
      // Effective luminance over land, which is what the eye actually gets. A frame
      // that outranks the dimmest prayer state is a frame drawing attention to itself.
      const land = luminance(GROUND.land)
      const seen = land + (luminance(BASEMAP.line) - land) * BASEMAP.lineOpacity
      expect(seen).toBeLessThan(luminance(INK.remaining) * 0.6)
    })

    it('is the only thing the basemap says about the town', () => {
      const about = style.layers.filter((l: any) => /town|blacksburg/i.test(
        l.id + JSON.stringify(l.filter ?? '')))
      // bg-place-town is the region's place names, Blacksburg among them; the line is
      // the limits. Anything else naming the town is an effect wearing a layer id.
      expect(about.map((l: any) => l.id).sort())
        .toEqual(['bg-place-town', 'bg-town-line'])
    })

    it('sits over the roads and under the names', () => {
      // Over the roads because a boundary is not hidden by traffic; under the names
      // because a name is the last thing a map says.
      const lastRoad = Math.max(...style.layers
        .map((l: any, i: number) => (l.type === 'line' && l.id.startsWith('bg-road-') ? i : -1)))
      const firstSymbol = style.layers.findIndex((l: any) => l.type === 'symbol')
      expect(ids.indexOf('bg-town-line')).toBeGreaterThan(lastRoad)
      expect(ids.indexOf('bg-town-line')).toBeLessThan(firstSymbol)
    })
  })

  // ------------------------------------------ what makes Blacksburg Blacksburg
  describe('the mission overlay', () => {
    /** Base width at a zoom, interpolating WIDTH_STOPS the way MapLibre does. */
    const base = (z: number) => {
      const s = WIDTH_STOPS
      if (z <= s[0][0]) return s[0][1]
      if (z >= s[s.length - 1][0]) return s[s.length - 1][1]
      const i = s.findIndex(([zz]) => zz > z) - 1
      const t = (z - s[i][0]) / (s[i + 1][0] - s[i][0])
      return s[i][1] + (s[i + 1][1] - s[i][1]) * t
    }

    /**
     * The dashboard's own zoom, measured on a Pixel 7 with the region fitted. The
     * number matters because it is the one place the map has to carry the whole story
     * in a single glance, and it is the far end of the width ramp.
     */
    const DASHBOARD_Z = 10.79

    it('draws the town at a width the display can actually render', () => {
      // A line narrower than a pixel does not draw thin. It draws as a fraction of one
      // pixel's coverage, and then the layer opacity is applied on top of that. The
      // shipped map asked for 0.53 px at 45% and got roughly an eighth of a line —
      // which is why Blacksburg looked exactly like the county around it, and why
      // three rounds of work went looking for an emphasis effect to make up for it.
      const c = CONTEXTS.town
      const px = base(DASHBOARD_Z) * STATE_WEIGHT.remaining * c.emphasis
      expect(px).toBeGreaterThan(0.9)
      // Ink on the page: width times opacity. Below about 0.6 the network stops
      // reading as a fabric and starts reading as noise.
      expect(px * c.remainingOpacity).toBeGreaterThan(0.6)
    })

    it('keeps the states apart while doing it', () => {
      // Turning remaining up must not let it approach covered ground. The gap is the
      // whole point of the dashboard: what has been prayed for against what has not.
      const c = CONTEXTS.town
      const remaining = base(DASHBOARD_Z) * STATE_WEIGHT.remaining * c.emphasis
        * c.remainingOpacity
      const covered = base(DASHBOARD_Z) * STATE_WEIGHT.subject * c.emphasis
        * INK_OPACITY.subject
      expect(covered / remaining).toBeGreaterThan(2.5)
      // And by luminance, which is where this system's hierarchy actually lives.
      expect(luminance(INK.subject) / luminance(INK.remaining)).toBeGreaterThan(8)
    })

    it('outranks the brightest thing the basemap can put under it', () => {
      // The town's streets and the county's streets are the same geometry class. The
      // only difference is that one set has the mission drawn on it, so that set has
      // to win, at the dashboard's opacity, against the loudest road in the archive.
      const land = luminance(GROUND.land)
      const seen = land + (luminance(INK.remaining) - land) * CONTEXTS.town.remainingOpacity
      expect(seen / luminance(BASEMAP.road.motorway)).toBeGreaterThan(1.4)
    })
  })
})
