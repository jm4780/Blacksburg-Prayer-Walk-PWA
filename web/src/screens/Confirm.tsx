/**
 * Post-walk confirmation (§14).
 *
 * One question — "Did you complete the route as shown?" — and three answers:
 *
 *   Yes, mark it complete    the plan is the record
 *   Review and edit          drop streets you skipped, add nearby ones you walked
 *                            instead, in one pass; the adjusted distance and street
 *                            count update as you go
 *   I didn't complete it     nothing is recorded, the streets you were holding go back
 *
 * The three answers are a selection, not three submits. Choosing one decides which
 * panel opens beneath; nothing is recorded until the one button that says Submit is
 * pressed, and that button is the only thing on the screen dressed as a decision.
 *
 * Editing is street selection, never freehand drawing. A drawn line would have to be
 * matched back onto the street network, and every match would be a silent guess about
 * what somebody actually prayed for.
 *
 * Whatever is reported, the original planned route is untouched in the record.
 */
import { useEffect, useMemo, useState } from 'react'
import { ApiError, api, isOffline } from '../api'
import FeedbackForm from '../components/FeedbackForm'
import MapView, { type SegmentFeature } from '../components/MapView'
import type { ProgressMap, Walk } from '../types'
import type { Nav } from '../App'

type Outcome = 'AS_PLANNED' | 'EDITED' | 'DID_NOT_COMPLETE'

const OUTCOMES: Outcome[] = ['AS_PLANNED', 'EDITED', 'DID_NOT_COMPLETE']

/**
 * THE ANSWER IN PROGRESS, KEPT ACROSS A RELOAD.
 *
 * A phone reloads this page for reasons nobody chose — the tab was evicted while the
 * walker was reading a text message, a thumb caught the refresh gesture. Before this,
 * that threw away the whole edit: the answer, the note, and every one of the twenty
 * streets somebody had just tapped through. The walk survived; the work did not.
 *
 * What is kept is deliberately the smallest thing that saves that work, and nothing
 * else: the three-way answer, the ids of the streets ticked, and the note as typed.
 * No name, no email, no coordinates, no addresses, no token — those belong to the
 * server, and this is an unlocked phone that gets left on kitchen tables.
 *
 * `sessionStorage`, not `localStorage`: a reload keeps it, closing the tab does not.
 * Keyed by walk id so a later walk can never inherit an earlier one's selection, and
 * dropped the moment the walk is recorded — or the moment we find it already recorded
 * — so a finished walk can never resurrect a stale draft.
 */
interface Draft { outcome: Outcome; picked: string[]; note: string }

const draftKey = (walkId: string) => `bpw.confirm.${walkId}`

function readDraft(walkId: string): Draft | null {
  try {
    const raw = sessionStorage.getItem(draftKey(walkId))
    if (!raw) return null
    const d = JSON.parse(raw)
    // Anything we did not write ourselves is discarded rather than trusted.
    if (!OUTCOMES.includes(d?.outcome)) return null
    return {
      outcome: d.outcome,
      picked: Array.isArray(d.picked)
        ? d.picked.filter((s: unknown): s is string => typeof s === 'string')
        : [],
      note: typeof d.note === 'string' ? d.note : '',
    }
  } catch { return null }
}

function writeDraft(walkId: string, d: Draft) {
  try { sessionStorage.setItem(draftKey(walkId), JSON.stringify(d)) }
  catch { /* private browsing, or a full quota: the draft simply is not kept */ }
}

function clearDraft(walkId: string) {
  try { sessionStorage.removeItem(draftKey(walkId)) } catch { /* nothing to clear */ }
}

/** A walk in one of these states is finished with. It must not be asked about again. */
const RESOLVED = ['COMPLETED', 'DISCARDED']

