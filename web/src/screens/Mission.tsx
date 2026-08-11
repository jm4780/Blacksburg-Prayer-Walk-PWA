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
 *                        account, nothing asked for until the walker accepts — and,
 *                        since the "Find a walk near me instead" entry point came out,
 *                        nothing on this screen that quietly leads to one either. See
 *                        the note where that button used to be.
 *
 *   ONE WAY FORWARD.     "Walk this" is the only thing on this screen styled as a
 *                        decision. Swapping the recommendation, browsing the other
 *                        walks, and getting directions to the start are all real and
 *                        all kept — as links and a disclosure, because a walker
 *                        standing outside should have to read one button, not five.
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
import { api, ApiError } from '../api'
import IdentityGate from '../components/IdentityGate'
import MapView from '../components/MapView'
import type { MissionOptions, MissionResponse, ParticipantOut, Walk } from '../types'
import type { Nav } from '../App'

const FALLBACK_OPTIONS: MissionOptions = {
  min_minutes: 20, max_minutes: 90, step_minutes: 5, default_minutes: 45,
  pace_mph: 3.0,
  pace_note: 'Walking time is an estimate.',
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
  const [error, setError] = useState<string | null>(null)
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
    } catch (e: any) {
      if (seq.current === mine) setError(e.message)
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
    } catch (e: any) {
      setError(e.message)
      // 409 means the world moved: somebody took these streets, or this walker
      // already has a walk open. Either way the current card is stale — so it is
      // replaced, with the message kept, because the swapped-in walk is the answer to
      // a question the walker never asked and needs the sentence that explains it.
      if (e instanceof ApiError && e.status === 409) load(minutes, undefined, true)
    } finally { setAccepting(false) }
  }

  const m = data?.mission ?? null

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
          a card with a 320px map in it, and a message at the top of the screen is
          simply off-screen from where the walker just tapped. See the mission card. */}
      {error && !m && <p className="error" role="alert">{error}</p>}

      {loading && !m && <p className="muted">Finding you a walk…</p>}

      {!loading && data && !data.available && (
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
              because the walker is about to commit to them — see src/map/style.ts. */}
          <MapView route={m.geometry} context="briefing"
                   start={{ lat: m.start.lat, lon: m.start.lon }}
                   height={320}
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
          <p className="fine">
            Directions take you to where the walk begins. The route itself stays here.
            The walk ends where it starts.
          </p>

          {/* The accept can fail — 409 when somebody else took these streets, or a
              network error — and until this was here it failed silently as far as the
              walker could see: the button re-enabled itself and the explanation was a
              full map's height above. */}
          {error && <p className="error" role="alert">{error}</p>}

          <button className="primary big" disabled={accepting || loading}
                  onClick={accept}>
            {accepting ? 'Holding these streets…' : 'Walk this'}
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
          one.

          And it says what it costs. /generate is identity-gated — App.tsx puts an
          IdentityGate in front of it for anyone without a token, because generating
          from a device location records a route request against a person. This screen
          promises no location and no account, so the one route off it that asks for
          both has to say so before it is tapped, not after. */}
      <div className="secondary-entry">
        <button className="link" onClick={() => nav('/generate')}>
          Find a walk near me instead
        </button>
        <p className="fine">
          Uses your location once, when you ask, to start the walk from where you are,
          and asks who you are first.
        </p>
      </div>

      {needIdentity && (
        <IdentityGate
          reason={'Almost there. We ask who you are now because accepting a walk '
                  + 'holds these streets for you so nobody else is sent the same ones.'}
          cta="Save and start"
          onCancel={() => setNeedIdentity(false)}
          onDone={(p) => { setNeedIdentity(false); onIdentity(p); doAccept() }} />
      )}

      <p className="fine">{opts.pace_note}</p>
    </div>
  )
}
