/**
 * Identity, asked for at the moment it starts to mean something (Priority 2).
 *
 * This was the first screen of the app. It is now a gate that appears when somebody
 * accepts a walk, because that is the first action with a consequence for anyone else:
 * a walk is recorded against a person, and the streets in it are held so two people do
 * not pray the same block on the same morning.
 *
 * Everything before that — the shared progress, the recommendation, the map, the route
 * itself — works without knowing who is looking.
 *
 * Still first name, last name, email (§5). Nothing else is asked for or stored, and the
 * browser keeps only an opaque token.
 */
import { useState } from 'react'
import { api, setToken } from '../api'
import type { ParticipantOut } from '../types'

interface Props {
  onDone: (p: ParticipantOut) => void
  onCancel?: () => void
  /** Why we are asking, phrased for the thing the walker just tried to do. */
  reason?: string
  cta?: string
}

export default function IdentityGate({ onDone, onCancel, reason, cta }: Props) {
  const [first, setFirst] = useState('')
  const [last, setLast] = useState('')
  const [email, setEmail] = useState('')
  const [invite, setInvite] = useState('')
  const [needsInvite, setNeedsInvite] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true); setError(null)
    try {
      const p = await api.register(first, last, email, invite || undefined)
      setToken(p.token ?? null)
      onDone(p)
    } catch (err: any) {
      // The deployment decides whether an invite is needed (BPW_ACCESS_MODE=invite).
      // The form asks for one only once the server has said it wants one.
      if (err?.status === 403) setNeedsInvite(true)
      setError(err.message ?? 'Could not sign you up.')
    } finally { setBusy(false) }
  }

  return (
    <div className="card identity">
      <h2>Who is walking?</h2>
      <p className="lede">
        {reason ?? 'Tell us who you are so this walk counts toward the town total.'}
      </p>
      <form onSubmit={submit}>
        <label>
          First name
          <input value={first} onChange={(e) => setFirst(e.target.value)}
                 required autoComplete="given-name" />
        </label>
        <label>
          Last name
          <input value={last} onChange={(e) => setLast(e.target.value)}
                 required autoComplete="family-name" />
        </label>
        <label>
          Email
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)}
                 required autoComplete="email" inputMode="email" />
        </label>
        {needsInvite && (
          <label>
            Invite code
            <input value={invite} onChange={(e) => setInvite(e.target.value)}
                   autoComplete="off" />
          </label>
        )}
        {error && <p className="error" role="alert">{error}</p>}
        <button className="primary big" disabled={busy || !first || !last || !email}>
          {busy ? 'Just a moment…' : (cta ?? 'Start walking')}
        </button>
        {onCancel && (
          <button type="button" className="secondary" onClick={onCancel}>
            Not yet
          </button>
        )}
      </form>
      <p className="fine">
        We store your name and email so that walking on a new phone still finds your
        history. Your browser keeps only an anonymous sign-in token. We never record
        where you are or where you have been — only which streets have been prayed for.
      </p>
    </div>
  )
}
