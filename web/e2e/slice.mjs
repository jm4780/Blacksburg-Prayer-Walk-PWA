/**
 * End-to-end walk of the Phase 3.5 flow, on a phone-sized viewport.
 *
 * Drives the required flow in order:
 *
 *   open the app with no account -> see the town's progress -> ask for a walk ->
 *   move the time slider -> get a specific recommendation -> read it on a real map ->
 *   see how to get to the start -> accept -> give a name -> start -> finish ->
 *   confirm -> see the town total move
 *
 * Alongside the flow it checks the things that are meant to be true *because someone
 * decided they should be*, and would otherwise rot quietly:
 *
 *   - the dashboard works signed out (Priority 2)
 *   - no location is requested for the default recommendation (Priority 5)
 *   - the map is a real map: pannable, zoomable, and tappable with a thumb (Priority 1)
 *   - no parking language anywhere (Priority 5)
 *   - no engineering metrics on any walker-facing screen (Priority 8)
 *   - no tracking language and no continuous location, ever (§13, §18)
 *   - no residential data in any API payload (§18)
 *
 *   node e2e/slice.mjs [baseUrl]
 */
import { chromium, devices } from 'playwright'

const BASE = process.argv[2] ?? 'http://127.0.0.1:8000'
const START = { latitude: 37.2296, longitude: -80.4139 }   // downtown Blacksburg

