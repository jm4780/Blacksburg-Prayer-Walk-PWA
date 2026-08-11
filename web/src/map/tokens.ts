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
  land: '#0F1518',
  /**
   * Public open space. Presence, not decoration: a park should be felt, not read.
   *
   * Greener and a third brighter than it was. It spent a while at #141B19, which on a
   * near-black ground is not a colour so much as a rumour of one — and the reason it
   * was that low was that a green tint was also being used as an emphasis effect, so
   * anything actually green risked being read as part of it. That effect is gone, and
   * a park can go back to being a park. Relative luminance 0.017, still five times
   * under the dimmest prayer state.
   */
  park: '#2B3533',
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
 *     minor 0.019  <  secondary 0.024  <  primary 0.029  <  trunk 0.035
 *                                                       <  motorway 0.042
 *
 * and the top of that ladder sits at roughly half of `INK.remaining` (0.085) — the
 * dimmest prayer state. So a six-lane interstate crossing the frame can never out-rank
 * a cul-de-sac somebody has prayed for, at any zoom, anywhere in the region.
 *
 * A LADDER IS ONLY A LADDER IF SOMETHING IS ON EACH RUNG. For three revisions this one
 * was not: TNM's functional road class returned 4 for 91% of the region, so `primary`
 * held twelve thousand county lanes and campus side streets, `secondary`, `tertiary`
 * and `minor` held nothing at all, and every gravel track in Montgomery County was
 * drawn at the third-brightest weight the design system has. The countryside came out
 * exactly as loud as the town. See pipeline/basemap/extract.py, which now classifies
 * from the Census feature code at the bottom of the range and from FRC at the top.
 * Nothing in this file changed to fix that, and nothing in this file was ever wrong.
 *
 * These went up 7% for one round and have come back down. Lifting the whole ramp was
 * how the town was made to read brighter before the mission overlay was doing it, and
 * the cost was a global lift that had to be cancelled somewhere else. Roads are the
 * region; the region is drawn one way everywhere.
 */
