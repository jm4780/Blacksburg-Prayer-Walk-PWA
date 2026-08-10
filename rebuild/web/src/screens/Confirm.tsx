import { StreetList } from '../components/StreetList'
import { formatMiles } from '../state/geo'
import type { Segment, WalkState } from '../types'

/** The only screen that can put anything on the town map, and only on a tap. */
export function Confirm({
  walk,
  busy,
  notice,
  name,
  onName,
  claimedSegments,
  suggestedSegments,
  covered,
  onToggle,
  onMatch,
  onConfirm,
  onDiscard,
}: {
  walk: WalkState
  busy: string | null
  notice: string | null
  name: string
  onName: (v: string) => void
  claimedSegments: Segment[]
  suggestedSegments: Segment[]
  covered: Set<number>
  onToggle: (seg_id: number) => void
  onMatch: () => void
  onConfirm: () => void
  onDiscard: () => void
}) {
  const claimed = new Set(walk.claimed)
  const metres = claimedSegments.reduce((sum, s) => sum + s.length_m, 0)
  const fresh = claimedSegments.filter((s) => !covered.has(s.seg_id)).length

  return (
    <div className="sheet">
      <h1>Did you walk these?</h1>
      <p>
        {claimedSegments.length} streets · {formatMiles(metres)} miles · {fresh} of them new to the town map.
        Take off anything you did not walk.
      </p>

      <StreetList segments={claimedSegments} checked={claimed} covered={covered} onToggle={onToggle} />

      {suggestedSegments.length > 0 && (
        <>
          <p className="label">Close to your track, not certain</p>
          <p>Tick any of these you actually walked. Left alone, they count for nothing.</p>
          <StreetList
            segments={suggestedSegments}
            checked={claimed}
            covered={covered}
            onToggle={onToggle}
          />
        </>
      )}

      {notice && <p className="notice notice-warn">{notice}</p>}

      {walk.trace.length > 0 && (
        <>
          <button className="btn" onClick={onMatch} disabled={busy === 'match'}>
            {busy === 'match' ? 'Checking…' : 'Check my track for streets I missed'}
          </button>
          <p className="privacy">
            That button is the one and only time your location leaves this phone. It is sent to be matched
            against the street map, and the server keeps none of it. Skip it and tick the streets yourself if
            you would rather.
          </p>
        </>
      )}

      <input
        className="name-input"
        value={name}
        onChange={(e) => onName(e.target.value)}
        placeholder="Your name, if you want to leave one"
        autoComplete="name"
      />

      <button
        className="btn btn-primary"
        onClick={onConfirm}
        disabled={claimedSegments.length === 0 || busy === 'confirm'}
      >
        Add these streets to the map
      </button>
      <button className="btn btn-quiet" onClick={onDiscard}>
        Throw this walk away
      </button>
    </div>
  )
}
