/**
 * Which build am I looking at?
 *
 * Temporary, and deliberately visible on every screen. It exists because a Phase 3.5
 * preview looked identical to the previous version on a phone and there was no way to
 * tell, from the app, whether that was a stale checkout, a stale bundle, a stale
 * service worker or a real bug.
 *
 * It shows two identities and compares them:
 *
 *   APP     the commit this JavaScript bundle was built from (stamped at build time)
 *   SERVER  the commit the process answering /api/version is running
 *
 * If they disagree, the browser is running an old bundle — that is the stale-cache
 * case, and the badge says so and offers the one-tap fix rather than describing it.
 * If the server reports old network data, it says that too.
 *
 * Remove this once previewing is boring again.
 */
import { useEffect, useState } from 'react'

declare const __BUILD_ID__: string
declare const __BUILT_AT__: string

const APP_BUILD = typeof __BUILD_ID__ === 'string' ? __BUILD_ID__ : 'unknown'
const APP_BUILT_AT = typeof __BUILT_AT__ === 'string' ? __BUILT_AT__ : ''

interface ServerBuild {
  build_id: string
  branch: string | null
  dirty: boolean
  started_at: string
}

export default function BuildBadge() {
  const [server, setServer] = useState<ServerBuild | null>(null)
  const [data, setData] = useState<{ neighborhoods: number; note: string | null } | null>(null)
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    // cache: 'no-store' on purpose — asking "which build is this?" through a cache
    // is how you get the wrong answer to exactly the question that matters.
    fetch('/api/version', { cache: 'no-store' })
      .then((r) => r.json()).then(setServer).catch(() => {})
    fetch('/api/health', { cache: 'no-store' })
      .then((r) => r.json()).then((h) => setData(h.network_data)).catch(() => {})
  }, [])

  const serverId = server ? server.build_id + (server.dirty ? '+edits' : '') : null
  // Compare the commit only. The app stamp may carry "+edits" from a build made with
  // a dirty tree, and that on its own is not a mismatch worth alarming about.
  const mismatch = Boolean(serverId && APP_BUILD !== 'unknown'
    && APP_BUILD.split('+')[0] !== serverId.split('+')[0])
  const staleData = Boolean(data && data.neighborhoods === 0)

  /** Drop every cache and service worker, then reload from the network. */
  async function forceRefresh() {
    setBusy(true)
    try {
      if ('serviceWorker' in navigator) {
        const regs = await navigator.serviceWorker.getRegistrations()
        await Promise.all(regs.map((r) => r.unregister()))
      }
      if ('caches' in window) {
        const keys = await caches.keys()
        await Promise.all(keys.map((k) => caches.delete(k)))
      }
    } catch { /* nothing here is worth blocking the reload for */ }
    // Cache-busted so the shell itself cannot come from a cache we just cleared.
    window.location.replace(`${window.location.pathname}?fresh=${Date.now()}${window.location.hash}`)
  }

  return (
    <div className={mismatch || staleData ? 'buildbadge warn' : 'buildbadge'}>
      <button type="button" onClick={() => setOpen(!open)} aria-expanded={open}>
        build <strong>{APP_BUILD}</strong>
        {mismatch && <span className="bb-flag"> · stale</span>}
        {!mismatch && staleData && <span className="bb-flag"> · old map data</span>}
      </button>

      {open && (
        <div className="bb-detail">
          <dl>
            <div><dt>App bundle</dt><dd>{APP_BUILD}</dd></div>
            <div><dt>Built</dt><dd>{APP_BUILT_AT || 'unknown'}</dd></div>
            <div><dt>Server</dt><dd>{serverId ?? 'unreachable'}</dd></div>
            <div><dt>Branch</dt><dd>{server?.branch ?? '—'}</dd></div>
            <div><dt>Neighbourhoods</dt><dd>{data ? data.neighborhoods : '—'}</dd></div>
          </dl>

          {mismatch && (
            <p className="bb-msg">
              This phone is running an older copy of the app than the server. That is
              a cache, not a broken build — clear it below.
            </p>
          )}
          {staleData && (
            <p className="bb-msg">
              {data?.note}
            </p>
          )}

          <button type="button" className="secondary" disabled={busy}
                  onClick={forceRefresh}>
            {busy ? 'Clearing…' : 'Clear cache and load the newest build'}
          </button>
        </div>
      )}
    </div>
  )
}
