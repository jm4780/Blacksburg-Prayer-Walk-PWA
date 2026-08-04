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
import { CONTEXTS, type MapContext, baseStyle, prayerLayers } from '../map/style'
import { MOTION } from '../map/tokens'
import type { LineString } from '../types'

mlConfig.WORKER_URL = workerUrl

/**
 * Set once a basemap fetch has demonstrably failed. Later maps in the same session
 * skip the six-second discovery and start on the fallback immediately — otherwise
 * tapping "Explore" on a blocked network shows an empty panel for six seconds while
 * a second map independently rediscovers what the first one already knows.
 */
let basemapKnownDead = false

export interface SegmentFeature {
  id: string
  coordinates: [number, number][]
  state: 'done' | 'todo' | 'held' | 'planned' | 'selected' | 'removed' | 'added'
  /** Drives the width ramp. Road class may only nudge — see src/map/tokens.ts. */
  roadClass?: string | null
  pathType?: string | null
  /** Drives labels, which appear only for mission and covered streets. */
  name?: string | null
}

interface Props {
  route?: LineString | null
  segments?: SegmentFeature[]
  start?: { lat: number; lon: number; label?: string } | null
  onSegmentTap?: (id: string) => void
  /** Tap anywhere to choose a point. Used by the "start from here" picker. */
  onMapTap?: (p: { lat: number; lon: number }) => void
  /** Public open space, the town outline, and the rest of the town's public roads. */
  parks?: any
  boundary?: any
  townRoads?: any
  /** Pre-system rendering, for screens not yet migrated to a map context. */
  theme?: 'light' | 'dark'
  height?: number | string
  /**
   * What to frame, when that is not the drawn content. Editing a walk shows the whole
   * required network so nearby streets can be added, but should open framed on the
   * walk — otherwise the first thing the walker sees is the entire town.
   */
  fitTo?: LineString | null
  /** Zoom in close enough that individual streets are separable by thumb. */
  editing?: boolean
  /**
   * Zoom buttons. Off for the dashboard's compact map, which is read rather than
   * navigated — a +/- box there reads as GIS chrome sitting on a briefing.
   */
  controls?: boolean
  /**
   * Which of the map system's six contexts this is. Governs weights, labels, controls,
   * tap targets and how much unwalked ground is let through — see src/map/style.ts.
   * Omitted, the map falls back to the pre-system light rendering used by the screens
   * that have not been migrated yet.
   */
  context?: MapContext
  ariaLabel: string
}

const BLACKSBURG: [number, number] = [-80.4139, 37.2296]

// Overridable per deployment. The default is a free, key-less OpenStreetMap-derived
// vector style. Attribution is required and is rendered by the attribution control.
const STYLE_URL = (import.meta as any).env?.VITE_BASEMAP_STYLE
  ?? 'https://tiles.openfreemap.org/styles/liberty'

