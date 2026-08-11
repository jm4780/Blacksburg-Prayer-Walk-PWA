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
import MapView from '../components/MapView'
import type { Walk } from '../types'
import type { Nav } from '../App'

export default function ActiveWalk({ nav, walkId, onWalk }: {
  nav: Nav; walkId: string; onWalk: (w: Walk | null) => void
}) {
  const [walk, setWalk] = useState<Walk | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [reporting, setReporting] = useState(false)
  // Cancelling a walk in progress releases every street held for this walker, and
  // there is no undo — so it is asked for twice, and answered once it is done.
  const [confirming, setConfirming] = useState(false)
  const [released, setReleased] = useState(false)

  useEffect(() => {
    api.walk(walkId).then(setWalk).catch((e) => setError(e.message))
  }, [walkId])

  async function begin() {
    setBusy(true); setError(null)
    try { const w = await api.start(walkId); setWalk(w); onWalk(w) }
    catch (e: any) { setError(e.message) }
    finally { setBusy(false) }
  }

  async function discard() {
    setBusy(true); setError(null)
    try {
      await api.discard(walkId)
      onWalk(null)
      // A preview was never under way: "not this one" needs no receipt, so it goes
      // straight back. Ending a walk that had started does — the walker gave streets
      // up, and landing silently on the dashboard reads exactly like a tap that did
      // nothing. They go home from the acknowledgement, deliberately.
      if (walk?.status === 'ACTIVE') setReleased(true)
      else nav('/')
    }
    // The confirmation stays open on failure: the message appears directly above it,
    // and the walker who meant to cancel can try again without asking for it twice.
    catch (e: any) { setError(e.message) }
    finally { setBusy(false) }
  }

  // Only fatal while there is nothing to show. Once the walk has loaded, a failed
  // start or a failed cancel belongs beside the button that failed — see below.
  if (error && !walk) {
    return <div className="screen"><p className="error" role="alert">{error}</p></div>
  }
  if (!walk) return <div className="screen"><p className="muted">Loading…</p></div>

  if (released) {
    return (
      <div className="screen narrow">
        <h1>Walk cancelled</h1>
        <div className="note ok">
          <strong>Your streets are released</strong>
          <p>
            Nothing was recorded, and the streets held for you are free straight away
            so someone else can walk them.
          </p>
        </div>
        <button className="primary big" onClick={() => nav('/')}>Back to home</button>
      </div>
    )
  }

  const started = walk.status === 'ACTIVE'

  return (
    <div className="screen">
      <h1>{started ? 'Your walk' : 'Preview your walk'}</h1>

      <div className="card">
        {/* The marker is the walk's fixed start and end point, computed once when
            the route was generated. It is not the walker — it never moves. */}
        {/* `walking` is the map system's outdoors setting: heaviest weights, highest
            contrast, street names on, and nothing on the map that is not the route or
            the way to it — see src/map/style.ts. */}
        <MapView route={walk.geometry} height={360} context="walking"
                 start={walk.start_point
                   ? { lon: walk.start_point[0], lat: walk.start_point[1] } : null}
                 ariaLabel={`Planned route, ${walk.distance_miles} miles`} />
        <p className="fine centered">Starts and ends at the same point.</p>
        {/* Priority 8: what a walker needs to know about today's walk, and nothing
            that describes the optimiser. Segment counts moved to the admin views. */}
        <p className="mission-line">
          About {walk.estimated_minutes} minutes · {walk.distance_miles} miles
          {walk.households ? ` · approximately ${walk.households.toLocaleString()} households` : ''}
        </p>
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
        /* No `onDone`. It closed the form the instant the report was sent, which threw
           away the form's own "Thank you — that helps" before anybody could read it:
           reporting a problem looked like it had done nothing at all. The form keeps
           its acknowledgement on screen instead, exactly as it does on the
           confirmation screen. */
        <FeedbackForm walkId={walk.id} from="ACTIVE_WALK" />
      )}

      {/* A failed start or a failed cancel used to be invisible here: `error` was only
          rendered in the branch that returns before the walk has loaded, so the button
          simply re-enabled itself and said nothing. */}
      {error && <p className="error" role="alert">{error}</p>}

      {/* Cancelling asks first. Everything held for this walker is released the moment
          it is confirmed, and no part of that is recoverable, so the walker gets to
          read what it costs and where it leaves them before it happens. */}
      {started && confirming && (
        <div className="note warn">
          <strong>Cancel this walk?</strong>
          <p>
            No streets are marked as prayed for, and the ones held for you are released
            straight away so someone else can walk them. You cannot pick this walk back
            up afterwards.
          </p>
          <div className="actions">
            <button className="primary" disabled={busy} onClick={discard}>
              {busy ? 'Releasing…' : 'Yes, cancel and release my streets'}
            </button>
            <button className="secondary" disabled={busy}
                    onClick={() => setConfirming(false)}>
              No, keep walking
            </button>
          </div>
        </div>
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
        {/* A preview holds streets too, but nothing has been started, so going back to
            choose again is not a decision worth interrupting. */}
        <button className="secondary" disabled={busy || (started && confirming)}
                onClick={() => (started ? setConfirming(true) : discard())}>
          {started ? 'Cancel this walk' : 'Choose a different walk'}
        </button>
      </div>
    </div>
  )
}
