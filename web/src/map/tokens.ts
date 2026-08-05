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
 * The second idea is that the basemap is ours. Not a vendor's tiles with our lines
 * painted over them — that is the actual reason the old map felt borrowed — but a
 * single `.pmtiles` archive we build, style and serve ourselves, exactly as
 * docs/02-technical-plan.md §1.1 specified before anything was written.
 *
 * Getting there cost two corrections. The first cut drew only the required segments,
 * which is not a quiet basemap but no basemap, and produced a network diagram with
 * the bypass and the whole non-obligation street fabric missing. The second drew the
 * town's own roads, parks and boundary — a real town, ending at a hard line, floating
 * in a void. **Removing the world is not the same as letting the prayer data lead
 * it.** The ground now carries a fifty-kilometre region: roads, water, forest,
 * railways and place names, continuing past the town limit in every direction, drawn
 * dark enough to sit underneath without ever competing.
 *
 * Consequences, all deliberate:
 *
 *   - the prayer data leads through contrast, against a world that is present
 *   - it renders identically offline, which matters for a tool used outdoors
 *   - no third-party host can change how this product looks, or stop it working
 *   - the basemap corpus is US federal public domain, so it carries no share-alike
 *     obligation onto the town data and no licence gate of its own (docs/05, G1)
 *
 * The regional ground lives in `public/basemap/blacksburg.json`, which is a static
 * style document rather than TypeScript. The colours below are the same colours;
 * `__tests__/basemap.test.ts` fails the build if they ever drift apart.
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
  park: '#141B19',
  /** The edge of the obligation. Not a border — a limit on what we claim. */
  boundary: '#242B2D',
  /**
   * The town itself: every public road that is not part of the obligation, including
   * US 460 and its ramps. This is the layer whose absence made the map read as a
   * network diagram instead of a place. Removing the world is not the same as
   * letting the prayer data lead it — the world just has to be quiet.
   */
  context: '#252C2F',
  contextMajor: '#333C40',
} as const

/**
 * The regional basemap — everything outside the obligation, and the ground beneath
 * it. These values are duplicated in `public/basemap/blacksburg.json`, which is what
 * MapLibre actually loads; the test in `__tests__/basemap.test.ts` asserts the two
 * agree and that the whole set stays under the prayer states.
 *
 * The road ramp is the load-bearing part. Five steps of luminance and nothing else —
 * no hue, no texture, no casing:
 *
 *     minor 0.020  <  secondary 0.026  <  primary 0.032  <  trunk 0.038
 *                                                       <  motorway 0.046
 *
 * and the top of that ladder still sits at a little over half of `INK.remaining`
 * (0.085) — the dimmest prayer state. So a six-lane interstate crossing the frame can
 * never out-rank a cul-de-sac somebody has prayed for, at any zoom, anywhere in the
 * region. The ramp was lifted about 7% from its first cut, which is what lets the town
 * read as slightly richer than the country around it once the wash is applied to
 * everything else.
 */
