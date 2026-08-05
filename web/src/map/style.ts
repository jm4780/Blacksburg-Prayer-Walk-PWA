/**
 * The Prayer Walk Map Design System — style construction.
 *
 * Turns the tokens into a MapLibre style. Every screen in the product gets its map
 * from here, so "the map" is a single artefact with six settings rather than six maps
 * that happen to look similar. If a rule is worth having, it is enforced in this file;
 * if it is worth breaking, it is broken here too, once, where the exception is visible.
 *
 * Contexts, and what each is actually for:
 *
 *   TOWN       the dashboard's picture of progress. Read, not navigated. No labels,
 *              no controls, thin context, covered ground carrying the whole message.
 *   BRIEFING   a mission being considered. The route is the only saturated thing on
 *              screen; its streets are named because the walker is about to commit.
 *   WALKING    in use, outdoors, one-handed, in sunlight. Heaviest weights, highest
 *              contrast, labels on. Nothing that is not the route or the way to it.
 *   RECORDING  what was walked, being confirmed. Assigned and covered shown together
 *              so the difference between plan and record is visible.
 *   EDITING    picking streets by thumb. Context lifted — you cannot choose a street
 *              you cannot see — and the widest tap targets in the system.
 *   ATLAS      the whole obligation, expanded. Boundary visible. Still no labels: at
 *              this scale a name is a smudge.
 */
import {
  CLASS_WEIGHT, CONTEXT_WIDTH, CONTROL, GROUND, HALO, INK, INK_OPACITY, LABELS,
  STATE_WEIGHT, TEXTURE, WIDTH_STOPS,
} from './tokens'

export type MapContext =
  | 'town' | 'briefing' | 'walking' | 'recording' | 'editing' | 'atlas'

export interface ContextSpec {
  /**
   * Which state is the point of this screen. It is drawn in light and given the halo;
   * every other state recedes to grey. This is the field that makes the six contexts
   * one system rather than six palettes.
   */
  subject: 'covered' | 'assigned'
  /** Labels at all, and from which zoom. */
  labels: boolean
  /** Show the town boundary. */
  boundary: boolean
  /** Show public open space. */
  parks: boolean
  /**
   * The rest of the town's public roads. Orientation, not obligation — this is the
   * layer whose absence made the map read as a network diagram.
   */
  context: boolean
  /** Zoom buttons. */
  controls: boolean
  /** Multiplier on every line width — the single knob for "how loud is this screen". */
  emphasis: number
  /** Invisible tap-target width, px. 0 disables selection. */
  hit: number
  /** Ceiling for auto-fit. */
  maxZoom: number
  /** How much unwalked context to let through. */
  remainingOpacity: number
}

export const CONTEXTS: Record<MapContext, ContextSpec> = {
  // A picture. Nothing here is navigated, so nothing here is a control.
  town:      { context: true, subject: 'covered',
               labels: false, boundary: false, parks: true,  controls: false,
               emphasis: 1.0, hit: 0,  maxZoom: 15,   remainingOpacity: 0.45 },
  // A decision. The route is the subject and its streets are named.
  briefing:  { context: true, subject: 'assigned',
               labels: true,  boundary: false, parks: true,  controls: false,
               emphasis: 1.1, hit: 0,  maxZoom: 16,   remainingOpacity: 0.3 },
  // In use. Loudest weights, least context, most contrast.
  walking:   { context: true, subject: 'assigned',
               labels: true,  boundary: false, parks: false, controls: true,
               emphasis: 1.35, hit: 0, maxZoom: 17,   remainingOpacity: 0.22 },
  // Plan against record. Both states present at once, deliberately.
  recording: { context: true, subject: 'assigned',
               labels: true,  boundary: false, parks: false, controls: true,
               emphasis: 1.2, hit: 0,  maxZoom: 17,   remainingOpacity: 0.3 },
  // Selection by thumb. Context lifted so nearby streets are findable.
  editing:   { context: true, subject: 'assigned',
               labels: true,  boundary: false, parks: false, controls: true,
               emphasis: 1.15, hit: 26, maxZoom: 17.5, remainingOpacity: 0.55 },
  // The whole obligation.
  atlas:     { context: true, subject: 'covered',
               labels: false, boundary: true,  parks: true,  controls: true,
               emphasis: 1.0, hit: 0,  maxZoom: 15,   remainingOpacity: 0.5 },
}

// ---------------------------------------------------------------- helpers
type Expr = any

const interpolate = (stops: Array<[number, number]>, scale = 1): Expr => [
  'interpolate', ['linear'], ['zoom'],
  ...stops.flatMap(([z, v]) => [z, v * scale]),
]

