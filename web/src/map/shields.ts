/**
 * Route shields, drawn at runtime.
 *
 * The reference does not put route numbers in a box. It puts them in the actual
 * highway markers — the US route escutcheon with its notched crown, the Interstate
 * shield with its flat top and pointed foot, a rounded plate for state routes — which
 * is what makes "460" read as a road rather than as a label that happens to be a
 * number.
 *
 * These are generated into a canvas and handed to `map.addImage`, rather than shipped
 * as a sprite sheet, for three reasons. A sprite is one more file to fetch, one more
 * entry in the offline precache, and one more thing that can 404 into a map with no
 * shields on it. Drawing them here costs about a millisecond, works with no network at
 * all, and keeps the shapes in the same repository as the colours they are drawn in.
 *
 * Each image is registered STRETCHABLE: `stretchX`/`stretchY` name the pixel ranges
 * MapLibre may repeat, and `content` names the box the numerals sit inside, so one
 * 26-pixel marker serves "81" and "460" and "460 Bus" without three assets and without
 * the crown distorting.
 */
import { BASEMAP } from './tokens'

/** Drawn at 4x and handed over with pixelRatio 4, so a 3x phone never sees a stair. */
const SCALE = 4
const W = 26
const H = 22

type Shape = (c: CanvasRenderingContext2D, w: number, h: number) => void

/**
 * The US route escutcheon: a shield with a dipped crown and a rounded foot. Traced as
 * a bezier outline rather than approximated with a rounded rectangle, because at this
 * size the silhouette is the only thing carrying the meaning — nobody reads a 6-pixel
 * numeral and thinks "federal highway", they recognise the shape.
 */
const usShield: Shape = (c, w, h) => {
  const x = (v: number) => v * w
  const y = (v: number) => v * h
  c.beginPath()
  c.moveTo(x(0.5), y(0.06))
  c.bezierCurveTo(x(0.62), y(0.06), x(0.70), y(0.14), x(0.84), y(0.13))
  c.bezierCurveTo(x(0.95), y(0.12), x(0.97), y(0.10), x(0.97), y(0.10))
  c.lineTo(x(0.97), y(0.52))
  c.bezierCurveTo(x(0.97), y(0.76), x(0.76), y(0.90), x(0.5), y(0.96))
  c.bezierCurveTo(x(0.24), y(0.90), x(0.03), y(0.76), x(0.03), y(0.52))
  c.lineTo(x(0.03), y(0.10))
  c.bezierCurveTo(x(0.03), y(0.10), x(0.05), y(0.12), x(0.16), y(0.13))
  c.bezierCurveTo(x(0.30), y(0.14), x(0.38), y(0.06), x(0.5), y(0.06))
  c.closePath()
}

/** The Interstate shield: flat crown, swept shoulders, pointed foot. */
const interstate: Shape = (c, w, h) => {
  const x = (v: number) => v * w
  const y = (v: number) => v * h
  c.beginPath()
  c.moveTo(x(0.5), y(0.04))
  c.bezierCurveTo(x(0.74), y(0.04), x(0.92), y(0.09), x(0.97), y(0.13))
  c.bezierCurveTo(x(0.93), y(0.30), x(0.90), y(0.52), x(0.78), y(0.74))
  c.bezierCurveTo(x(0.70), y(0.87), x(0.58), y(0.94), x(0.5), y(0.97))
  c.bezierCurveTo(x(0.42), y(0.94), x(0.30), y(0.87), x(0.22), y(0.74))
  c.bezierCurveTo(x(0.10), y(0.52), x(0.07), y(0.30), x(0.03), y(0.13))
  c.bezierCurveTo(x(0.08), y(0.09), x(0.26), y(0.04), x(0.5), y(0.04))
  c.closePath()
}

/** State and county routes: a plain rounded plate. */
const plate: Shape = (c, w, h) => {
  const r = Math.min(w, h) * 0.16
  c.beginPath()
  c.moveTo(r, 0)
  c.arcTo(w, 0, w, h, r)
  c.arcTo(w, h, 0, h, r)
  c.arcTo(0, h, 0, 0, r)
  c.arcTo(0, 0, w, 0, r)
  c.closePath()
}

const SHAPES: Array<[string, Shape]> = [
  ['shield-us', usShield],
  ['shield-i', interstate],
  ['shield-state', plate],
]

function draw(shape: Shape): ImageData | null {
  const w = W * SCALE
  const h = H * SCALE
  const canvas = document.createElement('canvas')
  canvas.width = w
  canvas.height = h
  const c = canvas.getContext('2d')
  if (!c) return null
  const inset = 1 * SCALE
  c.translate(inset, inset)
  shape(c, w - inset * 2, h - inset * 2)
  c.fillStyle = BASEMAP.shieldFill
  c.fill()
  // The border is the same grey as the numerals — measured off the reference, the
  // marker never carries a colour the type does not.
  c.strokeStyle = BASEMAP.label.shield
  c.lineWidth = 1.1 * SCALE
  c.stroke()
  return c.getImageData(0, 0, w, h)
}

/**
 * Register every marker on a map. Safe to call again after a style reload — MapLibre
 * drops its images with the style, and `hasImage` is how we tell.
 */
export function addShields(map: {
  hasImage: (id: string) => boolean
  addImage: (id: string, img: ImageData, opts?: Record<string, unknown>) => void
}): void {
  for (const [id, shape] of SHAPES) {
    if (map.hasImage(id)) continue
    const img = draw(shape)
    if (!img) continue
    map.addImage(id, img, {
      pixelRatio: SCALE,
      // Only the flat middle of each marker may repeat, so "460" widens the waist
      // without stretching the crown or the foot.
      stretchX: [[0.36 * W * SCALE, 0.64 * W * SCALE]],
      stretchY: [[0.42 * H * SCALE, 0.62 * H * SCALE]],
      content: [0.14 * W * SCALE, 0.24 * H * SCALE, 0.86 * W * SCALE, 0.78 * H * SCALE],
    })
  }
}

/**
 * Which marker a route number belongs in, and the number without its prefix.
 *
 * The archive stores refs as people say them — "I-81", "US 460", "US 460 Bus",
 * "VA 114" — because that is what the shield label reads out and what a walker would
 * search for. On the map the shape says which system it is, so the text says only the
 * number, exactly as the reference does.
 */
export const SHIELD_IMAGE: any = [
  'case',
  ['==', ['slice', ['get', 'ref'], 0, 2], 'I-'], 'shield-i',
  ['==', ['slice', ['get', 'ref'], 0, 3], 'US '], 'shield-us',
  'shield-state',
]

export const SHIELD_TEXT: any = [
  'case',
  ['==', ['slice', ['get', 'ref'], 0, 2], 'I-'], ['slice', ['get', 'ref'], 2],
  ['==', ['slice', ['get', 'ref'], 0, 3], 'US '], ['slice', ['get', 'ref'], 3],
  ['==', ['slice', ['get', 'ref'], 0, 3], 'VA '], ['slice', ['get', 'ref'], 3],
  ['get', 'ref'],
]