export default function Confirm({ nav, walkId, onDone }: {
  nav: Nav; walkId: string; onDone: () => void
}) {
  const [walk, setWalk] = useState<Walk | null>(null)
  const [base, setBase] = useState<ProgressMap | null>(null)
  /**
   * THE ANSWER STARTS AT "YES", AND THE WALKER CAN SEE THAT IT DOES.
   *
   * This screen used to open with nothing chosen, which meant somebody who had just
   * walked for forty-five minutes arrived at three grey boxes, empty space, and no
   * button to press at all. The one answer that is right most of the time is "yes,
   * I walked what you showed me", so that is where the screen starts, and it arrives
   * with a live Submit under it.
   *
   * This is a default on an attestation — a statement that somebody actually prayed
   * for these streets — so it is only allowed to exist because it is fully disclosed.
   * Everything that answer commits to is on screen without a tap: the route drawn, the
   * minutes, the miles and the households restated, and a plain sentence saying what
   * Submit will record. The other two answers sit directly above it, selected-looking
   * only when selected, one tap away. A default a walker can read and change is a
   * kindness; a default that submits something they never read would be us putting
   * words in their mouth, and no amount of convenience buys that.
   */
  const [outcome, setOutcome] = useState<Outcome>('AS_PLANNED')
  const [picked, setPicked] = useState<Set<string>>(new Set())
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState<any | null>(null)

  useEffect(() => {
    /*
     * EVERYTHING RESETS WHEN THE WALK ID CHANGES, AND NOTHING LATE MAY WRITE.
     *
     * Without this the screen kept the previous walk's answer, its ticked streets and
     * its note while the new walk loaded — and the draft effect below then wrote walk
     * A's selection into storage under walk B's key. A reviewer opened
     * `#/confirm/<B>` and found "Review and edit" already on, 34 streets ticked, 31 of
     * them belonging to walk A, and a live Submit under them. The server takes the
     * segment ids it is given, so pressing it would have recorded streets from a walk
     * that was not this one.
     *
     * The same shape of bug was fixed on the walk screen and this screen did not get
     * it. `live` closes the other half: a response for the walk we have navigated away
     * from must not land on top of the one we navigated to.
     */
    let live = true
    setWalk(null); setError(null); setDone(null)
    setOutcome('AS_PLANNED'); setPicked(new Set()); setNote('')

    api.walk(walkId).then((w) => {
      if (!live) return
      setWalk(w)
      if (RESOLVED.includes(w.status)) {
        // Already recorded, or cancelled. There is no answer to keep, and any draft
        // sitting in storage is from before that happened.
        clearDraft(walkId)
        return
      }
      const draft = readDraft(walkId)
      // "Review and edit" starts from the plan, so the common edit — dropping the
      // last street because it started raining — is two taps, not forty. A draft, if
      // there is one, is where the walker had already got to.
      setPicked(new Set(draft?.picked ?? w.planned_required_ids ?? []))
      if (draft) { setOutcome(draft.outcome); setNote(draft.note) }
    }).catch((e) => { if (live) setError(e.message) })
    api.progressMap().then((m) => { if (live) setBase(m) }).catch(() => { if (live) setBase(null) })
    return () => { live = false }
  }, [walkId])

  // Written on every change rather than on unload: a tab that is killed outright, or a
  // phone that goes to sleep and never comes back, never gets an unload event.
  useEffect(() => {
    if (!walk || RESOLVED.includes(walk.status) || done) return
    // The loaded walk must BE the walk in the URL. This is the guard that stops one
    // walk's selection being saved under another walk's key; the reset above stops it
    // being shown, and this stops it being written.
    if (walk.id !== walkId) return
    writeDraft(walkId, { outcome, picked: [...picked], note })
  }, [walkId, walk, done, outcome, picked, note])

  const planned = useMemo(
    () => new Set(walk?.planned_required_ids ?? []), [walk])

  function toggle(id: string) {
    setPicked((prev) => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }

  // Live preview of what is being reported, computed from what the server already told
  // us about this walk plus per-street lengths from the map payload.
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
      clearDraft(walkId)
      setDone(r)
      onDone()
    } catch (e: any) {
      // 409 means the walk stopped being open to record while this screen sat there —
      // a second phone, another tab, or the server's own guard against recording the
      // same walk twice. Nothing of ours was written, so the honest thing is to go and
      // find out what the walk actually says and show that instead of the question.
      if (e instanceof ApiError && e.status === 409) {
        // The server writes these sentences for walkers and there is more than one of
        // them — "already recorded" and "never started" are different facts. Flattening
        // every 409 into the first told somebody who had not started their walk that it
        // was already recorded, which is not true and not actionable.
        setError(e.message)
        api.walk(walkId).then((w) => {
          setWalk(w)
          // Only once the walk itself confirms it is finished with — a draft is the
          // walker's work, and a refusal we have not yet understood is no reason to
          // throw it away.
          if (RESOLVED.includes(w.status)) clearDraft(walkId)
        }).catch(() => { /* the message stands alone */ })
      } else if (isOffline(e)) {
        // The draft is untouched, so "try again" is a real instruction here.
        setError(`${e.message} Your answer is kept on this phone in the meantime.`)
      } else setError(e.message)
    }
    finally { setBusy(false) }
  }

  if (error && !walk) return <div className="screen"><p className="error">{error}</p></div>
  // `walk.id !== walkId` is the frame between a hash change and the fetch landing. It
  // is up to fifteen seconds wide on a bad link, and it used to render the previous
  // walk in full, with a live Submit.
  if (!walk || walk.id !== walkId) {
    return <div className="screen"><p className="muted">Loading…</p></div>
  }

  if (done) {
    // What the server recorded, in the server's own numbers.
    //
    // `miles_credited` is the length of the streets themselves. `final_distance_miles`
    // is the whole walk, including getting to the first street and home from the last.
    // The second is always the bigger one, and this screen used to promise the bigger
    // one and then report the smaller one with no explanation — same walk, two numbers,
    // and a walker with no way to tell which was a mistake.
    const walked = Number(done.final_distance_miles ?? 0)
    const credited = Number(done.miles_credited ?? 0)
    // Two decimals, the precision every other mileage in this product is quoted at.
    // The server's own three — "1.945 miles" — is a machine talking.
    const mi = (n: number) => n.toFixed(2)
    return (
      <div className="screen narrow">
        <h1>{done.outcome === 'DID_NOT_COMPLETE' ? 'No problem' : 'Thank you'}</h1>
        <p className="lede">
          {done.outcome === 'DID_NOT_COMPLETE'
            ? 'Nothing was recorded, and the streets you were holding are free for '
              + 'someone else.'
            : done.segments_newly_recorded > 0
              ? `${mi(credited)} miles of streets are now marked as prayed for.`
              : 'This walk was already recorded — nothing was counted twice.'}
        </p>
        {/* Only when the two are actually different once rounded — a sentence
            explaining the gap between 1.95 and 1.95 is worse than no sentence. */}
        {done.outcome !== 'DID_NOT_COMPLETE' && walked > credited
          && mi(walked) !== mi(credited) && (
          <p className="fine">
            You walked {mi(walked)} miles in all. The difference is getting to the streets
            and back again — that counts toward miles walked, not toward the streets
            themselves.
          </p>
        )}
        {done.campus_credited_segments > 0 && (
          <p className="fine">
            {done.campus_credited_segments} streets on campus counted too, because the
            walkway you took runs alongside them.
          </p>
        )}
        {(done.manual_additions > 0 || done.manual_removals > 0) &&
          done.outcome === 'EDITED' && (
          <p className="fine">
            You added {done.manual_additions} and skipped {done.manual_removals}. We
            kept your original route as well.
          </p>
        )}
        <FeedbackForm walkId={walkId} from="AFTER_SUBMISSION" />
        <button className="primary big" onClick={() => nav('/')}>Back to home</button>
      </div>
    )
  }

  /**
   * A WALK THAT IS FINISHED WITH IS NOT ASKED ABOUT AGAIN.
   *
   * Reloading this page landed straight back on the question, whatever the walk's
   * state, so a walk that had already been recorded could be answered a second time —
   * "I didn't complete it" on a completed walk rolled the town's mileage back while
   * leaving every street marked as prayed for. The server refuses this now; the screen
   * must not offer it in the first place. What is left is what was recorded, and the
   * way home.
   */
  if (RESOLVED.includes(walk.status)) {
    const cancelled = walk.status === 'DISCARDED'
    const when = walk.resolved_at
      ? new Date(walk.resolved_at).toLocaleString(undefined,
          { dateStyle: 'long', timeStyle: 'short' })
      : null
    return (
      <div className="screen narrow">
        <h1>{cancelled ? 'This walk was cancelled' : 'This walk is already recorded'}</h1>
        <p className="lede">
          {cancelled
            ? 'Nothing was recorded for it, and the streets it was holding went back '
              + 'for someone else to walk.'
            : walk.outcome === 'DID_NOT_COMPLETE'
              ? 'You reported that you did not complete it, so nothing was recorded '
                + 'and the streets you were holding went back for someone else.'
              : walk.outcome === 'EDITED'
                ? 'You reported it with changes, and the streets you picked are marked '
                  + 'as prayed for.'
                : `All ${walk.required_segment_count} streets of this route are marked `
                  + 'as prayed for.'}
        </p>
        {when && <p className="fine">Recorded {when}. It cannot be sent again.</p>}
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
          selection. Assistive tech announces which of the three is selected — the
          first one is, from the moment the screen opens — and the one thing that
          submits is the one button that says Submit. `.choice.on` already marks the
          selection visually. */}
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
              part that matters — they are what is being signed for.

              180px, not 300. This is the screen somebody reaches having just walked
              the route it is drawing — they do not need to study it, they need to
              recognise it — and at 300px it pushed Submit some 400px below the fold on
              a phone, so the way out of the screen was invisible on arrival. The
              cartography is untouched; only the height. */}
          {walk.geometry && (
            <MapView route={walk.geometry} height={180} context="recording"
                     ariaLabel="The route you planned" />
          )}
          {/* "Yes, mark it complete" was asking the walker to affirm a distance and a
              household count they had last seen on the previous screen — and it is now
              the answer the screen opens on, so every word of it has to be here to be
              read. The walk restates itself, in the same words the active-walk screen
              used, and the sentence under it says plainly what pressing Submit will
              record. Straight off the `walk` already loaded — nothing new is fetched
              to say it. */}
          <p className="mission-line">
            About {walk.estimated_minutes} minutes · {walk.distance_miles} miles
            {walk.households
              ? ` · approximately ${walk.households.toLocaleString()} households`
              : ''}
          </p>
          {/* This sentence used to read "records all 14 streets — 2.42 miles — as
              prayed for", and then the receipt said 2.294 miles had been recorded. Both
              numbers were real and neither was wrong: 2.42 is how far the walker walks,
              door to door, and 2.294 is how much street the town can now count. The
              screen was quietly swapping one for the other, so it said the thing that
              is not true — that the whole 2.42 is recorded as prayed for. The promise
              is now made in streets, which is exactly what Submit records, and the
              miles are described as what they are. */}
          <p className="fine">
            Submitting marks all {walk.required_segment_count} streets of this route as
            prayed for, exactly as planned. The {walk.distance_miles} miles is the whole
            walk, including getting there and back; the streets themselves come to a
            little less, and that is what the town’s total goes up by.
          </p>
        </div>
      )}

      {outcome === 'EDITED' && (
        <div className="card">
          <p className="muted">
            Tap a street to add or remove it. Your planned route is selected to start
            with; a street you take off it turns into a dashed grey line. Pinch to zoom
            out if you walked somewhere further off.
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
          {/* TWO SWATCHES, BECAUSE THE MAP PAINTS TWO COLOURS.
              This legend had three: white for counting, #4F5458 for "Planned, skipped",
              and #6E7676 for "Not yet prayed for". But `prayerLayers('editing')` paints
              a dropped street and an unwalked one in the same INK.remaining #4F5458 —
              they differ by a dash, not a hue — and #6E7676 is not on that map at all.
              So the legend claimed a distinction the map does not draw, in a colour the
              map does not use. Counting and not counting is the whole of what these
              colours mean, and two swatches is the vocabulary the home screen's legend
              already uses. The dash is real and is named in the sentence above, where
              it belongs: it is a thing you do, not a third state. */}
          <div className="legend">
            <span><i className="picked" /> Counting</span>
            <span><i className="dropped" /> Not counting</span>
          </div>
          <p className="mission-line">
            {adjusted.count} streets · about {adjusted.miles.toFixed(2)} miles of street
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

      <label>
        Anything you would like to note? (optional)
        <textarea value={note} maxLength={2000}
                  onChange={(e) => setNote(e.target.value)} rows={3} />
      </label>
      {error && <p className="error" role="alert">{error}</p>}
      <button className="primary big"
              disabled={busy || (outcome === 'EDITED' && picked.size === 0)}
              onClick={() => submit(outcome)}>
        {busy ? 'Recording…' : 'Submit'}
      </button>
    </div>
  )
}
