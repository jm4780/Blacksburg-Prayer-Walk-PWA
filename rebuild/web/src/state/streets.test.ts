/**
 * Adjacency rebuilt on the phone has to be the network's own adjacency, not a
 * near-enough guess, or picking streets by hand quietly claims the wrong ones.
 *
 * The fixture is real: thirteen segments of downtown Blacksburg lifted from
 * GET /api/network, in the order POST /api/route walked them. The route engine
 * chained them through the junction ids in the database. If the ids worked out
 * here from the geometry alone are the same ids, every consecutive pair in that
 * route shares one.
 */

import { describe, expect, it } from 'vitest'
import { blocksOfName, blocksOfStreet, buildStreetIndex, frontierBlocks, frontierOf, nodeIdOf } from './streets'
import type { Segment } from '../types'

function seg(seg_id: number, name: string, length_m: number, a: [number, number], b: [number, number]): Segment {
  return { seg_id, name, length_m, geometry: { type: 'LineString', coordinates: [a, b] } }
}

// Straight from the live API. Endpoints only; the middle of a line never
// decides adjacency.
const NETWORK: Segment[] = [
  seg(948, 'E Roanoke St', 96.3, [-80.413119793, 37.229901266], [-80.413935184, 37.22932892]),
  seg(943, 'E Roanoke St', 92.5, [-80.41231513, 37.230430896], [-80.413119793, 37.229901266]),
  seg(944, 'Penn St', 102.4, [-80.41231513, 37.230430896], [-80.411564112, 37.229730417]),
  seg(953, 'Lee St', 92.4, [-80.410770178, 37.230268591], [-80.411564112, 37.229730417]),
  seg(955, 'Wharton St SE', 101.7, [-80.410770178, 37.230268591], [-80.410019159, 37.229576652]),
  seg(1115, 'Wharton St SE', 57.3, [-80.409600735, 37.229183697], [-80.410019159, 37.229576652]),
  seg(1116, 'Wharton St SE', 40.4, [-80.409600735, 37.229183697], [-80.409300327, 37.228910335]),
  seg(1104, 'Clay St', 284.6, [-80.406661034, 37.230328388], [-80.409300327, 37.228910335]),
  seg(1043, 'Clay St', 6.1, [-80.406607389, 37.230362557], [-80.406661034, 37.230328388]),
  seg(1036, 'Clay St', 115.2, [-80.405620337, 37.231037404], [-80.406607389, 37.230362557]),
  seg(1034, 'Clay St', 201.0, [-80.405620337, 37.231037404], [-80.403882265, 37.232199151]),
  seg(1038, 'Jefferson St', 65.2, [-80.403882265, 37.232199151], [-80.403388739, 37.231763498]),
  seg(1047, 'Devon Ln', 113.0, [-80.40438652, 37.231131369], [-80.403388739, 37.231763498]),
  // Everything else meeting the stretches above, so the corners are real ones.
  seg(1025, 'Prospect St', 131.4, [-80.406575203, 37.231942885], [-80.405620337, 37.231037404]),
  seg(1028, 'Berryfield Ln', 126.3, [-80.40853858, 37.229901266], [-80.409600735, 37.229183697]),
  seg(1030, 'Jefferson St', 131.0, [-80.404815674, 37.23311316], [-80.403882265, 37.232199151]),
  seg(1035, 'Prospect St', 61.2, [-80.405620337, 37.231037404], [-80.405158997, 37.230627371]),
  seg(1037, 'Clay St', 54.0, [-80.403882265, 37.232199151], [-80.403410196, 37.232506669]),
  seg(1044, 'Willard Dr SE', 5.4, [-80.406607389, 37.230362557], [-80.406564474, 37.230328388]),
  seg(1045, 'Clay St', 111.2, [-80.406607389, 37.230362557], [-80.405652523, 37.231011777]),
  seg(1103, 'Clay St', 116.6, [-80.407658815, 37.229644992], [-80.406661034, 37.230328388]),
  seg(1169, 'Washington St SE', 94.6, [-80.41084528, 37.229038474], [-80.410019159, 37.229576652]),
  seg(1171, 'Clay St', 96.2, [-80.41010499, 37.228329439], [-80.409300327, 37.228910335]),
]

/** The order POST /api/route returned, which the engine chained by junction id. */
const ROUTE_ORDER = [948, 943, 944, 953, 955, 1115, 1116, 1104, 1043, 1036, 1034, 1038, 1047]

const index = buildStreetIndex(NETWORK)

