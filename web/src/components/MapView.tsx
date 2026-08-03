/**
 * A real slippy map (Priority 1).
 *
 * Replaces the fixed SVG renderer, which drew the route correctly but gave no
 * geographic context and could not be zoomed — so a route read as a blob and
 * individual streets could not be tapped.
 *
 * MapLibre GL, with a vector basemap. Three things matter more than they look:
 *
 *   TAP TARGETS.  Segment selection queries an invisible line layer drawn at 24px
 *                 width. MapLibre's hit-testing respects rendered width, so the
 *                 fingertip target is 24px wide while the visible line stays 3px.
 *                 This is a functional requirement, not polish — at town zoom a
 *                 thumb covers a dozen streets.
 *
 *   FIT vs USER.  The route is fitted when it changes. It is NOT refitted when the
 *                 user has panned or zoomed, because fighting somebody's chosen view
 *                 is the fastest way to make a map feel broken. "Recenter" puts them
 *                 back deliberately.
 *
 *   DEGRADES.     If the basemap tiles fail — offline, blocked, host down — the map
 *                 falls back to a plain background and the route still draws. A
 *                 missing basemap should cost context, not the whole screen.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
// maplibre-gl v6 ships named exports only — there is no default export to import.
import {
  config as mlConfig, LngLatBounds, Map as MLMap, NavigationControl,
  type StyleSpecification,
} from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
// MapLibre parses GeoJSON in a web worker, and v6 locates that worker at runtime with
// `new URL(`./${name}`, import.meta.url)`. Rollup cannot see through the computed
// name, so the worker is never emitted and the request 404s in a built bundle.
// Nothing throws: the map draws its background, every source silently stays unloaded,
// and the screen is a blank rectangle — which is precisely the failure this whole
// component exists to avoid, so it is worth the two lines to prevent.
//
// `?worker&url` makes Vite bundle the worker properly — it pulls in the shared chunk
// the worker itself imports, which a plain `?url` copy would leave dangling — and
// hands back the hashed path to give MapLibre.
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url'
import type { LineString } from '../types'

mlConfig.WORKER_URL = workerUrl

export interface SegmentFeature {
  id: string
  coordinates: [number, number][]
  state: 'done' | 'todo' | 'held' | 'planned' | 'selected' | 'removed' | 'added'
}

interface Props {
  route?: LineString | null
  segments?: SegmentFeature[]
  start?: { lat: number; lon: number; label?: string } | null
  onSegmentTap?: (id: string) => void
  /** Tap anywhere to choose a point. Used by the "start from here" picker. */
  onMapTap?: (p: { lat: number; lon: number }) => void
  height?: number | string
  /**
   * What to frame, when that is not the drawn content. Editing a walk shows the whole
   * required network so nearby streets can be added, but should open framed on the
   * walk — otherwise the first thing the walker sees is the entire town.
   */
  fitTo?: LineString | null
  /** Zoom in close enough that individual streets are separable by thumb. */
  editing?: boolean
  ariaLabel: string
}

const BLACKSBURG: [number, number] = [-80.4139, 37.2296]

// Overridable per deployment. The default is a free, key-less OpenStreetMap-derived
// vector style. Attribution is required and is rendered by the attribution control.
const STYLE_URL = (import.meta as any).env?.VITE_BASEMAP_STYLE
  ?? 'https://tiles.openfreemap.org/styles/liberty'

/** Last-resort style used when the vector basemap cannot be reached. */
const FALLBACK_STYLE: StyleSpecification = {
  version: 8,
  sources: {},
  layers: [{ id: 'bg', type: 'background', paint: { 'background-color': '#f2f1ec' } }],
}

const COLORS: Record<SegmentFeature['state'], string> = {
  done: '#2f7d4f',
  todo: '#b9b5ac',
  held: '#d99a2b',
  planned: '#1f3d2b',
  selected: '#b5801f',
  removed: '#c8c5bc',
  added: '#2f7d4f',
}

