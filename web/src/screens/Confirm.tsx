/**
 * Post-walk confirmation (§14).
 *
 * Three paths: walked it as planned, walked part of it, walked something different.
 * The second and third are segment selection, never freehand drawing — a drawn line
 * would have to be map-matched back onto the network, and every one of those matches
 * would be a silent guess about what somebody prayed for.
 *
 * Whatever is reported here, the original plan is untouched in the record.
 */
import { useEffect, useState } from 'react'
import { api } from '../api'
import MapCanvas, { type MapLine } from '../components/MapCanvas'
import type { ProgressMap, Walk } from '../types'
import type { Nav } from '../App'

type Outcome = 'AS_PLANNED' | 'PARTIAL' | 'DIFFERENT_ROUTE'

export default function Confirm({ nav, walkId, onDone }: {
  nav: Nav; walkId: string; onDone: () => void
}) {
  const [walk, setWalk] = useState<Walk | null>(null)
  const [base, setBase] = useState<ProgressMap | null>(null)
  const [outcome, setOutcome] = useState<Outcome | null>(null)
  const [picked, setPicked] = useState<Set<string>>(new Set())
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState<any | null>(null)

  useEffect(() => {
    api.walk(walkId).then(setWalk).catch((e) => setError(e.message))
    api.progressMap().then(setBase).catch(() => setBase(null))
  }, [walkId])

  function toggle(id: string) {
    setPicked((prev) => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }

  async function submit() {
    if (!outcome) return
    setBusy(true); setError(null)
    try {
      const r = await api.complete(
        walkId, outcome,
        outcome === 'AS_PLANNED' ? undefined : [...picked],
        note || undefined)
      setDone(r)
      onDone()
    } catch (e: any) { setError(e.message) }
    finally { setBusy(false) }
  }

  if (error && !walk) return <div className="screen"><p className="error">{error}</p></div>
  if (!walk) return <div className="screen"><p className="muted">Loading…</p></div>

  if (done) {
    return (
      <div className="screen narrow">
        <h1>Thank you</h1>
        <p className="lede">
          {done.segments_newly_recorded > 0
            ? `${done.miles_credited} miles are now recorded as prayed for.`
            : 'This walk was already recorded — nothing was counted twice.'}
        </p>
        {done.campus_credited_segments > 0 && (
          <p className="fine">
            {done.campus_credited_segments} campus corridors counted from the walkway
            you took alongside them.
          </p>
        )}
        <button className="primary big" onClick={() => nav('/')}>Back to home</button>
      </div>
    )
  }

  // Selection surface. For PARTIAL that is the walk's own segments; for
  // DIFFERENT_ROUTE it is the whole required network, because they went elsewhere.
  const planned = new Set(walk.directions ? [] : [])
  const selectable: MapLine[] = (base?.features ?? [])
    .filter((f) => outcome === 'DIFFERENT_ROUTE' || planned.size === 0)
    .map((f) => ({
      id: f.properties.id,
      coords: f.geometry.coordinates,
      className: picked.has(f.properties.id)
        ? 'ln-picked' : f.properties.done ? 'ln-done' : 'ln-todo',
      onClick: () => toggle(f.properties.id),
    }))

  return (
    <div className="screen">
      <h1>How did the walk go?</h1>

      <div className="choices">
        <button className={outcome === 'AS_PLANNED' ? 'choice on' : 'choice'}
                onClick={() => setOutcome('AS_PLANNED')}>
          <strong>I walked the route as planned</strong>
          <span>{walk.distance_miles} mi · {walk.required_segment_count} streets</span>
        </button>
        <button className={outcome === 'PARTIAL' ? 'choice on' : 'choice'}
                onClick={() => setOutcome('PARTIAL')}>
          <strong>I walked part of it</strong>
          <span>Pick the streets you covered</span>
        </button>
        <button className={outcome === 'DIFFERENT_ROUTE' ? 'choice on' : 'choice'}
                onClick={() => setOutcome('DIFFERENT_ROUTE')}>
          <strong>I walked somewhere different</strong>
          <span>Pick the streets you covered</span>
        </button>
      </div>

      {outcome === 'AS_PLANNED' && walk.geometry && (
        <div className="card">
          <MapCanvas lines={[]} focus={walk.geometry} height={280}
                     ariaLabel="The route you planned" />
        </div>
      )}

      {(outcome === 'PARTIAL' || outcome === 'DIFFERENT_ROUTE') && (
        <div className="card">
          <p className="muted">
            Tap each street you prayed for. {picked.size} selected.
          </p>
          <MapCanvas lines={selectable} focus={walk.geometry} height={380}
                     ariaLabel="Select the streets you walked" />
          {outcome === 'PARTIAL' && (
            <p className="fine">
              For a partial walk, choose only streets that were part of your plan. If
              you went elsewhere, pick “I walked somewhere different” instead.
            </p>
          )}
        </div>
      )}

      {outcome && (
        <>
          <label>
            Anything you would like to note? (optional)
            <textarea value={note} maxLength={2000}
                      onChange={(e) => setNote(e.target.value)} rows={3} />
          </label>
          {error && <p className="error" role="alert">{error}</p>}
          <button className="primary big" disabled={busy ||
                    (outcome !== 'AS_PLANNED' && picked.size === 0)}
                  onClick={submit}>
            {busy ? 'Recording…' : 'Record this walk'}
          </button>
        </>
      )}
    </div>
  )
}
