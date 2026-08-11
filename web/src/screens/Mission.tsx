/**
 * The mission screen (Priorities 3, 4, 6, 7, 8).
 *
 * The old flow asked the walker to configure a route: share your location, then pick
 * one of five named sizes, then read six numbers about it. This screen asks one
 * question — how long do you have? — and answers with a specific walk it recommends,
 * described in terms of where it goes and who lives there.
 *
 * Five things are deliberate:
 *
 *   NO LOCATION NEEDED.  The recommendation is town-wide (Priority 5). The app opens,
 *                        you move the slider, you get a real walk. No location, no
 *                        account, nothing asked for until the walker accepts.
 *
 *   ONE WAY FORWARD.     "Walk this" is the only thing on this screen styled as a
 *                        decision. Swapping the recommendation, browsing the other
 *                        walks, and getting directions to the start are all real and
 *                        all kept — as links and a disclosure, because a walker
 *                        standing outside should have to read one button, not five.
 *                        When the identity gate opens it takes the screen: the walk
 *                        cannot be accepted while the question is unanswered, so
 *                        leaving a live orange button behind it offered a decision
 *                        that no longer existed.
 *
 *   NO DEAD ENDS.        Every state that can fail says what to do next, in the same
 *                        furniture: a heading, a sentence a walker can act on, and a
 *                        button. Whatever the server said about itself stays on the
 *                        server, except for the one message it writes to walkers —
 *                        the walk you already have open, which names it.
 *
 *   TIME, NOT SIZE.      A continuous slider from 20 to 90 minutes in 5-minute steps
 *                        (Priority 4). "Quick / Medium / Long" were engine bands
 *                        wearing product clothing.
 *
 *   MISSION WORDS.       "Continue praying through Hethwood — approximately 1,031
 *                        households, about 45 minutes." Not coverage gain, not route
 *                        score, not efficiency (Priority 8). Those decided the walk;
 *                        they are not what the walk is.
 *
 *   GETTING THERE.       A link out to Apple or Google Maps for the *start point*
 *                        only (Priority 6). Never phrased as parking — where somebody
 *                        leaves a car, or whether they have one, is not ours to
 *                        assume.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { api, ApiError, isOffline } from '../api'
import IdentityGate from '../components/IdentityGate'
import MapView from '../components/MapView'
import type { MissionOptions, MissionResponse, ParticipantOut, Walk } from '../types'
import type { Nav } from '../App'

const FALLBACK_OPTIONS: MissionOptions = {
  min_minutes: 20, max_minutes: 90, step_minutes: 5, default_minutes: 45,
  pace_mph: 3.0,
  pace_note: 'Walking times are an estimate.',
}

/**
 * Something went wrong, already translated out of whatever the server said about
 * itself. Nothing constructs one of these from a raw `detail` string unless that
 * string was written to a walker — the only one that is, is the 409 naming the walk
 * they already have open, and the client's own offline sentences.
 *
 * `walk` carries the walk in progress when there is one, because "you already have a
 * walk" is not an answer unless it comes with the way back to it.
 */
type Trouble = { heading: string; message: string; walk: Walk | null }

/** For the load that failed: say which of the two things happened, and only that. */
function loadTrouble(e: unknown): Trouble {
  // The client writes its own status-0 sentences — no signal, too slow, unreadable
  // reply — and each is already true and already addressed to a walker.
  // "No signal" is what App.tsx already calls this, and it is the difference that
  // matters to somebody standing outside: nothing is broken and nothing is lost, the
  // phone simply could not ask. The sentence underneath says which — unreachable, too
  // slow, or an answer we could not read — because the client wrote all three.
  if (isOffline(e)) {
    return { heading: 'No signal', walk: null, message: (e as Error).message }
  }
  // 404 is the slate moving on: the walk that was suggested a minute ago has been
  // taken or has stopped making sense. That is worth saying, because the fix is a
  // fresh recommendation and not patience.
  if (e instanceof ApiError && e.status === 404) {
    return { heading: 'That walk is no longer on offer', walk: null,
             message: 'The town has moved on since it was suggested. '
                    + 'We can find you another one.' }
  }
  return { heading: 'Something went wrong at our end', walk: null,
           message: 'This is not something you did. Try again in a moment.' }
}

