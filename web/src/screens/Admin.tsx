/**
 * Minimal administration (§17).
 *
 * Read-mostly. Notably absent: any way to look up one named participant's routes.
 * §16 forbids tying routes to names, and an admin screen is exactly where that rule
 * would otherwise leak.
 */
import { useEffect, useState } from 'react'
import { api } from '../api'
import type { AdminOverview, ParticipantOut } from '../types'

type Tab = 'overview' | 'network' | 'review' | 'walks' | 'people' | 'holds' | 'deploy' | 'audit'

const TABS: [Tab, string][] = [
  ['overview', 'Overview'], ['network', 'Network'], ['review', 'Review queues'],
  ['walks', 'Walks'], ['people', 'Participants'], ['holds', 'Reservations'],
  ['deploy', 'Deployment'], ['audit', 'Audit log'],
]

export default function Admin({ me }: { me: ParticipantOut }) {
  const [tab, setTab] = useState<Tab>('overview')
  const [data, setData] = useState<any>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setData(null); setError(null)
    const load = {
      overview: api.adminOverview, network: api.adminNetwork,
      review: api.adminReviewQueues, walks: api.adminWalks,
      people: api.adminParticipants, holds: api.adminReservations,
      deploy: api.adminDeployment, audit: api.adminAudit,
    }[tab]
    load().then(setData).catch((e: any) => setError(e.message))
  }, [tab])

  if (!me.is_admin) return <div className="screen"><p>Administrator access required.</p></div>

  return (
    <div className="screen">
      <h1>Administration</h1>
      <div className="tabs">
        {TABS.map(([k, label]) => (
          <button key={k} className={tab === k ? 'on' : ''} onClick={() => setTab(k)}>
            {label}
          </button>
        ))}
      </div>

      {error && <p className="error" role="alert">{error}</p>}
      {!data && !error && <p className="muted">Loading…</p>}

      {data && tab === 'overview' && <Overview d={data as AdminOverview} />}
      {data && tab === 'review' && <Review d={data} />}
      {data && tab === 'deploy' && <Deploy d={data} />}
      {data && !['overview', 'review', 'deploy'].includes(tab) && (
        <pre className="json">{JSON.stringify(data, null, 2)}</pre>
      )}
    </div>
  )
}

function Overview({ d }: { d: AdminOverview }) {
  return (
    <>
      <dl className="facts">
        <div><dt>Prayed for</dt><dd>{d.metrics.percent_prayed_for.value.toFixed(1)}%</dd></div>
        <div><dt>Miles walked</dt><dd>{d.metrics.total_miles_walked.value}</dd></div>
        <div><dt>Households</dt><dd>{d.metrics.estimated_households_prayed_for.value.toLocaleString()}</dd></div>
        <div><dt>Participants</dt><dd>{d.participants}</dd></div>
      </dl>
      <h2>Walks</h2>
      <pre className="json">{JSON.stringify(d.walks_by_status, null, 2)}</pre>
      <h2>Routing components</h2>
      <pre className="json">{JSON.stringify(d.components, null, 2)}</pre>
    </>
  )
}

function Review({ d }: { d: any }) {
  const crc = d.crc_crossings
  return (
    <>
      <h2>Corporate Research Center crossings</h2>
      {crc ? (
        <>
          <p className="muted">{crc.status}</p>
          {crc.if_promoted && <p className="note warn">{crc.if_promoted.finding}</p>}
          <table className="grid">
            <thead>
              <tr><th>Segment</th><th>Class</th><th>m</th><th>Link</th></tr>
            </thead>
            <tbody>
              {crc.rows.map((r: any) => (
                <tr key={r.segment_id}>
                  <td>{r.segment_id}</td>
                  <td>{r.classification}</td>
                  <td>{r.length_m}</td>
                  <td>{r.from_feature} → {r.to_feature}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      ) : <p className="muted">Review artifact not generated.</p>}

      <h2>Segments needing review</h2>
      <pre className="json">{JSON.stringify(d.segments_needing_review, null, 2)}</pre>
    </>
  )
}

function Deploy({ d }: { d: any }) {
  return (
    <>
      <dl className="facts">
        <div><dt>Tier</dt><dd>{d.tier}</dd></div>
        <div><dt>Database</dt><dd>{d.database}</dd></div>
        <div><dt>Token pepper</dt><dd>{d.token_pepper_set ? 'set' : 'NOT SET'}</dd></div>
        <div><dt>Public geometry</dt><dd>{d.public_geometry_enabled ? 'ENABLED' : 'off'}</dd></div>
      </dl>
      {d.warnings.length > 0 && (
        <div className="note warn">
          <strong>Deployment warnings</strong>
          <ul>{d.warnings.map((w: string) => <li key={w}>{w}</li>)}</ul>
        </div>
      )}
      <h2>Licensing gate {d.licensing_gate.gate}</h2>
      <p className="note stop"><strong>{d.licensing_gate.status}</strong></p>
      <p>{d.licensing_gate.summary}</p>
      <h3>Blocks</h3>
      <ul>{d.licensing_gate.blocks.map((x: string) => <li key={x}>{x}</li>)}</ul>
      <h3>Does not block</h3>
      <ul>{d.licensing_gate.does_not_block.map((x: string) => <li key={x}>{x}</li>)}</ul>
    </>
  )
}
