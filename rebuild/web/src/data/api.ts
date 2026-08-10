/**
 * Talking to the server. Contract section 4.
 *
 * The only call in this file that carries a coordinate off the device is
 * `match`, and the server stores nothing it receives there. `route` sends the
 * one point you chose to start from, which is a choice the walker makes on
 * screen, not a track.
 */

import type { Fix, Progress, Proposal, RouteResult, Segment } from '../types'

export class ApiError extends Error {
  status: number
  payload: unknown
  constructor(status: number, message: string, payload?: unknown) {
    super(message)
    this.status = status
    this.payload = payload
  }
  /** True when trying again later is the right move. */
  get retryable(): boolean {
    return this.status === 0 || this.status === 408 || this.status === 429 || this.status >= 500
  }
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(path, {
      ...init,
      headers: { 'content-type': 'application/json', ...(init?.headers || {}) },
    })
  } catch (e) {
    // No network at all. Retryable by definition.
    throw new ApiError(0, e instanceof Error ? e.message : 'offline')
  }
  const text = await res.text()
  let body: unknown = null
  try {
    body = text ? JSON.parse(text) : null
  } catch {
    body = text
  }
  if (!res.ok) {
    const msg =
      body && typeof body === 'object' && 'message' in body
        ? String((body as { message: unknown }).message)
        : `Request failed (${res.status})`
    throw new ApiError(res.status, msg, body)
  }
  return body as T
}

export const api = {
  network: () => req<{ segments: Segment[] }>('/api/network'),
  progress: () => req<Progress>('/api/progress'),
  coverage: () => req<{ covered: number[] }>('/api/coverage'),

  route: (lon: number, lat: number, minutes: number) =>
    req<RouteResult>('/api/route', {
      method: 'POST',
      body: JSON.stringify({ lon, lat, minutes }),
    }),

  walk: (body: {
    device_id: string
    client_walk_id: string
    display_name?: string | null
    started_at?: string | null
    seg_ids: number[]
  }) =>
    req<{ walk_id: string; newly_covered: number[] }>('/api/walk', {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  /** The one place a raw coordinate leaves the phone. */
  match: (trace: Fix[]) =>
    req<{ proposals: Proposal[] }>('/api/match', {
      method: 'POST',
      body: JSON.stringify({ trace }),
    }),
}
