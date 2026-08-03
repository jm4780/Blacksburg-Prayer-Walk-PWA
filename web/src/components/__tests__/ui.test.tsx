/**
 * Component tests for the pieces of UI logic that are easy to get quietly wrong.
 *
 * The screen flows are covered end to end in e2e/slice.mjs and e2e/mission.mjs
 * against the real API; these cover rules a browser test would only catch by
 * accident — which sizes the slider will let you pick, and the map's three
 * functional contracts (tap targets, fit-vs-user, degrading without a basemap).
 *
 * MapLibre needs WebGL, which jsdom does not have, so the map is tested against a
 * mock of the library. That is the right seam: what matters here is what MapView
 * *asks MapLibre for*, not how MapLibre draws it. Whether the basemap actually
 * renders is a browser question and is answered in e2e/screenshots.mjs.
 */
import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

// MapView's state changes originate in MapLibre's own event callbacks, not in React
// event handlers. `act()` traps those updates and never flushes them, so these tests
// drive the mock directly and wait a tick — and turn off the act warning that would
// otherwise fire on every one of them.

import SizeSlider from '../SizeSlider'
import type { Variant } from '../../types'

// --------------------------------------------------------------- maplibre mock
const handlers = new Map<string, (e: any) => void>()
const layers = new Map<string, any>()
const sources = new Map<string, any>()
const fitBounds = vi.fn()
const setStyle = vi.fn()
const disableRotation = vi.fn()
let queryResult: any[] = []
let styleLoaded = true

class FakeMap {
  constructor(public opts: any) { setTimeout(() => handlers.get('load')?.({}), 0) }
  on(ev: string, fn: any) { handlers.set(ev, fn) }
  off() {}
  addControl() {}
  remove() {}
  isStyleLoaded() { return styleLoaded }
  setStyle = setStyle
  getSource(id: string) { return sources.get(id) }
  addSource(id: string, s: any) { sources.set(id, { ...s, setData: vi.fn() }) }
  getLayer(id: string) { return layers.get(id) }
  addLayer(l: any) { layers.set(l.id, l) }
  queryRenderedFeatures() { return queryResult }
  fitBounds = fitBounds
  touchZoomRotate = { disableRotation }
}

vi.mock('maplibre-gl', () => ({
  Map: FakeMap,
  config: {},
  NavigationControl: class {},
  LngLatBounds: class {
    pts: any[] = []
    constructor(a: any) { this.pts.push(a) }
    extend(p: any) { this.pts.push(p); return this }
  },
}))
vi.mock('maplibre-gl/dist/maplibre-gl.css', () => ({}))
// Vite resolves `?worker&url` at build time; under vitest it is just a string.
vi.mock('maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url',
        () => ({ default: '/assets/maplibre-gl-worker.js' }))

const MapView = (await import('../MapView')).default

const ROUTE = {
  type: 'LineString' as const,
  coordinates: [[-80.42, 37.22], [-80.41, 37.23], [-80.40, 37.22]] as [number, number][],
}

/** Renders, then lets the mocked 'load' event fire and the layer effect settle. */
async function mount(ui: React.ReactElement) {
  const r = render(ui)
  await settle()
  return r
}

/** Enough turns for: the mocked 'load', the re-render it causes, and the effect. */
async function settle() {
  for (let i = 0; i < 4; i++) await new Promise((res) => setTimeout(res, 1))
}

beforeEach(() => {
  // Set here rather than at module scope: @testing-library/react turns it back on
  // when it loads, and it is read at update time.
  ;(globalThis as any).IS_REACT_ACT_ENVIRONMENT = false
  handlers.clear(); layers.clear(); sources.clear()
  fitBounds.mockClear(); setStyle.mockClear(); disableRotation.mockClear()
  queryResult = []; styleLoaded = true
})

