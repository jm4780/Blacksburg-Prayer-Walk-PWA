/**
 * Pilot feedback (Phase 3.1 §5).
 *
 * Five structured questions and a comment. Deliberately not a survey: the purpose is
 * to make a bad route reproducible, and the reproduction key — network version,
 * engine version, seed, coverage area, band — is attached server-side from the walk
 * itself, so the walker never has to describe where they were.
 *
 * Offered twice: from the active-walk screen (so "this crossing doesn't exist" can be
 * reported standing at the crossing) and after submission. One row per walk either
 * way; the second answer replaces the first.
 */
import { useState } from 'react'
import { api } from '../api'

type YesNo = boolean | null

export default function FeedbackForm({ walkId, from, onDone }: {
  walkId: string
  from: 'ACTIVE_WALK' | 'AFTER_SUBMISSION'
  onDone?: () => void
}) {
  const [rating, setRating] = useState(0)
  const [easy, setEasy] = useState<YesNo>(null)
  const [timeOk, setTimeOk] = useState<YesNo>(null)
  const [asPlanned, setAsPlanned] = useState<YesNo>(null)
  const [bad, setBad] = useState(false)
  const [badDetail, setBadDetail] = useState('')
  const [comment, setComment] = useState('')
  const [busy, setBusy] = useState(false)
  const [sent, setSent] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function submit() {
    setBusy(true); setError(null)
    try {
      await api.feedback(walkId, {
        rating, easy_to_follow: easy, time_felt_accurate: timeOk,
        completed_as_planned: asPlanned, had_bad_connection: bad,
        bad_connection_detail: bad ? badDetail || null : null,
        comment: comment || null, submitted_from: from,
      })
      setSent(true)
      onDone?.()
    } catch (e: any) { setError(e.message) }
    finally { setBusy(false) }
  }

  if (sent) {
    return (
      <div className="note ok">
        <strong>Thank you — that helps</strong>
        <p>
          {bad
            ? 'We have kept everything needed to regenerate this exact route, so the '
              + 'problem can be looked at directly.'
            : 'Your rating is recorded against this route.'}
        </p>
      </div>
    )
  }

  return (
    <div className="card feedback">
      <h2>How was this route?</h2>

      <div className="field">
        <span className="q">Overall</span>
        <div className="stars" role="radiogroup" aria-label="Overall rating">
          {[1, 2, 3, 4, 5].map((n) => (
            <button key={n} type="button" role="radio" aria-checked={rating === n}
                    aria-label={`${n} out of 5`}
                    className={n <= rating ? 'star on' : 'star'}
                    onClick={() => setRating(n)}>★</button>
          ))}
        </div>
      </div>

      <YesNoRow q="Was it easy to follow?" value={easy} onChange={setEasy} />
      <YesNoRow q="Did the estimated time feel about right?" value={timeOk}
                onChange={setTimeOk} />
      <YesNoRow q="Did you walk it as planned?" value={asPlanned}
                onChange={setAsPlanned} />

      <div className="field">
        <label className="check">
          <input type="checkbox" checked={bad}
                 onChange={(e) => setBad(e.target.checked)} />
          <span>
            It sent me somewhere unsafe, inaccessible, or that doesn’t exist
          </span>
        </label>
      </div>
      {bad && (
        <label>
          Where, and what was wrong?
          <textarea rows={3} maxLength={2000} value={badDetail}
                    onChange={(e) => setBadDetail(e.target.value)}
                    placeholder="e.g. the route crossed Prices Fork Rd where there is no crosswalk" />
        </label>
      )}

      <label>
        Anything else? (optional)
        <textarea rows={2} maxLength={2000} value={comment}
                  onChange={(e) => setComment(e.target.value)} />
      </label>

      {error && <p className="error" role="alert">{error}</p>}
      <button className="primary" disabled={busy || rating === 0} onClick={submit}>
        {busy ? 'Sending…' : 'Send feedback'}
      </button>
    </div>
  )
}

function YesNoRow({ q, value, onChange }: {
  q: string; value: YesNo; onChange: (v: YesNo) => void
}) {
  return (
    <div className="field">
      <span className="q">{q}</span>
      <div className="yesno" role="radiogroup" aria-label={q}>
        <button type="button" role="radio" aria-checked={value === true}
                className={value === true ? 'on' : ''}
                onClick={() => onChange(value === true ? null : true)}>Yes</button>
        <button type="button" role="radio" aria-checked={value === false}
                className={value === false ? 'on' : ''}
                onClick={() => onChange(value === false ? null : false)}>No</button>
      </div>
    </div>
  )
}
