/**
 * API client.
 *
 * The only thing this stores in the browser is an opaque bearer token (§18). Name and
 * email live on the server; the browser holds a random string that identifies the
 * participant record and nothing else. Clearing site data logs you out and loses
 * nothing but the link back to your own history.
 */
import type {
  AdminOverview, Metrics, ParticipantOut, ProgressMap, RouteResponse, Walk,
} from './types'

const TOKEN_KEY = 'bpw.token'

export function getToken(): string | null {
  try { return localStorage.getItem(TOKEN_KEY) } catch { return null }
}

export function setToken(t: string | null) {
  try { t ? localStorage.setItem(TOKEN_KEY, t) : localStorage.removeItem(TOKEN_KEY) }
  catch { /* private browsing: the session simply does not persist */ }
}

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message) }
}

async function req<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = getToken()
  const headers: Record<string, string> = { ...(init.headers as any) }
  if (init.body) headers['Content-Type'] = 'application/json'
  if (token) headers['Authorization'] = `Bearer ${token}`

  const res = await fetch(path, { ...init, headers })
  if (!res.ok) {
    let detail = res.statusText
    try { detail = (await res.json()).detail ?? detail } catch { /* not json */ }
    throw new ApiError(res.status, typeof detail === 'string' ? detail : res.statusText)
  }
  return res.status === 204 ? (null as T) : res.json()
}

export const api = {
  health: () => req<any>('/api/health'),

  register: (first_name: string, last_name: string, email: string) =>
    req<ParticipantOut>('/api/identity/register', {
      method: 'POST', body: JSON.stringify({ first_name, last_name, email }),
    }),

  me: () => req<ParticipantOut>('/api/identity/me'),

  generate: (lat: number, lon: number, start_source: 'DEVICE_LOCATION' | 'MAP') =>
    req<RouteResponse>('/api/routes/generate', {
      method: 'POST', body: JSON.stringify({ lat, lon, start_source }),
    }),

  select: (request_id: string, band: string) =>
    req<Walk>('/api/walks/select', {
      method: 'POST', body: JSON.stringify({ request_id, band }),
    }),

  start: (id: string) => req<Walk>(`/api/walks/${id}/start`, { method: 'POST' }),
  discard: (id: string) => req<Walk>(`/api/walks/${id}/discard`, { method: 'POST' }),
  current: () => req<Walk | null>('/api/walks/current'),
  walk: (id: string) => req<Walk>(`/api/walks/${id}`),

  complete: (id: string, outcome: string, segment_ids?: string[], note?: string) =>
    req<any>(`/api/walks/${id}/complete`, {
      method: 'POST', body: JSON.stringify({ outcome, segment_ids, note }),
    }),

  metrics: () => req<Metrics>('/api/progress/metrics'),
  progressMap: () => req<ProgressMap>('/api/progress/map'),

  adminOverview: () => req<AdminOverview>('/api/admin/overview'),
  adminReviewQueues: () => req<any>('/api/admin/review-queues'),
  adminDeployment: () => req<any>('/api/admin/deployment'),
  adminReservations: () => req<any[]>('/api/admin/reservations'),
  adminAudit: () => req<any[]>('/api/admin/audit'),
  adminNetwork: () => req<any>('/api/admin/network'),
  adminWalks: () => req<any[]>('/api/admin/walks'),
  adminParticipants: () => req<any[]>('/api/admin/participants'),
}

/**
 * One-time location (§6).
 *
 * `getCurrentPosition`, never `watchPosition`. The distinction is the whole point: a
 * watch would stream the walker's position for as long as the page is open, and this
 * application has no use for that and makes no claim to it.
 */
export function requestLocationOnce(): Promise<{ lat: number; lon: number }> {
  return new Promise((resolve, reject) => {
    if (!('geolocation' in navigator)) {
      reject(new Error('This device cannot share its location.')); return
    }
    navigator.geolocation.getCurrentPosition(
      (p) => resolve({ lat: p.coords.latitude, lon: p.coords.longitude }),
      (e) => reject(new Error(
        e.code === e.PERMISSION_DENIED
          ? 'Location permission was declined.'
          : 'Could not get a location fix.')),
      { enableHighAccuracy: true, timeout: 15000, maximumAge: 0 },
    )
  })
}
