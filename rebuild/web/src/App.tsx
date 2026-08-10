import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { MapView } from './map/MapView'
import { BLACKSBURG } from './map/style'
import { api, ApiError } from './data/api'
import { loadCoverage, loadSegments, refreshSegments } from './data/network'
import { bboxOf, claimedByProximity, metresBetween } from './state/geo'
import { clearWalk, deviceId, displayName, emptyWalk, loadWalk, newId, saveWalk, setDisplayName } from './state/walk'
import { enqueue, flushOnce, startFlushLoop, subscribe } from './state/outbox'
import { useLocation } from './hooks/useLocation'
import { useWakeLock } from './hooks/useWakeLock'
import type { OutboxItem, Progress, Segment, WalkState } from './types'
import { TownCounters } from './components/TownCounters'
import { QueueBar } from './components/QueueBar'
import { Home } from './screens/Home'
import { Plan } from './screens/Plan'
import { Walking } from './screens/Walking'
import { Confirm } from './screens/Confirm'
import { Sent } from './screens/Sent'

export function App() {
  const [segments, setSegments] = useState<Segment[]>([])
  const [covered, setCovered] = useState<Set<number>>(new Set())
  const [coverageStale, setCoverageStale] = useState(false)
  const [progress, setProgress] = useState<Progress | null>(null)
  const [walk, setWalk] = useState<WalkState | null>(null)
  const [queue, setQueue] = useState<OutboxItem[]>([])
  const [busy, setBusy] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [name, setName] = useState('')
  const [wantLocation, setWantLocation] = useState(false)
  const [fitTo, setFitTo] = useState<[number, number, number, number] | null>(null)
  const [online, setOnline] = useState(typeof navigator === 'undefined' ? true : navigator.onLine)

  // ---- boot --------------------------------------------------------------
  useEffect(() => {
    let live = true
    void (async () => {
      setWalk(await loadWalk())
      setName(await displayName())
      let current: WalkState | null = null
      try {
        const { segments } = await loadSegments()
        if (live) setSegments(segments)
      } catch {
        setNotice('The street map has not downloaded yet. Open the app once with signal and it will keep working after that.')
      }
      // Street ids hold within a build of the town's street file and not
      // across one, so a rebuilt file has to be said out loud to anyone with a
      // walk already under way.
      void refreshSegments().then(async (fresh) => {
        if (!fresh || !live) return
        setSegments(fresh.segments)
        current = await loadWalk()
        if (fresh.changed && current.phase !== 'idle') {
          setNotice(
            "The town's street file was rebuilt while you were out. Check the streets below before you send this walk.",
          )
        }
      })
      const cov = await loadCoverage()
      if (!live) return
      setCovered(new Set(cov.covered))
      setCoverageStale(cov.fromCache)
      try {
        setProgress(await api.progress())
      } catch {
        /* the counters simply stay quiet offline */
      }
    })()
    const unsub = subscribe(setQueue)
    const stopLoop = startFlushLoop()
    const on = () => setOnline(true)
    const off = () => setOnline(false)
    window.addEventListener('online', on)
    window.addEventListener('offline', off)
    return () => {
      live = false
      unsub()
      stopLoop()
      window.removeEventListener('online', on)
      window.removeEventListener('offline', off)
    }
  }, [])

  const segById = useMemo(() => new Map(segments.map((s) => [s.seg_id, s])), [segments])

  // With no signal the counters are worked out from the copies already on the
  // phone rather than left blank. Same arithmetic the server does.
  const shownProgress = useMemo<Progress | null>(() => {
    if (progress) return progress
    if (!segments.length) return null
    const total_m = segments.reduce((sum, s) => sum + s.length_m, 0)
    const covered_m = segments.reduce((sum, s) => (covered.has(s.seg_id) ? sum + s.length_m : sum), 0)
    return {
      segments_covered: covered.size,
      segments_total: segments.length,
      covered_m,
      total_m,
      percent: total_m ? Math.round((covered_m / total_m) * 10000) / 100 : 0,
      homes_covered: null,
      homes_total: null,
    }
  }, [progress, segments, covered])

  const update = useCallback((patch: Partial<WalkState>) => {
    setWalk((prev) => {
      if (!prev) return prev
      const next = { ...prev, ...patch }
      void saveWalk(next) // every change hits IndexedDB before it hits the screen
      return next
    })
  }, [])

  const refreshTown = useCallback(async () => {
    const cov = await loadCoverage()
    setCovered(new Set(cov.covered))
    setCoverageStale(cov.fromCache)
    try {
      setProgress(await api.progress())
    } catch {
      /* keep the last numbers */
    }
  }, [])

  // When a queued walk lands, the town map moves.
  const sentCount = queue.filter((q) => q.status === 'sent').length
  useEffect(() => {
    if (sentCount > 0) void refreshTown()
  }, [sentCount, refreshTown])

  // ---- location and screen -----------------------------------------------
  const watching = (walk?.phase === 'walking' && !walk.manual) || wantLocation
  const { status: locStatus, fix } = useLocation(watching)
  useWakeLock(walk?.phase === 'walking')

  const locationDenied = locStatus === 'denied' || locStatus === 'unsupported'

  // Streets tick themselves off as you pass them. This runs on the phone,
  // against the street file the phone already has.
  const lastFixRef = useRef<number>(0)
  useEffect(() => {
    if (!walk || walk.phase !== 'walking' || !fix) return
    const point: [number, number] = [fix.lon, fix.lat]
    const last = walk.trace[walk.trace.length - 1]
    const moved = !last || metresBetween([last.lon, last.lat], point) > 12 || fix.t - last.t > 20
    const routeSegs = walk.route
      ? (walk.route.seg_ids.map((id) => segById.get(id)).filter(Boolean) as Segment[])
      : []
    const near = claimedByProximity(point, fix.accuracy_m, routeSegs.length ? routeSegs : segments)
    const already = new Set(walk.claimed)
    const add = near.filter((id) => !already.has(id))
    if (!moved && add.length === 0) return
    if (fix.t === lastFixRef.current && add.length === 0) return
    lastFixRef.current = fix.t
    update({
      trace: moved ? [...walk.trace, fix].slice(-4000) : walk.trace,
      claimed: add.length ? [...walk.claimed, ...add] : walk.claimed,
    })
  }, [fix, walk, segById, segments, update])

  // ---- actions -----------------------------------------------------------

  const startPlanning = useCallback(() => {
    setNotice(null)
    setWantLocation(true)
    update({
      phase: 'planning',
      client_walk_id: newId(),
      started_at: null,
      route: null,
      claimed: [],
      suggested: [],
      trace: [],
      manual: false,
      start: null,
    })
  }, [update])

  const chooseMinutes = useCallback(
    async (minutes: number) => {
      if (!walk) return
      const start = walk.start ?? (fix ? { lon: fix.lon, lat: fix.lat } : BLACKSBURG)
      setBusy('route')
      setNotice(null)
      try {
        const route = await api.route(start.lon, start.lat, minutes)
        update({ minutes, start, route, manual: false })
        if (route.geometry) setFitTo(bboxOf(route.geometry.coordinates))
      } catch (e) {
        const msg =
          e instanceof ApiError && e.status === 503
            ? 'Route planning is not running yet. Pick the streets you want to walk and go.'
            : 'Could not build a route just now. Pick the streets you want to walk and go.'
        setNotice(msg)
        update({ minutes, start, route: null, manual: true })
      } finally {
        setBusy(null)
      }
    },
    [walk, fix, update],
  )

  const goManual = useCallback(() => {
    setNotice(null)
    update({ manual: true, route: null })
  }, [update])

  const tapSegment = useCallback(
    (seg: { seg_id: number; name: string }) => {
      if (!walk) return
      if (walk.phase === 'planning' && !walk.manual) {
        const s = segById.get(seg.seg_id)
        if (!s) return
        const [lon, lat] = s.geometry.coordinates[0]
        update({ start: { lon, lat } })
        void chooseMinutes(walk.minutes)
        return
      }
      const has = walk.claimed.includes(seg.seg_id)
      update({
        claimed: has ? walk.claimed.filter((id) => id !== seg.seg_id) : [...walk.claimed, seg.seg_id],
      })
    },
    [walk, segById, update, chooseMinutes],
  )

  /** Add every stretch of a named street. The list below can trim it back. */
  const addByName = useCallback(
    (name: string) => {
      if (!walk) return
      const has = new Set(walk.claimed)
      const add = segments.filter((s) => s.name === name && !has.has(s.seg_id)).map((s) => s.seg_id)
      if (add.length) update({ claimed: [...walk.claimed, ...add] })
    },
    [walk, segments, update],
  )

  const startWalking = useCallback(() => {
    if (!walk) return
    const claimed = walk.claimed
    update({ phase: 'walking', started_at: new Date().toISOString(), claimed })
    setWantLocation(true)
  }, [walk, update])

  const finishWalk = useCallback(() => update({ phase: 'confirming' }), [update])

  const matchTrace = useCallback(async () => {
    if (!walk || walk.trace.length === 0) return
    setBusy('match')
    setNotice(null)
    try {
      const { proposals } = await api.match(walk.trace)
      // Anything the matcher is sure of gets ticked. Anything it is unsure of
      // is put in front of the walker unticked, for them to decide. The engine
      // draws that line itself at a confidence of 0.5.
      const strong = proposals.filter((p) => p.confidence >= 0.5).map((p) => p.seg_id)
      const claimed = Array.from(new Set([...walk.claimed, ...strong]))
      const weak = proposals
        .filter((p) => p.confidence < 0.5 && !claimed.includes(p.seg_id))
        .map((p) => p.seg_id)
      update({ claimed, suggested: Array.from(new Set([...walk.suggested, ...weak])) })
      if (proposals.length === 0) setNotice('Nothing in your track matched a street closely enough to be sure.')
      else if (strong.length === 0 && weak.length > 0)
        setNotice('These are the closest streets to your track. Tick the ones you actually walked.')
    } catch (e) {
      setNotice(
        e instanceof ApiError && e.status === 503
          ? 'Street matching is not running yet. Tick the streets you walked and they will count the same.'
          : 'Could not check your track just now. Tick the streets you walked and they will count the same.',
      )
    } finally {
      setBusy(null)
    }
  }, [walk, update])

  const confirmWalk = useCallback(async () => {
    if (!walk || walk.claimed.length === 0) return
    setBusy('confirm')
    const id = await deviceId()
    await setDisplayName(name)
    await enqueue({
      device_id: id,
      client_walk_id: walk.client_walk_id,
      display_name: name || null,
      started_at: walk.started_at,
      seg_ids: walk.claimed,
    })
    update({ phase: 'sent' })
    setBusy(null)
    void flushOnce()
  }, [walk, name, update])

  const discard = useCallback(async () => {
    await clearWalk()
    setWalk(emptyWalk())
    setFitTo(null)
    setNotice(null)
    setWantLocation(false)
  }, [])

  const done = useCallback(async () => {
    await clearWalk()
    setWalk(emptyWalk())
    setFitTo(null)
    setWantLocation(false)
    void refreshTown()
  }, [refreshTown])

  // ---- render ------------------------------------------------------------

  const claimedSegments = useMemo(
    () => (walk ? (walk.claimed.map((id) => segById.get(id)).filter(Boolean) as Segment[]) : []),
    [walk, segById],
  )

  const suggestedSegments = useMemo(
    () =>
      walk
        ? (walk.suggested
            .filter((id) => !walk.claimed.includes(id))
            .map((id) => segById.get(id))
            .filter(Boolean) as Segment[])
        : [],
    [walk, segById],
  )

  const routeSegments = useMemo(
    () =>
      walk?.route
        ? (Array.from(new Set(walk.route.seg_ids))
            .map((id) => segById.get(id))
            .filter(Boolean) as Segment[])
        : [],
    [walk, segById],
  )

  const thisWalkItem = walk ? queue.find((q) => q.client_walk_id === walk.client_walk_id) : undefined

  return (
    <div className="app">
      <MapView
        segments={segments}
        covered={covered}
        claimed={walk?.claimed ?? []}
        route={walk?.route?.geometry ?? null}
        walker={watching ? fix : null}
        follow={walk?.phase === 'walking'}
        tappable={walk?.phase === 'planning' || walk?.phase === 'walking' || walk?.phase === 'confirming'}
        onTapSegment={tapSegment}
        fitTo={fitTo}
      />

      {(!online || queue.some((q) => q.status !== 'sent')) && (
        <QueueBar online={online} queue={queue} />
      )}

      <div
        className={
          walk?.phase === 'walking' || walk?.phase === 'confirming' ? 'top top-compact' : 'top'
        }
      >
        <TownCounters progress={shownProgress} stale={coverageStale} />
      </div>

      {walk?.phase === 'idle' && (
        <Home
          onStart={startPlanning}
          segmentsReady={segments.length > 0}
          notice={notice}
        />
      )}

      {walk?.phase === 'planning' && (
        <Plan
          walk={walk}
          busy={busy}
          notice={notice}
          locationDenied={locationDenied}
          locationOn={locStatus === 'on'}
          claimedSegments={claimedSegments}
          routeSegments={routeSegments}
          allSegments={segments}
          covered={covered}
          onChooseMinutes={chooseMinutes}
          onManual={goManual}
          onStartWalking={startWalking}
          onToggle={(id) => tapSegment({ seg_id: id, name: '' })}
          onAddByName={addByName}
          onCancel={discard}
        />
      )}

      {walk?.phase === 'walking' && (
        <Walking
          walk={walk}
          locationOn={locStatus === 'on'}
          locationDenied={locationDenied}
          claimedSegments={claimedSegments}
          routeSegments={routeSegments}
          covered={covered}
          onToggle={(id) => tapSegment({ seg_id: id, name: '' })}
          onFinish={finishWalk}
        />
      )}

      {walk?.phase === 'confirming' && (
        <Confirm
          walk={walk}
          busy={busy}
          notice={notice}
          name={name}
          onName={setName}
          claimedSegments={claimedSegments}
          suggestedSegments={suggestedSegments}
          covered={covered}
          onToggle={(id) => tapSegment({ seg_id: id, name: '' })}
          onMatch={matchTrace}
          onConfirm={confirmWalk}
          onDiscard={discard}
        />
      )}

      {walk?.phase === 'sent' && (
        <Sent item={thisWalkItem} claimedSegments={claimedSegments} onDone={done} />
      )}
    </div>
  )
}
