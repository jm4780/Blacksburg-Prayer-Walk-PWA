/**
 * The Prayer Walk Map Design System — tokens.
 *
 * One idea holds the whole system together:
 *
 *     PRAYER STATE OWNS COLOUR. ROAD CLASS OWNS WIDTH.
 *
 * Prayer state — covered, assigned, remaining, held — is the only thing on this map
 * allowed to use hue, opacity and texture. Road class may only make a line slightly
 * wider or slightly narrower. That single rule is what stops the cartography from
 * competing with the mission: an arterial road that nobody has walked stays quieter
 * than a cul-de-sac that somebody has, because width can never out-shout colour.
 *
 * It also means the map cannot drift. Any new road attribute we ever want to show has
 * exactly one honest place to go — the width ramp — and if it does not belong there,
 * it does not belong on the map.
 *
 * The second idea is that there is no basemap. Blacksburg is drawn from the town's own
 * walkable-obligation network, not from a vendor's tiles with our lines painted over
 * them. That is the actual reason the old map felt borrowed: it was. Consequences,
 * all deliberate:
 *
 *   - the prayer data is structurally the subject, because it is the only subject
 *   - it renders identically offline, which matters for a tool used outdoors
 *   - no third-party host can change how this product looks, or stop it working
 *   - nobody else's map looks like this, because nobody else has this dataset
 *
 * What we give up: buildings, land use, and water, none of which we publish. Water is
 * the real loss — it is how people orient in unfamiliar ground. Parks and the town
 * boundary carry that load instead. See docs/20 §3.
 */

// ---------------------------------------------------------------- ground
/**
 * Land is very slightly cooler and darker than the app's card, so the map reads as a
 * surface you are looking *at* rather than a panel of the interface. The difference is
 * about 4% — enough to separate, not enough to notice.
 */
export const GROUND = {
  land: '#0D1113',
  /** Public open space. Presence, not decoration: a park should be felt, not read. */
  park: '#121819',
  /** The edge of the obligation. Not a border — a limit on what we claim. */
  boundary: '#242B2D',
} as const

// ------------------------------------------------------------- prayer ink
/**
 * HIERARCHY IS BUILT FROM LUMINANCE, NOT HUE.
 *
 * The first cut of this palette used a saturated green for covered ground and a
 * saturated orange for the assignment. Two loud hues, competing, and the result read
 * as a default map with brand colours applied — precisely what this system exists to
 * stop being.
 *
 * The rule now: **the subject of the context is drawn in light; everything else is
 * drawn in grey.** On the dashboard the subject is covered ground, so covered is the
 * brightest thing on the map. In a briefing or on a walk the subject is today's
 * assignment, so that is. Nothing else is ever bright.
 *
 * Saturated colour survives in exactly one place — the start point, and the interface
 * around the map. A single warm dot against a monochrome field carries further than a
 * coloured line, and it can never be mistaken for a street.
 *
 * Every state still differs in texture as well as tone: a walker reads this in direct
 * sunlight, and roughly one man in twelve will not separate two greys by hue.
 */
export const INK = {
  /** The subject of this context, whatever it is. Warm white, and unmistakable. */
  subject: '#F2EFE9',
  /**
   * Prayed for, when it is not the subject — on a walk, ground covered last month is
   * context. Desaturated toward green so it stays distinguishable from the merely
   * unwalked without asking for attention.
   */
  covered: '#7E8C86',
  /** Today's assignment, when it is not the subject. */
  assigned: '#9A8A76',
  /** Still to walk. Present, legible, and deliberately receding. */
  remaining: '#414A4D',
  /** Held by another walker right now. Visible so it is not offered twice. */
  held: '#6E6455',
  /** The one saturated mark on the map. Points only, never lines. */
  accent: '#E4712C',
} as const

export const INK_OPACITY = {
  subject: 1,
  covered: 0.85,
  assigned: 0.85,
  // Low-chroma enough to carry full opacity and still recede.
  remaining: 0.9,
  held: 0.7,
} as const

/**
 * Texture carries the same information as colour, independently.
 * `null` means solid. Values are in line-widths, as MapLibre expects.
 */
