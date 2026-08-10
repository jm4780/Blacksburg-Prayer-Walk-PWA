/**
 * Location, if the walker allows it.
 *
 * Location is a convenience here, never a requirement. Every screen works with
 * it switched off, and the app asks for it once, at the moment it would help,
 * rather than at the door.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import type { Fix } from '../types'

export type LocationStatus = 'off' | 'asking' | 'on' | 'denied' | 'unsupported' | 'error'

export function useLocation(watch: boolean) {
  const [status, setStatus] = useState<LocationStatus>('off')
  const [fix, setFix] = useState<Fix | null>(null)
  const watchId = useRef<number | null>(null)

  const stop = useCallback(() => {
    if (watchId.current !== null) {
      navigator.geolocation.clearWatch(watchId.current)
      watchId.current = null
    }
  }, [])

  const start = useCallback(() => {
    if (typeof navigator === 'undefined' || !navigator.geolocation) {
      setStatus('unsupported')
      return
    }
    setStatus((s) => (s === 'on' ? s : 'asking'))
    stop()
    watchId.current = navigator.geolocation.watchPosition(
      (pos) => {
        setStatus('on')
        setFix({
          lat: pos.coords.latitude,
          lon: pos.coords.longitude,
          accuracy_m: pos.coords.accuracy ?? 30,
          t: Math.round(pos.timestamp / 1000),
        })
      },
      (err) => {
        setStatus(err.code === err.PERMISSION_DENIED ? 'denied' : 'error')
      },
      { enableHighAccuracy: true, maximumAge: 5000, timeout: 20000 },
    )
  }, [stop])

  useEffect(() => {
    if (watch) start()
    else stop()
    return stop
  }, [watch, start, stop])

  return { status, fix, start, stop }
}

/** One reading, for choosing a starting point. Never starts a watch. */
export function locateOnce(): Promise<Fix | null> {
  return new Promise((resolve) => {
    if (typeof navigator === 'undefined' || !navigator.geolocation) return resolve(null)
    navigator.geolocation.getCurrentPosition(
      (pos) =>
        resolve({
          lat: pos.coords.latitude,
          lon: pos.coords.longitude,
          accuracy_m: pos.coords.accuracy ?? 30,
          t: Math.round(pos.timestamp / 1000),
        }),
      () => resolve(null),
      { enableHighAccuracy: true, timeout: 8000, maximumAge: 30000 },
    )
  })
}
