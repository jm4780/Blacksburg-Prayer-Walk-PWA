/**
 * Generate a walk (§6, §8, §9, §10).
 *
 * Three things this screen is careful about:
 *
 *   Location is asked for once, at the moment the walker asks for a route, with the
 *   reason stated before the browser prompt appears. If they decline, the map-start
 *   fallback is not a consolation prize — it is a first-class way to plan a walk from
 *   somewhere you are not yet standing.
 *
 *   The size control offers only what the server computed, and says why a size is
 *   missing rather than hiding it.
 *
 *   When there is nothing good to walk from here, the screen says so plainly and
 *   offers the specific next step the server identified — a longer size, a different
 *   start — instead of padding a route to look busy.
 */
import { useEffect, useState } from 'react'
import { api, requestLocationOnce } from '../api'
import MapView, { type SegmentFeature } from '../components/MapView'
import SizeSlider from '../components/SizeSlider'
import type { ProgressMap, RouteResponse, Variant, Walk } from '../types'
import type { Nav } from '../App'

type Phase = 'ASK' | 'PICKING' | 'WORKING' | 'RESULT'

const LOCATION_EXPLANATION =
  'We use your location once, right now, to find streets near you that have not been ' +
  'prayed for yet. It is not saved, and we do not track you during your walk.'

export default function Generate({ nav, onWalk }: {
  nav: Nav; onWalk: (w: Walk | null) => void
}) {
  const [phase, setPhase] = useState<Phase>('ASK')
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<RouteResponse | null>(null)
  const [band, setBand] = useState<string | null>(null)
  const [start, setStart] = useState<{ lat: number; lon: number } | null>(null)
  const [base, setBase] = useState<ProgressMap | null>(null)
  const [busy, setBusy] = useState(false)

  // The required-street network, used both as map context and as the pick surface.
  useEffect(() => { api.progressMap().then(setBase).catch(() => setBase(null)) }, [])

  async function useMyLocation() {
    setError(null); setPhase('WORKING')
    try {
      const p = await requestLocationOnce()
      setStart(p)
      await run(p.lat, p.lon, 'DEVICE_LOCATION')
    } catch (e: any) {
      setError(e.message)
      setPhase('PICKING')
    }
  }

  async function run(lat: number, lon: number, src: 'DEVICE_LOCATION' | 'MAP') {
    setPhase('WORKING'); setError(null)
    try {
      const r = await api.generate(lat, lon, src)
      setResult(r)
      setBand(r.available_bands.includes('Medium')
        ? 'Medium' : (r.available_bands[0] ?? null))
      setPhase('RESULT')
    } catch (e: any) {
      setError(e.message); setPhase('PICKING')
    }
  }

  async function preview() {
    if (!result || !band) return
    setBusy(true)
    try {
      const w = await api.select(result.request_id, band)
      onWalk(w)
      nav(`/walk/${w.id}`)
    } catch (e: any) {
      setError(e.message)
    } finally { setBusy(false) }
  }

  const lines: SegmentFeature[] = (base?.features ?? []).map((f) => ({
    id: f.properties.id,
    coordinates: f.geometry.coordinates,
    state: f.properties.done ? 'done' : 'todo',
  }))

  const selected: Variant | undefined =
    result?.variants.find((v) => v.band === band)

  // A component with less required mileage than the shortest band cannot offer five
  // meaningful sizes; §9 says replace the control rather than pad the route.
  const isSmallArea = Boolean(result?.component
    && result.component.complete_area_miles != null)

  return (
    <div className="screen">
      <h1>Find a walk near me</h1>
      <p className="lede">
        Start from where you are standing. If you would rather be given a walk without
        sharing a location, <button className="link" onClick={() => nav('/mission')}>
        go back to the recommendation</button>.
      </p>

      {phase === 'ASK' && (
        <div className="card">
          <p className="lede">{LOCATION_EXPLANATION}</p>
          <button className="primary big" onClick={useMyLocation}>
            Use my location
          </button>
          <button className="secondary" onClick={() => setPhase('PICKING')}>
            Choose a starting point on the map instead
          </button>
        </div>
      )}

      {phase === 'PICKING' && (
        <div className="card">
          {error && <p className="error" role="alert">{error}</p>}
          <p>Pan and zoom to where you would like to start, then tap.</p>
          <MapView segments={lines} start={start} height={400}
                   ariaLabel="Blacksburg required streets. Tap to choose a start point."
                   onMapTap={(p) => { setStart(p); run(p.lat, p.lon, 'MAP') }} />
          <button className="secondary" onClick={useMyLocation}>
            Use my location instead
          </button>
        </div>
      )}

      {phase === 'WORKING' && <p className="muted">Finding a route…</p>}

      {phase === 'RESULT' && result && (
        <>
          <Opportunity result={result} />

          {result.available_bands.length > 0 && (
            <>
              {/* §9: a component that cannot support the normal Quick band gets a
                  focused "Complete this area" option INSTEAD of the slider — not a
                  sixth size bolted onto a control whose other five do not apply. */}
              {isSmallArea ? (
                <div className="note ok">
                  <strong>Complete this area</strong>
                  <p>
                    {result.component!.description} is its own area with{' '}
                    {result.component!.required_miles} mi of streets left, and it is
                    not connected to the rest of the network. One walk covers what is
                    here rather than a set distance.
                  </p>
                </div>
              ) : (
                <SizeSlider variants={result.variants} selected={band}
                            onSelect={setBand} disabled={busy} />
              )}

              {selected?.available && (
                <div className="card">
                  <MapView route={selected.geometry} start={start} height={340}
                           ariaLabel={`${selected.band} route, ${selected.distance_miles} miles`} />
                  {/* Priority 8: what the walk is, not how it scored. */}
                  <p className="mission-line">
                    About {selected.estimated_minutes} minutes · {selected.distance_miles} miles
                    {selected.households
                      ? ` · approximately ${selected.households.toLocaleString()} households`
                      : ''}
                  </p>
                  {selected.campus_credited_miles ? (
                    <p className="fine">
                      {selected.campus_credited_miles} mi of this is a campus corridor
                      you cover by walking the parallel walkway — walking one side counts.
                    </p>
                  ) : null}
                  {/* Moved down here from the top of the RESULT block. In this phase
                      the only thing that can fail is this button — `run` sends its own
                      failures back to PICKING — and the message was rendering above a
                      340px map, off the top of the screen from where the walker had
                      just tapped. A hold that did not happen has to say so where the
                      thumb already is. */}
                  {error && (
                    <div className="note warn" role="alert">
                      <strong>{error}</strong>
                      {/* The common case is a walk left in progress: /api/walks/select
                          refuses to start a second one. Point at the way out. */}
                      <button className="secondary" onClick={() => nav('/')}>
                        Go to your walk in progress
                      </button>
                    </div>
                  )}
                  <button className="primary big" disabled={busy} onClick={preview}>
                    {busy ? 'Holding your route…'
                      : isSmallArea ? 'Complete this area' : 'Preview this walk'}
                  </button>
                </div>
              )}
            </>
          )}

          {/* The one way back out of a result, and the only one — Opportunity used to
              render its own "Choose a different starting point" in two of its four
              states, which meant those states showed two buttons doing the identical
              thing while the other two states relied on this one alone. This is the
              button that is always here, so this is the button that stayed.

              It is primary when there is no walk to preview. A start point with
              nothing worth walking from it is still a dead end if the only live
              control on the screen is drawn as an afterthought; when there *is* a
              route, previewing it is the decision and this drops back to secondary. */}
          <button className={selected?.available ? 'secondary' : 'primary big'}
                  onClick={() => setPhase('PICKING')}>
            Start somewhere else
          </button>
        </>
      )}
    </div>
  )
}

