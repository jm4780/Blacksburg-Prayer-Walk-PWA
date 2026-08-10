// @vitest-environment jsdom

/**
 * The walk, from cold open to the map, with the map itself stubbed out.
 *
 * What this is really guarding: nothing reaches POST /api/walk until the walker
 * taps confirm, and the tap count from a cold open to walking stays at one.
 *
 * It used to be three, and this file asserted three. Opening the app is the
 * walker saying they want to walk, and the length already had a default, so the
 * screen that only led here and the tap that only accepted the default are both
 * gone. The count is a promise to someone standing in a car park, so it is
 * counted here rather than described.
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
  // A second, quite separate stretch of Progress St, a mile off. Searching for
  // "Progress St" used to claim this one too, sight unseen.
  {
    seg_id: 4,
    name: 'Progress St',
    length_m: 900,
    geometry: { type: 'LineString', coordinates: [[-80.44, 37.25], [-80.44, 37.259]] },
  },
]

let posted: { url: string; body: Record<string, unknown> }[] = []

function json(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), { status, headers: { 'content-type': 'application/json' } })
}

beforeEach(async () => {
  posted = []
  cleanup()
  // Let the previous render's writes land before the database is thrown away,
  // otherwise a stray save recreates the walk this test is meant to start
  // without.
  await new Promise((r) => setTimeout(r, 25))
  _resetForTests()
  await new Promise<void>((resolve) => {
    const req = indexedDB.deleteDatabase('prayer-walk')
    req.onsuccess = () => resolve()
    req.onerror = () => resolve()
    req.onblocked = () => resolve()
  })
  await new Promise((r) => setTimeout(r, 5))
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
  it('takes one tap to get walking, and commits only on the confirm tap', async () => {
    render(<App />)

    // No tap at all. There is no screen before this one, and the length was
    // already a default, so the app plans the ordinary walk on its own.
    await waitFor(() => expect(posted.some((p) => p.url === '/api/route')).toBe(true))
    expect(posted.find((p) => p.url === '/api/route')!.body.minutes).toBe(30)

    // The one tap between opening the app and walking.
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

    // It says so plainly and hands over to picking streets by name.
    await screen.findByText('Which streets are you walking?')
    fireEvent.change(screen.getByLabelText('Find a street by name'), { target: { value: 'progress' } })
    fireEvent.click(await screen.findByRole('button', { name: /Progress St/ }))

    // A street name is not a thing anyone walked. Progress St is two stretches
    // a mile apart, so it opens into them and the walker says which.
    const stretches = document.querySelectorAll('.street-add')
    expect(stretches.length).toBe(2)
    fireEvent.click(stretches[0])

    const go = await screen.findByRole('button', { name: 'Start walking' })
    await waitFor(() => expect((go as HTMLButtonElement).disabled).toBe(false))
    fireEvent.click(go)
    fireEvent.click(await screen.findByRole('button', { name: 'Finish walk' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Add these streets to the map' }))

    await waitFor(() => expect(posted.filter((p) => p.url === '/api/walk')).toHaveLength(1))
    // The one stretch tapped, and not the other one carrying the same name.
    // Claiming every stretch of a name is what put ten miles of US 460 Bus on
    // the town map from a walker who meant two blocks, and coverage is
    // permanent.
    const sent = posted.find((p) => p.url === '/api/walk')!.body.seg_ids as number[]
    expect(sent).toHaveLength(1)
    expect([1, 4]).toContain(sent[0])
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