export const TEXTURE: Record<string, number[] | null> = {
  subject: null,
  covered: null,
  assigned: null,
  remaining: [2, 2.4],
  held: [0.6, 1.8],   // dotted — present, but not a line you may take
}

// ------------------------------------------------------------ road weight
/**
 * A deliberately compressed ramp. On a driving map an arterial might be six times a
 * residential street; here the spread is 1.25:1, because the residential street is
 * where the households are and therefore where the mission is. Arterials earn just
 * enough width to orient by and no more.
 *
 * Trails are narrower than streets but never invisible: they are often the only way
 * between two neighbourhoods on foot.
 */
export const CLASS_WEIGHT: Record<string, number> = {
  Arterial: 1.25,
  Secondary: 1.15,
  Collector: 1.08,
  Local: 1.0,
  Trail: 0.85,
  Sidewalk: 0.7,
  Alley: 0.7,
  default: 0.95,
}

/**
 * Base width in pixels at each zoom, before the class multiplier. The curve is steep:
 * at town scale lines must be thin enough that 1,582 of them do not become a solid
 * mass, and at walking scale thick enough to read at arm's length in sunlight.
 */
export const WIDTH_STOPS: Array<[number, number]> = [
  [10, 0.9],
  [12, 1.6],
  [14, 3.0],
  [16, 5.5],
  [18, 9.0],
]

/** Covered and assigned ground is drawn heavier than context. */
export const STATE_WEIGHT = {
  subject: 1.9,
  covered: 1.15,
  assigned: 1.15,
  remaining: 0.8,
  held: 0.95,
} as const

/** The halo under covered and assigned ground. Not a glow — a suggestion of depth. */
export const HALO = {
  widthFactor: 3.4,
  opacity: { subject: 0.10 },
} as const

// ---------------------------------------------------------------- labels
/**
 * The label philosophy is the sharpest departure from a general-purpose map, and the
 * one most likely to be argued with, so it is stated plainly:
 *
 *     A general map labels everything it can fit. This map labels only what the
 *     walker has been asked to do, and only when they are close enough to act on it.
 *
 * At town scale there are no labels at all — the dashboard map is a picture of
 * progress, and 2,600 street names would bury it. Labels begin at the zoom where a
 * person is deciding which way to turn, and even then only for streets that are part
 * of today's mission or already covered. An unwalked street two neighbourhoods away
 * does not need naming; naming it is noise wearing the costume of helpfulness.
 */
export const LABELS = {
  /** Below this zoom, none. */
  minZoom: 14.5,
  /** Below this zoom, only assigned streets. Above it, covered ones join them. */
  coveredFromZoom: 15.5,
  font: ['Prayer Walk Regular'],
  size: [
    [14.5, 10],
    [17, 13],
  ] as Array<[number, number]>,
  color: '#C6C3BC',
  haloColor: '#0D1113',
  haloWidth: 1.4,
} as const

// ------------------------------------------------------------------ motion
/**
 * Motion here reports state; it never celebrates. A route drawing itself in tells the
 * walker "this is yours now". A completed walk settling into the covered colour tells
 * them "it is recorded". Neither should feel like a reward — the walk was the point,
 * and an app that congratulates you for praying has misunderstood what it is for.
 *
 * Everything is short, eased out, and never bounces.
 */
export const MOTION = {
  routeDrawMs: 700,
  coverageSettleMs: 900,
  cameraMs: 650,
  easing: 'cubic-bezier(.22,.61,.36,1)',
  /** Respected everywhere; motion is decoration if it cannot be turned off. */
  reducedMotionMs: 0,
} as const

// ---------------------------------------------------------------- controls
export const CONTROL = {
  bg: 'rgba(16, 20, 22, .55)',
  border: 'rgba(247, 245, 241, .12)',
  ink: '#9AA0A0',
  inkActive: '#F7F5F1',
  height: 32,
  radius: 999,
  blur: 6,
  /** Mono, uppercase, letter-spaced — the same treatment as the metric labels, so a
   *  map control reads as part of the interface rather than as map furniture. */
  font: "500 10px/1 'IBM Plex Mono', ui-monospace, monospace",
  tracking: '.12em',
} as const
