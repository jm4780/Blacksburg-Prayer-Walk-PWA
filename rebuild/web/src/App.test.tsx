// @vitest-environment jsdom

/**
 * The walk, from cold open to the map, with the map itself stubbed out.
 *
 * What this is really guarding: nothing reaches POST /api/walk until the walker
 * taps confirm, and the tap count from a cold open to walking stays at three.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { App } from './App'
import { _resetForTests } from './data/idb'

vi.mock('./map/MapView', () => ({
  MapView: () => null,
}))

const SEGMENTS = [
  {
    seg_id: 1,
    name: 'Progress St',
    length_m: 400,
    geometry: { type: 'LineString', coordinates: [[-80.42, 37.23], [-80.42, 37.234]] },
  },
  {
    seg_id: 2,
    name: 'Draper Rd',
    length_m: 300,
    geometry: { type: 'LineString', coordinates: [[-80.42, 37.234], [-80.415, 37.234]] },
  },
  {
    seg_id: 3,
    name: 'Clay St',
    length_m: 250,
    geometry: { type: 'LineString', coordinates: [[-80.415, 37.234], [-80.415, 37.23]] },
  },
]

let posted: { url: string; body: Record<string, unknown> }[] = []

function json(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), { status, headers: { 'content-type': 'application/json' } })
}

beforeEach(async () => {
  posted = []
  cleanup()
  _resetForTests()
  await new Promise((r) => setTimeout(r, 0))
  await new Promise<void>((resolve) => {
    const req = indexedDB.deleteDatabase('prayer-walk')
    req.onsuccess = () => resolve()
    req.onerror = () => resolve()
    req.onblocked = () => resolve()
  })
  vi.stubGlobal('fetch', async (url: string, init?: RequestInit) => {
    const path = String(url)
    if (init?.method === 'POST') {
      const body = JSON.parse(String(init.body))
      posted.push({ url: path, body })
      if (path === '/api/route')
        return json({
          seg_ids: [1, 2, 3],
          new_seg_ids: [1, 2, 3],
          geometry: { type: 'LineString', coordinates: [[-80.42, 37.23], [-80.415, 37.234]] },
          length_m: 950,
          new_m: 950,
          minutes: body.minutes,
        })
      if (path === '/api/walk') return json({ walk_id: 'w-1', newly_covered: body.seg_ids })
      return json({ proposals: [] })
    }
    if (path === '/api/network') return json({ segments: SEGMENTS })
    if (path === '/api/coverage') return json({ covered: [] })
    if (path === '/api/progress')
      return json({
        segments_covered: 0,
        segments_total: 1553,
        covered_m: 0,
        total_m: 251923,
        percent: 0,
        homes_covered: null,
        homes_total: null,
      })
    return json({}, 404)
  })
})

afterEach(() => {
  cleanup()
  _resetForTests()
  vi.unstubAllGlobals()
})

describe('a walk', () => {
  it('takes three taps to get walking, and commits only on the confirm tap', async () => {
    render(<App />)

    // Tap 1
    const start = await screen.findByRole('button', { name: 'Start a walk' })
    await waitFor(() => expect((start as HTMLButtonElement).disabled).toBe(false))
    fireEvent.click(start)

    // Tap 2: how long you have. The route is fetched on that same tap.
    fireEvent.click(await screen.findByRole('button', { name: /30/ }))
    await waitFor(() => expect(posted.some((p) => p.url === '/api/route')).toBe(true))

    // Tap 3: go.
    const go = await screen.findByRole('button', { name: 'Start walking' })
    await waitFor(() => expect((go as HTMLButtonElement).disabled).toBe(false))
    fireEvent.click(go)

    // Walking, with the streets of the route listed for ticking by hand.
    await screen.findByText(/of 3 streets/)
    fireEvent.click(await screen.findByRole('checkbox', { name: /Progress St/ }))
    fireEvent.click(await screen.findByRole('checkbox', { name: /Draper Rd/ }))

    // Still nothing committed.
    expect(posted.filter((p) => p.url === '/api/walk')).toHaveLength(0)

    fireEvent.click(screen.getByRole('button', { name: 'Finish walk' }))
    await screen.findByText('Did you walk these?')

    // And still nothing committed, on the confirm screen itself.
    expect(posted.filter((p) => p.url === '/api/walk')).toHaveLength(0)

    fireEvent.click(screen.getByRole('button', { name: 'Add these streets to the map' }))

    await waitFor(() => expect(posted.filter((p) => p.url === '/api/walk')).toHaveLength(1))
    const walkPost = posted.find((p) => p.url === '/api/walk')!
    expect(walkPost.body.seg_ids).toEqual([1, 2])
    expect(typeof walkPost.body.client_walk_id).toBe('string')

    await screen.findByText("It's on the map.")
  })

  it('walks by hand when the route engine is down, with no location at all', async () => {
    const realFetch = globalThis.fetch
    vi.stubGlobal('fetch', async (url: string, init?: RequestInit) => {
      if (String(url) === '/api/route' && init?.method === 'POST') {
        posted.push({ url: '/api/route', body: JSON.parse(String(init.body)) })
        return json({ message: 'Route planning is not running yet.' }, 503)
      }
      return realFetch(url as never, init)
    })

    render(<App />)
    const start = await screen.findByRole('button', { name: 'Start a walk' })
    await waitFor(() => expect((start as HTMLButtonElement).disabled).toBe(false))
    fireEvent.click(start)
    fireEvent.click(await screen.findByRole('button', { name: /30/ }))

    // It says so plainly and hands over to picking streets by name.
    await screen.findByText("Pick the streets you'll walk.")
    fireEvent.change(screen.getByLabelText('Find a street by name'), { target: { value: 'progress' } })
    fireEvent.click(await screen.findByRole('button', { name: /Progress St/ }))

    const go = await screen.findByRole('button', { name: 'Start walking' })
    await waitFor(() => expect((go as HTMLButtonElement).disabled).toBe(false))
    fireEvent.click(go)
    fireEvent.click(await screen.findByRole('button', { name: 'Finish walk' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Add these streets to the map' }))

    await waitFor(() => expect(posted.filter((p) => p.url === '/api/walk')).toHaveLength(1))
    expect(posted.find((p) => p.url === '/api/walk')!.body.seg_ids).toEqual([1])
  })

  it('ticks streets off by itself, and leaves an unsure match unticked', async () => {
    // A phone sitting on Progress St.
    vi.stubGlobal('navigator', {
      ...navigator,
      onLine: true,
      geolocation: {
        watchPosition: (ok: PositionCallback) => {
          ok({
            coords: { latitude: 37.232, longitude: -80.42, accuracy: 10 },
            timestamp: 1_700_000_000_000,
          } as GeolocationPosition)
          return 1
        },
        clearWatch: () => {},
      },
    })
    const realFetch = globalThis.fetch
    vi.stubGlobal('fetch', async (url: string, init?: RequestInit) => {
      if (String(url) === '/api/match') {
        posted.push({ url: '/api/match', body: JSON.parse(String(init!.body)) })
        // Exactly what the coverage engine does with a short, ambiguous track:
        // offers it below 0.5 rather than deciding for the walker.
        return json({
          proposals: [
            { seg_id: 3, name: 'Clay St', confidence: 0.4, matched_m: 73, reason: 'posterior 0.75' },
          ],
        })
      }
      return realFetch(url as never, init)
    })

    render(<App />)
    const start = await screen.findByRole('button', { name: 'Start a walk' })
    await waitFor(() => expect((start as HTMLButtonElement).disabled).toBe(false))
    fireEvent.click(start)
    fireEvent.click(await screen.findByRole('button', { name: /30/ }))
    const go = await screen.findByRole('button', { name: 'Start walking' })
    await waitFor(() => expect((go as HTMLButtonElement).disabled).toBe(false))
    fireEvent.click(go)

    // Progress St ticked itself off, with no tap and no coordinate leaving.
    const walked = await screen.findByRole('checkbox', { name: /Progress St/ })
    await waitFor(() => expect(walked.getAttribute('aria-checked')).toBe('true'))
    expect(posted.filter((p) => p.url === '/api/match')).toHaveLength(0)

    fireEvent.click(screen.getByRole('button', { name: 'Finish walk' }))
    fireEvent.click(await screen.findByRole('button', { name: /Check my track/ }))

    // The unsure one is shown, and shown unticked.
    const clay = await screen.findByRole('checkbox', { name: /Clay St/ })
    expect(clay.getAttribute('aria-checked')).toBe('false')

    // Left alone, it commits nothing.
    fireEvent.click(screen.getByRole('button', { name: 'Add these streets to the map' }))
    await waitFor(() => expect(posted.filter((p) => p.url === '/api/walk')).toHaveLength(1))
    expect(posted.find((p) => p.url === '/api/walk')!.body.seg_ids).toEqual([1])
  })

  it('shows no home count while homes are unknown', async () => {
    render(<App />)
    await screen.findByText(/of Blacksburg's streets prayed for/)
    expect(screen.queryByText(/homes/i)).toBeNull()
    expect(screen.queryByText(/\b0 homes\b/)).toBeNull()
  })

  it('picks up a walk that was in progress when the app was killed', async () => {
    const { unmount } = render(<App />)
    const start = await screen.findByRole('button', { name: 'Start a walk' })
    await waitFor(() => expect((start as HTMLButtonElement).disabled).toBe(false))
    fireEvent.click(start)
    fireEvent.click(await screen.findByRole('button', { name: /30/ }))
    const go = await screen.findByRole('button', { name: 'Start walking' })
    await waitFor(() => expect((go as HTMLButtonElement).disabled).toBe(false))
    fireEvent.click(go)
    fireEvent.click(await screen.findByRole('checkbox', { name: /Progress St/ }))

    // Kill it.
    unmount()

    // Open it again: same walk, same ticked street.
    render(<App />)
    await screen.findByRole('button', { name: 'Finish walk' })
    const progressStreet = await screen.findByRole('checkbox', { name: /Progress St/ })
    expect(progressStreet.getAttribute('aria-checked')).toBe('true')
  })
})
