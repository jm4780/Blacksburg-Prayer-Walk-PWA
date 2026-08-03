export interface ParticipantOut {
  id: string
  first_name: string
  last_name: string
  email: string
  is_admin: boolean
  token?: string | null
  returning: boolean
}

export interface LineString { type: 'LineString'; coordinates: [number, number][] }

export interface Variant {
  band: string
  target_miles: number
  available: boolean
  state: string
  reason: string
  distance_miles: number | null
  estimated_minutes: number | null
  new_required_miles: number | null
  repeated_miles: number | null
  efficiency: number | null
  households: number | null
  walk_quality: number | null
  dead_end_returns_miles: number | null
  closing_leg_miles: number | null
  segment_count: number | null
  required_segment_count: number | null
  nests_within_shorter: boolean | null
  component: ComponentInfo | null
  score_components: Record<string, number> | null
  campus_credited_miles: number | null
  suggested_band: string | null
  nearest_incomplete_miles: number | null
  segment_ids: string[]
  required_segment_ids: string[]
  connector_segment_ids: string[]
  start_point: [number, number] | null
  end_point: [number, number] | null
  route_score: number | null
  seed: number
  network_version: string
  engine_version: string
  geometry: LineString | null
}

export interface ComponentInfo {
  index: number
  description: string
  classification: string
  required_miles: number
  supported_bands: string[]
  complete_area_miles: number | null
}

export interface RouteResponse {
  request_id: string
  network_id: string
  network_version: string
  engine_version: string
  seed: number
  state: string
  coverage_area_id: string | null
  completion_state_version: string
  component: ComponentInfo | null
  available_bands: string[]
  variants: Variant[]
}

export interface Walk {
  id: string
  status: string
  band: string
  target_miles: number
  distance_miles: number
  estimated_minutes: number
  network_id: string
  engine_version: string
  required_segment_count: number
  planned_required_ids: string[]
  households: number | null
  start_point: [number, number] | null
  created_at: string
  started_at: string | null
  resolved_at: string | null
  outcome: string | null
  geometry: LineString | null
  directions: Direction[] | null
}

export interface Direction {
  name: string
  miles: number
  derived: boolean
  required: boolean
  campus_alternative: boolean
}

export interface MetricValue { value: number; definition: string }

export interface Metrics {
  network_id: string
  network_version: string
  percent_prayed_for: MetricValue & { numerator_miles: number; denominator_miles: number }
  total_miles_walked: MetricValue
  estimated_households_prayed_for: MetricValue & { total: number; held_for_review: number }
  required_segments_total: number
  required_segments_complete: number
  completed_walks: number
  distinct_walkers: number
  mileage_breakdown: Record<string, number>
}

export interface ProgressFeature {
  type: 'Feature'
  geometry: LineString
  properties: { id: string; name: string | null; kind: string; done: boolean; held: boolean }
}

export interface ProgressMap {
  type: 'FeatureCollection'
  network_id: string
  network_version: string
  features: ProgressFeature[]
  boundary: { type: 'MultiLineString'; coordinates: [number, number][][] } | null
  excludes: string[]
}

/**
 * A mission: the walk we recommend, described in mission terms.
 *
 * Note what is NOT here — route score, walk quality, coverage gain, efficiency,
 * cluster identifiers, seed. Those are real and they are how the route was chosen,
 * but they are the optimiser's business, not the walker's (Priority 8). They stay on
 * the server and remain visible through the admin endpoints.
 */
export interface Mission {
  id: string
  title: string
  households_line: string
  has_households: boolean
  households: number
  completes_area: boolean
  area: string | null
  areas: string[]
  estimated_minutes: number
  distance_miles: number
  start: {
    lat: number
    lon: number
    description: string
    streets: string[]
  }
  geometry: LineString
  segment_ids: string[]
  required_segment_ids: string[]
  network_version: string
  engine_version: string
  directions?: DirectionsLinks
}

export interface DirectionsLinks { apple: string; google: string; geo: string }

export interface MissionAlternative {
  id: string
  title: string
  estimated_minutes: number
  distance_miles: number
  households: number
}

export interface MissionResponse {
  available: boolean
  minutes: number
  requested_minutes?: number
  reason?: string
  mission: Mission | null
  alternatives: MissionAlternative[]
  slate_size?: number
  network_version: string
}

export interface MissionOptions {
  min_minutes: number
  max_minutes: number
  step_minutes: number
  default_minutes: number
  pace_mph: number
  pace_note: string
}

export interface AdminOverview {
  metrics: Metrics
  components: Record<string, any>
  participants: number
  walks_by_status: Record<string, number>
}