export default function Mission({ nav, me, onIdentity, onWalk }: {
  nav: Nav
  me: ParticipantOut | null
  onIdentity: (p: ParticipantOut) => void
  onWalk: (w: Walk | null) => void
}) {
  const [opts, setOpts] = useState<MissionOptions>(FALLBACK_OPTIONS)
  const [minutes, setMinutes] = useState(FALLBACK_OPTIONS.default_minutes)
  const [data, setData] = useState<MissionResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<Trouble | null>(null)
  const [accepting, setAccepting] = useState(false)
  const [needIdentity, setNeedIdentity] = useState(false)
  const [swapping, setSwapping] = useState(false)

  // Guards against a slow request for 35 minutes landing after a fast one for 60 and
  // painting the wrong walk. Only the newest request may write.
  const seq = useRef(0)

  useEffect(() => {
    api.missionOptions().then((o) => { setOpts(o); setMinutes(o.default_minutes) })
      .catch(() => { /* the fallback bounds are the same ones the server ships */ })
  }, [])

  /**
   * `keepError` is for the one caller that reloads *because* something went wrong: the
   * 409 on accept. Clearing the message on the way in wiped the only explanation the
   * walker had, and a different walk then appeared unannounced.
   */
  const load = useCallback(async (mins: number, missionId?: string, keepError = false) => {
    const mine = ++seq.current
    setLoading(true)
    if (!keepError) setError(null)
    try {
      const r = missionId ? await api.mission(missionId, mins) : await api.recommend(mins)
      if (seq.current === mine) setData(r)
    } catch (e: unknown) {
      if (seq.current === mine) setError(loadTrouble(e))
    } finally {
      if (seq.current === mine) { setLoading(false); setSwapping(false) }
    }
  }, [])

  // Debounced: dragging the slider from 20 to 90 must not fire fifteen requests.
  useEffect(() => {
    const t = window.setTimeout(() => { load(minutes) }, 300)
    return () => window.clearTimeout(t)
  }, [minutes, load])

  function accept() {
    if (!data?.mission) return
    if (!me) { setNeedIdentity(true); return }
    doAccept()
  }

  /** The accept itself. Safe to call the instant identity exists, because the token
   *  is written to storage before `onDone` fires — there is no render to wait for. */
  async function doAccept() {
    const m = data?.mission
    if (!m) return
    setAccepting(true); setError(null)
    try {
      const r = await api.acceptMission(m.id, data!.minutes)
      const w = await api.walk(r.walk_id)
      onWalk(w)
      nav(`/walk/${r.walk_id}`)
    } catch (e: unknown) {
      // 409 means the world moved: somebody took these streets, or this walker
      // already has a walk open. Either way the current card is stale — so it is
      // replaced, with the message kept, because the swapped-in walk is the answer to
      // a question the walker never asked and needs the sentence that explains it.
      const conflict = e instanceof ApiError && e.status === 409
      setError(conflict || isOffline(e)
        // Two sentences on this screen are genuinely addressed to walkers: the 409,
        // which names the walk they already have and how far it goes, and the
        // client's own "we could not reach the server". Those are shown as written.
        ? { heading: isOffline(e) ? 'No signal' : 'We could not start that walk',
            walk: null, message: (e as Error).message }
        : { heading: 'We could not start that walk', walk: null,
            message: 'Something went wrong at our end. This is not something you '
                   + 'did. Try again in a moment.' })
      if (conflict) {
        load(minutes, undefined, true)
        // The 409 body carries no walk id, so ask for the walk itself. It arrives
        // after the sentence rather than delaying it: the explanation is useful on
        // its own, and the way back to the walk is what turns it into a way forward.
        api.current()
          .then((w) => { if (w) setError((prev) => (prev ? { ...prev, walk: w } : prev)) })
          .catch(() => { /* no id, no button — the sentence still stands */ })
      }
    } finally { setAccepting(false) }
  }

  /** The gate is a question, not an overlay: it takes the screen until it is answered. */
  useEffect(() => { if (needIdentity) window.scrollTo(0, 0) }, [needIdentity])

  const m = data?.mission ?? null
  const openWalk = error?.walk ?? null

  /**
   * The way back to a walk that is already open. Rendered beside whichever message
   * explained why this one could not start — the same shape /generate uses for the
   * same refusal, except that here the walk's own id is known, so it goes to the walk
   * rather than to the home screen to look for it.
   */
  const resume = openWalk && (
    <button className="secondary"
            onClick={() => { onWalk(openWalk); nav(`/walk/${openWalk.id}`) }}>
      Go to your walk in progress
    </button>
  )

  /*
   * Identity is a question, and a question owns the screen it is asked on. This is
   * what App.tsx already does for every route it guards — the gate is the whole
   * screen, not a card appended below a live one — and it is the only arrangement in
   * which "one primary per state" is true here: the walk cannot be accepted until the
   * question is answered, so "Walk this" is not a thing the walker may still press.
   */
  if (needIdentity) {
    return (
      <div className="screen">
        <IdentityGate
          reason={'Almost there. We ask who you are now because starting this walk '
                  + 'sets these streets aside for you, so nobody else is sent the '
                  + 'same ones.'}
          cta="Save and start"
          onCancel={() => setNeedIdentity(false)}
          onDone={(p) => { setNeedIdentity(false); onIdentity(p); doAccept() }} />
      </div>
    )
  }

  return (
    <div className="screen">
      <h1>Find my next walk</h1>

      {/* ---------------------------------------------------------- the slider */}
      <div className="card timebox">
        <label className="timelabel" htmlFor="minutes">
          How much time do you have?
        </label>
        <output className="timevalue" htmlFor="minutes">{minutes} minutes</output>
        <input
          id="minutes" type="range" className="timeslider"
          min={opts.min_minutes} max={opts.max_minutes} step={opts.step_minutes}
          value={minutes}
          aria-valuetext={`${minutes} minutes`}
          onChange={(e) => setMinutes(Number(e.target.value))} />
        <div className="timeends">
          <span>{opts.min_minutes} min</span>
          <span>{opts.max_minutes} min</span>
        </div>
      </div>

      {/* Only the errors that have no walk to sit beside are reported up here. A
          failed accept belongs against the button that failed — it is at the bottom of
          a card with a map in it, and a message at the top of the screen is simply
          off-screen from where the walker just tapped. See the mission card.

          With no card there is nothing else on the screen at all, so this is not a red
          sentence: it is the same block, in the same words, as "nothing left to
          assign" below — a heading, what happened, and the two ways out. A screen
          whose only content is a failure has to carry its own way forward. */}
      {error && !m && (
        <div className="note stop" role="alert">
          <strong>{error.heading}</strong>
          <p>{error.message}</p>
          <div className="actions">
            {/* Always a fresh recommendation, never a retry of the mission id that
                just failed — if the slate has moved on, asking for the same walk
                again fails the same way. */}
            <button className="primary" onClick={() => load(minutes)}>
              Try again
            </button>
            <button className="secondary" onClick={() => nav('/')}>
              Back to home
            </button>
          </div>
          {resume}
        </div>
      )}

      {loading && !m && <p className="muted">Finding you a walk…</p>}

      {/* `!error` so a failed reload cannot stack a second stop block, and a second
          primary, on top of the one above. */}
      {!error && !loading && data && !data.available && (
        <div className="note stop">
          <strong>Nothing left to assign</strong>
          <p>{data.reason}</p>
          {/* A dead end with no way out of it. The answer is rarely permanent — a
              different length asks a different question of the network, and streets
              held by other walkers come back when those walks end — so the screen
              says what to try instead of stopping. */}
          <p className="fine">
            Try a different length with the slider above, or look again in a moment.
          </p>
          <div className="actions">
            {/* No busy label: this whole block is behind `!loading`, so the moment it
                is tapped the screen is back on "Finding you a walk…". */}
            <button className="primary" onClick={() => load(minutes)}>
              Look again
            </button>
            <button className="secondary" onClick={() => nav('/')}>
              Back to home
            </button>
          </div>
        </div>
      )}

      {/* ------------------------------------------------------- the mission */}
      {m && (
        <div className={loading ? 'card mission stale' : 'card mission'}>
          <h2>{m.title}</h2>
          <p className="mission-line">{m.households_line}</p>
          <p className="mission-line">
            About {m.estimated_minutes} minutes · {m.distance_miles} miles
          </p>

          {/* `briefing` is the map system's setting for a walk being considered: the
              route is the only saturated thing on screen and its streets are named,
              because the walker is about to commit to them — see src/map/style.ts.

              220, not 320. The map is the evidence for a decision, and at 320 it was
              pushing the decision itself 149px below the fold on a phone: the screen
              arrived showing a picture of a walk and no way to take it. Height only —
              the cartography is unchanged. */}
          <MapView route={m.geometry} context="briefing"
                   start={{ lat: m.start.lat, lon: m.start.lon }}
                   height={220}
                   ariaLabel={`Recommended walk: ${m.title}, ${m.distance_miles} miles`} />

          <div className="startbox">
            <div>
              <span className="startlabel">Starts at</span>
              <strong>{m.start.description}</strong>
            </div>
            {m.directions && (
              <div className="dirlinks">
                {/* Directions to the START only. The app stays the source of truth for
                    the route itself — no claim is made that a mapping app preserves it.

                    No `secondary` class on these: `button.secondary` never matched an
                    anchor, so it styled nothing and only made the markup read as two
                    more buttons on a screen that already had too many. `.dirlinks a`
                    is what actually dresses them, and it dresses them as links. */}
                <a href={m.directions.apple}
                   target="_blank" rel="noreferrer">Apple Maps</a>
                <a href={m.directions.google}
                   target="_blank" rel="noreferrer">Google Maps</a>
              </div>
            )}
          </div>
          {/* The paragraph that used to sit here — that the links go to the start,
              that the route stays in the app, that the walk ends where it began —
              came out. It was twenty words of reassurance directly above the only
              decision on the screen, and it was part of why that decision started
              below the fold. The two links say where they go; the map shows a loop. */}

          {/* The accept can fail — 409 when the walk is gone or this walker already
              has one open, or a network error — and until this was here it failed
              silently as far as the walker could see: the button re-enabled itself
              and the explanation was a full map's height above. */}
          {error && (
            <div className="note warn" role="alert">
              <strong>{error.message}</strong>
              {resume}
            </div>
          )}

          <button className="primary big" disabled={accepting || loading}
                  onClick={accept}>
            {accepting ? 'Starting your walk…' : 'Walk this'}
          </button>

          {/* A link, not a button. This is the same offer the "Other walks" disclosure
              below makes — one tap instead of a list — and when it was a full-width
              outlined button under the orange one, the screen asked the walker to
              choose between accepting a walk and rejecting it, in matching furniture.
              Only "Walk this" is a decision here. */}
          {data!.alternatives.length > 0 && (
            <button className="link" disabled={swapping || loading}
                    onClick={() => {
                      setSwapping(true)
                      load(minutes, data!.alternatives[0].id)
                    }}>
              {swapping ? 'Finding another…' : 'Show me a different walk'}
            </button>
          )}
        </div>
      )}

      {/* --------------------------------------------- other ways to choose */}
      {data && data.alternatives.length > 0 && (
        <details className="alts">
          <summary>Other walks about this long ({data.alternatives.length})</summary>
          <ul>
            {data.alternatives.map((a) => (
              <li key={a.id}>
                <button className="altrow" onClick={() => load(minutes, a.id)}>
                  <strong>{a.title}</strong>
                  <span className="muted">
                    about {a.estimated_minutes} min · {a.distance_miles} mi
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </details>
      )}

      {/* Priority 7: preserved, demoted twice over.

          A link, not a button. This screen has one decision on it and "Walk this" is
          it; starting from where you are standing is a different way in, not a rival
          answer to the same question, and as a second full-width control it read as
          one. It stays: it is the only entry to /generate, and without it that screen
          is unreachable.

          The two lines of terms that used to sit under it are gone. /generate asks for
          nothing on the way in — App.tsx gates it, and the screen itself explains what
          the location is for and why, in its own words, before the browser prompt
          appears. Printing those terms here as well spent twenty words warning about a
          cost that is not charged until the walker is standing in front of it. */}
      <div className="secondary-entry">
        <button className="link" onClick={() => nav('/generate')}>
          Find a walk near me instead
        </button>
      </div>

      {/* The server's own note here reads "Distances come from the canonical network;
          pace is assumed, not measured." Both halves are true and neither is a
          sentence anybody outside this repository can use. What it means to a walker
          is that the number is an estimate, so that is what it says. */}
      <p className="fine">Walking times are an estimate.</p>
    </div>
  )
}
