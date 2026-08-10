/**
 * Keeps the screen awake while a walk is running, where the browser allows it.
 * Where it does not, nothing breaks and nothing is said: the walk works the
 * same, the screen just sleeps.
 */

import { useEffect, useRef, useState } from 'react'

type Sentinel = { released: boolean; release: () => Promise<void> }

export function useWakeLock(active: boolean) {
  const [held, setHeld] = useState(false)
  const ref = useRef<Sentinel | null>(null)
  const supported =
    typeof navigator !== 'undefined' && 'wakeLock' in navigator && 'request' in (navigator as never)

  useEffect(() => {
    let cancelled = false
    const nav = navigator as unknown as {
      wakeLock?: { request: (t: 'screen') => Promise<Sentinel> }
    }

    async function acquire() {
      if (!active || !nav.wakeLock) return
      try {
        const s = await nav.wakeLock.request('screen')
        if (cancelled) {
          void s.release()
          return
        }
        ref.current = s
        setHeld(true)
        ;(s as unknown as { addEventListener?: (t: string, f: () => void) => void }).addEventListener?.(
          'release',
          () => setHeld(false),
        )
      } catch {
        // Denied, unsupported, or the tab is hidden. Not worth a word on screen.
        setHeld(false)
      }
    }

    const onVisible = () => {
      if (document.visibilityState === 'visible' && active) void acquire()
    }

    void acquire()
    document.addEventListener('visibilitychange', onVisible)

    return () => {
      cancelled = true
      document.removeEventListener('visibilitychange', onVisible)
      const s = ref.current
      ref.current = null
      setHeld(false)
      if (s && !s.released) void s.release().catch(() => {})
    }
  }, [active])

  return { held, supported: Boolean(supported) }
}