/**
 * Width = base(zoom) x class multiplier x state weight x context emphasis.
 *
 * The zoom interpolation has to be the OUTERMOST expression — MapLibre rejects a
 * `['zoom']` nested inside another operator, and rejects it silently through the map's
 * error event rather than by throwing, so the layer simply never appears. The class
 * multiplier therefore lives inside each interpolation stop rather than wrapping the
 * whole thing.
 */
function classMultiplier(): Expr {
  return ['match', ['coalesce', ['get', 'road_class'], ['get', 'path_type'], 'default'],
    ...Object.entries(CLASS_WEIGHT).filter(([k]) => k !== 'default')
      .flatMap(([k, v]) => [k, v]),
    CLASS_WEIGHT.default]
}

function widthFor(state: keyof typeof STATE_WEIGHT, emphasis: number): Expr {
  const scale = STATE_WEIGHT[state] * emphasis
  return [
    'interpolate', ['linear'], ['zoom'],
    ...WIDTH_STOPS.flatMap(([z, v]) => [z, ['*', v * scale, classMultiplier()]]),
  ]
}

const isState = (s: string): Expr => ['==', ['get', 'state'], s]

/**
 * The map with no basemap under it.
 *
 * Used when `/basemap/blacksburg.pmtiles` cannot be reached at all — a first run with
 * no network and a cold service worker, or a deployment that has not shipped the
 * archive. The town's own roads, parks and boundary still draw on top of it, so the
 * degraded map is the map this product had before the archive existed: correct, and
 * missing the region.
 *
 * Glyphs are served from our own origin, so even the fallback has no third-party
 * runtime dependency — see docs/20 §2.
 */
export function baseStyle(): any {
  return {
    version: 8,
    glyphs: '/fonts/{fontstack}/{range}.pbf',
    sources: {},
    layers: [
      { id: 'ground', type: 'background',
        paint: { 'background-color': GROUND.land } },
    ],
  }
}

// ------------------------------------------------------------------ layers
/**
 * Draw order is the hierarchy, made literal. Bottom to top:
 *
 *   ground -> parks -> boundary -> remaining -> held -> covered halo -> covered
 *          -> assigned halo -> assigned -> labels -> tap targets
 *
 * Nothing above can be obscured by anything below it, so the most important thing on
 * the map is also, structurally, the last thing drawn.
 */
