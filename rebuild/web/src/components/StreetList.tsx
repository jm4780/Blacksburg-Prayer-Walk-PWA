import { useMemo } from 'react'
import type { Segment } from '../types'
import { formatMiles } from '../state/geo'

/**
 * Streets you can tick on and off with a thumb. This is the manual path, and it
 * is the same list whether location is switched on or not.
 *
 * One row per street, not one row per segment. The network splits a road at
 * every junction, so a route along one road arrives here as twenty-five
 * segments all called "US 460 Bus", and the list rendered as twenty-five
 * identical rows: nothing to read, nothing to aim at, and no way to tell where
 * you were in it. A walker thinks in streets, so the list is grouped by name,
 * carries the whole street's distance, and ticks the whole street at once —
 * the same unit "add every stretch of this street" already uses when you search
 * for one by name.
 */

type Group = {
  name: string
  ids: number[]
  metres: number
  checked: number
  covered: number
}

export function StreetList({
  segments,
  checked,
  covered,
  onToggle,
  onToggleMany,
}: {
  segments: Segment[]
  checked: Set<number>
  covered: Set<number>
  onToggle: (seg_id: number) => void
  onToggleMany?: (seg_ids: number[], on: boolean) => void
}) {
  const groups = useMemo<Group[]>(() => {
    const byName = new Map<string, Group>()
    for (const s of segments) {
      let g = byName.get(s.name)
      if (!g) {
        g = { name: s.name, ids: [], metres: 0, checked: 0, covered: 0 }
        byName.set(s.name, g)
      }
      g.ids.push(s.seg_id)
      g.metres += s.length_m
      if (checked.has(s.seg_id)) g.checked += 1
      if (covered.has(s.seg_id)) g.covered += 1
    }
    return [...byName.values()]
  }, [segments, checked, covered])

  if (groups.length === 0) return null

  return (
    <ul className="streets">
      {groups.map((g) => {
        const all = g.checked === g.ids.length
        const some = g.checked > 0 && !all
        return (
          <li key={g.name}>
            <button
              className="street"
              role="checkbox"
              aria-checked={some ? 'mixed' : all}
              onClick={() => {
                if (g.ids.length === 1) onToggle(g.ids[0])
                else if (onToggleMany) onToggleMany(g.ids, !all)
                else onToggle(g.ids[0])
              }}
            >
              <span className="tick" />
              <span className="name">{g.name}</span>
              {g.covered > 0 && (
                <span className="already">
                  {g.covered === g.ids.length ? 'prayed' : 'part prayed'}
                  <span className="sr-only"> for already</span>
                </span>
              )}
              <span className="dist">{formatMiles(g.metres)} mi</span>
            </button>
          </li>
        )
      })}
    </ul>
  )
}
