/**
 * Design tokens. The only place a colour, a size, or a weight is decided.
 *
 * The rule the whole look hangs on: the map is greyscale except for three
 * things, and each of those three carries one meaning and nothing else.
 *
 *   route   the way you are being sent
 *   prayed  a street the town has already covered
 *   walker  where you are, right now
 *
 * Everything else, including water and parks, separates by value alone. If a
 * fourth colour ever shows up on this map, something has gone wrong.
 */

export const color = {
  // --- ground: near-black, cool, never pure black -------------------------
  ground: '#0D1113',
  groundRaised: '#141A1D',
  groundSunk: '#090C0E',

  // --- basemap greys. Value separation only, no hue steps. ---------------
  //
  // Every step below is roughly 1.17-1.20:1 against the one beneath it, which
  // is about the smallest difference a thin line can carry on a phone held at
  // arm's length. The old ramp lived between 1.24:1 and 1.63:1 against the
  // ground for its whole five-class span, which is to say it did not exist:
  // the network was invisible and every road class looked the same.
  land: '#1A2419', // wooded ground and parks, a large area so it needs little
  water: '#070C10', // darker than the ground, so water reads as a hole
  waterEdge: '#26333A', // ...and a shoreline, because 1.03:1 alone is nothing
  waterway: '#1E2C35',
  rail: '#242A2E',
  roadMinor: '#2C3338', // 1.48:1 on ground
  roadSecondary: '#353E43', // 1.74
  roadPrimary: '#3F484E', // 2.03
  roadTrunk: '#4A545A', // 2.45
  roadMotorway: '#556067', // 2.94
  boundary: '#4E5C63',

  // --- text on the map: sparse, small, quiet -----------------------------
  labelFaint: '#5A666B',
  labelQuiet: '#79868B',
  labelPlace: '#9AA5A8',

  // --- interface text ----------------------------------------------------
  ink: '#E8EDEE',
  inkQuiet: '#96A0A3',
  inkFaint: '#5F696C',
  hairline: '#222A2D',

  // --- the three colours -------------------------------------------------
  /** A street the town has prayed over. Warm, cumulative, the point of it all. */
  prayed: '#E0A03A',
  prayedDim: '#7A5A25',
  prayedLift: '#F3C77E', // the core of a street claimed on this walk
  /** A street nobody has covered yet. Grey on purpose: absence has no colour.
   *  It sits inside the road ramp, between primary and trunk, so that it reads
   *  as "a street" first and "not yet prayed for" second. It used to be the
   *  brightest grey on the map, which made absence shout. */
  unprayed: '#414B51',
  /** The route you were given. */
  route: '#4D8DF0',
  routeDim: '#22456F',
  /** You.
   *
   *  Achromatic on purpose. Under deuteranopia the old green (#37E0A8) and the
   *  prayed amber both collapse to a pale yellow and land 1.11:1 apart, i.e.
   *  the same colour. Amber and blue already use up both ends of the one hue
   *  axis a red-green colourblind viewer still has, so the third signal has to
   *  separate by value: the walker is the brightest thing on the map, and the
   *  only circle. That holds for normal, deutan, protan and tritan vision. */
  walker: '#F2F8F9',

  // --- states ------------------------------------------------------------
  warn: '#D98A3C',
  danger: '#D9603C',
} as const

export const type = {
  sans: "system-ui, -apple-system, 'Segoe UI', 'Helvetica Neue', Arial, sans-serif",
  mono: "ui-monospace, 'SF Mono', Menlo, Consolas, monospace",
  size: {
    counter: '3.25rem',
    counterSmall: '1.875rem',
    title: '1.25rem',
    body: '1rem',
    small: '0.875rem',
    micro: '0.8125rem',
    label: '0.75rem',
  },
  weight: { regular: 400, medium: 500, bold: 600 },
  tracking: { label: '0.1em', tight: '-0.02em' },
} as const

export const space = {
  xs: '4px',
  sm: '8px',
  md: '14px',
  lg: '22px',
  xl: '34px',
} as const

export const radius = { sm: '4px', md: '8px', pill: '999px' } as const

/** Map line widths.
 *
 * MapLibre will only accept a zoom expression at the top level of a property,
 * so a wider or thinner version of a ramp has to be a whole ramp of its own
 * rather than a multiplication. `widthRamp` builds them from one set of stops
 * so the proportions stay fixed in one place.
 */
type Stops = readonly (readonly [number, number])[]

const SEGMENT_STOPS: Stops = [
  [11, 1.0],
  [13, 1.8],
  [15, 3.2],
  [17, 5.4],
  [19, 8.0],
]

const ROUTE_STOPS: Stops = [
  [11, 2.0],
  [13, 3.2],
  [15, 5.0],
  [17, 8.0],
  [19, 12.0],
]

export function widthRamp(stops: Stops, factor = 1): unknown[] {
  return [
    'interpolate',
    ['linear'],
    ['zoom'],
    ...stops.flatMap(([z, w]) => [z, Math.round(w * factor * 100) / 100]),
  ]
}

export const mapWidth = {
  segment: widthRamp(SEGMENT_STOPS),
  segmentWide: widthRamp(SEGMENT_STOPS, 1.35),
  segmentCore: widthRamp(SEGMENT_STOPS, 0.35),
  route: widthRamp(ROUTE_STOPS),
  routeCasing: widthRamp(ROUTE_STOPS, 1.9),
} as const

/** Emitted onto :root so CSS and the map read the same numbers. */
export function cssVariables(): string {
  const lines: string[] = []
  for (const [k, v] of Object.entries(color)) {
    lines.push(`  --c-${kebab(k)}: ${v};`)
    // ...and the same colour as bare channels, so a scrim can be built at a
    // partial alpha without any stylesheet ever retyping the hex.
    lines.push(`  --c-${kebab(k)}-rgb: ${rgbChannels(v)};`)
  }
  for (const [k, v] of Object.entries(space)) lines.push(`  --s-${k}: ${v};`)
  for (const [k, v] of Object.entries(radius)) lines.push(`  --r-${k}: ${v};`)
  for (const [k, v] of Object.entries(type.size)) lines.push(`  --t-${kebab(k)}: ${v};`)
  lines.push(`  --font-sans: ${type.sans};`)
  lines.push(`  --font-mono: ${type.mono};`)
  return `:root {\n${lines.join('\n')}\n}`
}

function kebab(s: string): string {
  return s.replace(/[A-Z]/g, (m) => '-' + m.toLowerCase())
}

function rgbChannels(hex: string): string {
  const h = hex.replace('#', '')
  const n = parseInt(h, 16)
  return `${(n >> 16) & 255} ${(n >> 8) & 255} ${n & 255}`
}
