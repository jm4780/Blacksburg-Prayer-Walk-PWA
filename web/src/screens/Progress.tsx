/**
 * Public progress map (§16).
 *
 * The map shows required streets, trails and canonical campus corridors, coloured by
 * whether they have been prayed for. It shows nothing else, and the list of what it
 * excludes comes from the server so the two cannot drift apart.
 */
import { useEffect, useState } from 'react'
import { api, ApiError } from '../api'
import MapView, { type SegmentFeature } from '../components/MapView'
import type { Metrics, ProgressMap } from '../types'

export default function Progress() {
  const [map, setMap] = useState<ProgressMap | null>(null)
  const [m, setM] = useState<Metrics | null>(null)
  const [blocked, setBlocked] = useState<string | null>(null)

  useEffect(() => {
    api.metrics().then(setM).catch(() => {})
    api.progressMap().then(setMap).catch((e) => {
      if (e instanceof ApiError && e.status === 403) setBlocked(e.message)
    })
  }, [])

  const lines: SegmentFeature[] = (map?.features ?? []).map((f) => ({
    id: f.properties.id,
    coordinates: f.geometry.coordinates,
    state: f.properties.done ? 'done' : f.properties.held ? 'held' : 'todo',
  }))

  const done = map?.features.filter((f) => f.properties.done).length ?? 0

  return (
    <div className="screen">
      <h1>Progress</h1>

      {m && (
        <p className="lede">
          <strong>{m.percent_prayed_for.value.toFixed(1)}%</strong> of Blacksburg's{' '}
          {m.percent_prayed_for.denominator_miles} required miles have been prayed for,
          across {m.completed_walks} walks.
        </p>
      )}

      {blocked && (
        <div className="note stop">
          <strong>The map is not public yet</strong>
          <p>{blocked}</p>
        </div>
      )}

      {map && (
        <>
          <MapView segments={lines} height={460}
                   ariaLabel={`Progress map: ${done} of ${map.features.length} required streets prayed for`} />
          <div className="legend">
            <span><i className="sw done" /> Prayed for</span>
            <span><i className="sw todo" /> Not yet</span>
            <span><i className="sw held" /> Someone is walking it now</span>
          </div>
          <details className="fine">
            <summary>What this map does not show</summary>
            <ul>{map.excludes.map((x) => <li key={x}>{x}</li>)}</ul>
          </details>
          <p className="fine">Network {map.network_version} · {map.network_id}</p>
        </>
      )}
    </div>
  )
}