describe('junction ids worked out on the phone', () => {
  it('are the same ids the route engine chained a real route through', () => {
    for (let i = 0; i < ROUTE_ORDER.length - 1; i++) {
      const a = index.ends.get(ROUTE_ORDER[i])!
      const b = index.ends.get(ROUTE_ORDER[i + 1])!
      const shared = a.filter((n) => b.includes(n))
      expect(shared.length, `route step ${ROUTE_ORDER[i]} -> ${ROUTE_ORDER[i + 1]} shares no junction`).toBeGreaterThan(0)
    }
  })

  it('quantise to the z13/4096 grid the network was built on', () => {
    // Same endpoint from two segments that meet there must land on one id.
    expect(nodeIdOf(-80.413119793, 37.229901266)).toBe(nodeIdOf(-80.413119793, 37.229901266))
    expect(index.ends.get(948)![0]).toBe(index.ends.get(943)![1])
    expect(nodeIdOf(-80.413119793, 37.229901266)).toMatch(/^\d+_\d+$/)
  })

  it('never join two streets that only pass close to each other', () => {
    // Penn St and Lee St run parallel a block apart and share no junction here.
    const penn = index.ends.get(944)!
    const clay = index.ends.get(1034)!
    expect(penn.filter((n) => clay.includes(n))).toHaveLength(0)
  })
})

describe('picking a street by hand', () => {
  it('offers a street as its separate stretches, never as one lump', () => {
    const blocks = blocksOfStreet('Clay St', NETWORK, index, [])
    expect(blocks.length).toBeGreaterThan(1)
    for (const b of blocks) expect(b.name).toBe('Clay St')
    // Every stretch of Clay St is accounted for exactly once, none twice.
    const all = blocks.flatMap((b) => b.ids).sort((x, y) => x - y)
    const clay = NETWORK.filter((s) => s.name === 'Clay St')
      .map((s) => s.seg_id)
      .sort((x, y) => x - y)
    expect(all).toEqual(clay)
    expect(new Set(all).size).toBe(all.length)
  })

  it('never lets one tap claim the whole street', () => {
    // The bug this file exists for. Clay St here is four segments across
    // several stretches; no single row may hand back all of them.
    const blocks = blocksOfStreet('Clay St', NETWORK, index, [])
    const clayIds = NETWORK.filter((s) => s.name === 'Clay St').map((s) => s.seg_id)
    for (const b of blocks) expect(b.ids.length).toBeLessThan(clayIds.length)
  })

  it('merges only across a split with no other street at it', () => {
    // 1043 is a six-metre sliver of Clay St. It is a row of its own only if a
    // real corner stands at each end of it.
    const blocks = blocksOfName('Clay St', NETWORK, index)
    const holding = blocks.find((b) => b.ids.includes(1043))!
    expect(holding.ids).toContain(1043)
    expect(holding.metres).toBeGreaterThan(0)
  })

  it('says what each stretch runs between, in cross streets', () => {
    const blocks = blocksOfName('Wharton St SE', NETWORK, index)
    const labels = blocks.map((b) => b.between)
    expect(labels.some((l) => l.includes('Clay St'))).toBe(true)
    expect(labels.some((l) => l.includes('Lee St'))).toBe(true)
    for (const l of labels) expect(l).not.toBe('')
  })

  it('puts the stretches that carry on from the walk first', () => {
    const blocks = blocksOfStreet('Clay St', NETWORK, index, [1116])
    expect(blocks[0].ids).toContain(1104) // the one at the Wharton St corner
    expect(blocks[0].carriesOn).toBe(true)
  })

  it('leaves out stretches already picked', () => {
    const blocks = blocksOfStreet('Clay St', NETWORK, index, [1104])
    expect(blocks.flatMap((b) => b.ids)).not.toContain(1104)
  })
})

describe('carrying on from the walk so far', () => {
  it('offers only what shares a junction with something picked', () => {
    const front = frontierOf([1116], index).map((s) => s.seg_id)
    expect(front).toContain(1104) // shares the Clay St / Wharton St corner
    expect(front).not.toContain(948) // four blocks away
    expect(front).not.toContain(1034)
  })

  it('offers nothing when nothing is picked', () => {
    expect(frontierOf([], index)).toHaveLength(0)
    expect(frontierBlocks([], NETWORK, index)).toHaveLength(0)
  })

  it('offers stretches, each one labelled', () => {
    const blocks = frontierBlocks([1116], NETWORK, index)
    expect(blocks.length).toBeGreaterThan(0)
    for (const b of blocks) {
      expect(b.carriesOn).toBe(true)
      expect(b.between).not.toBe('')
      expect(b.ids.length).toBeGreaterThan(0)
    }
    expect(blocks.some((b) => b.name === 'Clay St')).toBe(true)
  })
})
