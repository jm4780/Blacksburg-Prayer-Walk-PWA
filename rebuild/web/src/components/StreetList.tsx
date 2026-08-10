import type { Segment } from '../types'
import { formatMiles } from '../state/geo'

/**
 * Streets you can tick on and off with a thumb. This is the manual path, and it
 * is the same list whether location is switched on or not.
 */
export function StreetList({
  segments,
  checked,
  covered,
  onToggle,
}: {
  segments: Segment[]
  checked: Set<number>
  covered: Set<number>
  onToggle: (seg_id: number) => void
}) {
  if (segments.length === 0) return null
  return (
    <ul className="streets">
      {segments.map((s) => (
        <li key={s.seg_id}>
          <button
            className="street"
            role="checkbox"
            aria-checked={checked.has(s.seg_id)}
            onClick={() => onToggle(s.seg_id)}
          >
            <span className="tick" />
            <span className="name">{s.name}</span>
            {covered.has(s.seg_id) && <span className="already">already prayed for</span>}
            <span className="dist">{formatMiles(s.length_m)} mi</span>
          </button>
        </li>
      ))}
    </ul>
  )
}
