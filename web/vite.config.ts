import { execSync } from 'node:child_process'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'

/**
 * Stamp the bundle with the commit it was built from.
 *
 * This is what makes a stale frontend visible. The server reports its own commit
 * separately; when the two disagree, the browser or the service worker is holding an
 * old bundle, and the app says so on screen instead of leaving it to be guessed at.
 *
 * Falls back to BPW_BUILD_ID, then to 'unknown' — a build outside a git checkout
 * should still build.
 */
function buildStamp() {
  const run = (cmd: string) => {
    try { return execSync(cmd, { stdio: ['ignore', 'pipe', 'ignore'] }).toString().trim() }
    catch { return '' }
  }
  const commit = run('git rev-parse --short=7 HEAD')
  const dirty = run('git status --porcelain') ? '+edits' : ''
  return {
    id: (commit ? commit + dirty : process.env.BPW_BUILD_ID || 'unknown'),
    at: new Date().toISOString().replace(/\.\d+Z$/, 'Z'),
  }
}

const STAMP = buildStamp()

export default defineConfig({
  define: {
    __BUILD_ID__: JSON.stringify(STAMP.id),
    __BUILT_AT__: JSON.stringify(STAMP.at),
  },
  plugins: [
    react(),
    VitePWA({
      registerType: 'autoUpdate',
      includeAssets: ['icon.svg'],
      manifest: {
        name: 'Blacksburg Prayer Walk',
        short_name: 'Prayer Walk',
        description: 'Pray for Blacksburg, one street at a time.',
        theme_color: '#1f3d2b',
        background_color: '#faf9f6',
        display: 'standalone',
        orientation: 'portrait',
        start_url: '/',
        scope: '/',
        icons: [
          { src: 'icon.svg', sizes: 'any', type: 'image/svg+xml', purpose: 'any maskable' },
        ],
      },
      workbox: {
        // NOTE the missing `html`. Assets are content-hashed, so precaching them is
        // safe and permanent. index.html is not hashed — it is the file that names
        // which asset hashes to load — so precaching it pins the whole app to the
        // build that was current when the service worker last updated.
        //
        // That is what made a Phase 3.5 preview look identical to Phase 3.1 on a
        // phone: correct server, correct commit, and an installed PWA serving the
        // previous shell out of its own cache. On iOS a Home Screen app can hold
        // that shell across launches, so "reload the page" does not clear it.
        //
        // index.html is now NetworkFirst: online, every launch fetches the current
        // shell and therefore the current build; offline, the last good one is still
        // served, so an installed app still opens on a walk with no signal.
        //
        // The basemap is in here on purpose. `pmtiles` is the ~4.4 MB regional
        // archive and `basemap/*.json` is the style that names it; together they are
        // the whole map, and precaching them is what makes the map work on a walk
        // with no signal. Workbox revisions them, so a rebuilt archive replaces the
        // old one instead of accumulating.
        //
        // The archive is read by src/map/basemap.ts, which is written to accept the
        // full 200 response a precache returns to a range request — pmtiles' own
        // FetchSource throws on that, which would break the map offline and only
        // offline. See the comment there before changing either side.
        globPatterns: ['**/*.{js,css,svg,pmtiles}', 'basemap/*.json'],
        // Default is 2 MiB, which silently drops the archive from the manifest.
        maximumFileSizeToCacheInBytes: 16 * 1024 * 1024,
        cleanupOutdatedCaches: true,
        clientsClaim: true,
        skipWaiting: true,
        // Must be null, not merely absent. vite-plugin-pwa otherwise emits
        // `createHandlerBoundToURL('index.html')`, which throws `non-precached-url`
        // now that index.html is deliberately not in the precache manifest — killing
        // the whole service worker registration. The navigation route below replaces
        // it, and the FastAPI catch-all already serves index.html for deep links.
        navigateFallback: null,
        // API responses are NOT cached: a stale completion state would show a walker
        // streets that someone else has since prayed for, and silently rewarding a
        // duplicate walk is worse than an honest offline message.
        runtimeCaching: [
          {
            urlPattern: ({ request }: { request: Request }) =>
              request.mode === 'navigate',
            handler: 'NetworkFirst',
            options: {
              cacheName: 'bpw-shell',
              // A slow connection should not mean a blank screen; fall back to the
              // cached shell rather than spinning.
              networkTimeoutSeconds: 4,
              expiration: { maxEntries: 8 },
            },
          },
        ],
      },
      devOptions: { enabled: false },
    }),
  ],
  // MapLibre's GeoJSON parsing runs in a module worker (see MapView.tsx). Vite's
  // default worker output is an IIFE, which cannot be loaded with {type:'module'}.
  worker: { format: 'es' },
  server: {
    port: 5173,
    proxy: { '/api': 'http://127.0.0.1:8000' },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: [],
  },
})
