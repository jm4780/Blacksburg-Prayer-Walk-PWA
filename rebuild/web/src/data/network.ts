/**
 * The street file and the town's coverage, cached on the device.
 *
 * The street network never changes between builds, so it is fetched once and
 * kept. Coverage is refreshed when there is signal and falls back to the last
 * copy when there is not, which is what lets the map draw in a basement.
 */

import { api } from './api'
import { kv } from './idb'
import type { Progress, Segment } from '../types'

const SEGMENTS_KEY = 'network:segments'
const FINGERPRINT_KEY = 'network:fingerprint'
const COVERED_KEY = 'coverage:ids'
const COVERED_AT_KEY = 'coverage:fetched_at'

/** Enough to tell one build of the street file from another. Segment ids are
 *  stable within a build and not across one, so a change here means the ids on
 *  this phone may no longer point at the streets they used to. */
export function fingerprint(segments: Segment[]): string {
  const metres = segments.reduce((sum, s) => sum + s.length_m, 0)
  return `${segments.length}:${Math.round(metres)}`
}

export async function loadSegments(): Promise<{ segments: Segment[]; fromCache: boolean }> {
  const cached = await kv.get<Segment[]>(SEGMENTS_KEY)
  if (cached && cached.length) return { segments: cached, fromCache: true }
  const r = await api.network()
  await kv.set(SEGMENTS_KEY, r.segments)
  await kv.set(FINGERPRINT_KEY, fingerprint(r.segments))
  return { segments: r.segments, fromCache: false }
}

/** Fetch the street file again and say whether the town rebuilt it. */
export async function refreshSegments(): Promise<{ segments: Segment[]; changed: boolean } | null> {
  try {
    const r = await api.network()
    const fresh = fingerprint(r.segments)
    const previous = await kv.get<string>(FINGERPRINT_KEY)
    await kv.set(SEGMENTS_KEY, r.segments)
    await kv.set(FINGERPRINT_KEY, fresh)
    return { segments: r.segments, changed: Boolean(previous) && previous !== fresh }
  } catch {
    return null
  }
}

const PROGRESS_KEY = 'progress:last'

/**
 * The town's own count of itself, kept for when there is no signal.
 *
 * The app deliberately does not work this figure out for itself. The town
 * counts a divided road once, not once per side, and only the server knows
 * which segments are two halves of the same street. A number this app added up
 * on its own would quietly disagree with the number on everyone else's screen.
 */
export async function loadProgress(): Promise<{ progress: Progress | null; fromCache: boolean }> {
  try {
    const p = await api.progress()
    await kv.set(PROGRESS_KEY, p)
    return { progress: p, fromCache: false }
  } catch {
    const cached = (await kv.get<Progress>(PROGRESS_KEY)) ?? null
    return { progress: cached, fromCache: true }
  }
}

export async function loadCoverage(): Promise<{ covered: number[]; fromCache: boolean; at: string | null }> {
  try {
    const r = await api.coverage()
    const at = new Date().toISOString()
    await kv.set(COVERED_KEY, r.covered)
    await kv.set(COVERED_AT_KEY, at)
    return { covered: r.covered, fromCache: false, at }
  } catch {
    const covered = (await kv.get<number[]>(COVERED_KEY)) ?? []
    const at = (await kv.get<string>(COVERED_AT_KEY)) ?? null
    return { covered, fromCache: true, at }
  }
}

export function toFeatureCollection(segments: Segment[]) {
  return {
    type: 'FeatureCollection' as const,
    features: segments.map((s) => ({
      type: 'Feature' as const,
      id: s.seg_id,
      properties: { seg_id: s.seg_id, name: s.name, length_m: s.length_m },
      geometry: s.geometry,
    })),
  }
}
