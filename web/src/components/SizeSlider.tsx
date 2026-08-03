/**
 * Route-size control (§8).
 *
 * A slider, but it snaps to the variants the server actually returned — it does not
 * interpolate. There is no such thing as a 2.7-mile route here; there are five
 * computed routes and the slider picks between them.
 *
 * Unavailable bands are rendered but not selectable, and each says why. Hiding them
 * would be worse: a walker who asks for a Quick loop near the end of the project needs
 * to know that Quick found nothing, not that Quick has quietly disappeared.
 */
import type { Variant } from '../types'

interface Props {
  variants: Variant[]
  selected: string | null
  onSelect: (band: string) => void
  disabled?: boolean
}

export default function SizeSlider({ variants, selected, onSelect, disabled }: Props) {
  const available = variants.filter((v) => v.available)
  const index = Math.max(0, available.findIndex((v) => v.band === selected))

  if (!available.length) {
    return (
      <div className="sizes empty" role="group" aria-label="Route size">
        <p className="muted">No route size is available from this start point.</p>
      </div>
    )
  }

  return (
    <div className="sizes" role="group" aria-label="Route size">
      <input
        type="range"
        min={0}
        max={available.length - 1}
        step={1}
        value={index}
        disabled={disabled || available.length < 2}
        aria-label="Route size"
        aria-valuetext={`${available[index].band}, ${available[index].distance_miles} miles`}
        onChange={(e) => onSelect(available[Number(e.target.value)].band)}
      />
      <div className="ticks">
        {variants.map((v) => {
          const isAvailable = v.available
          const isSelected = v.band === selected
          return (
            <button
              key={v.band}
              type="button"
              className={`tick ${isSelected ? 'on' : ''} ${isAvailable ? '' : 'off'}`}
              disabled={!isAvailable || disabled}
              aria-pressed={isSelected}
              aria-disabled={!isAvailable}
              title={isAvailable
                ? `${v.distance_miles} mi · about ${v.estimated_minutes} min`
                : v.reason}
              onClick={() => isAvailable && onSelect(v.band)}
            >
              {/* Time first. "Quick / Medium / Long" are engine bands, and the thing
                  a walker is actually choosing between is how long they will be out
                  (Priority 4). The band name stays as the smaller line so the label
                  still matches what the server called it. */}
              <span className="band">
                {isAvailable ? `${v.estimated_minutes} min` : v.band}
              </span>
              <span className="mi">
                {isAvailable ? `${v.distance_miles} mi` : 'unavailable'}
              </span>
            </button>
          )
        })}
      </div>
    </div>
  )
}