export const BASEMAP = {
  /** National forest. Felt as a mass on the horizon, never read as a shape. */
  forest: '#141A18',
  /** The New River and its lakes. Cooler than land, barely lighter. */
  water: '#141821',
  waterway: '#1C242D',
  /** Norfolk Southern through Christiansburg. Dashed, and almost gone. */
  rail: '#262B2E',
  road: {
    minor: '#34393C',
    secondary: '#383D40',
    primary: '#3C4144',
    trunk: '#404548',
    motorway: '#44494C',
  },
  /**
   * THE MUNICIPAL LIMITS, AND NOTHING ELSE.
   *
   * There is no emphasis field on this map any more, and removing it is the single
   * largest thing in this revision. What was there: a near-black wash feathered 3.2 km
   * outward from the town to darken the country, and a green-leaning "plate" tinted
   * under the linework inside it to lift the ground the mission stands on. Two ramps,
   * forty bands, three rounds of tuning, and measurements that said it was working —
   * a ten display-level step at the line, which is a real number.
   *
   * On screen it was a soft green cloud with a findable edge. That is what an effect
   * painted over a map looks like, however carefully the falloff is shaped, because
   * the falloff is not the problem: the map is being asked to say something that is
   * not in it.
   *
   * It is in it. Blacksburg is where the mission is, so Blacksburg is where all 1,868
   * prayer segments are drawn, and nowhere else in fifty kilometres has one. The town
   * separates itself by the only means a map may use — what is on it — as soon as the
   * overlay is drawn at a weight that can be seen at all. It was not: a half-pixel
   * hairline at 45% opacity, which renders as roughly nothing, which is why the town
   * looked no different from the county and why three rounds went hunting for an
   * effect to make up the difference. See WIDTH_STOPS and CONTEXTS.town.
   *
   * So this is all that is left of the emphasis work: the municipal line, drawn once,
   * as a boundary. Dashed, because that is what a jurisdictional limit is drawn as on
   * every map that has ever had one, and because a dash carries the shape at a
   * fraction of a solid line's ink. Under the labels, over the roads, quiet enough to
   * miss and definite enough to find when looked for.
   *
   * Geometry: public/basemap/boundary.json, from pipeline/basemap/boundary.py — USGS
   * GovtUnit, Census-sourced, public domain, so it clears release gate G1 (docs/05).
   */
  line: '#FFFFFF',
  lineOpacity: 0.55,
  /**
   * Basemap labels are not the design system's labels. A street name on today's walk
   * is `LABELS.color` (0.55) because the walker is about to act on it; CHRISTIANSBURG
   * is 0.18 because it is only there so the walker knows which way is south.
   */
  label: {
    town: '#4D5255',
    hamlet: '#484D50',
    terrain: '#42474A',
    shield: '#6A6F72',
    water: '#3A4145',
    halo: '#0F1518',
  },
  /** The shield's own plate: darker than the ground it sits on, with a hairline. */
  shieldFill: '#080D10',
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
  subject: '#FFFFFF',
  /**
   * Prayed for, when it is not the subject — on a walk, ground covered last month is
   * context. Desaturated toward green so it stays distinguishable from the merely
   * unwalked without asking for attention.
   */
  covered: '#7E8C86',
  /** Today's assignment, when it is not the subject. */
  assigned: '#9A8A76',
  /** Still to walk. Present, legible, and deliberately receding. */
  remaining: '#4F5458',
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
 * at town scale lines must be thin enough that 1,868 of them do not become a solid
 * mass, and at walking scale thick enough to read at arm's length in sunlight.
 *
 * THE BOTTOM OF THIS RAMP WAS BELOW A PIXEL, AND THAT WAS A BUG, NOT A SETTING.
 *
 * At the dashboard's z10.8 the base was 1.32 px. Multiply by the weight of the state
 * that covers the whole town — remaining, 0.4 — and the mission network was being
 * asked to render at 0.53 px, then composited at 45% opacity on top of that. A line
 * narrower than a pixel does not draw thin; it draws as a fraction of one pixel's
 * coverage, so that is about an eighth of a line's worth of ink. The result is what
 * the last three rounds were actually looking at: a town indistinguishable from the
 * county around it, on a map whose entire hierarchy is supposed to come from the fact
 * that the mission is drawn in one and not the other.
 *
 * 1.5 puts the thinnest state on the map at just under a pixel at z10, and the rest
 * of the curve is unchanged. Nothing here is a preference; a line that is meant to be
 * read may not be drawn narrower than the display can draw.
 */
export const WIDTH_STOPS: Array<[number, number]> = [
  [10, 1.5],
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
  haloColor: '#0F1518',
  haloWidth: 1.4,

  /**
   * THE BRIGHT TIER, and the reason there is a tier at all.
   *
   * Measured off the approved reference, every label outside the municipal line sits
   * between #42474A and #4D5255, and every neighbourhood inside it sits between
   * #D5D6DA and #EBEFEE. Same face, same caps, same tracking; nine times the
   * luminance. Nothing about the type is doing the work — the split is entirely
   * positional, and it says the same thing the rest of this map says: what is inside
   * the town is the mission, and what is outside it is where the mission is not.
   *
   * The outside tier lives in public/basemap/blacksburg.json with the rest of the
   * basemap. This is the inside one, drawn from the app's own segments.
   */
  place: {
    minZoom: 10.2,
    maxZoom: 14.5,
    size: [[10.2, 5.4], [13, 6.6]] as Array<[number, number]>,
    tracking: 0.2,
    color: '#DDE1E2',
  },
  /** BLACKSBURG. The only pure white type on the map, and the largest. */
  town: {
    minZoom: 9.5,
    maxZoom: 14.5,
    size: [[9.5, 6.6], [13, 8.2]] as Array<[number, number]>,
    tracking: 0.28,
    color: '#FFFFFF',
  },
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
