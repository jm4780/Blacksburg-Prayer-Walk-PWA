import type { Progress } from '../types'
import { formatMiles } from '../state/geo'

/**
 * The town's numbers, as typography. No cards, no shadows.
 *
 * Homes are null everywhere in this build, so no home line is drawn at all.
 * A zero here would be a claim that nobody lives on those streets.
 */
export function TownCounters({ progress, stale }: { progress: Progress | null; stale: boolean }) {
  if (!progress) return null

  const showHomes = progress.homes_covered !== null && progress.homes_total !== null

  return (
    <div>
      <p className="counter">{progress.percent.toFixed(1)}%</p>
      <p className="label">of Blacksburg's streets prayed for</p>
      <p className="stat-line">
        {progress.segments_covered.toLocaleString()} of {progress.segments_total.toLocaleString()} streets
        {'  ·  '}
        {formatMiles(progress.covered_m)} of {formatMiles(progress.total_m)} miles
      </p>
      {showHomes && (
        <p className="stat-line">
          {progress.homes_covered!.toLocaleString()} of {progress.homes_total!.toLocaleString()} homes
        </p>
      )}
      {stale && <p className="stat-line">Last count from when you had signal.</p>}
    </div>
  )
}
