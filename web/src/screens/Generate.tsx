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
import MapCanvas, { type MapLine } from '../components/MapCanvas'
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

  const lines: MapLine[] = (base?.features ?? []).map((f) => ({
    id: f.properties.id,
    coords: f.geometry.coordinates,
    className: f.properties.done ? 'ln-done' : 'ln-todo',
  }))

  const selected: Variant | undefined =
    result?.variants.find((v) => v.band === band)

  return (
    <div className="screen">
      <h1>Generate a Prayer Walk</h1>

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
          <p>Tap where you would like to start.</p>
          <MapCanvas lines={lines} marker={start} height={380}
                     ariaLabel="Blacksburg required streets. Tap to choose a start point."
                     onPick={(p) => { setStart(p); run(p.lat, p.lon, 'MAP') }} />
          <button className="secondary" onClick={useMyLocation}>
            Use my location instead
          </button>
        </div>
      )}

      {phase === 'WORKING' && <p className="muted">Finding a route…</p>}

      {phase === 'RESULT' && result && (
        <>
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

          <Opportunity result={result} onRestart={() => setPhase('PICKING')} />

          {result.available_bands.length > 0 && (
            <>
              <SizeSlider variants={result.variants} selected={band}
                          onSelect={setBand} disabled={busy} />

              {selected?.available && (
                <div className="card">
                  <MapCanvas lines={lines} focus={selected.geometry} marker={start}
                             height={320}
                             ariaLabel={`${selected.band} route, ${selected.distance_miles} miles`} />
                  <dl className="facts">
                    <div><dt>Distance</dt><dd>{selected.distance_miles} mi</dd></div>
                    <div><dt>About</dt><dd>{selected.estimated_minutes} min</dd></div>
                    <div><dt>New streets</dt><dd>{selected.new_required_miles} mi</dd></div>
                    <div><dt>Households</dt><dd>~{selected.households?.toLocaleString()}</dd></div>
                  </dl>
                  {selected.campus_credited_miles ? (
                    <p className="fine">
                      {selected.campus_credited_miles} mi of this is a campus corridor
                      you cover by walking the parallel walkway — walking one side counts.
                    </p>
                  ) : null}
                  <button className="primary big" disabled={busy} onClick={preview}>
                    {busy ? 'Holding your route…' : 'Preview this walk'}
                  </button>
                </div>
              )}
            </>
          )}

          <button className="secondary" onClick={() => setPhase('PICKING')}>
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
 */
function Opportunity({ result, onRestart }: {
  result: RouteResponse; onRestart: () => void
}) {
  const worst = result.variants.find((v) => !v.available) ?? null
  const nearest = worst?.nearest_incomplete_miles
    ?? result.variants.find((v) => v.nearest_incomplete_miles != null)?.nearest_incomplete_miles

  const comp = result.component
  // §9: an area with less required mileage than the shortest size is offered as
  // "complete this area", not as a sixth size on the slider.
  const smallArea = comp && comp.complete_area_miles != null

  switch (result.state) {
    case 'ROUTE_AVAILABLE':
      return smallArea ? (
        <div className="note ok">
          <strong>Complete this area</strong>
          <p>
            {comp!.description} has {comp!.required_miles} mi of streets left and is not
            connected to the rest of the network. This walk covers what is here rather
            than a fixed distance.
          </p>
        </div>
      ) : null

    case 'LIMITED_LOCAL_COVERAGE':
      return (
        <div className="note warn">
          <strong>Most of the streets near here have already been prayed for</strong>
          <p>
            We can still put a walk together, but much of it retraces ground that is
            already covered.
          </p>
        </div>
      )

    case 'LONGER_ROUTE_REQUIRED':
      return (
        <div className="note warn">
          <strong>A longer walk is needed from here</strong>
          <p>
            The nearest streets that still need prayer are
            {nearest != null ? ` about ${nearest} miles away` : ' further out'}, so the
            shorter sizes cannot reach them and get back.
          </p>
        </div>
      )

    case 'SELECT_DIFFERENT_START_AREA':
      return (
        <div className="note stop">
          <strong>Try starting somewhere else</strong>
          <p>
            Everything within walking distance of here has been prayed for. The nearest
            area that still needs it is
            {nearest != null ? ` about ${nearest} miles away` : ' some distance away'} —
            better to start closer to it than to walk there and back.
          </p>
          <button className="secondary" onClick={onRestart}>
            Choose a different starting point
          </button>
        </div>
      )

    default:
      return (
        <div className="note stop">
          <strong>No useful route from this point</strong>
          <p>{result.variants[0]?.reason || 'Nothing reachable from here needs prayer right now.'}</p>
          <button className="secondary" onClick={onRestart}>
            Choose a different starting point
          </button>
        </div>
      )
  }
}
