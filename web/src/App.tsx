/**
 * Shell and routing.
 *
 * A hash router rather than a library: the whole app is seven screens, and an
 * installed PWA opened from the home screen has to resume on a real route without a
 * server round trip. Hash routes do that with no configuration.
 */
import { useCallback, useEffect, useState } from 'react'
import { api, getToken, setToken } from './api'
import type { ParticipantOut, Walk } from './types'
import ActiveWalk from './screens/ActiveWalk'
import Admin from './screens/Admin'
import Confirm from './screens/Confirm'
import Generate from './screens/Generate'
import Home from './screens/Home'
import Progress from './screens/Progress'
import Register from './screens/Register'

export type Nav = (route: string) => void

function useHashRoute(): [string, Nav] {
  const [route, setRoute] = useState(() => window.location.hash.slice(1) || '/')
  useEffect(() => {
    const onHash = () => setRoute(window.location.hash.slice(1) || '/')
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])
  const nav = useCallback((r: string) => { window.location.hash = r }, [])
  return [route, nav]
}

export default function App() {
  const [route, nav] = useHashRoute()
  const [me, setMe] = useState<ParticipantOut | null>(null)
  const [walk, setWalk] = useState<Walk | null>(null)
  const [loading, setLoading] = useState(true)

  const refreshWalk = useCallback(async () => {
    try { setWalk(await api.current()) } catch { setWalk(null) }
  }, [])

  useEffect(() => {
    (async () => {
      if (!getToken()) { setLoading(false); return }
      try {
        setMe(await api.me())
        await refreshWalk()
      } catch {
        // A token the server does not recognise is worse than no token: it produces
        // 401s on every screen. Drop it and start over.
        setToken(null)
      } finally { setLoading(false) }
    })()
  }, [refreshWalk])

  function signOut() {
    setToken(null); setMe(null); setWalk(null); nav('/')
  }

  if (loading) return <div className="screen"><p className="muted">Loading…</p></div>

  if (!me) return <Register onDone={(p) => { setMe(p); nav('/') }} />

  const screen = (() => {
    if (route.startsWith('/generate')) {
      return <Generate nav={nav} onWalk={setWalk} />
    }
    if (route.startsWith('/walk/')) {
      return <ActiveWalk nav={nav} walkId={route.split('/')[2]} onWalk={setWalk} />
    }
    if (route.startsWith('/confirm/')) {
      return <Confirm nav={nav} walkId={route.split('/')[2]}
                      onDone={() => { setWalk(null); refreshWalk() }} />
    }
    if (route.startsWith('/progress')) return <Progress />
    if (route.startsWith('/admin')) return <Admin me={me} />
    return <Home nav={nav} me={me} walk={walk} />
  })()

  return (
    <div className="app">
      <header className="topbar">
        <button className="brand" onClick={() => nav('/')}>Blacksburg Prayer Walk</button>
        <nav>
          <button onClick={() => nav('/progress')}>Progress</button>
          {me.is_admin && <button onClick={() => nav('/admin')}>Admin</button>}
          <button onClick={signOut} title={`Signed in as ${me.email}`}>Sign out</button>
        </nav>
      </header>
      <main>{screen}</main>
    </div>
  )
}