// §13: no screen may imply the phone is following the walker.
const FORBIDDEN_TRACKING = [
  /\btracking\b/i, /\btracked\b/i, /\brecording your\b/i, /\bgps\b/i,
  /\blive location\b/i, /\bfollowing you\b/i,
]
// Priority 5: never tell somebody where to leave a car. "Parkway" and "Park Street"
// are real Blacksburg street names, so this matches "park" as a word only.
const FORBIDDEN_PARKING = [/\bpark\b/i, /\bparking\b/i, /\bparked\b/i]
// Priority 8: the optimiser's vocabulary stays on the server.
const FORBIDDEN_ENGINEERING = [
  /\bcoverage gain\b/i, /\bwalk quality\b/i, /\broute score\b/i, /\befficiency\b/i,
  /\bcluster\b/i, /\bseed\b/i, /\bband\b/i,
]
// §18 / §16: nothing residential may cross the wire.
const FORBIDDEN_IN_PAYLOADS = [
  /\baddress_point/i, /\bstreet_address\b/i, /"household_key"/i,
  /"households"\s*:\s*\[/i, /\bunit_number\b/i, /"point"\s*:\s*\{/i,
]

const log = (...a) => console.log(...a)
let failures = 0
function check(name, cond, detail = '') {
  if (cond) log(`  PASS  ${name}`)
  else { failures++; log(`  FAIL  ${name} ${detail}`) }
}
function checkNone(label, patterns, text) {
  for (const re of patterns) {
    const m = text.match(re)
    check(`${label}: no match for ${re}`, !m, m ? `"${m[0]}"` : '')
  }
}

const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' })
const ctx = await browser.newContext({
  ...devices['Pixel 7'],
  permissions: ['geolocation'],
  geolocation: START,
  baseURL: BASE,
})
const page = await ctx.newPage()

// §6/§13: the app must use a one-time fix and never a continuous watch. Instrument
// both APIs before any app code runs, so a watch would be recorded rather than
// merely invisible.
await page.addInitScript(() => {
  window.__watchIds = []
  window.__getCurrentPositionCalls = 0
  const g = navigator.geolocation
  const watch = g.watchPosition.bind(g)
  const once = g.getCurrentPosition.bind(g)
  g.watchPosition = (...a) => { const id = watch(...a); window.__watchIds.push(id); return id }
  g.getCurrentPosition = (...a) => { window.__getCurrentPositionCalls++; return once(...a) }
})

const payloads = []
page.on('response', async (r) => {
  if (!r.url().includes('/api/')) return
  try { payloads.push({ url: r.url(), body: await r.text() }) } catch { /* streamed */ }
})

/** The map is ready when MapLibre says its style has loaded. */
async function mapReady(timeout = 30000) {
  await page.locator('.maplibre[data-ready="true"]').first().waitFor({ timeout })
  await page.waitForFunction(
    () => window.__bpwMap && window.__bpwMap.isStyleLoaded(), null, { timeout })
}

/** Ready, and actually holding the town network — not just mounted. */
async function mapHasSegments(timeout = 40000) {
  await mapReady(timeout)
  await page.waitForFunction(() => {
    try { return window.__bpwMap.querySourceFeatures('segments').length > 0 }
    catch { return false }
  }, null, { timeout })
}

// ---------------------------------------------------------------------------
log('\n1    arrive with no account')
await page.goto('/')
await page.locator('.dash-pct-value').waitFor({ timeout: 30000 })
check('no sign-up wall — the app opens on mission control',
  await page.getByLabel('First name').count() === 0)
check('no "walking as" bar before there is anybody to name',
  await page.locator('.whoami').count() === 0)
check('the shared mission is stated first',
  /every household in Blacksburg/i.test(await page.locator('.dash-mission').innerText()))

log('\n2    mission control, signed out')
const metricLabels = await page.locator('.dash-metrics .dash-label').allTextContents()
check('three supporting metrics present', metricLabels.length === 3, metricLabels.join(' | '))
check('households leads the metric row',
  /households/i.test(metricLabels[0]), metricLabels.join(' | '))
check('the numbers are declared as the town\'s, not the visitor\'s',
  /whole town, not for you/i.test(await page.locator('.dash-shared').innerText()))

// The town map is part of this screen now, not a place you navigate to.
await mapHasSegments()
const townDrawn = await page.evaluate(
  () => window.__bpwMap.querySourceFeatures('segments').length)
check('the town map is embedded in the dashboard', townDrawn > 100, `${townDrawn}`)
check('no separate progress destination is offered',
  await page.getByRole('button', { name: /progress map/i }).count() === 0
  && await page.getByRole('button', { name: 'Progress', exact: true }).count() === 0)

// Requirement 10: expands in place, no second destination.
const routeBefore = await page.evaluate(() => window.location.hash)
await page.getByRole('button', { name: /Explore/ }).click()
check('Explore expands the map in place', await page.locator('.dash-expand').count() === 1)
check('expanding creates no new destination',
  await page.evaluate(() => window.location.hash) === routeBefore)
await page.getByRole('button', { name: /Close/ }).click()
check('and collapses back', await page.locator('.dash-expand').count() === 0)

// Phase 3's commitment: every number carries its definition.
await page.locator('.dash-metric').first().click()
check('metric definitions are still reachable',
  (await page.locator('.dash-defs').innerText()).length > 120)
await page.getByRole('button', { name: 'Close', exact: true }).click()
const startPct = Number(await page.locator('.dash-pct-value').innerText())

log('\n3    ask for a walk — still no account')
await page.getByRole('button', { name: /Begin today's walk/ }).click()
await page.locator('.mission h2').waitFor({ timeout: 90000 })
const geoAtRecommend = await page.evaluate(
  () => ({ once: window.__getCurrentPositionCalls, watches: window.__watchIds.length }))
check('no location requested for the default recommendation (Priority 5)',
  geoAtRecommend.once === 0, JSON.stringify(geoAtRecommend))
check('still signed out', await page.locator('.whoami').count() === 0)

log('\n4    the time slider (Priority 4)')
const slider = page.locator('.timeslider')
check('a single continuous time control', await slider.count() === 1)
const bounds = await slider.evaluate(
  (el) => ({ min: el.min, max: el.max, step: el.step, value: el.value }))
check('runs 20 to 90 in steps of 5',
  bounds.min === '20' && bounds.max === '90' && bounds.step === '5',
  JSON.stringify(bounds))
check('opens at a sensible default', bounds.value === '45', bounds.value)

const firstTitle = await page.locator('.mission h2').innerText()
const firstMiles = await page.locator('.mission .mission-line').nth(1).innerText()
/** Move the slider and wait for the recommendation that answers it. */
async function setMinutes(m) {
  const landed = page.waitForResponse(
    (r) => r.url().includes(`/api/missions/recommend?minutes=${m}`) && r.status() === 200,
    { timeout: 120000 })
  await slider.fill(String(m))
  await page.locator('.timevalue').getByText(`${m} minutes`).waitFor({ timeout: 5000 })
  await landed
  // The card dims while a newer recommendation is in flight, then settles.
  await page.waitForFunction(
    () => !document.querySelector('.mission.stale'), null, { timeout: 30000 })
}

await setMinutes(80)
check('the reading follows the slider immediately', true)
const longerMiles = await page.locator('.mission .mission-line').nth(1).innerText()
check('a longer time budget produces a longer walk',
  firstMiles !== longerMiles, `${firstMiles} vs ${longerMiles}`)
await setMinutes(45)

log('\n5    the recommendation reads as a mission, not a configuration')
const missionText = await page.locator('.mission').innerText()
check('the walk has a title naming somewhere real',
  /\b(through|around|in|corridors)\b/i.test(firstTitle) && firstTitle.length > 12,
  firstTitle)
check('says roughly how many households', /households|no homes/i.test(missionText),
  missionText.split('\n')[1])
check('says roughly how long', /About \d+ minutes/i.test(missionText))
checkNone('mission card', FORBIDDEN_PARKING, missionText)
checkNone('mission card', FORBIDDEN_ENGINEERING, missionText)
checkNone('mission card', FORBIDDEN_TRACKING, missionText)

log('\n6    a real map (Priority 1)')
await mapReady()
const drawn = await page.evaluate(
  () => window.__bpwMap.queryRenderedFeatures({ layers: ['route-line'] }).length)
check('the route is drawn on the map', drawn > 0, `${drawn} features`)

const before = await page.evaluate(() => {
  const m = window.__bpwMap
  return { z: m.getZoom(), c: [m.getCenter().lng, m.getCenter().lat] }
})
// Pan by dragging, the way a thumb does.
const box = await page.locator('.maplibre').first().boundingBox()
await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
await page.mouse.down()
await page.mouse.move(box.x + box.width / 2 - 90, box.y + box.height / 2 - 60, { steps: 12 })
await page.mouse.up()
await page.waitForTimeout(600)
const panned = await page.evaluate(() => {
  const m = window.__bpwMap
  return [m.getCenter().lng, m.getCenter().lat]
})
check('the map pans', Math.abs(panned[0] - before.c[0]) > 1e-4,
  `${before.c} -> ${panned}`)

await page.locator('.maplibregl-ctrl-zoom-in').first().click()
await page.waitForTimeout(800)
const zoomed = await page.evaluate(() => window.__bpwMap.getZoom())
check('the map zooms', zoomed > before.z, `${before.z} -> ${zoomed}`)

await page.getByRole('button', { name: 'Recenter route' }).click()
await page.waitForTimeout(900)
const recentred = await page.evaluate(() => {
  const m = window.__bpwMap
  return [m.getCenter().lng, m.getCenter().lat]
})
check('recenter puts the route back',
  Math.abs(recentred[0] - before.c[0]) < 5e-3, `${recentred} vs ${before.c}`)

log('\n7    getting to the start (Priority 6)')
const startBox = await page.locator('.startbox').innerText()
check('the start is named as a place', startBox.length > 12, startBox)
checkNone('start box', FORBIDDEN_PARKING, startBox)
const dirs = await page.locator('.dirlinks a').evaluateAll(
  (els) => els.map((e) => e.getAttribute('href')))
check('directions to the start are offered', dirs.length >= 2, JSON.stringify(dirs))
const startLatLon = await page.evaluate(() => {
  const s = window.__bpwMap.getSource('startpt')
  return s && s.serialize().data.features[0].geometry.coordinates
})
check('every directions link points at the start point, not the route',
  dirs.every((d) => d.includes(startLatLon[1].toFixed(6))
                 && d.includes(startLatLon[0].toFixed(6))),
  JSON.stringify({ dirs, startLatLon }))

log('\n8    "find a walk near me" is preserved, as a secondary way in (Priority 7)')
check('offered below the recommendation',
  await page.getByRole('button', { name: /Find a walk near me/i }).count() === 1)

log('\n9    accept — identity asked for here and not before (Priority 2)')
await page.getByRole('button', { name: 'Walk this' }).click()
await page.locator('.identity').waitFor({ timeout: 10000 })
const why = await page.locator('.identity .lede').innerText()
check('says why it is asking now', /hold|held|nobody else|counts/i.test(why), why)
await page.getByLabel('First name').fill('Ada')
await page.getByLabel('Last name').fill('Walker')
await page.getByLabel('Email').fill(`ada+${Date.now()}@example.com`)
await page.getByRole('button', { name: 'Save and start' }).click()
await page.getByRole('heading', { name: 'Preview your walk' }).waitFor({ timeout: 60000 })
check('accepting after signing up goes straight to the walk', true)
const who = await page.locator('.whoami').innerText()
check('now shows "Walking as [Name]"', /Walking as\s+Ada Walker/.test(who), who)

log('\n10   preview and start')
check('directions listed', await page.locator('.directions li').count() > 0)
await mapReady()
await page.getByRole('button', { name: 'Start this walk' }).click()
await page.getByRole('heading', { name: 'Your walk' }).waitFor({ timeout: 20000 })

log('\n     active-walk screen (§13, Priority 8)')
const activeText = await page.locator('main').innerText()
checkNone('active walk', FORBIDDEN_TRACKING, activeText)
checkNone('active walk', FORBIDDEN_PARKING, activeText)
checkNone('active walk', FORBIDDEN_ENGINEERING, activeText)
check('no geolocation watch is active',
  await page.evaluate(() => window.__watchIds.length === 0))
// §13 requires the start/end point to be SHOWN and forbids a moving user marker.
const dot1 = await page.evaluate(() => {
  const s = window.__bpwMap.getSource('startpt')
  return s.serialize().data.features.length
})
check('the fixed start/end point is shown', dot1 === 1, String(dot1))
await page.waitForTimeout(1500)
const dot2 = await page.evaluate(() => {
  const s = window.__bpwMap.getSource('startpt')
  return JSON.stringify(s.serialize().data.features[0].geometry.coordinates)
})
await page.waitForTimeout(1500)
const dot3 = await page.evaluate(() => {
  const s = window.__bpwMap.getSource('startpt')
  return JSON.stringify(s.serialize().data.features[0].geometry.coordinates)
})
check('the point does not move', dot2 === dot3, `${dot2} -> ${dot3}`)

log('\n11   finish and confirm')
await page.getByRole('button', { name: 'Finish Walk' }).click()
await page.getByRole('heading', { name: /Did you complete the route as shown/ }).waitFor()
check('three confirmation paths offered', await page.locator('.choice').count() === 3)

// Review-and-edit must start from the plan and be operable with a thumb.
await page.locator('.choice', { hasText: 'Review and edit' }).click()
await mapReady()
await page.waitForFunction(
  () => window.__bpwMap.querySourceFeatures('segments').length > 0, null, { timeout: 30000 })
const summaryBefore = await page.locator('.card .mission-line').innerText()

// The editing map sits below the fold on a phone. Scroll it into view before aiming
// at it, or the tap lands on nothing and the failure looks like a hit-testing bug.
await page.locator('.maplibre').first().scrollIntoViewIfNeeded()
await page.waitForTimeout(400)

// Tap a street the way a finger does: on the drawn line, at a point taken from the
// route itself. The invisible 24px hit layer is what makes this land.
const tapped = await page.evaluate(() => {
  const m = window.__bpwMap
  const data = m.getSource('segments').serialize().data
  // A planned street, currently counting, that is on screen. Its midpoint is the
  // least ambiguous place on it to aim a finger.
  const bounds = m.getBounds()
  for (const f of data.features) {
    if (f.properties.state !== 'selected') continue
    const c = f.geometry.coordinates[Math.floor(f.geometry.coordinates.length / 2)]
    if (!bounds.contains(c)) continue
    const p = m.project(c)
    return { x: p.x, y: p.y, id: f.properties.id }
  }
  return null
})
check('a planned street is visible on the editing map', tapped !== null)
const mapBox = await page.locator('.maplibre').first().boundingBox()
await page.mouse.click(mapBox.x + tapped.x, mapBox.y + tapped.y)
await page.waitForTimeout(600)
const summaryAfter = await page.locator('.card .mission-line').innerText()
check('a street can be selected by tapping the map',
  summaryBefore !== summaryAfter, `${summaryBefore} -> ${summaryAfter}`)
check('freehand drawing is not offered',
  await page.locator('[contenteditable="true"]').count() === 0)

await page.locator('.choice', { hasText: 'mark it complete' }).click()
await page.getByRole('button', { name: 'Submit contribution' }).click()
await page.getByRole('heading', { name: 'Thank you' }).waitFor({ timeout: 30000 })
check('completion confirmed', true)

log('\n     pilot feedback (Phase 3.1 §5)')
check('feedback offered after submission', await page.locator('.feedback').count() === 1)
await page.locator('.feedback .star').nth(3).click()
await page.locator('.feedback .yesno button').first().click()
await page.getByRole('button', { name: 'Send feedback' }).click()
await page.getByText(/Thank you — that helps/).waitFor({ timeout: 20000 })
check('feedback accepted and acknowledged', true)

log('\n12   the town total moves')
await page.getByRole('button', { name: 'Back to home' }).click()
// The value renders as an em dash until the metrics land; Number('—') is NaN.
await page.waitForFunction(() => {
  const el = document.querySelector('.dash-pct-value')
  return el && !Number.isNaN(Number(el.textContent))
}, null, { timeout: 30000 })
const endPct = Number(await page.locator('.dash-pct-value').innerText())
check('percentage prayed through went up', endPct > startPct, `${startPct}% -> ${endPct}%`)

log('\n     the town map, in place (§16)')
await mapHasSegments()
const required = await page.evaluate(
  () => window.__bpwMap.querySourceFeatures('segments').length)
check('the map renders required geometry', required > 100, `${required} features`)
const legend = await page.locator('.dash-legend').first().innerText()
check('legend explains the treatment',
  /Covered/i.test(legend) && /Still to walk/i.test(legend), legend)
await page.locator('.dash-metric').first().click()
check('what the map excludes is still stated',
  /excl|not show|private|highway/i.test(await page.locator('.dash-defs').innerText()))
// A bookmark to the old destination must land somewhere sensible, not nowhere.
await page.goto('/#/progress')
await page.locator('.dash-pct-value').waitFor({ timeout: 20000 })
check('the old /progress link redirects to mission control',
  await page.evaluate(() => window.location.hash) === '#/')

log('\n     PWA installability')
const manifest = await page.evaluate(async () => {
  const link = document.querySelector('link[rel="manifest"]')
  if (!link) return null
  return (await fetch(link.href)).json()
})
check('web manifest served', manifest !== null)
check('manifest is standalone-capable',
  manifest?.display === 'standalone', manifest?.display)
const sw = await page.evaluate(() =>
  navigator.serviceWorker.getRegistrations().then((r) => r.length))
check('service worker registered', sw > 0, `${sw} registrations`)

log('\n     privacy: no residential data in any API payload (§18)')
for (const re of FORBIDDEN_IN_PAYLOADS) {
  const hit = payloads.find((p) => re.test(p.body))
  check(`no match for ${re}`, !hit, hit ? hit.url : '')
}
log(`     (${payloads.length} API responses inspected)`)

const finalGeo = await page.evaluate(() => window.__watchIds.length)
check('no continuous location watch was ever started', finalGeo === 0, String(finalGeo))

await browser.close()
log(`\n${failures === 0 ? 'ALL CHECKS PASSED' : `${failures} CHECK(S) FAILED`}`)
process.exit(failures === 0 ? 0 : 1)
