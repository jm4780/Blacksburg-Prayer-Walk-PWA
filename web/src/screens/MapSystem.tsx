/**
 * The Prayer Walk map system, on one page, against real data.
 *
 * A design system written only as prose rots, because prose cannot be wrong out loud.
 * This is the specimen sheet: every context the product uses, rendered from the same
 * tokens the product renders from, with the town's actual network in it. If a rule in
 * docs/20 stops being true, this page stops agreeing with it.
 *
 * Reached at #/map-system. Deliberately not in any navigation — it is a reference for
 * whoever is working on the map, not a screen for walkers.
 */
import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import MapView, { type SegmentFeature } from '../components/MapView'
import { CONTEXTS, type MapContext } from '../map/style'
import { CLASS_WEIGHT, GROUND, INK, INK_OPACITY, STATE_WEIGHT } from '../map/tokens'
import type { LineString, ProgressMap } from '../types'

const ORDER: Array<{ ctx: MapContext; screen: string; asks: string }> = [
  { ctx: 'town', screen: 'Dashboard',
    asks: 'How far has the town come?' },
  { ctx: 'briefing', screen: 'Mission assignment',
    asks: 'What am I being asked to pray for?' },
  { ctx: 'walking', screen: 'Walking mode',
    asks: 'Where do I go next?' },
  { ctx: 'recording', screen: 'Recording',
    asks: 'Is this what I actually walked?' },
  { ctx: 'editing', screen: 'Route editing',
    asks: 'Which streets do I add or drop?' },
  { ctx: 'atlas', screen: 'Town progress, expanded',
    asks: 'What will still remain afterward?' },
]

export default function MapSystem() {
  const [map, setMap] = useState<ProgressMap | null>(null)
  const [route, setRoute] = useState<LineString | null>(null)

  useEffect(() => { api.progressMap().then(setMap).catch(() => {}) }, [])
  useEffect(() => {
    // A real recommendation, so the assigned state is shown against real geometry
    // rather than a drawn-on squiggle.
    api.recommend(45).then((r) => setRoute(r.mission?.geometry ?? null)).catch(() => {})
  }, [])

  const segments: SegmentFeature[] = useMemo(
    () => (map?.features ?? []).map((f, i) => ({
      id: f.properties.id,
      coordinates: f.geometry.coordinates,
      // The specimen needs every state present, including ones that only occur
      // mid-edit, so a few are synthesised here. Everything else is the real state.
      state: f.properties.done ? 'done'
        : f.properties.held ? 'held'
        : i % 37 === 0 ? 'selected'
        : i % 53 === 0 ? 'removed'
        : 'todo',
      roadClass: (f.properties as any).road_class ?? null,
      pathType: (f.properties as any).path_type ?? null,
      name: f.properties.name ?? null,
    } as SegmentFeature)), [map])

  return (
    <div className="spec">
      <header>
        <h1>Prayer Walk map system</h1>
        <p>
          One cartography, six contexts. Rendered from <code>src/map/tokens.ts</code>{' '}
          against the live network — the same code the product uses. Written up in{' '}
          <code>docs/20-map-design-system.md</code>.
        </p>
      </header>

      <section className="spec-swatches">
        <h2>Prayer hierarchy</h2>
        <p className="spec-note">
          Colour belongs to prayer state. Road class may only change width. Every state
          also differs in texture, so the map survives sunlight, greyscale and the ~8%
          of men who will not separate the green from the grey.
        </p>
        <ul>
          {(['assigned', 'covered', 'held', 'remaining'] as const).map((k) => (
            <li key={k}>
              <span className={`sw sw-${k}`} />
              <b>{k}</b>
              <code>{INK[k]}</code>
              <code>α {INK_OPACITY[k]}</code>
              <code>×{STATE_WEIGHT[k]}</code>
            </li>
          ))}
          <li><span className="sw sw-park" /><b>park</b><code>{GROUND.park}</code></li>
          <li><span className="sw sw-land" /><b>land</b><code>{GROUND.land}</code></li>
        </ul>
      </section>

      <section className="spec-swatches">
        <h2>Road hierarchy</h2>
        <p className="spec-note">
          A 1.25:1 spread from arterial to residential. On a driving map it would be
          six to one; here the residential street is where the households are, so
          arterials earn only enough width to orient by.
        </p>
        <ul className="spec-ramp">
          {Object.entries(CLASS_WEIGHT).map(([k, v]) => (
            <li key={k}>
              <i style={{ height: `${Math.max(1, v * 4)}px` }} />
              <b>{k}</b><code>×{v}</code>
            </li>
          ))}
        </ul>
      </section>

      {ORDER.map(({ ctx, screen, asks }) => {
        const c = CONTEXTS[ctx]
        return (
          <section key={ctx} className="spec-ctx">
            <div className="spec-head">
              <h2>{ctx}</h2>
              <span className="spec-screen">{screen}</span>
            </div>
            <p className="spec-asks">“{asks}”</p>
            <div className="spec-map">
              <MapView
                segments={segments}
                route={ctx === 'town' || ctx === 'atlas' ? null : route}
                fitTo={ctx === 'town' || ctx === 'atlas' ? null : route}
                context={ctx}
                parks={map?.open_space}
                boundary={map?.boundary}
                townRoads={map?.context}
                height={260}
                onSegmentTap={ctx === 'editing' ? () => {} : undefined}
                ariaLabel={`${ctx} context specimen`} />
            </div>
            <dl className="spec-props">
              <div><dt>labels</dt><dd>{String(c.labels)}</dd></div>
              <div><dt>emphasis</dt><dd>×{c.emphasis}</dd></div>
              <div><dt>context let through</dt><dd>α {c.remainingOpacity}</dd></div>
              <div><dt>tap target</dt><dd>{c.hit ? `${c.hit}px` : '—'}</dd></div>
              <div><dt>max zoom</dt><dd>{c.maxZoom}</dd></div>
              <div><dt>controls</dt><dd>{String(c.controls)}</dd></div>
            </dl>
          </section>
        )
      })}
    </div>
  )
}
