import { StreetList } from '../components/StreetList'
import { countStreets, formatMiles } from '../state/geo'
import type { Segment, WalkState } from '../types'

export function Walking({
  walk,
  locationOn,
  locationDenied,
  claimedSegments,
  routeSegments,
  covered,
  onToggle,
  onToggleMany,
  onFinish,
}: {
  walk: WalkState
  locationOn: boolean
  locationDenied: boolean
  claimedSegments: Segment[]
  routeSegments: Segment[]
  covered: Set<number>
  onToggle: (seg_id: number) => void
  onToggleMany: (seg_ids: number[], on: boolean) => void
  onFinish: () => void
}) {
  const claimed = new Set(walk.claimed)
  const metres = claimedSegments.reduce((sum, s) => sum + s.length_m, 0)
  const list = routeSegments.length ? routeSegments : claimedSegments
  const target = countStreets(routeSegments.length ? routeSegments : claimedSegments)

  return (
    /* Walking is the one screen with somewhere to look other than itself. The
       sheet used to stand 78% tall over a followed map, so the route ran off
       behind it and the walker was handed a checklist instead of the way to go.
       It keeps to the bottom third: figures, the one button, and the list of
       streets under it for putting right what the phone got wrong. */
    <div className="sheet sheet-walking">
      <div className="walking-figures">
        <p className="counter-small">
          {countStreets(claimedSegments)}
          <span className="unit">of {target} streets</span>
        </p>
        <p className="counter-small">
          {formatMiles(metres)}
          <span className="unit">miles</span>
        </p>
      </div>

      <p>
        {locationOn
          ? 'Follow the blue line. Streets tick off as you pass them.'
          : locationDenied
            ? 'Follow the blue line. Tap each street as you finish it.'
            : 'Tap each street as you finish it.'}
      </p>

      <button className="btn btn-primary" onClick={onFinish}>
        Finish walk
      </button>
      <p className="privacy">Your location stays on this phone. Nothing is sent while you walk.</p>

      {/* Below the button on purpose. Mid-walk this is for correcting the odd
          street, not for reading, and it used to push the map off the screen. */}
      <StreetList
        segments={list}
        checked={claimed}
        covered={covered}
        onToggle={onToggle}
        onToggleMany={onToggleMany}
      />
    </div>
  )
}
