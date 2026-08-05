/**
 * The offline path, forced.
 *
 * A Workbox precache answers a range request with the whole file and status 200.
 * pmtiles' own FetchSource throws on exactly that; src/map/basemap.ts is written to
 * take it as the archive. This intercepts the archive request and replies 200 with
 * the full body, which is the same thing the service worker does, and then checks
 * that the map still has real tiles in it.
 */
import { readFileSync } from 'node:fs'
import { chromium, devices } from 'playwright'

const OUT = process.argv[2] ?? '/tmp/shots'
const archive = readFileSync('public/basemap/blacksburg.pmtiles')

const b = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' })
const ctx = await b.newContext({ ...devices['Pixel 7'], baseURL: 'http://127.0.0.1:8000' })
const p = await ctx.newPage()
const errs = []
p.on('pageerror', (e) => errs.push(String(e)))
p.on('console', (m) => { if (m.type() === 'error') errs.push(m.text()) })

let served = 0
await p.route('**/basemap/blacksburg.pmtiles', async (route) => {
  served++
  await route.fulfill({
    status: 200,
    headers: { 'content-type': 'application/octet-stream',
               'content-length': String(archive.length) },
    body: archive,
  })
})

await p.goto('/')
await p.locator('.maplibre[data-ready="true"]').first().waitFor({ timeout: 40000 })
await p.waitForTimeout(5000)
await p.screenshot({ path: `${OUT}/20-offline-200.png`, fullPage: false })

const probe = await p.evaluate(() => {
  const m = window.__bpwMap
  return {
    roads: m.queryRenderedFeatures({ layers: ['bg-road-minor', 'bg-road-motorway'] }).length,
    places: m.queryRenderedFeatures({ layers: ['bg-place-town'] }).length,
    degraded: !!document.querySelector('.map-degraded'),
  }
})
await b.close()

let failures = 0
const check = (name, cond, detail = '') => {
  if (cond) console.log(`  PASS  ${name}`)
  else { failures++; console.log(`  FAIL  ${name} ${detail}`) }
}
check('the archive is fetched whole exactly once, not once per tile', served === 1, served)
check('the basemap has real road geometry', probe.roads > 0, JSON.stringify(probe))
check('the map does not report itself degraded', !probe.degraded)
check('nothing threw', errs.length === 0, errs.slice(0, 4).join(' | '))
console.log(failures ? `\n${failures} FAILED` : '\nOFFLINE BASEMAP VERIFIED')
process.exit(failures ? 1 : 0)
