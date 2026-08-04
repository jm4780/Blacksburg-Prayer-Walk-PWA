/**
 * Mission control — the landing screen.
 *
 * Implements design "01 — Mission control" from the approved Claude Design direction.
 * One story, top to bottom, in a fixed order: what we are doing, how far it has come,
 * where it stands on the ground, what it adds up to, and the single way in.
 *
 * Three things this screen commits to:
 *
 *   ONE DESTINATION.  The town map is not a separate screen any more. It lives here,
 *                     filling whatever vertical space the rest of the layout leaves,
 *                     and "Explore" expands it *in place* — an overlay, not a route.
 *                     There is nowhere else to go to see progress.
 *
 *   NOT ABOUT YOU.    Every number here belongs to the town. That is stated in words
 *                     ("Counted for the whole town, not for you.") rather than left to
 *                     be inferred, because a big percentage on a personal dashboard
 *                     reads as a personal score, and this one never is.
 *
 *   DEFINITIONS KEPT. Phase 3 committed to every number carrying its own definition —
 *                     "42% prayed for" is a claim about a denominator two phases of
 *                     work went into establishing. The design has no room for three
 *                     disclosures, so the whole metric row opens one panel instead.
 *                     The commitment survives; only its packaging changed.
 *
 * This screen is dark; the rest of the app is not yet. See docs/19 — the approved
 * direction is dark throughout and the other screens follow later.
 */
import { useEffect, useMemo, useState } from 'react'
import { api, ApiError } from '../api'
import MapView, { type SegmentFeature } from '../components/MapView'
import { boundsOf, frameAsRing, progressFrame } from './progressFrame'
import type { Metrics, ParticipantOut, ProgressMap, Walk } from '../types'
import type { Nav } from '../App'

