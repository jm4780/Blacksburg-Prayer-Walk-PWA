/**
 * Shell and routing.
 *
 * A hash router rather than a library: the whole app is a handful of screens, and an
 * installed PWA opened from the home screen has to resume on a real route without a
 * server round trip. Hash routes do that with no configuration.
 *
 * Identity is no longer a wall in front of the app (Priority 2). `me` may be null on
 * every screen. The screens that genuinely need a person — an active walk, the
 * confirmation, admin — say so when they are reached; the ones that do not, don't ask.
 */
import { useCallback, useEffect, useState } from 'react'
import { api, getToken, isAuthFailure, isOffline, setToken } from './api'
import type { ParticipantOut, Walk } from './types'
import BuildBadge from './components/BuildBadge'
import IdentityGate from './components/IdentityGate'
import ActiveWalk from './screens/ActiveWalk'
import Admin from './screens/Admin'
import Confirm from './screens/Confirm'
import Dashboard from './screens/Dashboard'
import Generate from './screens/Generate'
import MapSystem from './screens/MapSystem'
import Mission from './screens/Mission'

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
  // Set when the shell could not reach the server at boot and we kept the token
  // anyway. It is the difference between "we do not know you" and "we could not ask".
  const [offline, setOffline] = useState(false)

  const refreshWalk = useCallback(async () => {
    if (!getToken()) { setWalk(null); return }
    // An unreachable server is not evidence that the walk ended. Leave whatever we
    // already know on screen rather than replacing a real walk with nothing.
    try { setWalk(await api.current()) } catch (e) { if (!isOffline(e)) setWalk(null) }
  }, [])

  useEffect(() => {
    (async () => {
      if (!getToken()) { setLoading(false); return }
      try {
        setMe(await api.me())
        await refreshWalk()
      } catch (e) {
        // ONLY the server saying "not you" drops the token. A token the server does
        // not recognise is worse than no token — it produces 401s on every screen —
        // but a request that never got an answer says nothing about the token at all.
        //
        // This used to be a bare `catch`, and the cost of that was specific and bad:
        // a walker who lost signal for one page load, mid-walk, was signed out and
        // shown "This walk belongs to somebody. Sign in to open it." They could not
        // sign back in either, because registering is a network call. Standing
        // outside, halfway through, is the exact circumstance this app exists for.
        if (isAuthFailure(e)) {
          setToken(null)
        } else {
          // Keep the token and say so. The screens fetch their own data and will
          // report their own failures; what matters here is that we did not decide
          // a person was a stranger because their phone had one bar.
          setOffline(true)
        }
      } finally { setLoading(false) }
    })()
  }, [refreshWalk])

  const adopt = useCallback((p: ParticipantOut) => { setMe(p); refreshWalk() },
    [refreshWalk])

  // Requirements 3 and 9: the town map is no longer a separate destination — it lives
  // on the dashboard. The route survives only as a redirect, so a bookmark or a link
  // shared during the pilot still lands somewhere sensible.
  useEffect(() => {
    if (route.startsWith('/progress')) nav('/')
  }, [route, nav])

  function switchPerson() {
    // Drops the opaque token only. The participant record, and everything walked
    // under it, stays on the server and is recovered by signing in with the same
    // email — which is the whole reason identity is not stored in the browser.
    setToken(null); setMe(null); setWalk(null); nav('/')
  }

  /*
   * The first paint of the whole app, and for a returning walker it is two network
   * round trips long — /me and then /walks/current. It was a `.screen`, which is the
   * inner-page shell: a different ground from the dashboard that lands immediately
   * after it, so opening the app from the home screen flashed one colour and then
   * repainted in another. An install that changes colour on launch reads as broken
   * before anybody has done anything.
   *
   * `.dash` is the dashboard's own root — fixed to the viewport, dark ground, safe
   * areas — so the first frame is already the frame the dashboard arrives in and only
   * the content fills in. `.dash-mission` carries the page gutter and `.dash-label`
   * the system-label treatment, both borrowed rather than rebuilt.
   */
  if (loading) {
    return (
      <div className="dash">
        <section className="dash-mission">
          {/* A div, exactly as Dashboard writes its own label — `.dash-mission p` is
              the mission-statement paragraph and this is not that. */}
          <div className="dash-label" role="status">Loading…</div>
        </section>
      </div>
    )
  }

  /**
   * Screens that record something against a person. Reached without one, they ask.
   *
   * Unless we are holding a token we simply could not check. Asking "who is walking?"
   * of somebody who is already signed in, because their signal dropped, is the worst
   * sentence this app can produce: it reads as "your walk is gone", it is false, and
   * the sign-in they are being offered is itself a network call that will also fail.
   * Say what is actually true and give them the one button that can help.
   */
  const gate = (reason: string) => {
    if (offline && getToken()) {
      return (
        <div className="screen">
          <h1>No signal</h1>
          <p className="lede">
            You are still signed in. We just could not reach the server to load this
            screen.
          </p>
          <p className="muted">
            Your walk and everything you have prayed for are on the server, not on this
            phone. Nothing has been lost.
          </p>
          <div className="actions">
            <button className="primary big" onClick={() => window.location.reload()}>
              Try again
            </button>
            <button className="secondary" onClick={() => nav('/')}>Back to home</button>
          </div>
        </div>
      )
    }
    return (
      <div className="screen">
        <IdentityGate reason={reason} onDone={adopt} onCancel={() => nav('/')} />
      </div>
    )
  }

  const screen = (() => {
    // The map system's specimen sheet. Not in any navigation — a reference for
    // whoever is working on the cartography, not a screen for walkers.
    if (route.startsWith('/map-system')) return <MapSystem />
    if (route.startsWith('/mission')) {
      return <Mission nav={nav} me={me} onIdentity={adopt} onWalk={setWalk} />
    }
    if (route.startsWith('/generate')) {
      return me
        ? <Generate nav={nav} onWalk={setWalk} />
        : gate('Finding a walk from where you are standing records a route request, '
               + 'so we ask who you are first.')
    }
    if (route.startsWith('/walk/')) {
      return me
        ? <ActiveWalk nav={nav} walkId={route.split('/')[2]} onWalk={setWalk} />
        : gate('This walk belongs to somebody. Sign in to open it.')
    }
    if (route.startsWith('/confirm/')) {
      return me
        ? <Confirm nav={nav} walkId={route.split('/')[2]}
                   onDone={() => { setWalk(null); refreshWalk() }} />
        : gate('This walk belongs to somebody. Sign in to record it.')
    }
    if (route.startsWith('/admin')) {
      return me ? <Admin me={me} /> : gate('Administration requires an account.')
    }
    return <Dashboard nav={nav} me={me} walk={walk} />
  })()

  // Mission control is full-bleed by design: it owns the whole viewport and carries
  // its own header. The shared chrome would sit on top of it.
  const bare = route === '/' || route === '' || route.startsWith('/progress')
    || route.startsWith('/map-system')
  if (bare) return <><main>{screen}</main><BuildBadge /></>

  return (
    <div className="app">
      <header className="topbar">
        <button className="brand" onClick={() => nav('/')}>Blacksburg Prayer Walk</button>
        <nav>
          {me?.is_admin && <button onClick={() => nav('/admin')}>Admin</button>}
        </nav>
      </header>
      {/* §5: a returning walker should see who the app thinks they are, and be able
          to say it is not them — this is a shared-phone situation as often as not.
          Anonymous visitors get no such bar; there is nothing to correct. */}
      {me && (
        <div className="whoami">
          <span>Walking as <strong>{me.first_name} {me.last_name}</strong></span>
          <button className="link" onClick={switchPerson}>Not you? Switch person</button>
        </div>
      )}
      <main>{screen}</main>
      {/* Temporary, while previews are being verified on real phones. */}
      <BuildBadge />
    </div>
  )
}
