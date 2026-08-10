/**
 * The map. One instance, kept alive for the life of the app.
 *
 * Tiles are read from a file on the device (/basemap/blacksburg.pmtiles). No
 * request for a map tile ever leaves the phone.
 */

import { useEffect, useRef } from 'react'
import maplibregl from 'maplibre-gl'
import { Protocol } from 'pmtiles'
import 'maplibre-gl/dist/maplibre-gl.css'
import { BLACKSBURG, BLACKSBURG_BOUNDS, buildStyle } from './style'
import { toFeatureCollection } from '../data/network'
import type { Fix, Segment } from '../types'

let protocolRegistered = false
function registerProtocol() {
  if (protocolRegistered) return
  const protocol = new Protocol()
  maplibregl.addProtocol('pmtiles', protocol.tile)
  protocolRegistered = true
}

const TAP_LAYERS = ['seg-hit']

export type MapViewProps = {
  segments: Segment[]
  covered: Set<number>
  claimed: number[]
  route: { type: 'LineString'; coordinates: [number, number][] } | null
  walker: Fix | null
  follow: boolean
  tappable: boolean
  onTapSegment?: (seg: { seg_id: number; name: string }) => void
  fitTo?: [number, number, number, number] | null
}

export function MapView(props: MapViewProps) {
  const holder = useRef<HTMLDivElement | null>(null)
  const map = useRef<maplibregl.Map | null>(null)
  const ready = useRef(false)
  const prayedNow = useRef<Set<number>>(new Set())
  const claimedNow = useRef<Set<number>>(new Set())
  const tapRef = useRef(props.onTapSegment)
  const tappableRef = useRef(props.tappable)
  tapRef.current = props.onTapSegment
  tappableRef.current = props.tappable

  // ---- create once -------------------------------------------------------
  useEffect(() => {
    if (!holder.current || map.current) return
    registerProtocol()
    const m = new maplibregl.Map({
      container: holder.current,
      style: buildStyle(),
      center: [BLACKSBURG.lon, BLACKSBURG.lat],
      zoom: 13.2,
      minZoom: 9,
      maxZoom: 19,
      maxBounds: [
        [BLACKSBURG_BOUNDS[0] - 0.35, BLACKSBURG_BOUNDS[1] - 0.35],
        [BLACKSBURG_BOUNDS[2] + 0.35, BLACKSBURG_BOUNDS[3] + 0.35],
      ],
      attributionControl: false,
      dragRotate: false,
      pitchWithRotate: false,
      fadeDuration: 120,
    })
    m.touchZoomRotate.disableRotation()
    m.on('load', () => {
      ready.current = true
      m.getContainer().dataset.ready = 'true'
    })
    m.on('click', TAP_LAYERS, (e) => {
      const f = e.features?.[0]
      if (!f || !tappableRef.current) return
      const seg_id = Number(f.properties?.seg_id)
      if (!Number.isFinite(seg_id)) return
      tapRef.current?.({ seg_id, name: String(f.properties?.name ?? '') })
    })
    map.current = m
    return () => {
      m.remove()
      map.current = null
      ready.current = false
    }
  }, [])

  // ---- the street network -----------------------------------------------
  useEffect(() => {
    const m = map.current
    if (!m || !props.segments.length) return
    const apply = () => {
      const src = m.getSource('network') as maplibregl.GeoJSONSource | undefined
      if (!src) return
      src.setData(toFeatureCollection(props.segments) as never)
    }
    if (ready.current) apply()
    else m.once('load', apply)
  }, [props.segments])

  // ---- prayed / not prayed ----------------------------------------------
  useEffect(() => {
    const m = map.current
    if (!m) return
    const apply = () => {
      for (const id of prayedNow.current) {
        if (!props.covered.has(id)) {
          m.setFeatureState({ source: 'network', id }, { prayed: false })
        }
      }
      for (const id of props.covered) {
        if (!prayedNow.current.has(id)) {
          m.setFeatureState({ source: 'network', id }, { prayed: true })
        }
      }
      prayedNow.current = new Set(props.covered)
    }
    if (ready.current) apply()
    else m.once('load', apply)
  }, [props.covered])

  // ---- streets claimed on this walk --------------------------------------
  useEffect(() => {
    const m = map.current
    if (!m) return
    const next = new Set(props.claimed)
    const apply = () => {
      for (const id of claimedNow.current) {
        if (!next.has(id)) m.setFeatureState({ source: 'network', id }, { claimed: false })
      }
      for (const id of next) {
        if (!claimedNow.current.has(id)) m.setFeatureState({ source: 'network', id }, { claimed: true })
      }
      claimedNow.current = next
    }
    if (ready.current) apply()
    else m.once('load', apply)
  }, [props.claimed])

  // ---- the route ---------------------------------------------------------
  useEffect(() => {
    const m = map.current
    if (!m) return
    const apply = () => {
      const src = m.getSource('route') as maplibregl.GeoJSONSource | undefined
      if (!src) return
      src.setData(
        props.route
          ? ({ type: 'Feature', properties: {}, geometry: props.route } as never)
          : ({ type: 'FeatureCollection', features: [] } as never),
      )
    }
    if (ready.current) apply()
    else m.once('load', apply)
  }, [props.route])

  // ---- the walker --------------------------------------------------------
  useEffect(() => {
    const m = map.current
    if (!m) return
    const apply = () => {
      const src = m.getSource('walker') as maplibregl.GeoJSONSource | undefined
      if (!src) return
      src.setData(
        props.walker
          ? ({
              type: 'Feature',
              properties: { accuracy_m: props.walker.accuracy_m },
              geometry: { type: 'Point', coordinates: [props.walker.lon, props.walker.lat] },
            } as never)
          : ({ type: 'FeatureCollection', features: [] } as never),
      )
    }
    if (ready.current) apply()
    else m.once('load', apply)
  }, [props.walker])

  // ---- follow the walker -------------------------------------------------
  useEffect(() => {
    const m = map.current
    if (!m || !props.follow || !props.walker) return
    m.easeTo({
      center: [props.walker.lon, props.walker.lat],
      zoom: Math.max(m.getZoom(), 16),
      duration: 700,
    })
  }, [props.follow, props.walker])

  // ---- fit to a bounding box --------------------------------------------
  useEffect(() => {
    const m = map.current
    if (!m || !props.fitTo) return
    const b = props.fitTo
    const apply = () =>
      m.fitBounds(
        [
          [b[0], b[1]],
          [b[2], b[3]],
        ],
        { padding: { top: 70, bottom: 260, left: 40, right: 40 }, duration: 700, maxZoom: 17 },
      )
    if (ready.current) apply()
    else m.once('load', apply)
  }, [props.fitTo])

  return <div ref={holder} className="map" />
}
