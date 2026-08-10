/**
 * The street file and the town's coverage, cached on the device.
 *
 * The street network never changes between builds, so it is fetched once and
 * kept. Coverage is refreshed when there is signal and falls back to the last
 * copy when there is not, which is what lets the map draw in a basement.
 */

import { api } from './api'
import { kv } from './idb'
import type { Segment } from '../types'

const SEGMENTS_KEY = 'network:segments'
const COVERED_KEY = 'coverage:ids'
const COVERED_AT_KEY = 'coverage:fetched_at'

export async function loadSegments(): Promise<{ segments: Segment[]; fromCache: boolean }> {
  const cached = await kv.get<Segment[]>(SEGMENTS_KEY)
  if (cached && cached.length) {
    // Refresh quietly in the background; the map does not wait for it.
    void api
      .network()
      .then((r) => kv.set(SEGMENTS_KEY, r.segments))
      .catch(() => {})
    return { segments: cached, fromCache: true }
  }
  const r = await api.network()
  await kv.set(SEGMENTS_KEY, r.segments)
  return { segments: r.segments, fromCache: false }
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
