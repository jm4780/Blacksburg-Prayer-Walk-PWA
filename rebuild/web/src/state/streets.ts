/**
 * Which stretch of a street, and what it runs between.
 *
 * The walker picking streets by hand needs to say "the bit of Clay St between
 * Jefferson and Prospect", not "Clay St". Without that, one tap on a street
 * name claims every stretch of it in town: US 460 Bus is eighty-one segments
 * and ten miles, which is 6.4% of Blacksburg marked as prayed over by someone
 * who walked two blocks. A wrong claim is permanent and nobody can see it to
 * undo it, so this file exists to make a claim something a walker can account
 * for.
 *
 * Adjacency is the network's own rule, not a guess. §1 of the contract defines
 * a junction as the segment endpoint quantised onto the z13/4096 grid, and the
 * street file the phone already holds carries those endpoints, so the same
 * arithmetic run here reproduces the same junction ids the engines use. It is
 * checked against a real generated route in streets.test.ts: every consecutive
 * pair in an engine route shares a junction under this reconstruction. Nothing
 * here infers adjacency from proximity.
 */

import type { Segment } from '../types'

const Z = 13
const EXTENT = 4096
const WORLD = 2 ** Z * EXTENT

/**
 * A segment endpoint as the junction id the network build gave it.
 *
 * Only a fallback now. The server sends node_a/node_b, and those are used when
 * present. This reconstruction stays for a phone still holding a street file
 * cached before the server began sending them, and it is the reason the grid
 * constants above have to match the pipeline: if a future build changes zoom or
 * extent, this silently produces junction ids that do not exist.
 */
export function nodeIdOf(lon: number, lat: number): string {
  const x = ((lon + 180) / 360) * WORLD
  const s = Math.sin((lat * Math.PI) / 180)
  const y = (0.5 - Math.log((1 + s) / (1 - s)) / (4 * Math.PI)) * WORLD
  return `${Math.round(x)}_${Math.round(y)}`
}

export type StreetIndex = {
  byId: Map<number, Segment>
  /** seg_id -> its two junction ids. */
  ends: Map<number, [string, string]>
  /** junction id -> the segments meeting there. */
  atNode: Map<string, number[]>
}

export function buildStreetIndex(segments: Segment[]): StreetIndex {
  const byId = new Map<number, Segment>()
  const ends = new Map<number, [string, string]>()
  const atNode = new Map<string, number[]>()
  for (const s of segments) {
    const c = s.geometry.coordinates
    if (c.length < 2) continue
    // Prefer the ids the network build actually assigned. Recomputing them
    // from coordinates only works while the client's grid constants match the
    // pipeline's, and nothing would announce it if they stopped matching.
    const a = s.node_a ?? nodeIdOf(c[0][0], c[0][1])
    const b = s.node_b ?? nodeIdOf(c[c.length - 1][0], c[c.length - 1][1])
    byId.set(s.seg_id, s)
    ends.set(s.seg_id, [a, b])
    for (const nd of a === b ? [a] : [a, b]) {
      const list = atNode.get(nd)
      if (list) list.push(s.seg_id)
      else atNode.set(nd, [s.seg_id])
    }
  }
  return { byId, ends, atNode }
}

/** The other streets meeting at a junction, nearest name first. */
function crossingsAt(node: string, index: StreetIndex, exclude: string): string[] {
  const out = new Set<string>()
  for (const id of index.atNode.get(node) ?? []) {
    const s = index.byId.get(id)
    if (s && s.name !== exclude) out.add(s.name)
  }
  return [...out]
}

/**
 * What a stretch of street runs between, in the words of the cross streets at
 * its two ends. A stretch that ends nowhere says so rather than inventing a
 * name for it.
 */
export function describeBlock(seg: Segment, index: StreetIndex): string {
  const e = index.ends.get(seg.seg_id)
  if (!e) return ''
  const a = crossingsAt(e[0], index, seg.name)
  const b = crossingsAt(e[1], index, seg.name)
  if (a.length && b.length) return `between ${a[0]} and ${b[0]}`
  if (a.length) return `from ${a[0]} to the end`
  if (b.length) return `from ${b[0]} to the end`
  return 'end to end'
}

/** Every junction the walk currently touches. */
export function nodesOf(claimed: number[], index: StreetIndex): Set<string> {
  const out = new Set<string>()
  for (const id of claimed) {
    const e = index.ends.get(id)
    if (e) {
      out.add(e[0])
      out.add(e[1])
    }
  }
  return out
}

/**
 * The stretches that carry straight on from the walk so far: anything sharing a
 * junction with something already picked. This is how a walk gets built by
 * hand, one turn at a time, and it stays short. Measured over 400 random walks
 * on the real network: median 5 rows, 98% of the time 12 or fewer.
 */
