import { StreetList } from '../components/StreetList'
import { countStreets, formatMiles } from '../state/geo'
import type { Segment, WalkState } from '../types'

/** The only screen that can put anything on the town map, and only on a tap. */
export function Confirm({
  walk,
  busy,
  notice,
  claimedSegments,
  suggestedSegments,
  covered,
  onToggle,
  onToggleMany,
  onMatch,
  onConfirm,
  onDiscard,
}: {
  walk: WalkState
  busy: string | null
  notice: string | null
  claimedSegments: Segment[]
  suggestedSegments: Segment[]
  covered: Set<number>
  onToggle: (seg_id: number) => void
  onToggleMany: (seg_ids: number[], on: boolean) => void
  onMatch: () => void
  onConfirm: () => void
  onDiscard: () => void
}) {
  const claimed = new Set(walk.claimed)
  const metres = claimedSegments.reduce((sum, s) => sum + s.length_m, 0)
  const freshMetres = claimedSegments
    .filter((s) => !covered.has(s.seg_id))
    .reduce((sum, s) => sum + s.length_m, 0)

  return (
    <div className="sheet">
      <h1>Did you walk these?</h1>
      <p>
        {countStreets(claimedSegments)} {countStreets(claimedSegments) === 1 ? 'street' : 'streets'} ·{' '}
        {formatMiles(metres)} miles
        {/* Nothing new is not a nought to print at someone. Their walk still
            counted; the town map simply already had it. */}
        {freshMetres > 0 && ` · ${formatMiles(freshMetres)} miles nobody had prayed for`}. Take off
        anything you did not walk.
      </p>

      <StreetList
        segments={claimedSegments}
        checked={claimed}
        covered={covered}
        onToggle={onToggle}
        onToggleMany={onToggleMany}
      />

      {suggestedSegments.length > 0 && (
        <>
          <p className="label">Close to your track, not certain</p>
          <p>Tick any of these you actually walked. Left alone, they count for nothing.</p>
          <StreetList
            segments={suggestedSegments}
            checked={claimed}
            covered={covered}
            onToggle={onToggle}
            onToggleMany={onToggleMany}
          />
        </>
      )}

      {notice && <p className="notice notice-warn">{notice}</p>}

      {/* Still an explicit tap, and still the only one that sends a coordinate
          anywhere. Doing it automatically would have been one less thing on the
          screen and would have broken the promise the sentence under it makes. */}
      {walk.trace.length > 0 && (
        <>
          <button className="btn btn-quiet" onClick={onMatch} disabled={busy === 'match'}>
            {busy === 'match' ? 'Checking…' : 'Check my track for streets I missed'}
          </button>
          <p className="privacy">
            That is the one time your location leaves this phone, and the server keeps none of it.
          </p>
        </>
      )}

      {/* Throwing the walk away used to sit last, on the easiest inch of the
          screen to hit one-handed. It goes above the button that matters. */}
      <button className="btn btn-quiet btn-danger" onClick={onDiscard}>
        Throw this walk away
      </button>
      <button
        className="btn btn-primary"
        onClick={onConfirm}
        disabled={claimedSegments.length === 0 || busy === 'confirm'}
      >
        Add these streets to the map
      </button>
    </div>
  )
}
