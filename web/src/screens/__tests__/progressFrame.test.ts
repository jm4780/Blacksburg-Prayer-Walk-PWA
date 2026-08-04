/**
 * The map's framing rule.
 *
 * This is the piece that decides whether the dashboard's map corroborates the
 * percentage above it or quietly contradicts it, and it has two failure modes that
 * pull in opposite directions — too wide and progress vanishes, too tight and the
 * town looks nearly finished. Both are tested here, because either one is a
 * truthfulness bug rather than a cosmetic one.
 */
import { describe, expect, it } from 'vitest'
import { boundsOf, frameAsRing, progressFrame } from '../progressFrame'

/** Blacksburg's rough extent, near enough for these ratios. */
const TOWN = { west: -80.47, south: 37.18, east: -80.37, north: 37.28 }
const area = (b: { west: number; south: number; east: number; north: number }) =>
  (b.east - b.west) * (b.north - b.south)

describe('boundsOf', () => {
  it('returns null for nothing', () => {
    expect(boundsOf([])).toBeNull()
  })

  it('ignores non-finite coordinates rather than poisoning the box', () => {
    const b = boundsOf([[-80.4, 37.2], [NaN, 37.9] as any, [-80.3, 37.25]])!
    expect(b).toEqual({ west: -80.4, south: 37.2, east: -80.3, north: 37.25 })
  })
})

describe('progressFrame', () => {
  it('shows the whole town when nothing has been walked', () => {
    // There is no progress to make legible, and inventing a zoom would be arbitrary.
    expect(progressFrame(null, TOWN)).toEqual(TOWN)
  })

  it('returns null when there is no network at all', () => {
    expect(progressFrame(null, null)).toBeNull()
  })

  it('frames tightly enough that a single walk is legible', () => {
    // One ~1km loop in a 145-mile town. Framed on the town it is invisible; the
    // whole point of this function is that it is not.
    const covered = { west: -80.415, south: 37.228, east: -80.405, north: 37.236 }
    const f = progressFrame(covered, TOWN)!
    expect(area(f)).toBeLessThan(area(TOWN) * 0.25)
  })

  it('never fills the frame with progress — the town must stay visibly larger', () => {
    // The dishonest failure. Covered ground should read as the subject and clearly
    // not as the whole story.
    const covered = { west: -80.415, south: 37.228, east: -80.405, north: 37.236 }
    const f = progressFrame(covered, TOWN)!
    const share = area(covered) / area(f)
    expect(share).toBeLessThan(0.45)
  })

  it('does not zoom to building scale for one short street', () => {
    const tiny = { west: -80.4141, south: 37.2296, east: -80.4139, north: 37.2298 }
    const f = progressFrame(tiny, TOWN)!
    expect(f.north - f.south).toBeGreaterThanOrEqual(0.0099)
  })

  it('widens by itself as coverage spreads', () => {
    const near = { west: -80.415, south: 37.228, east: -80.405, north: 37.236 }
    const far = { west: -80.45, south: 37.19, east: -80.39, north: 37.26 }
    expect(area(progressFrame(far, TOWN)!)).toBeGreaterThan(
      area(progressFrame(near, TOWN)!))
  })

  it('converges on the town once coverage is general', () => {
    // Pulling back past the network's own extent would buy blank countryside.
    const nearlyEverywhere = {
      west: -80.465, south: 37.185, east: -80.375, north: 37.275,
    }
    expect(progressFrame(nearlyEverywhere, TOWN)).toEqual(TOWN)
  })

  it('never proposes a frame outside the network', () => {
    const edge = { west: -80.469, south: 37.181, east: -80.468, north: 37.182 }
    const f = progressFrame(edge, TOWN)!
    expect(f.west).toBeGreaterThanOrEqual(TOWN.west)
    expect(f.south).toBeGreaterThanOrEqual(TOWN.south)
    expect(f.east).toBeLessThanOrEqual(TOWN.east)
    expect(f.north).toBeLessThanOrEqual(TOWN.north)
  })
})

describe('frameAsRing', () => {
  it('closes the ring, so fitBounds sees all four corners', () => {
    const r = frameAsRing(TOWN)
    expect(r.coordinates).toHaveLength(5)
    expect(r.coordinates[0]).toEqual(r.coordinates[4])
    const b = boundsOf(r.coordinates)!
    expect(b).toEqual(TOWN)
  })
})
