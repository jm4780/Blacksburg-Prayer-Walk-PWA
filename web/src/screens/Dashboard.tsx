/**
 * The landing screen (Priority 2).
 *
 * This is what somebody sees when they open the app, signed in or not. It answers
 * "what is this and how is it going?" before it asks anything of them. Three numbers,
 * the shared progress, and one clear way in.
 *
 * The three numbers each carry their own definition behind a disclosure. That is not
 * decoration: "42% of Blacksburg prayed for" is a claim about a denominator two phases
 * of work went into establishing, and a number that cannot be questioned cannot be
 * trusted.
 *
 * Nothing here requires an identity. A visitor sees the same figures a walker does,
 * because the point of the number is that it belongs to the town.
 */
import { useEffect, useState } from 'react'
import { api } from '../api'
import type { Metrics, ParticipantOut, Walk } from '../types'
import type { Nav } from '../App'

function Metric({ label, value, unit, definition, extra }: {
  label: string; value: string; unit?: string; definition: string; extra?: string
}) {
  const [open, setOpen] = useState(false)
  return (
    <div className="metric">
      <div className="metric-value">{value}{unit && <span className="unit">{unit}</span>}</div>
      <div className="metric-label">{label}</div>
      {extra && <div className="metric-extra">{extra}</div>}
      <button className="link" aria-expanded={open} onClick={() => setOpen(!open)}>
        {open ? 'Hide' : 'What does this mean?'}
      </button>
      {open && <p className="definition">{definition}</p>}
    </div>
  )
}

export default function Dashboard({ nav, me, walk }: {
  nav: Nav; me: ParticipantOut | null; walk: Walk | null
}) {
  const [m, setM] = useState<Metrics | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.metrics().then(setM).catch((e) => setError(e.message))
  }, [walk?.id])

  return (
    <div className="screen">
      <h1>{me ? `Hello, ${me.first_name}` : 'Blacksburg Prayer Walk'}</h1>
      <p className="lede">
        {me
          ? 'Here is how far the town has come.'
          : 'Walk a route through Blacksburg and pray for the homes you pass. '
            + 'Here is how far the town has come.'}
      </p>

      {walk && (
        <div className="banner">
          <div>
            <strong>You have a walk in progress</strong>
            <div className="muted">
              About {walk.estimated_minutes} min · {walk.distance_miles} mi
            </div>
          </div>
          <button className="primary" onClick={() => nav(`/walk/${walk.id}`)}>
            Resume
          </button>
        </div>
      )}

      {error && <p className="error" role="alert">{error}</p>}

      {m && (
        <>
          <section className="metrics">
            <Metric
              label="of Blacksburg prayed for"
              value={m.percent_prayed_for.value.toFixed(1)} unit="%"
              extra={`${m.percent_prayed_for.numerator_miles} of ${m.percent_prayed_for.denominator_miles} required miles`}
              definition={m.percent_prayed_for.definition} />
            <Metric
              label="total miles walked"
              value={m.total_miles_walked.value.toLocaleString()}
              extra={`${m.completed_walks} walks by ${m.distinct_walkers} people`}
              definition={m.total_miles_walked.definition} />
            <Metric
              label="estimated households prayed for"
              value={m.estimated_households_prayed_for.value.toLocaleString()}
              extra={`of ${m.estimated_households_prayed_for.total.toLocaleString()} estimated · ${m.estimated_households_prayed_for.held_for_review.toLocaleString()} held for review`}
              definition={m.estimated_households_prayed_for.definition} />
          </section>

          <div className="actions">
            {/* One primary way in. It leads to a recommendation, not a form. */}
            <button className="primary big" onClick={() => nav('/mission')}>
              Find my next walk
            </button>
            <button className="secondary big" onClick={() => nav('/progress')}>
              See the progress map
            </button>
          </div>

          {!me && (
            <p className="fine">
              You can look around without signing in. We ask who you are when you
              accept a walk, so it counts toward the total and the streets are held
              for you.
            </p>
          )}

          <p className="fine">
            Network {m.network_version} · {m.required_segments_complete.toLocaleString()} of{' '}
            {m.required_segments_total.toLocaleString()} required segments recorded.
          </p>
        </>
      )}
    </div>
  )
}