export const BASEMAP = {
  /** National forest. Felt as a mass on the horizon, never read as a shape. */
  forest: '#111713',
  /** The New River and its lakes. Cooler than land, barely lighter. */
  water: '#0E161B',
  waterway: '#17222A',
  /** Norfolk Southern through Christiansburg. Dashed, and almost gone. */
  rail: '#1A1F22',
  road: {
    minor: '#21282C',
    secondary: '#262E32',
    primary: '#2B3337',
    trunk: '#2F383C',
    motorway: '#343E43',
  },
  /**
   * EMPHASIS, NOT CONTENT.
   *
   * The archive is one corpus drawn one way everywhere, which is what makes it read
   * as a real place instead of a town with scenery glued around it. What it lacked
   * was a centre. This is that: a neutral near-black, feathered outward from the town
   * over seven kilometres, drawn over everything the basemap puts down.
   *
   * It is composited, not restyled, and that is the whole trick. Alpha blending moves
   * every colour the same fraction toward the wash, so one number produces all three
   * of the things being asked for at once —
   *
   *     darker           values fall ~30% outside the town
   *     lower contrast   differences between them fall by the same fraction
   *     less saturated   chroma collapses toward a neutral
   *
   * — and none of them can drift out of agreement with the others, because there is
   * only one of them.
   *
   * The falloff follows the actual municipal limits, from 800 m inside the line to
   * 4 km outside it. It starts inside on purpose: a ramp that began exactly at the
   * boundary would put its first millimetre right on the municipal edge, which is how
   * you accidentally draw a border. Four kilometres of smootherstep has nowhere it
   * visibly begins.
   *
   * The boundary is USGS GovtUnit — Census-sourced, public domain — not the town's own
   * GIS, so it can be checked in without tripping release gate G1 (docs/05).
   *
   * Geometry: public/basemap/emphasis.json, from pipeline/basemap/emphasis.py.
   */
  wash: '#070707',
  washAlpha: 0.22,
  /**
   * Basemap labels are not the design system's labels. A street name on today's walk
   * is `LABELS.color` (0.55) because the walker is about to act on it; CHRISTIANSBURG
   * is 0.18 because it is only there so the walker knows which way is south.
   */
  label: {
    town: '#6F7674',
    hamlet: '#5C6362',
    terrain: '#4E5654',
    shield: '#5A6265',
    water: '#414E52',
    halo: '#0D1113',
  },
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
 * Separation is by luminance, and that is what makes it safe: a walker reads this in
 * direct sunlight, and roughly one man in twelve will not separate two greys by hue —
 * but nobody fails to separate 0.085 from 0.249 from 0.865. Texture is used only
 * where a state means something other than progress: held (dotted, someone else has
 * it) and dropped (dashed, deliberately not walked).
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
  remaining: '#4A5457',
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
 * `null` means solid. Values are in line-widths, as MapLibre expects.
 *
 * Remaining streets used to be dashed. They are not any more, and the reason is worth
 * keeping: a dash is a texture, and texture attracts the eye. Two thousand dashed
 * streets read as stippling — a deliberate pattern, something being *said* — when all
 * the map means by them is "not yet". Solid and dim, they become what they should
 * always have been: the town, waiting. Weight came down to pay for the extra ink.
 *
 * Texture survives only where a state is not a point on the progress scale: held is
 * dotted because somebody else is on it right now, dropped is dashed because it was
 * chosen against.
 */
export const TEXTURE: Record<string, number[] | null> = {
  subject: null,
  covered: null,
  assigned: null,
  remaining: null,
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
  [10, 1.0],
  [12, 1.8],
  [14, 3.2],
  [16, 5.8],
  [18, 9.5],
]

/**
 * Context roads — the town under the mission.
 *
 * These are NOT always thinner than the prayer overlays, and deliberately so: US 460
 * at z18 is 7.6 px where a remaining sidewalk is 3.7 px, because width belongs to road
 * class and 460 really is bigger than a sidewalk. Making the bypass hairline to keep
 * it "under" the mission would be a lie about the town.
 *
 * The hierarchy is carried by luminance instead, which is the founding rule of this
 * system. The brightest thing on the ground (`contextMajor`, relative luminance 0.043)
 * sits at roughly half the dimmest prayer state (`remaining`, 0.085), and every state
 * above that pulls further away — covered is 0.249, the subject 0.865. A wide road can
 * therefore never out-rank a narrow obligation, at any zoom.
 */
export const CONTEXT_WIDTH: Array<[number, number]> = [
  [10, 0.4],
  [12, 0.7],
  [14, 1.3],
  [16, 2.4],
  [18, 4.0],
]

/** Covered and assigned ground is drawn heavier than context. */
export const STATE_WEIGHT = {
  // Halved from the first cut. The references draw the route as a thin, precise line
  // and win attention through contrast against a quiet ground, not through mass. A
  // heavy stroke reads as emphasis at first glance and as clumsiness at second.
  subject: 0.95,
  covered: 0.7,
  assigned: 0.7,
  // Solid now, so thinner: the old 0.55 dashed at a 45% duty cycle laid down about
  // a quarter of a line's worth of ink, and drawing it solid at the same width would
  // have doubled the weight of the single largest layer on the map.
  remaining: 0.4,
  held: 0.6,
} as const

/** The halo under covered and assigned ground. Not a glow — a suggestion of depth. */
export const HALO = {
  // Tighter and fainter: separation from the ground beneath, not a glow around the
  // line. At 3.4x and 0.10 it was reading as a halo, which is decoration.
  widthFactor: 2.6,
  opacity: { subject: 0.07 },
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