describe('MapView', () => {
  it('draws the route on a real map, not a fixed picture', async () => {
    await mount(<MapView route={ROUTE} ariaLabel="route" />)
    expect(layers.get('route-line')).toBeTruthy()
    expect(sources.has('route')).toBe(true)
  })

  it('gives segments a tap target far wider than the drawn line', async () => {
    // The functional requirement behind Priority 1: at town zoom a thumb covers a
    // dozen streets, so selection has to query something much wider than 2.5px.
    await mount(
      <MapView segments={[{ id: 'SEG-1', coordinates: ROUTE.coordinates, state: 'todo' }]}
               onSegmentTap={() => {}} ariaLabel="edit" />)
    const hit = layers.get('segments-hit')
    const line = layers.get('segments-line')
    expect(hit.paint['line-width']).toBeGreaterThanOrEqual(20)
    expect(hit.paint['line-opacity']).toBe(0)
    expect(hit.paint['line-width']).toBeGreaterThan(line.paint['line-width'][3] ?? 3)
  })

  it('reports the tapped segment id, not the nearest coordinate', async () => {
    const onSegmentTap = vi.fn()
    await mount(
      <MapView segments={[{ id: 'SEG-42', coordinates: ROUTE.coordinates, state: 'todo' }]}
               onSegmentTap={onSegmentTap} ariaLabel="edit" />)
    queryResult = [{ properties: { id: 'SEG-42' } }]
    handlers.get('click')!({ point: [10, 10], lngLat: { lat: 37.22, lng: -80.41 } })
    expect(onSegmentTap).toHaveBeenCalledWith('SEG-42')
  })

  it('falls back to a bare map tap when nothing was hit', async () => {
    const onMapTap = vi.fn()
    await mount(<MapView onMapTap={onMapTap} ariaLabel="pick" />)
    handlers.get('click')!({ point: [1, 1], lngLat: { lat: 37.25, lng: -80.4 } })
    expect(onMapTap).toHaveBeenCalledWith({ lat: 37.25, lon: -80.4 })
  })

  it('zooms closer when editing, because streets must be separable by thumb', async () => {
    await mount(<MapView route={ROUTE} ariaLabel="m" />)
    const browsing = fitBounds.mock.calls[fitBounds.mock.calls.length - 1][1].maxZoom
    fitBounds.mockClear()
    await mount(<MapView route={ROUTE} editing ariaLabel="m" />)
    const editing = fitBounds.mock.calls[fitBounds.mock.calls.length - 1][1].maxZoom
    expect(editing).toBeGreaterThan(browsing)
  })

  it('stops auto-fitting once the user has moved the map', async () => {
    const { rerender } = await mount(<MapView route={ROUTE} ariaLabel="m" />)
    expect(fitBounds).toHaveBeenCalledTimes(1)

    handlers.get('dragstart')!({})               // the user takes the viewport
    await settle()
    fitBounds.mockClear()

    const other = { ...ROUTE, coordinates: [...ROUTE.coordinates, [-80.39, 37.24]] as any }
    rerender(<MapView route={other} ariaLabel="m" />)
    await settle()
    expect(fitBounds).not.toHaveBeenCalled()
  })

  it('recenters on request, deliberately', async () => {
    await mount(<MapView route={ROUTE} ariaLabel="m" />)
    handlers.get('dragstart')!({})
    await settle()
    fitBounds.mockClear()
    fireEvent.click(screen.getByRole('button', { name: /recenter/i }))
    expect(fitBounds).toHaveBeenCalledTimes(1)
  })

  it('disables rotation — a rotated street map helps nobody on foot', async () => {
    await mount(<MapView route={ROUTE} ariaLabel="m" />)
    expect(disableRotation).toHaveBeenCalled()
  })

  it('still shows the route when the basemap cannot be reached', async () => {
    styleLoaded = false
    await mount(<MapView route={ROUTE} ariaLabel="m" />)
    handlers.get('error')!({ error: { status: 502 } })
    await settle()
    expect(setStyle).toHaveBeenCalled()
    expect(await screen.findByRole('status')).toHaveProperty(
      'textContent', expect.stringContaining('route is still shown'))
  })

  it('carries the aria label onto the map itself', async () => {
    await mount(<MapView route={ROUTE} ariaLabel="Progress map" />)
    expect(screen.getByRole('application', { name: 'Progress map' })).toBeTruthy()
  })
})

// ------------------------------------------------------------------ size slider
function variant(band: string, available: boolean, miles = 1): Variant {
  return {
    band, target_miles: miles, available,
    state: available ? 'ROUTE_AVAILABLE' : 'LONGER_ROUTE_REQUIRED',
    reason: available ? 'ok' : 'nothing within reach at this length',
    distance_miles: available ? miles : null,
    estimated_minutes: available ? miles * 20 : null,
    new_required_miles: available ? miles : null,
    repeated_miles: 0, efficiency: 0.9, households: 10, walk_quality: 70,
    dead_end_returns_miles: 0, closing_leg_miles: 0, segment_count: 10,
    required_segment_count: 8, nests_within_shorter: true, component: null,
    score_components: {}, campus_credited_miles: 0, suggested_band: null,
    nearest_incomplete_miles: null, segment_ids: [], required_segment_ids: [],
    connector_segment_ids: [], start_point: null, end_point: null, route_score: 1,
    seed: 1, network_version: 'v1.3', engine_version: '2.1.1',
    geometry: null,
  }
}

describe('SizeSlider', () => {
  const variants = [
    variant('Quick', false, 1), variant('Short', true, 2),
    variant('Medium', true, 3.5), variant('Long', true, 5),
    variant('Extended', false, 7.5),
  ]

  it('labels available sizes by time, not by band name', () => {
    // Priority 4: what somebody is choosing between is how long they will be out.
    render(<SizeSlider variants={variants} selected="Medium" onSelect={() => {}} />)
    expect(screen.getByText('40 min')).toBeTruthy()   // Short, 2 mi
    expect(screen.getByText('70 min')).toBeTruthy()   // Medium, 3.5 mi
  })

  it('still renders the unavailable sizes rather than hiding them', () => {
    render(<SizeSlider variants={variants} selected="Medium" onSelect={() => {}} />)
    for (const b of ['Quick', 'Extended']) expect(screen.getByText(b)).toBeTruthy()
  })

  it('never lets an unavailable band be selected', () => {
    render(<SizeSlider variants={variants} selected="Medium" onSelect={() => {}} />)
    const quick = screen.getByText('Quick').closest('button')!
    expect(quick.getAttribute('aria-disabled')).toBe('true')
    expect((quick as HTMLButtonElement).disabled).toBe(true)
  })

  it('explains why an unavailable band is unavailable', () => {
    render(<SizeSlider variants={variants} selected="Medium" onSelect={() => {}} />)
    const quick = screen.getByText('Quick').closest('button')!
    expect(quick.getAttribute('title')).toContain('nothing within reach')
  })

  it('snaps the range to available bands only', () => {
    const onSelect = vi.fn()
    render(<SizeSlider variants={variants} selected="Short" onSelect={onSelect} />)
    const range = screen.getByRole('slider') as HTMLInputElement
    // Three available bands -> indices 0..2, not 0..4.
    expect(range.max).toBe('2')
    expect(range.value).toBe('0')
  })

  it('says so plainly when no size is available at all', () => {
    render(<SizeSlider variants={variants.map((v) => ({ ...v, available: false }))}
                       selected={null} onSelect={() => {}} />)
    expect(screen.getByText(/No route size is available/)).toBeTruthy()
  })
})