/**
 * Late-opportunity response states (§10).
 *
 * Every sentence here is built from what the server measured near this start — the
 * distance to the nearest unwalked street, how much of a route would be new, which
 * longer size reaches work. None of it is derived from a town-wide completion
 * percentage: a town at 40% can have a finished neighbourhood, and a town at 95% can
 * have good walking left one street over.
 *
 * These are statements, not exits. Two of them used to carry their own "Choose a
 * different starting point" button, duplicating the "Start somewhere else" the RESULT
 * phase already renders underneath in every state — the same action, twice, in two
 * wordings. The button belongs to the screen, so it stays with the screen and this
 * says only what the server found.
 */
function Opportunity({ result }: { result: RouteResponse }) {
  const worst = result.variants.find((v) => !v.available) ?? null
  const nearest = worst?.nearest_incomplete_miles
    ?? result.variants.find((v) => v.nearest_incomplete_miles != null)?.nearest_incomplete_miles

  switch (result.state) {
    case 'ROUTE_AVAILABLE':
      // The small-area case is handled by replacing the size control itself, above.
      return null

    case 'LIMITED_LOCAL_COVERAGE':
      return (
        <div className="note warn">
          <strong>There are few unprayed streets near this starting point</strong>
          <p>
            We can still put a walk together, but much of it retraces ground that is
            already covered.
            {nearest != null && ` The nearest unfinished area is approximately
              ${nearest} miles away.`}
          </p>
        </div>
      )

    case 'LONGER_ROUTE_REQUIRED':
      return (
        <div className="note warn">
          <strong>A longer walk is needed from here</strong>
          <p>
            {nearest != null
              ? `The nearest unfinished area is approximately ${nearest} miles away`
              : 'The nearest unfinished area is further out'}, so the shorter sizes
            cannot reach it and get back.
          </p>
        </div>
      )

    case 'SELECT_DIFFERENT_START_AREA':
      return (
        <div className="note stop">
          <strong>Try starting somewhere else</strong>
          <p>
            There are no remaining unprayed streets near this starting point.
            {nearest != null
              ? ` The nearest unfinished area is approximately ${nearest} miles away.`
              : ''}{' '}
            Choose a different starting point or start closer to the nearest
            unfinished area.
          </p>
        </div>
      )

    default:
      return (
        <div className="note stop">
          <strong>No useful route from this point</strong>
          <p>{result.variants[0]?.reason || 'Nothing reachable from here needs prayer right now.'}</p>
        </div>
      )
  }
}
