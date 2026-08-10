import { StreetList } from '../components/StreetList'
import { formatMiles } from '../state/geo'
import type { Segment, WalkState } from '../types'

export function Walking({
  walk,
  locationOn,
  locationDenied,
  claimedSegments,
  routeSegments,
  covered,
  onToggle,
  onFinish,
}: {
  walk: WalkState
  locationOn: boolean
  locationDenied: boolean
  claimedSegments: Segment[]
  routeSegments: Segment[]
  covered: Set<number>
  onToggle: (seg_id: number) => void
  onFinish: () => void
}) {
  const claimed = new Set(walk.claimed)
  const metres = claimedSegments.reduce((sum, s) => sum + s.length_m, 0)
  const list = routeSegments.length ? routeSegments : claimedSegments
  const target = routeSegments.length || claimedSegments.length

  return (
    <div className="sheet">
      <div className="walking-figures">
        <p className="counter-small">
          {claimedSegments.length}
          <span className="unit">of {target} streets</span>
        </p>
        <p className="counter-small">
          {formatMiles(metres)}
          <span className="unit">miles</span>
        </p>
      </div>

      <p>
        {locationOn
          ? 'Streets tick themselves off as you pass them. Tap any street to change it.'
          : locationDenied
            ? 'Tap each street as you finish it. Nothing here needs your location.'
            : 'Tap each street as you finish it.'}
      </p>

      <StreetList segments={list} checked={claimed} covered={covered} onToggle={onToggle} />

      <button className="btn btn-primary" onClick={onFinish}>
        Finish walk
      </button>
      <p className="privacy">
        Nothing has gone to the map yet. You'll see everything you walked before anything is sent.
      </p>
    </div>
  )
}
