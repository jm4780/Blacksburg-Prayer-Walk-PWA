import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { MapView } from './map/MapView'
import { BLACKSBURG } from './map/style'
import { api, ApiError } from './data/api'
import { loadCoverage, loadProgress, loadSegments, refreshSegments } from './data/network'
import { bboxOf, claimedByProximity, metresBetween } from './state/geo'
import { buildStreetIndex } from './state/streets'
import { clearWalk, deviceId, displayName, emptyWalk, loadWalk, newId, saveWalk } from './state/walk'
import { enqueue, flushOnce, startFlushLoop, subscribe } from './state/outbox'
import { useLocation } from './hooks/useLocation'
import { useWakeLock } from './hooks/useWakeLock'
import type { OutboxItem, Progress, Segment, WalkState } from './types'
import { TownCounters } from './components/TownCounters'
import { QueueBar } from './components/QueueBar'
import { Plan } from './screens/Plan'
import { Walking } from './screens/Walking'
import { Confirm } from './screens/Confirm'
import { Sent } from './screens/Sent'

export function App() {
  const [segments, setSegments] = useState<Segment[]>([])
  const [covered, setCovered] = useState<Set<number>>(new Set())
  const [coverageStale, setCoverageStale] = useState(false)
  const [progressStale, setProgressStale] = useState(false)
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
        const inProgress = await loadWalk()
        if (fresh.changed && inProgress.phase !== 'idle') {
          setNotice(
            "The town's street file was rebuilt while you were out. Check the streets below before you send this walk.",
          )
        }
      })
      const cov = await loadCoverage()
      if (!live) return
      setCovered(new Set(cov.covered))
      setCoverageStale(cov.fromCache)
      const p = await loadProgress()
      if (p.progress) setProgress(p.progress)
      setProgressStale(p.fromCache)
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

  // Junctions, worked out on the phone from the street file it already holds.
  const streetIndex = useMemo(() => buildStreetIndex(segments), [segments])


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
    const p = await loadProgress()
    if (p.progress) setProgress(p.progress)
    setProgressStale(p.fromCache)
  }, [])

  // When a queued walk lands, the town map moves.
  const sentCount = queue.filter((q) => q.status === 'sent').length
  useEffect(() => {
    if (sentCount > 0) void refreshTown()
  }, [sentCount, refreshTown])

  // ---- location and screen -----------------------------------------------
  const watching =
    walk?.phase === 'planning' || (walk?.phase === 'walking' && !walk.manual) || wantLocation
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

  /**
   * Opening the app is the walker saying they want to walk. There was a screen
   * before this one whose only button led here, and a loop nobody had asked for
   * yet, so the app sat waiting to be told twice. It plans the ordinary walk
   * straight away instead: the length already has a default, and the walker
   * standing in a car park should find a loop drawn and one button on it.
   */
  useEffect(() => {
    if (walk?.phase === 'idle' && segments.length > 0) startPlanning()
  }, [walk?.phase, segments.length, startPlanning])

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

  /**
   * The default length, planned as soon as the app knows where it is standing.
   *
   * It waits for location to come back one way or the other. Routing from the
   * middle of town and then quietly re-routing under the walker would be worse
   * than the short wait, and a denied answer is an answer: the loop starts in
   * the middle of town and the screen says so.
   */
  const plannedFor = useRef<string | null>(null)
  useEffect(() => {
    if (!walk || walk.phase !== 'planning' || walk.manual || walk.route) return
    if (!segments.length || busy === 'route') return
    if (!fix && !locationDenied) return
    if (plannedFor.current === walk.client_walk_id) return
    plannedFor.current = walk.client_walk_id
    void chooseMinutes(walk.minutes)
  }, [walk, segments.length, busy, fix, locationDenied, chooseMinutes])

  const goManual = useCallback(() => {
    setNotice(null)
    update({ manual: true, route: null })
  }, [update])

  /** Back out of picking by hand to the loop the app would have given you. */
  const useLoop = useCallback(() => {
    if (!walk) return
    setNotice(null)
    plannedFor.current = null
    update({ manual: false, claimed: [] })
  }, [walk, update])

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

  /** Tick or untick a whole street at once. One state write, not one per
   *  segment: the per-segment handler closes over `walk`, so calling it in a
   *  loop would have every call read the same stale list and only the last
   *  would survive. */
  const setClaimed = useCallback(
    (ids: number[], on: boolean) => {
      if (!walk) return
      const touched = new Set(ids)
      const kept = walk.claimed.filter((id) => !touched.has(id))
      update({ claimed: on ? [...kept, ...ids] : kept })
    },
    [walk, update],
  )

  /**
   * Add one stretch of street: the run between two corners the walker just
   * picked out by name, and nothing else.
   *
   * This used to add every segment in town carrying that name. Tapping
   * "US 460 Bus" claimed eighty-one segments and ten miles, 6.4% of Blacksburg,
   * from a walker who meant two blocks. Coverage is permanent and a phone
   * screen cannot show ten miles of list, so the confirm step could not catch
   * it. Now a tap can only ever claim what the walker was shown, corner to
   * corner.
   */
  const addBlock = useCallback((ids: number[]) => setClaimed(ids, true), [setClaimed])

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
    // A name box sat above this button asking for something nothing in the app
    // ever shows back. It put a keyboard between a walker in a car park and the
    // one tap that matters. A name already saved on the phone still rides
    // along, so nobody who set one loses it.
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
        /* Once the walk is sent, the route is no longer the way you are being
           sent — it is nothing. Leaving it drawn spends the one colour that
           means "go this way" on a screen where there is nowhere to go. */
        route={walk && walk.phase !== 'sent' ? (walk.route?.geometry ?? null) : null}
        walker={watching ? fix : null}
        follow={walk?.phase === 'walking'}
        tappable={walk?.phase === 'planning' || walk?.phase === 'walking' || walk?.phase === 'confirming'}
        onTapSegment={tapSegment}
        fitTo={fitTo}
      />

      {(!online || queue.some((q) => q.status !== 'sent')) && (
        <QueueBar online={online} queue={queue} />
      )}

      {/* The town's figure is the point of the whole thing, and it is the wrong
          thing to read while walking: it is not the next move, and at that size
          it takes the top of the map away from the route. It comes back the
          moment the walk is over, with the walk counted in it. */}
      {walk?.phase !== 'walking' && (
        <div className={walk?.phase === 'confirming' ? 'top top-compact' : 'top'}>
          <TownCounters progress={progress} stale={progressStale || coverageStale} />
        </div>
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
          streetIndex={streetIndex}
          onChooseMinutes={chooseMinutes}
          onManual={goManual}
          onUseLoop={useLoop}
          onStartWalking={startWalking}
          onToggle={(id) => tapSegment({ seg_id: id, name: '' })}
          onToggleMany={setClaimed}
          onAddBlock={addBlock}
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
          onToggleMany={setClaimed}
          onFinish={finishWalk}
        />
      )}

      {walk?.phase === 'confirming' && (
        <Confirm
          walk={walk}
          busy={busy}
          notice={notice}
          claimedSegments={claimedSegments}
          suggestedSegments={suggestedSegments}
          covered={covered}
          onToggle={(id) => tapSegment({ seg_id: id, name: '' })}
          onToggleMany={setClaimed}
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
