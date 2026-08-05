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
import { BASEMAP, GROUND, INK, INK_OPACITY } from '../tokens'

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

  it('draws basemap labels below the prayer overlays in the stack', () => {
    const ids = style.layers.map((l: any) => l.id)
    const firstSymbol = style.layers.findIndex((l: any) => l.type === 'symbol')
    const lastLine = style.layers.map((l: any) => l.type).lastIndexOf('line')
    // MapView inserts prayer lines before the first symbol layer; that only works if
    // every ground line is below every ground label.
    expect(lastLine).toBeLessThan(firstSymbol)
    expect(ids[0]).toBe('bg-land')
  })

  // ------------------------------------------------------------ emphasis
  describe('the emphasis wash', () => {
    const ids = style.layers.map((l: any) => l.id)
    const ground = style.layers.find((l: any) => l.id === 'bg-emphasis-ground')
    const labels = style.layers.find((l: any) => l.id === 'bg-emphasis-labels')

    it('is one colour at one alpha, in the tokens and in the style', () => {
      for (const l of [ground, labels]) {
        expect(l.paint['fill-color']).toBe(BASEMAP.wash)
        expect(l.paint['fill-opacity']).toEqual(['get', 'a'])
        // Adjacent bands share an edge. Antialiasing each one draws a hairline at
        // every seam, which is a set of concentric rings around Blacksburg — the
        // exact thing the falloff exists to avoid.
        expect(l.paint['fill-antialias']).toBe(false)
      }
    })

    it('is neutral, so it desaturates as well as darkens', () => {
      const ch = [1, 3, 5].map((i) => parseInt(BASEMAP.wash.slice(i, i + 2), 16))
      expect(Math.max(...ch) - Math.min(...ch)).toBe(0)
      // And near enough to black that it darkens roughly in proportion rather than
      // flattening the dark end of the ramp into a single tone.
      expect(Math.max(...ch)).toBeLessThan(16)
    })

    it('brackets the basemap without touching the prayer overlays', () => {
      // MapView inserts prayer lines before the first bg-* symbol layer and prayer
      // labels at the very top. So the ground wash has to sit above every basemap
      // line but below that anchor, and the label wash above every basemap label.
      const firstBgSymbol = ids.findIndex(
        (id: string, i: number) => style.layers[i].type === 'symbol' && id.startsWith('bg-'))
      const lastLine = style.layers.map((l: any) => l.type).lastIndexOf('line')
      expect(ids.indexOf('bg-emphasis-ground')).toBeGreaterThan(lastLine)
      expect(ids.indexOf('bg-emphasis-ground')).toBeLessThan(firstBgSymbol)
      expect(ids.indexOf('bg-emphasis-labels')).toBe(ids.length - 1)
    })

    it('takes about a third off the region, and never brightens anything', () => {
      const a = BASEMAP.washAlpha
      const w = [1, 3, 5].map((i) => parseInt(BASEMAP.wash.slice(i, i + 2), 16))
      const over = (hex: string) => '#' + [1, 3, 5]
        .map((i, k) => Math.round(parseInt(hex.slice(i, i + 2), 16) * (1 - a) + w[k] * a))
        .map((v) => v.toString(16).padStart(2, '0')).join('')
      // The roads are what the eye wanders over, so they are what the brief is about.
      // This is the arithmetic, and the arithmetic understates it: measured on a
      // render the region lands about 30% down, because a thin line is mostly
      // antialiased edge and edges sit where the sRGB curve is steep. The bound below
      // is the calculated figure, which is the one a test can check.
      for (const hex of Object.values(BASEMAP.road)) {
        const drop = 1 - luminance(over(hex)) / luminance(hex)
        expect(drop).toBeGreaterThan(0.22)
        expect(drop).toBeLessThan(0.36)
      }
      // Everything else only has to move the same direction. Land, forest and water
      // sit on the linear part of the sRGB curve, where the same alpha buys less.
      for (const hex of [GROUND.land, BASEMAP.forest, BASEMAP.water, BASEMAP.waterway,
                         BASEMAP.rail, ...Object.values(BASEMAP.label)]) {
        expect(luminance(over(hex))).toBeLessThanOrEqual(luminance(hex))
      }
    })
  })
})