/** Last-resort style used when the vector basemap cannot be reached. */
function fallbackStyle(theme: 'light' | 'dark'): StyleSpecification {
  return {
    version: 8,
    sources: {},
    layers: [{ id: 'bg', type: 'background',
               paint: { 'background-color': FALLBACK_BG[theme] } }],
  }
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

/** Palette for the dark Mission-control dashboard (design "01 — Mission control"). */
const DARK_COLORS: Record<SegmentFeature['state'], string> = {
  ...COLORS,
  done: '#5E9B7E',      // "Covered"
  todo: '#6E7676',      // "Still to walk" — drawn dashed, see `theme` below
  held: '#E4712C',
  planned: '#5E9B7E',
}

const FALLBACK_BG = { light: '#f2f1ec', dark: '#1B1F22' }

export default function MapView({
  route, segments, start, onSegmentTap, onMapTap, height = 340, fitTo = null,
  editing = false, theme = 'light', controls = true, context, parks, boundary,
  townRoads, ariaLabel,
}: Props) {
  const spec = context ? CONTEXTS[context] : null
  const dark = Boolean(context) || theme === 'dark'
  const palette = dark ? DARK_COLORS : COLORS
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
  // The map is created once, in an effect with no dependencies, but the failure
  // handlers inside it fire later and need the current theme.
  const themeRef = useRef<'light' | 'dark'>(dark ? 'dark' : 'light')
  themeRef.current = dark ? 'dark' : 'light'
  const specRef = useRef(spec)
  specRef.current = spec
  const controlsRef = useRef(controls)
  controlsRef.current = spec ? spec.controls : controls

  // ---------------------------------------------------------------- lifecycle
  useEffect(() => {
    if (!container.current || map.current) return
    const bornDead = basemapKnownDead
    // With a map context there is no basemap to *fetch* — but there is a basemap.
    // Blacksburg's roads, parks and boundary are drawn from our own data, so the style
    // is complete before the first frame and no tile host can fail or restyle us.
    // That is the point of the system, not a side effect.
    const m = new MLMap({
      container: container.current,
      style: specRef.current ? baseStyle()
        : bornDead ? fallbackStyle(themeRef.current) : STYLE_URL,
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
    if (controlsRef.current) {
      m.addControl(new NavigationControl({ showCompass: false }), 'top-right')
    }

    // A style that never arrives would otherwise leave a blank screen with a route
    // that never draws, because the layers are added on 'load'.
    if (bornDead && !specRef.current) setBasemapFailed(true)
    const failTimer = (bornDead || specRef.current) ? 0 : window.setTimeout(() => {
      if (!m.isStyleLoaded()) {
        basemapKnownDead = true
        setBasemapFailed(true)
        try { m.setStyle(fallbackStyle(themeRef.current)) } catch { /* already gone */ }
      }
    }, 6000)

    m.on('error', (e: any) => {
      // Tile 404s are noise; a failed *style* is not.
      if (e?.error?.status && e.error.status >= 400 && !m.isStyleLoaded()) {
        basemapKnownDead = true
        setBasemapFailed(true)
        try { m.setStyle(fallbackStyle(themeRef.current)) } catch { /* already gone */ }
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
    return () => {
      window.clearTimeout(failTimer)
      // Clear the test handle if it still points at this instance, so a probe after
      // unmount fails loudly instead of quietly querying a dead map's empty sources.
      if ((window as any).__bpwMap === m) delete (window as any).__bpwMap
      m.remove()
      map.current = null
    }
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
        properties: {
          id: s.id, state: s.state, color: palette[s.state],
          // The system's width ramp and label filter read these.
          road_class: s.roadClass ?? null,
          path_type: s.pathType ?? null,
          name: s.name ?? null,
        },
        geometry: { type: 'LineString' as const, coordinates: s.coordinates },
      })),
    }
    const routeFC = {
      type: 'FeatureCollection' as const,
      features: route
        ? [{ type: 'Feature' as const, properties: {}, geometry: route }]
        : [],
    }

    if (spec) {
      // --- the Prayer Walk map system -----------------------------------------
      upsertSource(m, 'pw-segments', segFC)
      upsertSource(m, 'pw-route', routeFC)
      upsertSource(m, 'pw-parks', parks ?? { type: 'FeatureCollection', features: [] })
      upsertSource(m, 'pw-context',
        townRoads ?? { type: 'FeatureCollection', features: [] })
      upsertSource(m, 'pw-boundary', boundary
        ? { type: 'Feature', properties: {}, geometry: boundary }
        : { type: 'FeatureCollection', features: [] })
      upsertSource(m, 'startpt', {
        type: 'FeatureCollection',
        features: start
          ? [{ type: 'Feature', properties: {},
               geometry: { type: 'Point', coordinates: [start.lon, start.lat] } }]
          : [],
      })
      for (const layer of prayerLayers(context!)) {
        if (!m.getLayer(layer.id)) m.addLayer(layer)
      }
      if (!m.getLayer('start-dot')) {
        m.addLayer({
          id: 'start-dot', type: 'circle', source: 'startpt',
          paint: {
            // The one saturated mark on the map. A point, never a line — it cannot
            // be mistaken for a street, and it carries further than colour on a line.
            'circle-radius': 5.5, 'circle-color': '#E4712C',
            'circle-stroke-width': 2.5, 'circle-stroke-color': '#0D1113',
          },
        })
      }
      return
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
    // Unwalked ground is dashed as well as grey, so "covered" and "still to walk"
    // are distinguishable without relying on colour.
    //
    // The weights are deliberately unequal. At town scale a few covered miles drawn
    // at the same weight as 140 uncovered ones simply disappear, and the map then
    // contradicts the percentage sitting above it. Covered ground is drawn heavy,
    // lit from beneath by a soft halo; everything else recedes to a thin dashed
    // context layer.
    if (dark && m.getLayer('segments-todo-dash') === undefined) {
      m.addLayer({
        id: 'segments-todo-dash', type: 'line', source: 'segments',
        filter: ['==', ['get', 'state'], 'todo'],
        layout: { 'line-cap': 'butt' },
        paint: {
          'line-color': DARK_COLORS.todo, 'line-width': 1.1,
          'line-opacity': 0.5, 'line-dasharray': [2, 2.4],
        },
      }, 'segments-line')
      m.addLayer({
        id: 'segments-done-glow', type: 'line', source: 'segments',
        filter: ['!=', ['get', 'state'], 'todo'],
        layout: { 'line-cap': 'round', 'line-join': 'round' },
        paint: {
          'line-color': DARK_COLORS.done, 'line-opacity': 0.16,
          'line-width': ['interpolate', ['linear'], ['zoom'], 10, 8, 15, 22],
        },
      }, 'segments-line')
      m.setPaintProperty('segments-line', 'line-opacity',
        ['case', ['==', ['get', 'state'], 'todo'], 0, 1])
      m.setPaintProperty('segments-line', 'line-width',
        ['interpolate', ['linear'], ['zoom'], 10, 3, 15, 7])
    }
    if (!m.getLayer('route-line')) {
      m.addLayer({
        id: 'route-line', type: 'line', source: 'route',
        layout: { 'line-cap': 'round', 'line-join': 'round' },
        paint: { 'line-color': dark ? '#5E9B7E' : '#1f3d2b',
                 'line-width': 5, 'line-opacity': 0.95 },
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
          'circle-radius': 8, 'circle-color': dark ? '#E4712C' : '#b5801f',
          'circle-stroke-width': 3,
          'circle-stroke-color': dark ? '#14171A' : '#fff',
        },
      })
    }
  }, [ready, styleEpoch, routeKey, segKey, start?.lat, start?.lon, segments, route,
      start, dark, palette, context, parks, boundary, townRoads])

  // -------------------------------------------------------------------- taps
  useEffect(() => {
    const m = map.current
    if (!m || !ready || (!onSegmentTap && !onMapTap)) return
    const handler = (e: any) => {
      // A segment hit wins over a bare map tap: on the picker there are no segment
      // layers, and where both exist the street is the more specific answer.
      const hitLayer = specRef.current ? 'pw-hit' : 'segments-hit'
      if (onSegmentTap && m.getLayer(hitLayer)) {
        const hits = m.queryRenderedFeatures(e.point, { layers: [hitLayer] })
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
      // Generous bottom padding on the light screens: the mission card sits over the
      // map on a phone. The dashboard panel is short and wide and the map is the
      // content, so it fills the frame instead of floating in the middle of it.
      padding: dark
        ? { top: 10, bottom: 10, left: 10, right: 10 }
        : { top: 48, bottom: 72, left: 40, right: 40 },
      // Editing needs streets far enough apart to tell one from another.
      maxZoom: spec ? spec.maxZoom : editing ? 17.5 : 16,
      duration: animate ? MOTION.cameraMs : 0,
    })
    setUserMoved(false)
  }, [route, segments, start, editing, fitTo, dark, spec])

  useEffect(() => {
    if (!ready) return
    const key = fitKey || routeKey || segKey
    if (!key || key === fittedKey.current) return
    fittedKey.current = key
    // Only auto-fit if the user has not taken control of the viewport.
    if (!userMoved) fit(false)
  }, [ready, fitKey, routeKey, segKey, fit, userMoved])

  return (
    <div className={dark ? 'mapwrap dark' : 'mapwrap'} style={{ height }}>
      <div ref={container} className="maplibre" role="application"
           aria-label={ariaLabel} data-ready={ready ? 'true' : 'false'} />
      <button type="button" className="map-recenter" onClick={() => fit(true)}
              aria-label="Recenter route">
        Recenter
      </button>
      {basemapFailed && (
        <div className="map-degraded" role="status">
          Street background unavailable
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
