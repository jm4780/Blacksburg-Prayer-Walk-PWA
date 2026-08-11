/**
 * The confirmation screen's identity rules.
 *
 * This screen is the only place a walker asserts what they actually prayed for, and
 * the only place the browser holds anything on their behalf between page loads. Both
 * of those went wrong in ways a browser test found and no unit test would have:
 *
 *   - Navigating from one walk's confirmation to another kept the first walk's ticked
 *     streets, showed them under the second walk's URL with a live Submit, and wrote
 *     them into storage under the second walk's key. A reviewer reproduced 31 of walk
 *     A's streets selected on walk B.
 *   - Every 409 was reported as "already recorded", including the one that means the
 *     walk was never started.
 *
 * MapView needs WebGL, which jsdom has not got, so it is mocked away — what is under
 * test is which walk's data the screen holds, not how a map draws.
 */
import { render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../../components/MapView', () => ({
  default: () => null,
  __esModule: true,
}))

const walkFor = (id: string, segments: string[]) => ({
  id, status: 'ACTIVE', outcome: null, band: 'MEDIUM',
  distance_miles: 2.4, estimated_minutes: 47, households: 900,
  required_segment_count: segments.length,
  planned_required_ids: segments, planned_segment_ids: segments,
  planned_connector_ids: [], geometry: null, start_point: null,
})

const walks: Record<string, any> = {
  A: walkFor('A', ['SEG-A1', 'SEG-A2', 'SEG-A3']),
  B: walkFor('B', ['SEG-B1']),
}

vi.mock('../../api', async () => {
  const actual = await vi.importActual<any>('../../api')
  return {
    ...actual,
    api: {
      walk: (id: string) => walks[id]
        ? Promise.resolve(walks[id])
        : Promise.reject(new actual.ApiError(404, 'unknown walk')),
      progressMap: () => Promise.resolve({ features: [], open_space: null, boundary: null }),
      complete: () => Promise.resolve({}),
      getFeedback: () => Promise.resolve(null),
    },
  }
})

import Confirm from '../Confirm'

const draft = (id: string) => sessionStorage.getItem(`bpw.confirm.${id}`)

beforeEach(() => sessionStorage.clear())
afterEach(() => vi.clearAllMocks())

describe('the confirmation screen never carries one walk into another', () => {
  it('does not write one walk’s streets under another walk’s key', async () => {
    const { rerender } = render(<Confirm nav={() => {}} walkId="A" onDone={() => {}} />)
    await waitFor(() => expect(draft('A')).toBeTruthy())
    expect(JSON.parse(draft('A')!).picked).toEqual(['SEG-A1', 'SEG-A2', 'SEG-A3'])

    rerender(<Confirm nav={() => {}} walkId="B" onDone={() => {}} />)
    await waitFor(() => expect(draft('B')).toBeTruthy())

    // The whole defect in one assertion: B's draft must contain B's streets only.
    expect(JSON.parse(draft('B')!).picked).toEqual(['SEG-B1'])
    expect(JSON.parse(draft('B')!).picked).not.toContain('SEG-A1')
  })

  it('shows nothing rather than the previous walk while the next one loads', async () => {
    const { rerender } = render(<Confirm nav={() => {}} walkId="A" onDone={() => {}} />)
    await waitFor(() => expect(screen.queryByText(/Loading/)).toBeNull())

    rerender(<Confirm nav={() => {}} walkId="B" onDone={() => {}} />)
    // Synchronously after the id changes, before B has landed: no stale walk, and in
    // particular no Submit that would record A against B.
    expect(screen.queryByRole('button', { name: /Submit/i })).toBeNull()
  })

  it('never resolves a walk id that does not exist', async () => {
    render(<Confirm nav={() => {}} walkId="nope" onDone={() => {}} />)
    await waitFor(() =>
      expect(screen.queryByRole('button', { name: /Submit/i })).toBeNull())
    expect(draft('nope')).toBeNull()
  })
})
