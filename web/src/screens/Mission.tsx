/**
 * The mission screen (Priorities 3, 4, 6, 7, 8).
 *
 * The old flow asked the walker to configure a route: share your location, then pick
 * one of five named sizes, then read six numbers about it. This screen asks one
 * question — how long do you have? — and answers with a specific walk it recommends,
 * described in terms of where it goes and who lives there.
 *
 * Four things are deliberate:
 *
 *   NO LOCATION NEEDED.  The default recommendation is town-wide (Priority 5). The
 *                        app opens, you move the slider, you get a real walk. Sharing
 *                        a location is one *optional* way to bias the answer, offered
 *                        below as "Find a walk near me" (Priority 7), not a toll gate.
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

  const load = useCallback(async (mins: number, missionId?: string) => {
    const mine = ++seq.current
    setLoading(true); setError(null)
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
      // already has a walk open. Either way the current card is stale.
      if (e instanceof ApiError && e.status === 409) load(minutes)
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

      {error && <p className="error" role="alert">{error}</p>}

      {loading && !m && <p className="muted">Finding you a walk…</p>}

      {!loading && data && !data.available && (
        <div className="note stop">
          <strong>Nothing left to assign</strong>
          <p>{data.reason}</p>
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

          <MapView route={m.geometry}
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
                    the route itself — no claim is made that a mapping app preserves it. */}
                <a className="secondary" href={m.directions.apple}
                   target="_blank" rel="noreferrer">Apple Maps</a>
                <a className="secondary" href={m.directions.google}
                   target="_blank" rel="noreferrer">Google Maps</a>
              </div>
            )}
          </div>
          <p className="fine">
            Directions take you to where the walk begins. The route itself stays here.
            The walk ends where it starts.
          </p>

          <button className="primary big" disabled={accepting || loading}
                  onClick={accept}>
            {accepting ? 'Holding these streets…' : 'Walk this'}
          </button>

          {data!.alternatives.length > 0 && (
            <button className="secondary" disabled={swapping || loading}
                    onClick={() => {
                      setSwapping(true)
                      load(minutes, data!.alternatives[0].id)
                    }}>
              Show me a different walk
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

      {/* Priority 7: preserved, demoted. Starting from where you are standing is a
          real thing people want; it is just not the only way to be given a walk. */}
      <div className="secondary-entry">
        <button className="secondary big" onClick={() => nav('/generate')}>
          Find a walk near me instead
        </button>
        <p className="fine">
          Uses your location once, when you ask, to start the walk from where you are.
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
