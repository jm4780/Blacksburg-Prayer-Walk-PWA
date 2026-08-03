/**
 * Component tests for the two pieces of UI logic that are easy to get quietly wrong:
 * which sizes the slider will let you pick, and how the map projects lon/lat.
 *
 * The screen flows are covered end to end in e2e/slice.mjs against the real API;
 * these cover the arithmetic and the disabled-state rules that a browser test would
 * only catch by accident.
 */
import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import MapCanvas from '../MapCanvas'
import SizeSlider from '../SizeSlider'
import type { Variant } from '../../types'

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
    seed: 1, network_version: 'v1.2', engine_version: '2.1.0',
    geometry: null,
  }
}

describe('SizeSlider', () => {
  const variants = [
    variant('Quick', false, 1), variant('Short', true, 2),
    variant('Medium', true, 3.5), variant('Long', true, 5),
    variant('Extended', false, 7.5),
  ]

  it('renders every band, including the unavailable ones', () => {
    render(<SizeSlider variants={variants} selected="Medium" onSelect={() => {}} />)
    for (const b of ['Quick', 'Short', 'Medium', 'Long', 'Extended']) {
      expect(screen.getByText(b)).toBeTruthy()
    }
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
    // getByLabelText('Route size') is ambiguous — the group and the input share
    // that label by design, so query by role.
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

describe('MapCanvas', () => {
  const line = {
    coords: [[-80.42, 37.22], [-80.41, 37.23], [-80.40, 37.22]] as [number, number][],
    className: 'ln-todo',
  }

  it('draws one path per line', () => {
    const { container } = render(<MapCanvas lines={[line]} ariaLabel="test map" />)
    expect(container.querySelectorAll('path.ln-todo').length).toBe(1)
  })

  it('corrects for longitude compression so routes are not squashed', () => {
    // A square in degrees is wider than it is tall on the ground at this latitude,
    // so the projected width must come out smaller than the projected height.
    const square: [number, number][] = [
      [-80.42, 37.22], [-80.41, 37.22], [-80.41, 37.23], [-80.42, 37.23],
    ]
    const { container } = render(
      <MapCanvas lines={[{ coords: square, className: 'ln-todo' }]} ariaLabel="m" />)
    const d = container.querySelector('path')!.getAttribute('d')!
    const pts = d.slice(1).split(/[ML]/).map((p) => p.trim().split(' ').map(Number))
    const w = Math.max(...pts.map((p) => p[0])) - Math.min(...pts.map((p) => p[0]))
    const h = Math.max(...pts.map((p) => p[1])) - Math.min(...pts.map((p) => p[1]))
    expect(w).toBeLessThan(h)
    expect(w / h).toBeCloseTo(Math.cos((37.23 * Math.PI) / 180), 1)
  })

  it('is only tappable when a pick handler is supplied', () => {
    const { container: a } = render(<MapCanvas lines={[line]} ariaLabel="m" />)
    expect(a.querySelector('svg')!.dataset.pickable).toBe('false')
    const { container: b } = render(
      <MapCanvas lines={[line]} ariaLabel="m" onPick={() => {}} />)
    expect(b.querySelector('svg')!.dataset.pickable).toBe('true')
  })

  it('renders no marker unless one is given', () => {
    const { container } = render(<MapCanvas lines={[line]} ariaLabel="m" />)
    expect(container.querySelector('.marker')).toBeNull()
  })

  it('draws the town boundary behind the network', () => {
    const ring: [number, number][] = [
      [-80.46, 37.19], [-80.38, 37.19], [-80.38, 37.27], [-80.46, 37.27], [-80.46, 37.19],
    ]
    const { container } = render(
      <MapCanvas lines={[line]} boundary={{ coordinates: [ring] }} ariaLabel="m" />)
    const paths = [...container.querySelectorAll('path')]
    expect(paths[0].getAttribute('class')).toBe('ln-boundary')
    expect(container.querySelectorAll('path.ln-boundary').length).toBe(1)
  })
})
