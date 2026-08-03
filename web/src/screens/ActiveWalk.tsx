/**
 * Active walk (§13).
 *
 * A static plan. That is a deliberate constraint, not a missing feature, and the
 * screen is written so nothing on it can drift into implying otherwise:
 *
 *   - no live-location indicator
 *   - no moving user marker
 *   - no "recording", "tracking" or "GPS" language
 *   - no claim that the walker is being followed
 *
 * The route was computed once from a one-time fix. The phone is not watching. A
 * walker should be able to put it in a pocket and pray, which is the point.
 */
import { useEffect, useState } from 'react'
import { api } from '../api'
import FeedbackForm from '../components/FeedbackForm'
import MapCanvas from '../components/MapCanvas'
import type { Walk } from '../types'
import type { Nav } from '../App'

export default function ActiveWalk({ nav, walkId, onWalk }: {
  nav: Nav; walkId: string; onWalk: (w: Walk | null) => void
}) {
  const [walk, setWalk] = useState<Walk | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [reporting, setReporting] = useState(false)

  useEffect(() => {
    api.walk(walkId).then(setWalk).catch((e) => setError(e.message))
  }, [walkId])

  async function begin() {
    setBusy(true)
    try { const w = await api.start(walkId); setWalk(w); onWalk(w) }
    catch (e: any) { setError(e.message) }
    finally { setBusy(false) }
  }

  async function discard() {
    setBusy(true)
    try { await api.discard(walkId); onWalk(null); nav('/') }
    catch (e: any) { setError(e.message) }
    finally { setBusy(false) }
  }

  if (error) return <div className="screen"><p className="error" role="alert">{error}</p></div>
  if (!walk) return <div className="screen"><p className="muted">Loading…</p></div>

  const started = walk.status === 'ACTIVE'

  return (
    <div className="screen">
      <h1>{started ? 'Your walk' : 'Preview your walk'}</h1>

      <div className="card">
        {/* The marker is the walk's fixed start and end point, computed once when
            the route was generated. It is not the walker — it never moves. */}
        <MapCanvas lines={[]} focus={walk.geometry} height={320}
                   marker={walk.start_point
                     ? { lon: walk.start_point[0], lat: walk.start_point[1] } : null}
                   ariaLabel={`Planned route, ${walk.distance_miles} miles`} />
        <p className="fine centered">Starts and ends at the same point.</p>
        <dl className="facts">
          <div><dt>Distance</dt><dd>{walk.distance_miles} mi</dd></div>
          <div><dt>About</dt><dd>{walk.estimated_minutes} min</dd></div>
          <div><dt>Streets</dt><dd>{walk.required_segment_count}</dd></div>
          <div><dt>Households</dt><dd>~{(walk.households ?? 0).toLocaleString()}</dd></div>
        </dl>
      </div>

      {/* Phrased as a statement about the screen, not as a denial of surveillance.
          "Your phone is not following you" was the first draft; it puts the idea of
          being followed in front of the walker in order to deny it, and it trips the
          §13 language guard in e2e/slice.mjs for a reason worth keeping. */}
      <p className="fine">
        This is your plan for the walk. Nothing here updates as you move — glance at
        the list below whenever you need it.
      </p>

      {walk.directions && walk.directions.length > 0 && (
        <ol className="directions">
          {walk.directions.map((d, i) => (
            <li key={i} className={d.derived ? 'crossing' : ''}>
              <span className="d-name">
                {d.derived ? `Cross to ${d.name}` : d.name}
              </span>
              <span className="d-miles">{d.miles} mi</span>
              {d.campus_alternative && (
                <span className="d-tag">either side counts</span>
              )}
            </li>
          ))}
        </ol>
      )}

      {/* §5: reportable from the active screen, so "this crossing doesn't exist" can
          be said standing at the crossing rather than remembered afterwards. */}
      {started && !reporting && (
        <button className="secondary" onClick={() => setReporting(true)}>
          Report a problem with this route
        </button>
      )}
      {started && reporting && (
        <FeedbackForm walkId={walk.id} from="ACTIVE_WALK"
                      onDone={() => setReporting(false)} />
      )}

      <div className="actions">
        {!started && (
          <button className="primary big" disabled={busy} onClick={begin}>
            Start this walk
          </button>
        )}
        {started && (
          <button className="primary big" onClick={() => nav(`/confirm/${walk.id}`)}>
            Finish Walk
          </button>
        )}
        <button className="secondary" disabled={busy} onClick={discard}>
          {started ? 'Cancel this walk' : 'Choose a different walk'}
        </button>
      </div>
    </div>
  )
}
