/**
 * A self-contained SVG map.
 *
 * Deliberately not MapLibre + a tile basemap, for three reasons that all point the
 * same way for this slice:
 *
 *   1. There is no basemap to show. Every tile and imagery host is blocked in this
 *      environment, and a Protomaps .pmtiles extract would itself be a redistribution
 *      question we have not answered.
 *   2. An installed PWA has to work with no network. Vector geometry we already
 *      fetched renders offline; a tile basemap does not.
 *   3. It draws exactly what the server sent and nothing else, which is easy to
 *      assert on in a privacy test.
 *
 * The trade is real and worth naming: without street context, a walker sees the shape
 * of their route but not the buildings around it. Turn-by-turn text carries that
 * weight instead (§13). A basemap is the obvious first upgrade once licensing is
 * settled.
 */
import { useMemo, useRef } from 'react'
import type { LineString } from '../types'

export interface MapLine {
  coords: [number, number][]
  className: string
  id?: string
  onClick?: () => void
}

interface Props {
  lines: MapLine[]
  /** Extra geometry drawn on top and always fully in frame. */
  focus?: LineString | null
  marker?: { lat: number; lon: number } | null
  height?: number
  /** When set, tapping the map reports the lon/lat tapped (§6 map-start fallback). */
  onPick?: (lonLat: { lon: number; lat: number }) => void
  ariaLabel: string
}

const PAD = 12

export default function MapCanvas({
  lines, focus, marker, height = 320, onPick, ariaLabel,
}: Props) {
  const svgRef = useRef<SVGSVGElement>(null)

  const { project, unproject, viewBox } = useMemo(() => {
    const pts: [number, number][] = []
    for (const l of lines) pts.push(...l.coords)
    if (focus) pts.push(...focus.coordinates)
    if (marker) pts.push([marker.lon, marker.lat])
    if (!pts.length) {
      const id = (p: { lon: number; lat: number }) => p
      return { project: () => [0, 0] as [number, number], unproject: id as any,
               viewBox: '0 0 100 100' }
    }
    let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity
    for (const [x, y] of pts) {
      if (x < minX) minX = x; if (x > maxX) maxX = x
      if (y < minY) minY = y; if (y > maxY) maxY = y
    }
    // Longitude degrees are shorter than latitude degrees at this latitude; without
    // the correction every route renders horizontally squashed.
    const K = Math.cos((37.23 * Math.PI) / 180)
    const w = Math.max((maxX - minX) * K, 1e-6)
    const h = Math.max(maxY - minY, 1e-6)
    const scale = Math.min((1000 - 2 * PAD) / w, (1000 - 2 * PAD) / h)
    const ox = (1000 - w * scale) / 2
    const oy = (1000 - h * scale) / 2

    const project = ([lon, lat]: [number, number]): [number, number] => [
      ox + (lon - minX) * K * scale,
      1000 - oy - (lat - minY) * scale,
    ]
    const unproject = (px: number, py: number) => ({
      lon: minX + (px - ox) / (K * scale),
      lat: minY + (1000 - oy - py) / scale,
    })
    return { project, unproject, viewBox: '0 0 1000 1000' }
  }, [lines, focus, marker])

  const path = (coords: [number, number][]) =>
    coords.map((c, i) => `${i ? 'L' : 'M'}${project(c).map((n) => n.toFixed(1)).join(' ')}`)
      .join('')

  function handleClick(e: React.MouseEvent<SVGSVGElement>) {
    if (!onPick || !svgRef.current) return
    const r = svgRef.current.getBoundingClientRect()
    const px = ((e.clientX - r.left) / r.width) * 1000
    const py = ((e.clientY - r.top) / r.height) * 1000
    onPick(unproject(px, py))
  }

  return (
    <svg
      ref={svgRef}
      className="map"
      viewBox={viewBox}
      style={{ height }}
      role="img"
      aria-label={ariaLabel}
      onClick={handleClick}
      data-pickable={onPick ? 'true' : 'false'}
    >
      {lines.map((l, i) => (
        <path key={l.id ?? i} d={path(l.coords)} className={l.className}
              onClick={l.onClick} vectorEffect="non-scaling-stroke" />
      ))}
      {focus && (
        <path d={path(focus.coordinates)} className="ln-route"
              vectorEffect="non-scaling-stroke" />
      )}
      {marker && (
        <g className="marker" aria-label="Start point">
          <circle cx={project([marker.lon, marker.lat])[0]}
                  cy={project([marker.lon, marker.lat])[1]} r={11} />
        </g>
      )}
    </svg>
  )
}
