/**
 * Post-walk confirmation (§14).
 *
 * One question — "Did you complete the route as shown?" — and three answers:
 *
 *   Yes, mark it complete    the plan is the record
 *   Review and edit          drop obligations you skipped, add nearby ones you walked
 *                            instead, in one pass; the adjusted distance and
 *                            contribution update as you go
 *   I didn't complete it     nothing is recorded, the holds are released
 *
 * The three answers are a selection, not three submits. Choosing one decides which
 * panel opens beneath; nothing is recorded until the one button that says Submit is
 * pressed, and that button is the only thing on the screen dressed as a decision.
 *
 * Editing is segment selection, never freehand drawing. A drawn line would have to be
 * map-matched back onto the network, and every match would be a silent guess about
 * what somebody actually prayed for.
 *
 * Whatever is reported, the original planned route is untouched in the record.
 */
import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import FeedbackForm from '../components/FeedbackForm'
import MapView, { type SegmentFeature } from '../components/MapView'
import type { ProgressMap, Walk } from '../types'
import type { Nav } from '../App'

type Outcome = 'AS_PLANNED' | 'EDITED' | 'DID_NOT_COMPLETE'

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
    api.walk(walkId).then((w) => {
      setWalk(w)
      // "Review and edit" starts from the plan, so the common edit — dropping the
      // last street because it started raining — is two taps, not forty.
      setPicked(new Set(w.planned_required_ids ?? []))
    }).catch((e) => setError(e.message))
    api.progressMap().then(setBase).catch(() => setBase(null))
  }, [walkId])

  const planned = useMemo(
    () => new Set(walk?.planned_required_ids ?? []), [walk])

  function toggle(id: string) {
    setPicked((prev) => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }

  // Live contribution preview, computed from what the server already told us about
  // this walk plus per-segment lengths from the map payload.
  const lengths = useMemo(() => {
    const m = new Map<string, number>()
    for (const f of base?.features ?? []) {
      let metres = 0
      const c = f.geometry.coordinates
      for (let i = 1; i < c.length; i++) {
        const dx = (c[i][0] - c[i - 1][0]) * 88_800
        const dy = (c[i][1] - c[i - 1][1]) * 111_320
        metres += Math.hypot(dx, dy)
      }
      m.set(f.properties.id, metres / 1609.344)
    }
    return m
  }, [base])

  const adjusted = useMemo(() => {
    let miles = 0
    for (const id of picked) miles += lengths.get(id) ?? 0
    const added = [...picked].filter((id) => !planned.has(id)).length
    const removed = [...planned].filter((id) => !picked.has(id)).length
    return { miles, added, removed, count: picked.size }
  }, [picked, planned, lengths])

  async function submit(chosen: Outcome) {
    setBusy(true); setError(null)
    try {
      const r = await api.complete(
        walkId, chosen,
        chosen === 'EDITED' ? [...picked] : undefined,
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
        <h1>{done.outcome === 'DID_NOT_COMPLETE' ? 'No problem' : 'Thank you'}</h1>
        <p className="lede">
          {done.outcome === 'DID_NOT_COMPLETE'
            ? 'Nothing was recorded, and the streets you were holding are free for '
              + 'someone else.'
            : done.segments_newly_recorded > 0
              ? `${done.miles_credited} miles are now recorded as prayed for.`
              : 'This walk was already recorded — nothing was counted twice.'}
        </p>
        {done.campus_credited_segments > 0 && (
          <p className="fine">
            {done.campus_credited_segments} campus corridors counted from the walkway
            you took alongside them.
          </p>
        )}
        {(done.manual_additions > 0 || done.manual_removals > 0) &&
          done.outcome === 'EDITED' && (
          <p className="fine">
            You added {done.manual_additions} and removed {done.manual_removals}. Your
            original plan is kept alongside the change.
          </p>
        )}
        <FeedbackForm walkId={walkId} from="AFTER_SUBMISSION" />
        <button className="primary big" onClick={() => nav('/')}>Back to home</button>
      </div>
    )
  }

  const selectable: SegmentFeature[] = (base?.features ?? []).map((f) => ({
    id: f.properties.id,
    coordinates: f.geometry.coordinates,
    state: picked.has(f.properties.id)
      ? 'selected'
      : planned.has(f.properties.id)
        ? 'removed'
        : f.properties.done ? 'done' : 'todo',
  }))

  return (
    <div className="screen">
      <h1>Did you complete the route as shown?</h1>

      {/* These three are one answer to one question, not three things to do. They were
          three identical bordered blocks that each read like a button you press to
          finish, so the screen appeared to have four submits — and pressing one of
          them, which only sets `outcome`, looked from outside like a submit that had
          done nothing.

          The same radiogroup treatment FeedbackForm gives its yes/no rows: a group
          labelled by the question above, radios inside it, `aria-checked` carrying the
          selection. Assistive tech now announces "1 of 3, not selected" instead of
          three buttons, and the one thing that submits is the one button that says
          Submit. `.choice.on` already marks the selection visually. */}
      <div className="choices" role="radiogroup"
           aria-label="Did you complete the route as shown?">
        <button type="button" role="radio" aria-checked={outcome === 'AS_PLANNED'}
                className={outcome === 'AS_PLANNED' ? 'choice on' : 'choice'}
                onClick={() => setOutcome('AS_PLANNED')}>
          <strong>Yes, mark it complete</strong>
          <span>{walk.distance_miles} mi · {walk.required_segment_count} streets</span>
        </button>
        <button type="button" role="radio" aria-checked={outcome === 'EDITED'}
                className={outcome === 'EDITED' ? 'choice on' : 'choice'}
                onClick={() => setOutcome('EDITED')}>
          <strong>Review and edit</strong>
          <span>Skip streets you missed, add ones you walked instead</span>
        </button>
        <button type="button" role="radio" aria-checked={outcome === 'DID_NOT_COMPLETE'}
                className={outcome === 'DID_NOT_COMPLETE' ? 'choice on' : 'choice'}
                onClick={() => setOutcome('DID_NOT_COMPLETE')}>
          <strong>I didn’t complete it</strong>
          <span>Nothing is recorded and your streets are released</span>
        </button>
      </div>

      {outcome === 'AS_PLANNED' && (
        <div className="card">
          {/* `recording` is the map system's setting for a walk being confirmed:
              assigned and covered ground shown together, so the difference between the
              plan and the record is visible — see src/map/style.ts.

              Guarded here rather than around the whole panel: a walk with no stored
              geometry used to select this option and produce nothing at all on screen,
              so the numbers below vanished along with the map. The numbers are the
              part that matters — they are what is being signed for. */}
          {walk.geometry && (
            <MapView route={walk.geometry} height={300} context="recording"
                     ariaLabel="The route you planned" />
          )}
          {/* "Yes, mark it complete" was asking the walker to affirm a distance and a
              household count they had last seen on the previous screen. Nobody confirms
              a number from memory; they just press the button. So the walk restates
              itself here, in the same words the active-walk screen used, and the
              sentence under it says plainly what pressing Submit will record. Straight
              off the `walk` already loaded — nothing new is fetched to say it. */}
          <p className="mission-line">
            About {walk.estimated_minutes} minutes · {walk.distance_miles} miles
            {walk.households
              ? ` · approximately ${walk.households.toLocaleString()} households`
              : ''}
          </p>
          <p className="fine">
            Submitting records all {walk.required_segment_count} streets of this route —
            {' '}{walk.distance_miles} miles — as prayed for, exactly as planned.
          </p>
        </div>
      )}

      {outcome === 'EDITED' && (
        <div className="card">
          <p className="muted">
            Tap a street to add or remove it. Your planned route is selected to start
            with. Pinch to zoom out if you walked somewhere further off.
          </p>
          {/* `editing` is the map system's setting for picking streets by thumb: it
              opens at the same close zoom the old `editing` flag asked for, lifts the
              surrounding context so a street you can't see can't be chosen, and carries
              the widest tap target in the system (26px, against the 24px the flag got).
              The flag is gone rather than kept alongside it — a context overrides it
              outright in MapView, so leaving it would only read as if it still did
              something. `fitTo` still frames the walk rather than the whole town: the
              streets the walker might have swapped in are the ones next to where they
              were. */}
          <MapView segments={selectable} height={420} context="editing"
                   fitTo={walk.geometry}
                   onSegmentTap={toggle}
                   ariaLabel="Select the streets you covered" />
          <div className="legend">
            <span><i className="sw picked" /> Counting</span>
            <span><i className="sw dropped" /> Planned, skipped</span>
            <span><i className="sw todo" /> Not yet prayed for</span>
          </div>
          <p className="mission-line">
            {adjusted.count} streets · {adjusted.miles.toFixed(2)} miles
            {adjusted.added > 0 && ` · ${adjusted.added} added`}
            {adjusted.removed > 0 && ` · ${adjusted.removed} skipped`}
          </p>
        </div>
      )}

      {outcome === 'DID_NOT_COMPLETE' && (
        <div className="note warn">
          <strong>Nothing will be recorded</strong>
          <p>
            No streets are marked as prayed for, and the ones held for you are released
            straight away so someone else can walk them. We keep only the walk itself,
            so the route can be looked at if something went wrong.
          </p>
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
          <button className="primary big"
                  disabled={busy || (outcome === 'EDITED' && picked.size === 0)}
                  onClick={() => submit(outcome)}>
            {busy ? 'Recording…'
              : outcome === 'DID_NOT_COMPLETE' ? 'Submit' : 'Submit contribution'}
          </button>
        </>
      )}
    </div>
  )
}