export default function MapView({
  route, segments, start, onSegmentTap, onMapTap, height = 340, fitTo = null,
  editing = false, ariaLabel,
}: Props) {
  const container = useRef<HTMLDivElement>(null)
  const map = useRef<MLMap | null>(null)
  const [ready, setReady] = useState(false)
  // Bumped on every style load. Switching to the fallback style throws away every
  // source and layer we added, so the route has to be put back — without this the
  // degraded path shows a blank rectangle, which is exactly the failure the fallback
  // exists to prevent.
  const [styleEpoch, setStyleEpoch] = useState(0)
  const [basemapFailed, setBasemapFailed] = useState(false)
  const [userMoved, setUserMoved] = useState(false)
  const fittedKey = useRef<string>('')

  // ---------------------------------------------------------------- lifecycle
  useEffect(() => {
    if (!container.current || map.current) return
    const m = new MLMap({
      container: container.current,
      style: STYLE_URL,
      center: BLACKSBURG,
      zoom: 12,
      attributionControl: { compact: true },
      // Mobile gestures. cooperativeGestures is deliberately OFF: this map is the
      // primary content of the screen, not an embed in an article, so one-finger pan
      // should just work.
      dragRotate: false,
      pitchWithRotate: false,
      touchZoomRotate: true,
    })
    m.touchZoomRotate?.disableRotation()
    m.addControl(new NavigationControl({ showCompass: false }), 'top-right')

    // A style that never arrives would otherwise leave a blank screen with a route
    // that never draws, because the layers are added on 'load'.
    const failTimer = window.setTimeout(() => {
      if (!m.isStyleLoaded()) {
        setBasemapFailed(true)
        try { m.setStyle(FALLBACK_STYLE) } catch { /* already gone */ }
      }
    }, 6000)

    m.on('error', (e: any) => {
      // Tile 404s are noise; a failed *style* is not.
      if (e?.error?.status && e.error.status >= 400 && !m.isStyleLoaded()) {
        setBasemapFailed(true)
        try { m.setStyle(FALLBACK_STYLE) } catch { /* already gone */ }
      }
    })
    m.on('load', () => { window.clearTimeout(failTimer); setReady(true) })
    m.on('styledata', () => {
      if (!m.isStyleLoaded()) return
      setReady(true)
      setStyleEpoch((n) => n + 1)
    })
    // Any deliberate gesture means the user owns the viewport from now on.
    m.on('dragstart', () => setUserMoved(true))
    m.on('zoomstart', (e: any) => { if (e.originalEvent) setUserMoved(true) })

    map.current = m
    // A handle for the end-to-end tests, which have to ask the map real questions —
    // is the route drawn, did the viewport move, is this street tappable — and cannot
    // ask a WebGL canvas anything at all. Read-only, and nothing in the app uses it.
    ;(window as any).__bpwMap = m
    return () => { window.clearTimeout(failTimer); m.remove(); map.current = null }
  }, [])

  // ------------------------------------------------------------------ sources
  const routeKey = route ? `${route.coordinates.length}:${route.coordinates[0]?.join()}` : ''
  const segKey = segments ? `${segments.length}:${segments.filter(s => s.state === 'selected').length}` : ''
  const fitKey = fitTo ? `fit:${fitTo.coordinates.length}:${fitTo.coordinates[0]?.join()}` : ''

  useEffect(() => {
    const m = map.current
    if (!m || !ready) return

    const segFC = {
      type: 'FeatureCollection' as const,
      features: (segments ?? []).map((s) => ({
        type: 'Feature' as const,
        id: s.id,
        properties: { id: s.id, state: s.state, color: COLORS[s.state] },
        geometry: { type: 'LineString' as const, coordinates: s.coordinates },
      })),
    }
    const routeFC = {
      type: 'FeatureCollection' as const,
      features: route
        ? [{ type: 'Feature' as const, properties: {}, geometry: route }]
        : [],
    }

    upsertSource(m, 'segments', segFC)
    upsertSource(m, 'route', routeFC)
    upsertSource(m, 'startpt', {
      type: 'FeatureCollection',
      features: start
        ? [{ type: 'Feature', properties: {},
             geometry: { type: 'Point', coordinates: [start.lon, start.lat] } }]
        : [],
    })

    if (!m.getLayer('segments-line')) {
      m.addLayer({
        id: 'segments-line', type: 'line', source: 'segments',
        layout: { 'line-cap': 'round', 'line-join': 'round' },
        paint: {
          'line-color': ['get', 'color'],
          'line-width': ['case', ['==', ['get', 'state'], 'selected'], 5, 2.5],
          'line-opacity': ['case', ['==', ['get', 'state'], 'todo'], 0.75, 1],
        },
      })
    }
    if (!m.getLayer('route-line')) {
      m.addLayer({
        id: 'route-line', type: 'line', source: 'route',
        layout: { 'line-cap': 'round', 'line-join': 'round' },
        paint: { 'line-color': '#1f3d2b', 'line-width': 5, 'line-opacity': 0.95 },
      })
    }
    // The tap layer. Invisible, 24px wide, above everything — this is what makes
    // segment editing possible with a thumb.
    if (!m.getLayer('segments-hit')) {
      m.addLayer({
        id: 'segments-hit', type: 'line', source: 'segments',
        paint: { 'line-color': '#000', 'line-opacity': 0, 'line-width': 24 },
      })
    }
    if (!m.getLayer('start-dot')) {
      m.addLayer({
        id: 'start-dot', type: 'circle', source: 'startpt',
        paint: {
          'circle-radius': 8, 'circle-color': '#b5801f',
          'circle-stroke-width': 3, 'circle-stroke-color': '#fff',
        },
      })
    }
  }, [ready, styleEpoch, routeKey, segKey, start?.lat, start?.lon, segments, route, start])

  // -------------------------------------------------------------------- taps
  useEffect(() => {
    const m = map.current
    if (!m || !ready || (!onSegmentTap && !onMapTap)) return
    const handler = (e: any) => {
      // A segment hit wins over a bare map tap: on the picker there are no segment
      // layers, and where both exist the street is the more specific answer.
      if (onSegmentTap && m.getLayer('segments-hit')) {
        const hits = m.queryRenderedFeatures(e.point, { layers: ['segments-hit'] })
        if (hits.length) { onSegmentTap(String(hits[0].properties?.id)); return }
      }
      if (onMapTap) onMapTap({ lat: e.lngLat.lat, lon: e.lngLat.lng })
    }
    m.on('click', handler)
    return () => { m.off('click', handler) }
  }, [ready, onSegmentTap, onMapTap])

  // --------------------------------------------------------------------- fit
  const fit = useCallback((animate = true) => {
    const m = map.current
    if (!m) return
    const pts: [number, number][] = []
    if (fitTo) pts.push(...fitTo.coordinates)
    else if (route) pts.push(...route.coordinates)
    else for (const s of segments ?? []) pts.push(...s.coordinates)
    if (start) pts.push([start.lon, start.lat])
    if (!pts.length) return
    const b = pts.reduce((acc, p) => acc.extend(p as any),
      new LngLatBounds(pts[0] as any, pts[0] as any))
    m.fitBounds(b, {
      // Generous bottom padding: the mission card sits over the map on a phone.
      padding: { top: 48, bottom: 72, left: 40, right: 40 },
      // Editing needs streets far enough apart to tell one from another.
      maxZoom: editing ? 17.5 : 16,
      duration: animate ? 500 : 0,
    })
    setUserMoved(false)
  }, [route, segments, start, editing, fitTo])

  useEffect(() => {
    if (!ready) return
    const key = fitKey || routeKey || segKey
    if (!key || key === fittedKey.current) return
    fittedKey.current = key
    // Only auto-fit if the user has not taken control of the viewport.
    if (!userMoved) fit(false)
  }, [ready, fitKey, routeKey, segKey, fit, userMoved])

  return (
    <div className="mapwrap" style={{ height }}>
      <div ref={container} className="maplibre" role="application"
           aria-label={ariaLabel} data-ready={ready ? 'true' : 'false'} />
      <button type="button" className="map-recenter" onClick={() => fit(true)}
              aria-label="Recenter route">
        Recenter
      </button>
      {basemapFailed && (
        <div className="map-degraded" role="status">
          Map background unavailable — the route is still shown.
        </div>
      )}
    </div>
  )
}

function upsertSource(m: MLMap, id: string, data: any) {
  const existing = m.getSource(id) as any
  if (existing) existing.setData(data)
  else m.addSource(id, { type: 'geojson', data })
}