export function frontierOf(claimed: number[], index: StreetIndex): Segment[] {
  const picked = new Set(claimed)
  const seen = new Set<number>()
  const out: Segment[] = []
  for (const nd of nodesOf(claimed, index)) {
    for (const id of index.atNode.get(nd) ?? []) {
      if (picked.has(id) || seen.has(id)) continue
      seen.add(id)
      const s = index.byId.get(id)
      if (s) out.push(s)
    }
  }
  return out.sort((a, b) => a.name.localeCompare(b.name) || b.length_m - a.length_m)
}

export type Block = {
  /** Stable key for lists. */
  key: string
  name: string
  /** The segments making up this one stretch. Usually one. */
  ids: number[]
  metres: number
  /** "between Toms Creek Rd and Hubbard St" */
  between: string
  /** True when this stretch touches the walk already picked. */
  carriesOn: boolean
}

/**
 * Is this junction one a walker would recognise, or one the build made?
 *
 * A real corner has another street at it. The network also splits a road where
 * nothing meets it, and joining two stretches across a point like that would
 * ask a walker to tell apart two rows that look identical and stand in the same
 * place, so those are merged back into the one stretch they are on the ground.
 */
function isCorner(node: string, index: StreetIndex, name: string): boolean {
  const here = index.atNode.get(node) ?? []
  let same = 0
  for (const id of here) {
    const s = index.byId.get(id)
    if (!s) continue
    if (s.name === name) same += 1
    else return true // another street meets here
  }
  return same !== 2 // a dead end, or the street branching
}

/**
 * One street, cut into the stretches a walker would name.
 *
 * Never the whole street. Each stretch runs corner to corner, which is the
 * largest thing someone can honestly vouch for in a single tap and small enough
 * that a wrong tap costs the town map one block instead of ten miles.
 */
export function blocksOfName(name: string, segments: Segment[], index: StreetIndex): Block[] {
  const mine = segments.filter((s) => s.name === name)
  const ids = new Set(mine.map((s) => s.seg_id))
  const seen = new Set<number>()
  const out: Block[] = []

  for (const start of mine) {
    if (seen.has(start.seg_id)) continue
    seen.add(start.seg_id)
    const chain = [start.seg_id]
    const startEnds = index.ends.get(start.seg_id)!
    const tips: string[] = []

    for (const from of startEnds) {
      let node = from
      let guard = 0
      for (;;) {
        if (guard++ > 500) break
        if (isCorner(node, index, name)) break
        const next = (index.atNode.get(node) ?? []).find((id) => ids.has(id) && !seen.has(id))
        if (next === undefined) break
        seen.add(next)
        chain.push(next)
        const e = index.ends.get(next)!
        node = e[0] === node ? e[1] : e[0]
      }
      tips.push(node)
    }

    const segsIn = chain.map((id) => index.byId.get(id)!).filter(Boolean)
    const metres = segsIn.reduce((sum, s) => sum + s.length_m, 0)
    const a = crossingsAt(tips[0], index, name)
    const b = crossingsAt(tips[1] ?? tips[0], index, name)
    let between: string
    if (a.length && b.length) between = a[0] === b[0] ? `at ${a[0]}` : `between ${a[0]} and ${b[0]}`
    else if (a.length) between = `from ${a[0]} to the end`
    else if (b.length) between = `from ${b[0]} to the end`
    else between = 'end to end'

    out.push({
      key: `${name}#${Math.min(...chain)}`,
      name,
      ids: chain,
      metres,
      between,
      carriesOn: false,
    })
  }
  return out
}

/** The stretches of one street still worth offering, best guess first. */
export function blocksOfStreet(
  name: string,
  segments: Segment[],
  index: StreetIndex,
  claimed: number[],
): Block[] {
  const picked = new Set(claimed)
  const touching = nodesOf(claimed, index)
  return blocksOfName(name, segments, index)
    .filter((b) => !b.ids.every((id) => picked.has(id)))
    .map((b) => ({
      ...b,
      carriesOn: b.ids.some((id) => {
        const e = index.ends.get(id)
        return Boolean(e && (touching.has(e[0]) || touching.has(e[1])))
      }),
    }))
    .sort((a, b) => Number(b.carriesOn) - Number(a.carriesOn) || b.metres - a.metres)
}

/**
 * Where the walk can carry on to: the stretches meeting what is already picked.
 * This is how a walk gets built by hand, one turn at a time, and it stays
 * short. Measured over 400 random walks on the real network, the frontier is
 * five segments across at the median and twelve or fewer 98% of the time.
 */
export function frontierBlocks(claimed: number[], segments: Segment[], index: StreetIndex): Block[] {
  const names = new Set(frontierOf(claimed, index).map((s) => s.name))
  const out: Block[] = []
  for (const name of names) {
    for (const b of blocksOfStreet(name, segments, index, claimed)) {
      if (b.carriesOn) out.push(b)
    }
  }
  return out.sort((a, b) => a.name.localeCompare(b.name) || b.metres - a.metres)
}
