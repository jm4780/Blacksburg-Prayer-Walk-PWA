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
import { ApiError, api, isOffline } from '../api'
import FeedbackForm from '../components/FeedbackForm'
import MapView from '../components/MapView'
import type { Walk } from '../types'
import type { Nav } from '../App'

export default function ActiveWalk({ nav, walkId, onWalk }: {
  nav: Nav; walkId: string; onWalk: (w: Walk | null) => void
}) {
  const [walk, setWalk] = useState<Walk | null>(null)
  const [error, setError] = useState<string | null>(null)
  // The load failing is a different kind of failure from a button failing: there is
  // nothing on screen to attach it to, so it is the screen. Kept as the thrown error
  // rather than its message — "could not reach the server" and "unknown walk" want
  // different words and different ways out, and only the error itself knows which.
  const [fatal, setFatal] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)
  const [reporting, setReporting] = useState(false)
  // Cancelling a walk in progress releases every street held for this walker, and
  // there is no undo — so it is asked for twice, and answered once it is done.
  const [confirming, setConfirming] = useState(false)
  const [released, setReleased] = useState(false)

  useEffect(() => {
    let live = true
    // A different id is a different walk. Everything already on screen — the map, the
    // mileage, the household count, the street list, a half-open cancel confirmation —
    // describes the walk we were just looking at, and none of it is true of this one.
    // Left in place, the screen showed one walk's route under another walk's id.
    setWalk(null); setFatal(null); setError(null)
    setConfirming(false); setReporting(false); setReleased(false)
    api.walk(walkId)
      .then((w) => { if (live) setWalk(w) })
      .catch((e) => { if (live) setFatal(e) })
    return () => { live = false }
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

  /**
   * "This is over, here is the way out."
   *
   * One shape for every state that cannot be walked: a heading that says what
   * happened, a note that says what it means for the walker, and a single button to
   * the one place worth going next. Written once because a walk can end four ways and
   * they should not each invent their own furniture.
   */
  function ended(title: string, heading: string, body: string) {
    return (
      <div className="screen narrow">
        <h1>{title}</h1>
        <div className="note ok">
          <strong>{heading}</strong>
          <p>{body}</p>
        </div>
        <button className="primary big" onClick={() => nav('/')}>Back to home</button>
      </div>
    )
  }

  // Nothing loaded, so there is nothing to put a message beside. An unreachable server
  // and a walk that does not exist are not the same problem and do not get the same
  // button: one is worth trying again, the other never will be.
  if (fatal) {
    const gone = fatal instanceof ApiError && fatal.status === 404
    const retry = isOffline(fatal)
    return (
      <div className="screen narrow">
        <h1>{gone ? 'We could not find that walk' : 'This walk did not load'}</h1>
        <p className="error" role="alert">
          {gone
            ? 'That link does not point at a walk of yours. Nothing you have walked '
              + 'is affected — everything is on the server, under your name.'
            : (fatal as Error).message}
        </p>
        <div className="actions">
          {retry
            ? <button className="primary big" onClick={() => window.location.reload()}>
                Try again
              </button>
            : <button className="primary big" onClick={() => nav('/')}>
                Back to home
              </button>}
          {retry && (
            <button className="secondary" onClick={() => nav('/')}>Back to home</button>
          )}
        </div>
      </div>
    )
  }
  // `walk.id !== walkId` covers the frame between the hash changing and the effect
  // clearing state: React renders the new id with the old walk still in hand.
  if (!walk || walk.id !== walkId) {
    return <div className="screen"><p className="muted">Loading…</p></div>
  }

  if (released || walk.status === 'DISCARDED') {
    return ended(
      'Walk cancelled',
      'Your streets are released',
      'Nothing was recorded, and the streets held for you are free straight away so '
      + 'someone else can walk them.')
  }

  /*
   * A completed walk is still reachable — the browser's back button lands on it the
   * moment a walk is submitted, which is one tap after finishing one. It used to say
   * "Preview your walk" and offer to start it; both buttons then failed with the
   * server's own words ("walk is COMPLETED, cannot be started"), and nothing on the
   * screen had said the walk was done.
   */
  if (walk.status === 'COMPLETED') {
    return walk.outcome === 'DID_NOT_COMPLETE'
      ? ended(
          'Walk closed',
          'Nothing was recorded for this one',
          'You told us it was not completed, so no streets were marked and the ones '
          + 'held for you went back straight away.')
      : ended(
          'Walk complete',
          'This walk is already recorded',
          'You submitted it, and the streets on it are counted towards the town. '
          + 'There is nothing left to do here.')
  }

  const started = walk.status === 'ACTIVE'

  // Any status this build has not heard of. It is not one that can be walked, so the
  // one thing this screen must not do is offer to start it.
  if (!started && walk.status !== 'PREVIEW') {
    return ended(
      'This walk is closed',
      'It cannot be started or finished',
      'Nothing has been lost. Everything you have walked is recorded on the server, '
      + 'under your name.')
  }

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

      {/* A failed start or a failed cancel used to be invisible here: `error` was only
          rendered in the branch that returns before the walk has loaded, so the button
          simply re-enabled itself and said nothing. It belongs directly above the
          buttons, which is where the tap that failed was. */}
      {error && <p className="error" role="alert">{error}</p>}

      {/*
        The decision, above the street list rather than under twenty-two rows of it.
        On a phone the primary sat around a thousand pixels down and nothing orange was
        in the first screenful: the walker arrived at a screen whose whole purpose is
        one tap and had to scroll the length of the walk to find it. The list is real
        content — it is what a walker reads at a junction — so it keeps its place, just
        below the decision instead of in front of it.
      */}
      {started && confirming ? (
        /* Cancelling asks first. Everything held for this walker is released the moment
           it is confirmed, and no part of that is recoverable, so the walker gets to
           read what it costs and where it leaves them before it happens.

           While the question is open it is the only question on screen. "Finish Walk"
           used to stay below it in the same orange, 133px from the button that throws
           the walk away — two primaries, one of them destructive, and no way to tell at
           a glance which was which. The confirmation owns the decision until it is
           answered; "No, keep walking" puts the walk back exactly as it was. */
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
      ) : (
        /* One primary, in both states. "Start this walk" before, "Finish Walk" after,
           and never both — the other exit is an outlined button underneath it, which is
           the only pairing on this screen that is meant to read as a pair. */
        <div className="actions">
          {started ? (
            <button className="primary big" onClick={() => nav(`/confirm/${walk.id}`)}>
              Finish Walk
            </button>
          ) : (
            /* The busy label is the evidence that the tap landed. Without it a slow
               start left the button looking untapped and disabled underneath, so a
               second tap did nothing either and the walker had no way to tell whether
               the app had heard them. Every other primary in the app says what it is
               doing — "Holding these streets…", "Recording…" — and this one now does. */
            <button className="primary big" disabled={busy} onClick={begin}>
              {busy ? 'Starting your walk…' : 'Start this walk'}
            </button>
          )}
          {/* A preview holds streets too, but nothing has been started, so going back to
              choose again is not a decision worth interrupting.

              Deliberately not `big`: full width and 18px would put it shoulder to
              shoulder with the orange button above and let a walker who meant to finish
              release everything they walked instead. */}
          <button className="secondary" disabled={busy}
                  onClick={() => (started ? setConfirming(true) : discard())}>
            {started ? 'Cancel this walk' : 'Choose a different walk'}
          </button>
        </div>
      )}

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
          be said standing at the crossing rather than remembered afterwards.

          A link rather than an outlined button. It is not a way to finish the walk and
          it is not a way to abandon it — it is a side channel back to us — but as a
          bordered button in the same shape as "Cancel this walk" it sat in the row of
          exits and made a three-way decision out of a one-way one. */}
      {started && !reporting && (
        <button className="link" onClick={() => setReporting(true)}>
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
    </div>
  )
}
