/**
 * Does the app tell the truth about which build it is?
 *
 * The Phase 3.5 preview problem was not a bug in the product — it was that nothing on
 * screen could distinguish "old code" from "old cache". This checks the machinery that
 * fixed that, because a diagnostic that quietly stops working is worse than none.
 *
 *   node e2e/verify-build.mjs [baseUrl]
 */
import { chromium, devices } from 'playwright'

const BASE = process.argv[2] ?? 'http://127.0.0.1:8000'
let failures = 0
const check = (name, cond, detail = '') => {
  if (cond) console.log(`  PASS  ${name}`)
  else { failures++; console.log(`  FAIL  ${name} ${detail}`) }
}

const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' })
const ctx = await browser.newContext({ ...devices['Pixel 7'], baseURL: BASE })
const page = await ctx.newPage()

const server = await (await ctx.request.get('/api/version')).json()
console.log(`\n  server reports: ${server.build_id} on ${server.branch}`)

await page.goto('/')
await page.locator('.buildbadge').waitFor({ timeout: 30000 })

const badge = await page.locator('.buildbadge > button').innerText()
check('a build badge is visible without opening anything', /build\s+\S+/.test(badge), badge)
check('the badge names a real commit, not "unknown"',
  !/unknown/.test(badge), badge)
check('the badge agrees with the server',
  badge.includes(server.build_id), `badge="${badge}" server=${server.build_id}`)
check('no stale flag on a freshly built bundle',
  !/stale/.test(badge), badge)

await page.locator('.buildbadge > button').click()
const detail = await page.locator('.bb-detail').innerText()
check('detail names the app bundle, the server and the branch',
  /App bundle/.test(detail) && /Server/.test(detail) && /Branch/.test(detail), detail)
check('detail reports the neighbourhood count as a number, not a list of names',
  /Neighbourhoods\s+\d+$/m.test(detail), detail.split('\n').slice(-4).join(' | '))
check('a cache-clearing escape hatch is offered',
  await page.getByRole('button', { name: /Clear cache and load the newest build/ })
    .count() === 1)

// The service worker must not pin index.html, or an installed PWA can serve an old
// shell forever — which is what happened.
const sw = await (await ctx.request.get('/sw.js')).text()
check('index.html is NOT precached', !/"index\.html"/.test(sw.split('],')[0]))
check('navigation requests are NetworkFirst', /NetworkFirst/.test(sw))
check('no handler is bound to a non-precached index.html',
  !/createHandlerBoundToURL/.test(sw))
check('the new worker takes over immediately',
  /skipWaiting/.test(sw) && /clientsClaim/.test(sw))

// And the badge must survive a reload rather than being a first-paint artefact.
await page.reload()
await page.locator('.buildbadge').waitFor({ timeout: 20000 })
check('badge still present after a reload', true)

await browser.close()
console.log(`\n${failures === 0 ? 'BUILD IDENTITY VERIFIED' : `${failures} CHECK(S) FAILED`}`)
process.exit(failures === 0 ? 0 : 1)
