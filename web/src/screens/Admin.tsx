/**
 * Administration (§17, Phase 3.1 §6 and §7).
 *
 * Phase 3.1 §7 asks whether each capability is *understandable and usable*, not merely
 * present. The honest answer for the Phase 3 version was: no. Nine of the eleven were
 * a `<pre>` of raw JSON, which is a capability an engineer can use and an
 * administrator cannot. Every screen below that drives a decision now renders as a
 * table with the numbers a person needs to act on. Two remain raw JSON on purpose —
 * see ADMIN_CAPABILITY_NOTES at the bottom of this file, which is the audit §7 asks
 * for and is deliberately kept in the code rather than only in a document.
 *
 * Still deliberately absent: any way to read one named participant's routes.
 */
import { useEffect, useState } from 'react'
import { api } from '../api'
import type { ParticipantOut } from '../types'

type Tab = 'pilot' | 'walks' | 'edits' | 'feedback' | 'reservations'
  | 'duplicates' | 'failures' | 'connectors' | 'network' | 'deploy' | 'audit'

const TABS: [Tab, string][] = [
  ['pilot', 'Pilot'], ['walks', 'Walks'], ['edits', 'Manual edits'],
  ['feedback', 'Feedback'], ['reservations', 'Reservations'],
  ['duplicates', 'Duplicates'], ['failures', 'Route failures'],
  ['connectors', 'Connectors'], ['network', 'Network'],
  ['deploy', 'Deployment'], ['audit', 'Audit log'],
]

