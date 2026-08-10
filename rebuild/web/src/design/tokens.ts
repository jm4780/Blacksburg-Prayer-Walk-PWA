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
  land: '#131A15', // wooded ground, one step up from the ground
  water: '#0E161B', // darker than land, so water reads as a hole
  waterway: '#17222A',
  rail: '#1A1F22',
  roadMinor: '#20262A',
  roadSecondary: '#252C2F',
  roadPrimary: '#2A3134',
  roadTrunk: '#2E3639',
  roadMotorway: '#333C40',
  boundary: '#3D4A50',

  // --- text on the map: sparse, small, quiet -----------------------------
  labelFaint: '#414E52',
  labelQuiet: '#5A6265',
  labelPlace: '#7F8583',

  // --- interface text ----------------------------------------------------
  ink: '#E8EDEE',
  inkQuiet: '#96A0A3',
  inkFaint: '#5F696C',
  hairline: '#222A2D',

  // --- the three colours -------------------------------------------------
  /** A street the town has prayed over. Warm, cumulative, the point of it all. */
  prayed: '#E0A03A',
  prayedDim: '#7A5A25',
  /** A street nobody has covered yet. Grey on purpose: absence has no colour. */
  unprayed: '#49535A',
  /** The route you were given. */
  route: '#4D8DF0',
  routeDim: '#22456F',
  /** You. */
  walker: '#37E0A8',

  // --- states ------------------------------------------------------------
  warn: '#D98A3C',
  danger: '#D9603C',
} as const

export const type = {
  sans: "system-ui, -apple-system, 'Segoe UI', 'Helvetica Neue', Arial, sans-serif",
  mono: "ui-monospace, 'SF Mono', Menlo, Consolas, monospace",
  size: {
    counter: '3.25rem',
    counterSmall: '1.75rem',
    title: '1.25rem',
    body: '1rem',
    small: '0.875rem',
    label: '0.6875rem',
  },
  weight: { regular: 400, medium: 500, bold: 600 },
  tracking: { label: '0.14em', tight: '-0.02em' },
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
  for (const [k, v] of Object.entries(color)) lines.push(`  --c-${kebab(k)}: ${v};`)
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
