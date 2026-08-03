/**
 * Home dashboard (§4).
 *
 * Three numbers, each with the definition available behind a disclosure. The
 * definitions are not decoration: "42% of Blacksburg prayed for" is a claim about a
 * denominator two phases of work went into establishing, and a number that cannot be
 * questioned cannot be trusted.
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

export default function Home({ nav, me, walk }: {
  nav: Nav; me: ParticipantOut; walk: Walk | null
}) {
  const [m, setM] = useState<Metrics | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.metrics().then(setM).catch((e) => setError(e.message))
  }, [walk?.id])

  return (
    <div className="screen">
      <h1>Hello, {me.first_name}</h1>

      {walk && (
        <div className="banner">
          <div>
            <strong>You have a walk in progress</strong>
            <div className="muted">
              {walk.band} · {walk.distance_miles} mi · about {walk.estimated_minutes} min
            </div>
          </div>
          <button className="primary"
                  onClick={() => nav(walk.status === 'ACTIVE'
                    ? `/walk/${walk.id}` : `/walk/${walk.id}`)}>
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
            <button className="primary big" onClick={() => nav('/generate')}>
              Generate a Prayer Walk
            </button>
            <button className="secondary big" onClick={() => nav('/progress')}>
              View Progress Map
            </button>
          </div>

          <p className="fine">
            Network {m.network_version} · {m.required_segments_complete.toLocaleString()} of{' '}
            {m.required_segments_total.toLocaleString()} required segments recorded.
          </p>
        </>
      )}
    </div>
  )
}
