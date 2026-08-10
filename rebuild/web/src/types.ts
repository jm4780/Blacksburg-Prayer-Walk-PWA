export type Segment = {
  seg_id: number
  name: string
  length_m: number
  geometry: { type: 'LineString'; coordinates: [number, number][] }
}

export type Progress = {
  segments_covered: number
  segments_total: number
  covered_m: number
  total_m: number
  percent: number
  /** Null until a real address source exists. Null means render nothing. */
  homes_covered: number | null
  homes_total: number | null
}

export type RouteResult = {
  seg_ids: number[]
  new_seg_ids: number[]
  geometry: { type: 'LineString'; coordinates: [number, number][] } | null
  length_m: number
  new_m: number
  minutes: number
  /** new_m / length_m. */
  new_ratio?: number
  /** True when nearly every street within reach is already prayed for. */
  saturated?: boolean
  /**
   * The nearest place a walk this long would find street nobody has covered.
   * Null when there is nowhere left, which is the honest answer once the town
   * is finished. distance_m is walking distance, not a straight line.
   */
  suggested_start?: { lon: number; lat: number; distance_m: number; uncovered_m: number } | null
}

export type Fix = { lat: number; lon: number; accuracy_m: number; t: number }

export type Proposal = {
  seg_id: number
  name: string
  confidence: number
  matched_m: number
  reason: string
}

export type WalkPhase = 'idle' | 'planning' | 'walking' | 'confirming' | 'sent'

/** The walk in progress. Written to IndexedDB on every change, so a reload, a
 *  suspend, or a kill loses nothing. */
export type WalkState = {
  phase: WalkPhase
  /** Minted before the walk starts and reused on every retry, forever. */
  client_walk_id: string
  started_at: string | null
  minutes: number
  start: { lon: number; lat: number } | null
  route: RouteResult | null
  /** Streets the walker has claimed on this walk. */
  claimed: number[]
  /** Streets the matcher offered but was not sure about. Shown unticked. */
  suggested: number[]
  /** True when the walker is picking streets by hand rather than by location. */
  manual: boolean
  /** Kept on the device only. Never sent anywhere except POST /api/match. */
  trace: Fix[]
}

export type OutboxItem = {
  client_walk_id: string
  body: {
    device_id: string
    client_walk_id: string
    display_name?: string | null
    started_at?: string | null
    seg_ids: number[]
  }
  attempts: number
  queued_at: string
  last_error: string | null
  status: 'pending' | 'sent' | 'stuck'
  walk_id?: string
  newly_covered?: number[]
}
