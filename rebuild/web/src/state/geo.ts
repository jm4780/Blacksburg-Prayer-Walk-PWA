/**
 * Geometry that runs on the phone.
 *
 * Matching a position to a street happens here, on the device, using the street
 * file the app already downloaded. That is the reason a walk can tick streets
 * off without ever sending a coordinate anywhere.
 */

import type { Segment } from '../types'

const M_PER_DEG_LAT = 111_320

export function metresBetween(a: [number, number], b: [number, number]): number {
  const kx = Math.cos(((a[1] + b[1]) / 2) * (Math.PI / 180)) * M_PER_DEG_LAT
  const dx = (a[0] - b[0]) * kx
  const dy = (a[1] - b[1]) * M_PER_DEG_LAT
  return Math.hypot(dx, dy)
}

/** Shortest distance in metres from a point to a line string. */
export function metresToLine(p: [number, number], line: [number, number][]): number {
  let best = Infinity
  const kx = Math.cos(p[1] * (Math.PI / 180)) * M_PER_DEG_LAT
  const px = p[0] * kx
  const py = p[1] * M_PER_DEG_LAT
  for (let i = 1; i < line.length; i++) {
    const ax = line[i - 1][0] * kx
    const ay = line[i - 1][1] * M_PER_DEG_LAT
    const bx = line[i][0] * kx
    const by = line[i][1] * M_PER_DEG_LAT
    const vx = bx - ax
    const vy = by - ay
    const len2 = vx * vx + vy * vy
    let t = len2 === 0 ? 0 : ((px - ax) * vx + (py - ay) * vy) / len2
    t = Math.max(0, Math.min(1, t))
    const d = Math.hypot(px - (ax + t * vx), py - (ay + t * vy))
    if (d < best) best = d
  }
  return best
}

export function nearestSegment(
  p: [number, number],
  segments: Segment[],
  withinM = 200,
): { segment: Segment; distance_m: number } | null {
  let best: Segment | null = null
  let bestD = Infinity
  for (const s of segments) {
    const d = metresToLine(p, s.geometry.coordinates)
    if (d < bestD) {
      bestD = d
      best = s
    }
  }
  if (!best || bestD > withinM) return null
  return { segment: best, distance_m: bestD }
}

/**
 * Which of these streets is the walker close enough to have walked?
 *
 * Deliberately conservative, and only ever applied to streets already on the
 * route: a wrong tick is worse than a missing one, and the walker can add or
 * remove any street by hand before anything is committed.
 */
export function claimedByProximity(
  point: [number, number],
  accuracy_m: number,
  candidates: Segment[],
): number[] {
  const tolerance = Math.min(35, Math.max(15, accuracy_m))
  const out: number[] = []
  for (const s of candidates) {
    if (metresToLine(point, s.geometry.coordinates) <= tolerance) out.push(s.seg_id)
  }
  return out
}

export function bboxOf(coords: [number, number][]): [number, number, number, number] {
  let minX = Infinity
  let minY = Infinity
  let maxX = -Infinity
  let maxY = -Infinity
  for (const [x, y] of coords) {
    if (x < minX) minX = x
    if (y < minY) minY = y
    if (x > maxX) maxX = x
    if (y > maxY) maxY = y
  }
  return [minX, minY, maxX, maxY]
}

/** How many streets a walker would say that is. The network splits a road at
 *  every junction, so counting segments would tell someone they walked
 *  twenty-five streets when they walked one. */
export function countStreets(segments: { name: string }[]): number {
  return new Set(segments.map((s) => s.name)).size
}

export function metresToMiles(m: number): number {
  return m / 1609.344
}

export function formatMiles(m: number): string {
  const mi = metresToMiles(m)
  // A stretch of street shorter than a tenth of a mile rounded to "0.0 mi",
  // which reads as nothing at all next to a street the walker is about to
  // claim. Say it is short instead of saying it is nothing.
  if (mi > 0 && mi < 0.05) return '<0.1'
  return mi < 10 ? mi.toFixed(1) : Math.round(mi).toString()
}