export default function Dashboard({ nav, me, walk }: {
  nav: Nav; me: ParticipantOut | null; walk: Walk | null
}) {
  const [m, setM] = useState<Metrics | null>(null)
  const [map, setMap] = useState<ProgressMap | null>(null)
  const [mapBlocked, setMapBlocked] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [expanded, setExpanded] = useState(false)
  const [defs, setDefs] = useState(false)

  useEffect(() => {
    api.metrics().then(setM).catch((e) => setError(e.message))
  }, [walk?.id])

  useEffect(() => {
    api.progressMap().then(setMap).catch((e) => {
      // The map is gated behind the G1 licensing decision. Under
      // BPW_ACCESS_MODE=authenticated an anonymous visitor gets a 403 here — on the
      // landing screen, where the map is the centrepiece. Say so rather than
      // showing an empty panel.
      if (e instanceof ApiError && e.status === 403) setMapBlocked(e.message)
    })
  }, [walk?.id])

  const segments: SegmentFeature[] = useMemo(
    () => (map?.features ?? []).map((f) => ({
      id: f.properties.id,
      coordinates: f.geometry.coordinates,
      state: f.properties.done ? 'done' : f.properties.held ? 'held' : 'todo',
    })), [map])

  // Point the map at the progress, pulled back until it is clearly a minority of the
  // view. See progressFrame.ts for why neither "whole town" nor "tight on covered"
  // is the right answer.
  const frame = useMemo(() => {
    if (!segments.length) return null
    const coveredCoords: [number, number][] = []
    const allCoords: [number, number][] = []
    for (const s of segments) {
      for (const c of s.coordinates) {
        allCoords.push(c)
        if (s.state !== 'todo') coveredCoords.push(c)
      }
    }
    const b = progressFrame(boundsOf(coveredCoords), boundsOf(allCoords))
    return b ? frameAsRing(b) : null
  }, [segments])

  const pct = m ? m.percent_prayed_for.value : null
  const done = m?.required_segments_complete ?? 0
  const total = m?.required_segments_total ?? 0
  // The percentage is measured in MILES. Showing a segment count beneath it invited
  // the reader to check the arithmetic against a different denominator and find it
  // wrong: 100 of 1,582 segments is 6.3%, while the same state of the town is 4.5%
  // by mileage. The sub-line now reports what the number above it actually measures.
  const milesDone = m?.percent_prayed_for.numerator_miles ?? 0
  const milesTotal = m?.percent_prayed_for.denominator_miles ?? 0

  return (
    <div className="dash">
      {/* Not in the design, and deliberately kept: somebody with an unfinished walk
          needs to get back to it, and burying that under a full-height map would be
          a regression in the name of fidelity. */}
      {walk && (
        <button className="dash-resume" onClick={() => nav(`/walk/${walk.id}`)}>
          <span>
            <strong>Walk in progress</strong>
            <em>{walk.distance_miles} mi · about {walk.estimated_minutes} min</em>
          </span>
          <span className="dash-resume-go">Resume →</span>
        </button>
      )}

      <header className="dash-head">
        <div className="dash-brand">PRAYER WALK</div>
        <div className="dash-place">Blacksburg, VA</div>
      </header>

      <section className="dash-mission">
        <div className="dash-label">The mission</div>
        <p>Pray for every household in Blacksburg, one street at a time.</p>
      </section>

      {error && <p className="dash-error" role="alert">{error}</p>}

      <section className="dash-pct">
        <div className="dash-pct-row">
          <div className="dash-pct-num">
            <span className="dash-pct-value">{pct === null ? '—' : pct.toFixed(1)}</span>
            <span className="dash-pct-sign">%</span>
          </div>
          <div className="dash-pct-side">
            <div className="dash-label">Prayed for</div>
            <div className="dash-pct-sub">
              {milesDone.toLocaleString()} of {milesTotal.toLocaleString()} miles
            </div>
          </div>
        </div>
        {/* Dashed rule, filled from the left — the design's own progress treatment. */}
        <div className="dash-bar" role="progressbar" aria-valuemin={0} aria-valuemax={100}
             aria-valuenow={pct ?? 0} aria-label="Share of Blacksburg prayed for">
          <i style={{ width: `${Math.min(100, Math.max(0, pct ?? 0))}%` }} />
        </div>
      </section>

      <section className="dash-map">
        {mapBlocked ? (
          <div className="dash-map-blocked" role="status">
            <strong>The town map is not public yet</strong>
            <p>{mapBlocked}</p>
          </div>
        ) : (
          <MapView segments={segments} theme="dark" height="100%"
                   fitTo={frame} controls={false}
                   ariaLabel={`Town progress map: ${milesDone} of ${milesTotal} miles prayed for`} />
        )}
        <div className="dash-legend">
          <span><i className="lg-done" /> Covered</span>
          <span><i className="lg-todo" /> Still to walk</span>
        </div>
        {!mapBlocked && (
          <button className="dash-explore" onClick={() => setExpanded(true)}>
            Explore ↗
          </button>
        )}
      </section>

      <section className="dash-metrics">
        <button className="dash-metric" onClick={() => setDefs(!defs)}
                aria-expanded={defs}>
          <span className="dash-metric-v">
            {(m?.estimated_households_prayed_for.value ?? 0).toLocaleString()}
          </span>
          <span className="dash-label">Households</span>
        </button>
        <button className="dash-metric" onClick={() => setDefs(!defs)}
                aria-expanded={defs}>
          <span className="dash-metric-v">{done.toLocaleString()}</span>
          <span className="dash-label">Streets</span>
        </button>
        <button className="dash-metric" onClick={() => setDefs(!defs)}
                aria-expanded={defs}>
          <span className="dash-metric-v">
            {(m?.total_miles_walked.value ?? 0).toLocaleString()}
          </span>
          <span className="dash-label">Miles</span>
        </button>
      </section>

      <p className="dash-shared">Shared progress across Blacksburg.</p>

      {defs && m && (
        <div className="dash-defs">
          <dl>
            <dt>Households</dt><dd>{m.estimated_households_prayed_for.definition}</dd>
            <dt>Streets</dt>
            <dd>
              Counted in <em>segments</em> — the pieces a street is split into between
              junctions, so one street is usually several. {done.toLocaleString()} of{' '}
              {total.toLocaleString()} recorded. The percentage above is measured by
              mileage, not by this count.
            </dd>
            <dt>The map</dt>
            <dd>
              Framed on the ground covered so far, pulled back far enough to show it
              in context. It widens by itself as coverage spreads.
            </dd>
            <dt>Miles</dt><dd>{m.total_miles_walked.definition}</dd>
            <dt>Percentage</dt><dd>{m.percent_prayed_for.definition}</dd>
            {map && (
              <>
                <dt>What the map does not show</dt>
                <dd>{map.excludes.join(' · ')}</dd>
              </>
            )}
          </dl>
          <button className="dash-defs-close" onClick={() => setDefs(false)}>Close</button>
        </div>
      )}

      <div className="dash-cta">
        <button onClick={() => nav('/mission')}>
          <span>Begin today's walk</span>
          <span aria-hidden="true">→</span>
        </button>
        {!me && (
          <p className="dash-fine">
            You can look around without signing in. We ask who you are when you accept
            a walk, so the streets are held for you.
          </p>
        )}
      </div>

      {/* Requirement 10: expands in place. No route, no history entry, no second
          destination — Escape or the close button and you are exactly where you were. */}
      {expanded && (
        <div className="dash-expand" role="dialog" aria-modal="true"
             aria-label="Town progress map">
          <MapView segments={segments} theme="dark" height="100%"
                   ariaLabel="Town progress map, expanded" />
          <div className="dash-legend expanded">
            <span><i className="lg-done" /> Covered</span>
            <span><i className="lg-todo" /> Still to walk</span>
          </div>
          <button className="dash-collapse" onClick={() => setExpanded(false)}
                  autoFocus>
            Close ✕
          </button>
        </div>
      )}
    </div>
  )
}
