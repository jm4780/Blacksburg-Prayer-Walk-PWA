/**
 * API client.
 *
 * The only thing this stores in the browser is an opaque bearer token (§18). Name and
 * email live on the server; the browser holds a random string that identifies the
 * participant record and nothing else. Clearing site data logs you out and loses
 * nothing but the link back to your own history.
 */
import type {
  AdminOverview, Metrics, MissionOptions, MissionResponse, ParticipantOut, ProgressMap,
  RouteResponse, Walk,
} from './types'

const TOKEN_KEY = 'bpw.token'

export function getToken(): string | null {
  try { return localStorage.getItem(TOKEN_KEY) } catch { return null }
}

export function setToken(t: string | null) {
  try { t ? localStorage.setItem(TOKEN_KEY, t) : localStorage.removeItem(TOKEN_KEY) }
  catch { /* private browsing: the session simply does not persist */ }
}

/**
 * Every failure this client can produce, with the one distinction that matters.
 *
 * `status` is the HTTP status, or **0 when the request never got an answer at all** —
 * offline, DNS gone, connection dropped, or our own timeout below. That difference is
 * not cosmetic. A walker outdoors on one bar and a walker whose session has genuinely
 * expired look identical to a `catch` block, and treating the first as the second is
 * how somebody standing on a street corner gets signed out and loses the walk they
 * are halfway through. Ask `isOffline()` before you decide a person is a stranger.
 */
export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message) }
}

/** No answer came back. The request may well have been received and acted on. */
export function isOffline(e: unknown): boolean {
  return e instanceof ApiError && e.status === 0
}

/** The server answered, and the answer was "not you". The only reason to drop a token. */
export function isAuthFailure(e: unknown): boolean {
  return e instanceof ApiError && (e.status === 401 || e.status === 403)
}

/**
 * How long any one request may hang before we call it.
 *
 * Nothing here was cancellable before, so a request that never resolved left the
 * screen saying "Holding these streets…" with no button and no end — forever, on a
 * phone, outdoors. Fifteen seconds is long enough for a slow rural link to finish a
 * route computation and short enough that a person has not yet decided the app is
 * broken.
 */
const TIMEOUT_MS = 15_000

async function req<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = getToken()
  const headers: Record<string, string> = { ...(init.headers as any) }
  if (init.body) headers['Content-Type'] = 'application/json'
  if (token) headers['Authorization'] = `Bearer ${token}`

  // A caller may pass its own signal (a screen unmounting); ours runs alongside it.
  const clock = new AbortController()
  const timer = setTimeout(() => clock.abort(), TIMEOUT_MS)
  const caller = init.signal
  const onCallerAbort = () => clock.abort()
  caller?.addEventListener('abort', onCallerAbort)

  let res: Response
  try {
    res = await fetch(path, { ...init, headers, signal: clock.signal })
  } catch (e) {
    // fetch rejects for exactly two reasons: the network never answered, or somebody
    // aborted. Neither is a statement about who the walker is.
    throw new ApiError(0, caller?.aborted
      ? 'Cancelled.'
      : clock.signal.aborted
        ? 'The server is taking too long to answer. Check your signal and try again.'
        : 'Could not reach the server. Check your signal and try again.')
  } finally {
    clearTimeout(timer)
    caller?.removeEventListener('abort', onCallerAbort)
  }

  if (!res.ok) {
    let detail = res.statusText
    try { detail = (await res.json()).detail ?? detail } catch { /* not json */ }
    throw new ApiError(res.status, typeof detail === 'string' ? detail : res.statusText)
  }
  // A 200 carrying malformed JSON used to surface the parser's own words to the walker
  // — "Unterminated string in JSON at position 18". That is a sentence about our
  // problem, written for us, shown to them.
  if (res.status === 204) return null as T
  try {
    return await res.json()
  } catch {
    throw new ApiError(0, 'The server sent back something we could not read. Try again.')
  }
}

export const api = {
  health: () => req<any>('/api/health'),

  register: (first_name: string, last_name: string, email: string,
             invite_code?: string) =>
    req<ParticipantOut>('/api/identity/register', {
      method: 'POST',
      body: JSON.stringify({ first_name, last_name, email, invite_code }),
    }),

  me: () => req<ParticipantOut>('/api/identity/me'),

  // --- missions (Priority 3) ------------------------------------------------
  // `options` and `recommend` are anonymous-friendly by design: somebody who has just
  // opened the app sees a real suggested walk before being asked who they are.
  // `acceptMission` is the first call that needs identity, because it is the first
  // one that records a walk against a person and holds streets against everyone else.
  missionOptions: () => req<MissionOptions>('/api/missions/options'),

  recommend: (minutes: number) =>
    req<MissionResponse>(`/api/missions/recommend?minutes=${minutes}`),

  mission: (id: string, minutes: number) =>
    req<MissionResponse>(`/api/missions/${id}?minutes=${minutes}`),

  acceptMission: (id: string, minutes: number) =>
    req<{ walk_id: string; mission_id: string; distance_miles: number;
          estimated_minutes: number }>(
      `/api/missions/${id}/accept?minutes=${minutes}`, { method: 'POST' }),

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

  feedback: (walkId: string, body: Record<string, unknown>) =>
    req<any>(`/api/walks/${walkId}/feedback`, {
      method: 'POST', body: JSON.stringify(body),
    }),
  getFeedback: (walkId: string) => req<any | null>(`/api/walks/${walkId}/feedback`),

  metrics: () => req<Metrics>('/api/progress/metrics'),
  progressMap: () => req<ProgressMap>('/api/progress/map'),

  adminOverview: () => req<AdminOverview>('/api/admin/overview'),
  adminPilot: () => req<any>('/api/admin/pilot-summary'),
  adminFeedback: () => req<any[]>('/api/admin/feedback'),
  adminWalkEdits: () => req<any>('/api/admin/walk-edits'),
  adminRouteFailures: () => req<any>('/api/admin/route-failures'),
  adminDuplicates: () => req<any>('/api/admin/participant-duplicates'),
  adminConnectors: () => req<any>('/api/admin/connector-candidates'),
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
