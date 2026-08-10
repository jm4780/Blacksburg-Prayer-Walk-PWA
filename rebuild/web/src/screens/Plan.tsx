import { useMemo, useState } from 'react'
import { StreetList } from '../components/StreetList'
import { countStreets, formatMiles } from '../state/geo'
import { blocksOfStreet, frontierBlocks, type Block, type StreetIndex } from '../state/streets'
import type { Segment, WalkState } from '../types'

const LENGTHS = [20, 30, 45, 60]

export function Plan({
  walk,
  busy,
  notice,
  locationDenied,
  claimedSegments,
  routeSegments,
  allSegments,
  covered,
  streetIndex,
  onChooseMinutes,
  onManual,
  onUseLoop,
  onStartWalking,
  onToggle,
  onToggleMany,
  onAddBlock,
}: {
  walk: WalkState
  busy: string | null
  notice: string | null
  locationDenied: boolean
  claimedSegments: Segment[]
  routeSegments: Segment[]
  allSegments: Segment[]
  covered: Set<number>
  streetIndex: StreetIndex
  onChooseMinutes: (m: number) => void
  onManual: () => void
  onUseLoop: () => void
  onStartWalking: () => void
  onToggle: (seg_id: number) => void
  onToggleMany: (seg_ids: number[], on: boolean) => void
  onAddBlock: (seg_ids: number[]) => void
}) {
  const picked = new Set(walk.claimed)
  const pickedMetres = claimedSegments.reduce((sum, s) => sum + s.length_m, 0)
  const [query, setQuery] = useState('')
  const [openStreet, setOpenStreet] = useState<string | null>(null)

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

  /** The stretches of the street the walker opened, best guess first. */
  const stretches = useMemo<Block[]>(
    () => (openStreet ? blocksOfStreet(openStreet, allSegments, streetIndex, walk.claimed) : []),
    [openStreet, allSegments, streetIndex, walk.claimed],
  )
  // Nine streets in ten are shorter than this cap. US 460 Bus is eighty-one
  // stretches, and a list that long is a search of its own, so the longest are
  // offered and the map takes the rest.
  const SHOWN = 12
  const shownStretches = stretches.slice(0, SHOWN)

  /** Where the walk can carry straight on to. Short: five rows at the median. */
  const carryOn = useMemo<Block[]>(
    () => (walk.claimed.length ? frontierBlocks(walk.claimed, allSegments, streetIndex) : []),
    [walk.claimed, allSegments, streetIndex],
  )

  if (walk.manual) {
    return (
      <div className="sheet">
        <h1>Which streets are you walking?</h1>
        <p>Tap them on the map, or find one by name below.</p>
        {notice && <p className="notice notice-warn">{notice}</p>}

        <input
          className="name-input"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value)
            setOpenStreet(null)
          }}
          placeholder="Find a street by name"
          aria-label="Find a street by name"
        />

        {/* A street name on its own is not a thing anyone walked. Tapping one
            opens the stretches it is made of, and a stretch is what gets
            added. */}
        {matches.length > 0 && !openStreet && (
          <ul className="streets">
            {matches.map(([name, metres]) => (
              <li key={name}>
                <button className="street street-add" onClick={() => setOpenStreet(name)}>
                  <span className="name">{name}</span>
                  <span className="dist">{formatMiles(metres)} mi</span>
                </button>
              </li>
            ))}
          </ul>
        )}

        {openStreet && (
          <>
            <p className="label">{openStreet}: which stretch?</p>
            <ul className="streets">
              {shownStretches.map((b) => (
                <li key={b.key}>
                  <button
                    className="street street-add"
                    onClick={() => {
                      onAddBlock(b.ids)
                      setOpenStreet(null)
                      setQuery('')
                    }}
                  >
                    <span className="name">
                      {b.between}
                      {b.carriesOn && <span className="carries-on">carries on from your walk</span>}
                    </span>
                    <span className="dist">{formatMiles(b.metres)} mi</span>
                  </button>
                </li>
              ))}
            </ul>
            {stretches.length > SHOWN && (
              <p className="stat-line">
                That is the longest {SHOWN} of {stretches.length}. For a shorter one, tap it on the
                map.
              </p>
            )}
            <button className="btn btn-quiet" onClick={() => setOpenStreet(null)}>
              Pick a different street
            </button>
          </>
        )}

        {carryOn.length > 0 && !openStreet && matches.length === 0 && (
          <>
            <p className="label">Carry on from here</p>
            <ul className="streets">
              {carryOn.map((b) => (
                <li key={b.key}>
                  <button className="street street-add" onClick={() => onAddBlock(b.ids)}>
                    <span className="name">
                      {b.name}
                      <span className="between">{b.between}</span>
                    </span>
                    <span className="dist">{formatMiles(b.metres)} mi</span>
                  </button>
                </li>
              ))}
            </ul>
          </>
        )}

        {claimedSegments.length > 0 && (
          <p className="stat-line">
            {countStreets(claimedSegments)} streets · {formatMiles(pickedMetres)} miles
          </p>
        )}
        <StreetList
          segments={claimedSegments}
          checked={picked}
          covered={covered}
          onToggle={onToggle}
          onToggleMany={onToggleMany}
        />
        <button className="btn btn-primary" onClick={onStartWalking} disabled={claimedSegments.length === 0}>
          Start walking
        </button>
        <button className="btn btn-quiet" onClick={onUseLoop}>
          Give me a loop instead
        </button>
      </div>
    )
  }

  return (
    <div className="sheet">
      {walk.route ? (
        <>
          <p className="route-figure">
            {formatMiles(walk.route.length_m)}
            <span className="unit">miles, back where you started</span>
          </p>
          <p className="stat-line">
            {countStreets(routeSegments)} streets
            {walk.route.new_m > 0 && ` · ${formatMiles(walk.route.new_m)} miles nobody has prayed for yet`}
          </p>
        </>
      ) : (
        <>
          <h1>How long do you have?</h1>
          {busy === 'route' && <p className="spinner">Working out a loop…</p>}
        </>
      )}

      {notice && <p className="notice notice-warn">{notice}</p>}

      {locationDenied && !notice && (
        <p className="notice">
          Location is off, so the loop starts in the middle of town. Tap any street on the map to
          start somewhere else.
        </p>
      )}

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

      <button className="btn btn-primary" onClick={onStartWalking} disabled={!walk.route}>
        {busy === 'route' ? 'Working out a loop…' : 'Start walking'}
      </button>
      <button className="btn btn-quiet" onClick={onManual}>
        Pick streets myself
      </button>
    </div>
  )
}