export default function Admin({ me }: { me: ParticipantOut }) {
  const [tab, setTab] = useState<Tab>('pilot')
  // The payload is stored WITH the tab it belongs to. Keeping them in separate state
  // meant React rendered the new tab against the previous tab's data for one frame —
  // clearing it inside the effect is too late — so switching to Connectors handed the
  // pilot summary to a component expecting `rows` and white-screened the whole admin
  // app. Pairing them makes the mismatch unrepresentable.
  const [loaded, setLoaded] = useState<{ tab: Tab; payload: any } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const data = loaded && loaded.tab === tab ? loaded.payload : null

  useEffect(() => {
    let cancelled = false
    setLoaded(null); setError(null)
    const load = {
      pilot: api.adminPilot, walks: api.adminWalks, edits: api.adminWalkEdits,
      feedback: api.adminFeedback, reservations: api.adminReservations,
      duplicates: api.adminDuplicates, failures: api.adminRouteFailures,
      connectors: api.adminConnectors, network: api.adminNetwork,
      deploy: api.adminDeployment, audit: api.adminAudit,
    }[tab]
    load()
      .then((payload) => { if (!cancelled) setLoaded({ tab, payload }) })
      .catch((e: any) => { if (!cancelled) setError(e.message) })
    // A slow tab whose response lands after the user has moved on must not overwrite
    // what they are looking at now.
    return () => { cancelled = true }
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

      {data && tab === 'pilot' && <Pilot d={data} />}
      {data && tab === 'walks' && <Walks rows={data} />}
      {data && tab === 'edits' && <Edits d={data} />}
      {data && tab === 'feedback' && <Feedback rows={data} />}
      {data && tab === 'reservations' && <Reservations rows={data} />}
      {data && tab === 'duplicates' && <Duplicates d={data} />}
      {data && tab === 'failures' && <Failures d={data} />}
      {data && tab === 'connectors' && <Connectors d={data} />}
      {data && tab === 'network' && <Network d={data} />}
      {data && tab === 'deploy' && <Deploy d={data} />}
      {data && tab === 'audit' && <Audit rows={data} />}
    </div>
  )
}

const pct = (v: number | null | undefined) =>
  v == null ? '—' : `${(v * 100).toFixed(0)}%`

function Stat({ label, value, sub }: { label: string; value: any; sub?: string }) {
  return (
    <div className="metric">
      <div className="metric-value">{value ?? '—'}</div>
      <div className="metric-label">{label}</div>
      {sub && <div className="metric-extra">{sub}</div>}
    </div>
  )
}

function Pilot({ d }: { d: any }) {
  const w = d.walks, f = d.feedback, r = d.route_generation
  return (
    <>
      <section className="metrics">
        <Stat label="participants" value={d.participants.total}
              sub={`${d.participants.with_a_completed_walk} have finished a walk`} />
        <Stat label="walks submitted" value={w.submitted}
              sub={`${w.in_progress} in progress · ${w.discarded} discarded`} />
        <Stat label="completion rate" value={pct(w.completion_rate)}
              sub="of walks that reached a terminal state" />
      </section>
      <section className="metrics">
        <Stat label="average rating" value={f.average_rating ?? '—'}
              sub={`${f.responses} responses · ${pct(f.response_rate)} of submitted walks rated`} />
        <Stat label="flagged unsafe or wrong" value={f.flagged_unsafe_or_incorrect}
              sub="each is reproducible from its seed" />
        <Stat label="route-generation failures" value={r.failures}
              sub={`of ${r.requests} requests · ${pct(r.failure_rate)}`} />
      </section>

      {f.flagged?.length > 0 && (
        <>
          <h2>Routes flagged unsafe or incorrect</h2>
          <table className="grid">
            <thead><tr><th>Walk</th><th>Band</th><th>Area</th><th>What was wrong</th>
              <th>Reproduce</th></tr></thead>
            <tbody>
              {f.flagged.map((x: any) => (
                <tr key={x.walk_id}>
                  <td>{x.walk_id.slice(0, 8)}</td>
                  <td>{x.band}</td>
                  <td>{x.coverage_area_id ?? '—'}</td>
                  <td>{x.detail || '(no detail given)'}</td>
                  <td><code>seed {x.reproduce.seed} · node {x.reproduce.start_node}</code></td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}

      <h2>Where people are walking</h2>
      <KeyCounts obj={d.coverage_areas} empty="no route requests yet" />
      <p className="fine">{d.starting_areas_note}</p>

      <h2>Route outcomes</h2>
      <KeyCounts obj={w.by_status} />
      <p className="fine">
        {w.edited} edited · {w.reported_not_completed} reported not completed ·{' '}
        {d.manual_edits.segments_added} segments added,{' '}
        {d.manual_edits.segments_removed} removed across{' '}
        {d.manual_edits.walks_with_edits} walks.
      </p>

      <h2>Late-opportunity states served</h2>
      <KeyCounts obj={d.late_opportunity_states} empty="none yet" />

      <p className="fine">
        Network {d.network.version} ({d.network.id}) · engine {d.network.engine_version}
      </p>
    </>
  )
}

function KeyCounts({ obj, empty }: { obj: Record<string, number>; empty?: string }) {
  const rows = Object.entries(obj || {})
  if (!rows.length) return <p className="muted">{empty ?? 'nothing yet'}</p>
  const max = Math.max(...rows.map(([, v]) => v))
  return (
    <div className="bars">
      {rows.map(([k, v]) => (
        <div key={k} className="bar">
          <span className="bar-k">{k}</span>
          <span className="bar-t"><i style={{ width: `${(v / max) * 100}%` }} /></span>
          <span className="bar-v">{v}</span>
        </div>
      ))}
    </div>
  )
}

function Walks({ rows }: { rows: any[] }) {
  if (!rows.length) return <p className="muted">No walks yet.</p>
  return (
    <table className="grid">
      <thead><tr><th>Walk</th><th>Status</th><th>Band</th><th>Miles</th>
        <th>Outcome</th><th>Segments</th><th>When</th></tr></thead>
      <tbody>
        {rows.map((w) => (
          <tr key={w.id}>
            <td>{w.id.slice(0, 8)}</td><td>{w.status}</td><td>{w.band}</td>
            <td>{w.distance_miles}</td><td>{w.outcome ?? '—'}</td>
            <td>{w.required_segments}</td>
            <td>{new Date(w.created_at).toLocaleString()}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function Edits({ d }: { d: any }) {
  if (!d.walks?.length) return <p className="muted">No manual edits yet.</p>
  return (
    <>
      <p className="lede">
        {d.edited_walks} walks were edited, {d.edits} changes in total.
      </p>
      <table className="grid">
        <thead><tr><th>Walk</th><th>Added</th><th>Removed</th><th>When</th></tr></thead>
        <tbody>
          {d.walks.map((w: any) => (
            <tr key={w.walk_id}>
              <td>{w.walk_id.slice(0, 8)}</td>
              <td>{w.added.length ? w.added.join(', ') : '—'}</td>
              <td>{w.removed.length ? w.removed.join(', ') : '—'}</td>
              <td>{new Date(w.at).toLocaleString()}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  )
}

function Feedback({ rows }: { rows: any[] }) {
  if (!rows.length) return <p className="muted">No feedback yet.</p>
  return (
    <table className="grid">
      <thead><tr><th>Rating</th><th>Band</th><th>Follow</th><th>Time</th>
        <th>Problem</th><th>Comment</th><th>Reproduce</th></tr></thead>
      <tbody>
        {rows.map((f) => (
          <tr key={f.id} className={f.had_bad_connection ? 'flagged' : ''}>
            <td>{'★'.repeat(f.rating)}</td>
            <td>{f.band}</td>
            <td>{f.easy_to_follow == null ? '—' : f.easy_to_follow ? 'yes' : 'no'}</td>
            <td>{f.time_felt_accurate == null ? '—' : f.time_felt_accurate ? 'yes' : 'no'}</td>
            <td>{f.had_bad_connection ? (f.bad_connection_detail || 'flagged') : '—'}</td>
            <td>{f.comment ?? '—'}</td>
            <td><code>seed {f.reproduce.seed} · {f.reproduce.engine_version}</code></td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function Reservations({ rows }: { rows: any[] }) {
  if (!rows.length) return <p className="muted">Nothing is held right now.</p>
  return (
    <table className="grid">
      <thead><tr><th>Walk</th><th>Segments held</th><th>Expires</th></tr></thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.walk_id}>
            <td>{r.walk_id.slice(0, 8)}</td><td>{r.segments}</td>
            <td>{new Date(r.expires_at).toLocaleString()}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function Duplicates({ d }: { d: any }) {
  const groups = [...(d.same_name ?? []), ...(d.same_mailbox_different_tag ?? [])]
  if (!groups.length) return (
    <><p className="muted">No likely duplicates.</p><p className="fine">{d.note}</p></>
  )
  return (
    <>
      <table className="grid">
        <thead><tr><th>Match</th><th>People</th></tr></thead>
        <tbody>
          {groups.map((g: any) => (
            <tr key={g.key}>
              <td>{g.key}</td>
              <td>{g.participants.map((p: any) => `${p.first_name} ${p.last_name} <${p.email}>`).join(' · ')}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="fine">{d.note}</p>
    </>
  )
}

function Failures({ d }: { d: any }) {
  if (!d.failures) return <p className="muted">No route-generation failures.</p>
  return (
    <>
      <p className="lede">{d.failures} requests produced no usable route.</p>
      <h2>By reason</h2><KeyCounts obj={d.by_reason} />
      <h2>By area</h2><KeyCounts obj={d.by_coverage_area} />
      <table className="grid">
        <thead><tr><th>Reason</th><th>Area</th><th>Node</th><th>Seed</th>
          <th>Engine</th><th>When</th></tr></thead>
        <tbody>
          {d.requests.map((r: any) => (
            <tr key={r.id}>
              <td>{r.reason}</td><td>{r.coverage_area_id ?? '—'}</td>
              <td>{r.start_node}</td><td><code>{r.seed}</code></td>
              <td>{r.engine_version}</td>
              <td>{new Date(r.created_at).toLocaleString()}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="fine">{d.reproduce}</p>
    </>
  )
}

function Connectors({ d }: { d: any }) {
  return (
    <>
      <p className="lede">
        {d.candidates} candidate connectors reviewed, <strong>{d.promoted} promoted</strong>.
      </p>
      <div className="note warn"><strong>No imagery was available</strong>
        <p>{d.basemap_evidence}</p></div>
      <table className="grid">
        <thead><tr><th>Segment</th><th>Recovers</th><th>Road</th><th>Class</th>
          <th>Crossing</th><th>Recommendation</th><th>Confidence</th><th>Map</th></tr></thead>
        <tbody>
          {d.rows.map((r: any) => (
            <tr key={r.segment_id}>
              <td>{r.segment_id}</td>
              <td>{r.required_miles_recovered} mi</td>
              <td>{r.road_crossed ?? '—'}</td>
              <td>{r.road_class ?? '—'} {r.speed_limit ? `${r.speed_limit}mph` : ''}</td>
              <td>{r.crossing_type}</td>
              <td>{r.recommendation}</td>
              <td>{r.confidence}</td>
              <td><a href={r.map_location.osm_link} target="_blank" rel="noreferrer">open</a></td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  )
}

function Network({ d }: { d: any }) {
  const m = d.manifest
  return (
    <>
      <dl className="facts">
        <div><dt>Network</dt><dd>{m.canonical_network_version}</dd></div>
        <div><dt>Required</dt><dd>{m.mileage.required_total} mi</dd></div>
        <div><dt>Segments</dt><dd>{m.counts.routing_segments}</dd></div>
        <div><dt>Snapshot</dt><dd>{m.snapshot_date}</dd></div>
      </dl>
      <p className="fine">{m.network_id}</p>
      <h2>Routing components</h2>
      <table className="grid">
        <thead><tr><th>#</th><th>Area</th><th>Required</th><th>Households</th>
          <th>Classification</th><th>Bands</th></tr></thead>
        <tbody>
          {d.components.map((c: any) => (
            <tr key={c.index}>
              <td>{c.index}</td><td>{c.description}</td>
              <td>{c.required_miles} mi</td><td>{c.households}</td>
              <td>{c.classification}</td>
              <td>{(c.supported_bands || []).join(', ') || '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
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
      <div className="note stop"><strong>{d.licensing_gate.status}</strong>
        <p>{d.licensing_gate.summary}</p></div>
      <h3>Blocks</h3>
      <ul>{d.licensing_gate.blocks.map((x: string) => <li key={x}>{x}</li>)}</ul>
      <h3>Does not block</h3>
      <ul>{d.licensing_gate.does_not_block.map((x: string) => <li key={x}>{x}</li>)}</ul>
    </>
  )
}

function Audit({ rows }: { rows: any[] }) {
  if (!rows.length) return <p className="muted">No administrative actions recorded.</p>
  return (
    <table className="grid">
      <thead><tr><th>When</th><th>Action</th><th>Target</th><th>Detail</th></tr></thead>
      <tbody>
        {rows.map((a) => (
          <tr key={a.id}>
            <td>{new Date(a.created_at).toLocaleString()}</td>
            <td>{a.action}</td><td>{a.target ?? '—'}</td>
            <td>{JSON.stringify(a.detail)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

/**
 * Phase 3.1 §7 audit — capabilities that exist but are NOT fully usable here.
 *
 *   correct a walk submission     API only (POST /api/admin/walks/{id}/correct).
 *                                 No screen. Correcting a walk means choosing an
 *                                 outcome AND a segment set, which needs the same map
 *                                 selection the walker gets; building a second, worse
 *                                 copy of it for an action nobody has needed yet was
 *                                 not worth the pilot's time. An administrator can
 *                                 curl it, and the audit log records it.
 *
 *   correct segment completion    API only (POST /api/admin/completions/reverse and
 *                                 /record). Same reasoning. Both require a written
 *                                 reason and are audited.
 *
 * Everything else in §17 and §7 has a screen above.
 */
export const ADMIN_CAPABILITY_NOTES = {
  api_only: ['correct a walk submission', 'correct segment completion'],
  reason: 'both need map-based segment selection; deferred rather than half-built',
}
