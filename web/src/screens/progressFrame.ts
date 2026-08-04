/**
 * Where should the town map be pointed?
 *
 * The obvious answer — fit the whole town — is the one that fails. Early in a
 * project, a few covered miles inside a 145-mile network is a fleck of green in a
 * field of grey, and the map ends up contradicting the percentage printed above it.
 * The screen says "4.5%" and the picture says "nothing has happened".
 *
 * The opposite failure is worse. Framing tightly on the covered ground fills the
 * screen with green and implies a town nearly finished. That would be flattering and
 * false, and this project has spent four phases refusing to overstate its numbers.
 *
 * So: frame the covered ground, then deliberately pull back until it occupies a
 * minority of the view. Progress is legible, and it is visibly a small part of
 * something much larger. The frame widens on its own as coverage spreads, and once
 * coverage is general it converges on the whole town — which is by then the honest
 * picture anyway.
 */

export interface Bounds { west: number; south: number; east: number; north: number }

/**
 * How much bigger than the covered area the view should be, per side. 0.75 puts the
 * covered extent at roughly a third of the frame's width — clearly the subject,
 * clearly not the whole story.
 */
const PULL_BACK = 0.75

/** Never zoom closer than this, in degrees of latitude (~1.1 km). A single short
 *  street would otherwise fill the screen at building scale. */
const MIN_SPAN_LAT = 0.010

export function boundsOf(coords: Iterable<[number, number]>): Bounds | null {
  let west = Infinity, south = Infinity, east = -Infinity, north = -Infinity
  let seen = false
  for (const [lon, lat] of coords) {
    if (!Number.isFinite(lon) || !Number.isFinite(lat)) continue
    seen = true
    if (lon < west) west = lon
    if (lon > east) east = lon
    if (lat < south) south = lat
    if (lat > north) north = lat
  }
  return seen ? { west, south, east, north } : null
}

function clampTo(inner: Bounds, outer: Bounds): Bounds {
  return {
    west: Math.max(inner.west, outer.west),
    south: Math.max(inner.south, outer.south),
    east: Math.min(inner.east, outer.east),
    north: Math.min(inner.north, outer.north),
  }
}

/**
 * The frame for a given state of the town.
 *
 * @param covered  bounds of everything recorded as prayed for, or null if nothing is
 * @param whole    bounds of the entire required network
 */
export function progressFrame(covered: Bounds | null, whole: Bounds | null): Bounds | null {
  if (!whole) return null
  // Nothing walked yet: the whole town is the only honest picture, and there is no
  // progress to make legible.
  if (!covered) return whole

  const latSpan = Math.max(covered.north - covered.south, 1e-9)
  const lonSpan = Math.max(covered.east - covered.west, 1e-9)

  // Pull back proportionally, then enforce a floor so a single street cannot zoom
  // the map to building scale.
  let padLat = latSpan * PULL_BACK
  let padLon = lonSpan * PULL_BACK
  const framedLat = latSpan + 2 * padLat
  if (framedLat < MIN_SPAN_LAT) {
    const extra = (MIN_SPAN_LAT - framedLat) / 2
    padLat += extra
    // Longitude is compressed at this latitude; widen proportionally so the frame
    // does not come out as a letterbox.
    padLon += extra / Math.cos((covered.north * Math.PI) / 180)
  }

  const framed: Bounds = {
    west: covered.west - padLon,
    south: covered.south - padLat,
    east: covered.east + padLon,
    north: covered.north + padLat,
  }

  // Never show emptiness beyond the town: pulling back past the network's own extent
  // buys blank space, not context.
  const clamped = clampTo(framed, whole)
  return (clamped.east > clamped.west && clamped.north > clamped.south) ? clamped : whole
}

/** The frame as a closed ring, which is what MapView's `fitTo` consumes. */
export function frameAsRing(b: Bounds): { type: 'LineString'; coordinates: [number, number][] } {
  return {
    type: 'LineString',
    coordinates: [
      [b.west, b.south], [b.east, b.south],
      [b.east, b.north], [b.west, b.north], [b.west, b.south],
    ],
  }
}