export function prayerLayers(ctx: MapContext, basemap = false): any[] {
  const c = CONTEXTS[ctx]
  const layers: any[] = []

  if (c.parks) {
    layers.push({
      id: 'pw-parks', type: 'fill', source: 'pw-parks',
      paint: { 'fill-color': GROUND.park, 'fill-opacity': 1 },
    })
  }

  // --- the town itself ---------------------------------------------------------
  // Drawn before anything that carries meaning, so it can never sit on top of the
  // mission. Major roads — US 460, the ramps — get a little more light, because they
  // are what somebody actually orients by.
  //
  // Skipped when the regional basemap is live: the archive already carries every
  // public road in Blacksburg, at the same luminance ramp, and drawing both would
  // double the ink on exactly the layer that has to stay quietest. This layer is
  // now the town's stand-in for a basemap that could not be fetched.
  if (c.context && !basemap) {
    layers.push({
      id: 'pw-context', type: 'line', source: 'pw-context',
      layout: { 'line-cap': 'round', 'line-join': 'round' },
      paint: {
        'line-color': ['case', ['get', 'major'], GROUND.contextMajor, GROUND.context],
        'line-width': [
          'interpolate', ['linear'], ['zoom'],
          ...CONTEXT_WIDTH.flatMap(([z, v]) =>
            [z, ['case', ['get', 'major'], v * 1.9, v]]),
        ],
        'line-opacity': 0.85,
      },
    })
  }

  if (c.boundary) {
    layers.push({
      id: 'pw-boundary', type: 'line', source: 'pw-boundary',
      layout: { 'line-cap': 'round' },
      paint: {
        'line-color': GROUND.boundary, 'line-width': 1.2,
        'line-dasharray': [4, 4], 'line-opacity': 0.9,
      },
    })
  }

  // --- still to walk: the ground the mission still owes -----------------------
  layers.push({
    id: 'pw-remaining', type: 'line', source: 'pw-segments',
    filter: isState('todo'),
    // Round now that the line is solid. Butt caps kept the old dashes crisp; on a
    // solid hairline they leave a visible nick at every segment junction, and the
    // network is stored as thousands of short segments.
    layout: { 'line-cap': 'round', 'line-join': 'round' },
    paint: {
      'line-color': INK.remaining,
      'line-width': widthFor('remaining', c.emphasis),
      'line-opacity': c.remainingOpacity,
      ...(TEXTURE.remaining ? { 'line-dasharray': TEXTURE.remaining } : null),
    },
  })

  // --- held by somebody else, right now ---------------------------------------
  layers.push({
    id: 'pw-held', type: 'line', source: 'pw-segments',
    filter: isState('held'),
    layout: { 'line-cap': 'round', 'line-join': 'round' },
    paint: {
      'line-color': INK.held,
      'line-width': widthFor('held', c.emphasis),
      'line-opacity': INK_OPACITY.held,
      'line-dasharray': TEXTURE.held as number[],
    },
  })

  // --- already prayed for -------------------------------------------------------
  const coveredIsSubject = c.subject === 'covered'
  if (coveredIsSubject) {
    layers.push({
      id: 'pw-covered-halo', type: 'line', source: 'pw-segments',
      filter: isState('done'),
      layout: { 'line-cap': 'round', 'line-join': 'round' },
      paint: {
        'line-color': INK.subject,
        'line-width': widthFor('subject', c.emphasis * HALO.widthFactor),
        'line-opacity': HALO.opacity.subject, 'line-blur': 2,
      },
    })
  }
  layers.push({
    id: 'pw-covered', type: 'line', source: 'pw-segments',
    filter: isState('done'),
    layout: { 'line-cap': 'round', 'line-join': 'round' },
    paint: {
      'line-color': coveredIsSubject ? INK.subject : INK.covered,
      'line-width': widthFor(coveredIsSubject ? 'subject' : 'covered', c.emphasis),
      'line-opacity': coveredIsSubject ? INK_OPACITY.subject : INK_OPACITY.covered,
    },
  })

  // --- today's assignment: the only saturated thing on the map ------------------
  const assignedIsSubject = c.subject === 'assigned'
  if (assignedIsSubject) {
    layers.push({
      id: 'pw-assigned-halo', type: 'line', source: 'pw-route',
      layout: { 'line-cap': 'round', 'line-join': 'round' },
      paint: {
        'line-color': INK.subject,
        'line-width': interpolate(WIDTH_STOPS,
          STATE_WEIGHT.subject * c.emphasis * HALO.widthFactor),
        'line-opacity': HALO.opacity.subject, 'line-blur': 3,
      },
    })
  }
  layers.push({
    id: 'pw-assigned', type: 'line', source: 'pw-route',
    layout: { 'line-cap': 'round', 'line-join': 'round' },
    paint: {
      'line-color': assignedIsSubject ? INK.subject : INK.assigned,
      'line-width': interpolate(WIDTH_STOPS,
        (assignedIsSubject ? STATE_WEIGHT.subject : STATE_WEIGHT.assigned) * c.emphasis),
      'line-opacity': assignedIsSubject ? INK_OPACITY.subject : INK_OPACITY.assigned,
    },
  })

  // --- selection, while editing --------------------------------------------------
  if (ctx === 'editing') {
    layers.push({
      id: 'pw-selected', type: 'line', source: 'pw-segments',
      filter: isState('selected'),
      layout: { 'line-cap': 'round', 'line-join': 'round' },
      paint: {
        'line-color': INK.subject,
        'line-width': widthFor('subject', c.emphasis),
        'line-opacity': 1,
      },
    })
    // A planned street the walker has dropped. Shown as an absence, not an error:
    // choosing not to walk something is a legitimate report, not a mistake.
    layers.push({
      id: 'pw-dropped', type: 'line', source: 'pw-segments',
      filter: isState('removed'),
      layout: { 'line-cap': 'butt' },
      paint: {
        'line-color': INK.remaining,
        'line-width': widthFor('remaining', c.emphasis * 1.3),
        'line-opacity': 0.7, 'line-dasharray': [1.2, 1.6],
      },
    })
  }

  // --- names, only where they help ------------------------------------------------
  if (c.labels) {
    layers.push({
      id: 'pw-labels', type: 'symbol', source: 'pw-segments',
      minzoom: LABELS.minZoom,
      filter: ['all',
        ['has', 'name'],
        // Only the mission, and only nearby coverage. See tokens.ts LABELS.
        ['any', isState('selected'), isState('done'), isState('assigned')]],
      layout: {
        'symbol-placement': 'line',
        'text-field': ['get', 'name'],
        'text-font': LABELS.font,
        'text-size': interpolate(LABELS.size as Array<[number, number]>),
        'text-max-angle': 34,
        'text-padding': 4,
        'symbol-spacing': 260,
      },
      paint: {
        'text-color': LABELS.color,
        'text-halo-color': LABELS.haloColor,
        'text-halo-width': LABELS.haloWidth,
      },
    })
  }

  // --- the thumb ------------------------------------------------------------------
  if (c.hit > 0) {
    layers.push({
      id: 'pw-hit', type: 'line', source: 'pw-segments',
      paint: { 'line-color': '#000', 'line-opacity': 0, 'line-width': c.hit },
    })
  }

  return layers
}

export const controlCss = CONTROL
