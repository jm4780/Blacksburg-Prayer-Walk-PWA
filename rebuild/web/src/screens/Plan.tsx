import { useMemo, useState } from 'react'
import { StreetList } from '../components/StreetList'
import { formatMiles } from '../state/geo'
import type { Segment, WalkState } from '../types'

const LENGTHS = [20, 30, 45, 60]

export function Plan({
  walk,
  busy,
  notice,
  locationDenied,
  locationOn,
  claimedSegments,
  routeSegments,
  allSegments,
  covered,
  onChooseMinutes,
  onManual,
  onStartWalking,
  onToggle,
  onAddByName,
  onCancel,
}: {
  walk: WalkState
  busy: string | null
  notice: string | null
  locationDenied: boolean
  locationOn: boolean
  claimedSegments: Segment[]
  routeSegments: Segment[]
  allSegments: Segment[]
  covered: Set<number>
  onChooseMinutes: (m: number) => void
  onManual: () => void
  onStartWalking: () => void
  onToggle: (seg_id: number) => void
  onAddByName: (name: string) => void
  onCancel: () => void
}) {
  const picked = new Set(walk.claimed)
  const pickedMetres = claimedSegments.reduce((sum, s) => sum + s.length_m, 0)
  const [query, setQuery] = useState('')

  const matches = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (q.length < 2) return []
    const names = new Map<string, number>()
    for (const s of allSegments) {
      if (!s.name.toLowerCase().includes(q)) continue
      names.set(s.name, (names.get(s.name) ?? 0) + s.length_m)
    }
    return [...names.entries()].sort((a, b) => b[1] - a[1]).slice(0, 8)
  }, [query, allSegments])

  if (walk.manual) {
    return (
      <div className="sheet">
        <h1>Pick the streets you'll walk.</h1>
        <p>Tap streets on the map, or find them by name. Tap one again to take it off.</p>
        {notice && <p className="notice notice-warn">{notice}</p>}
        <input
          className="name-input"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Find a street by name"
          aria-label="Find a street by name"
        />
        {matches.length > 0 && (
          <ul className="streets">
            {matches.map(([name, metres]) => (
              <li key={name}>
                <button
                  className="street street-add"
                  onClick={() => {
                    onAddByName(name)
                    setQuery('')
                  }}
                >
                  <span className="name">{name}</span>
                  <span className="dist">add {formatMiles(metres)} mi</span>
                </button>
              </li>
            ))}
          </ul>
        )}
        {claimedSegments.length > 0 && (
          <p className="stat-line">
            {claimedSegments.length} streets · {formatMiles(pickedMetres)} miles
          </p>
        )}
        <StreetList
          segments={claimedSegments}
          checked={picked}
          covered={covered}
          onToggle={onToggle}
        />
        <button className="btn btn-primary" onClick={onStartWalking} disabled={claimedSegments.length === 0}>
          Start walking
        </button>
        <button className="btn btn-quiet" onClick={onCancel}>
          Never mind
        </button>
      </div>
    )
  }

  return (
    <div className="sheet">
      <h1>How long do you have?</h1>
      <div className="choices">
        {LENGTHS.map((m) => (
          <button
            key={m}
            className="choice"
            aria-pressed={walk.minutes === m && Boolean(walk.route)}
            onClick={() => onChooseMinutes(m)}
          >
            {m}
            <small>min</small>
          </button>
        ))}
      </div>

      {busy === 'route' && <p className="spinner">Working out a loop…</p>}
      {notice && <p className="notice notice-warn">{notice}</p>}

      {locationDenied && !notice && (
        <p className="notice">
          Location is switched off, so the loop starts in the middle of town. Tap any street on the map to
          start there instead.
        </p>
      )}
      {!locationDenied && !locationOn && !walk.route && (
        <p className="notice">Tap any street on the map to start there.</p>
      )}

      {walk.route && (
        <>
          <p className="stat-line">
            {formatMiles(walk.route.length_m)} miles · {routeSegments.length} streets ·{' '}
            {walk.route.new_seg_ids.length} nobody has prayed for yet
          </p>
          <p className="stat-line">It ends where it starts.</p>
        </>
      )}

      <button className="btn btn-primary" onClick={onStartWalking} disabled={!walk.route}>
        Start walking
      </button>
      <div className="btn-row">
        <button className="btn" onClick={onManual}>
          Pick streets myself
        </button>
        <button className="btn btn-quiet" onClick={onCancel}>
          Never mind
        </button>
      </div>
    </div>
  )
}
