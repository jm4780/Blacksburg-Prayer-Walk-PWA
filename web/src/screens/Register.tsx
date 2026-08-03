/**
 * Lightweight identity (§5). First name, last name, email. Nothing else is asked for
 * and nothing else is stored.
 */
import { useState } from 'react'
import { api, setToken } from '../api'
import type { ParticipantOut } from '../types'

export default function Register({ onDone }: { onDone: (p: ParticipantOut) => void }) {
  const [first, setFirst] = useState('')
  const [last, setLast] = useState('')
  const [email, setEmail] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true); setError(null)
    try {
      const p = await api.register(first, last, email)
      setToken(p.token ?? null)
      onDone(p)
    } catch (err: any) {
      setError(err.message ?? 'Could not sign you up.')
    } finally { setBusy(false) }
  }

  return (
    <div className="screen narrow">
      <h1>Blacksburg Prayer Walk</h1>
      <p className="lede">
        Walk a route through Blacksburg and pray for the homes you pass. Tell us who
        you are so your walks count toward the town total.
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
        {error && <p className="error" role="alert">{error}</p>}
        <button className="primary" disabled={busy || !first || !last || !email}>
          {busy ? 'Signing you up…' : 'Start walking'}
        </button>
      </form>
      <p className="fine">
        We store your name and email so that walking on a new phone still finds your
        history. Your browser keeps only an anonymous sign-in token. We never record
        where you are or where you have been — only which streets have been prayed for.
      </p>
    </div>
  )
}
