/**
 * End-to-end walk of the vertical slice, on a phone-sized viewport.
 *
 * Drives the twelve steps in order: arrive -> sign up -> dashboard -> generate ->
 * grant location -> see sizes -> change size -> preview -> start -> finish ->
 * confirm -> see the dashboard move. Also checks the two things §13 and §16 forbid:
 * no live-tracking language on the active-walk screen, and no residential data in any
 * network response.
 *
 *   node e2e/slice.mjs [baseUrl]
 */
import { chromium, devices } from 'playwright'
import assert from 'node:assert/strict'

const BASE = process.argv[2] ?? 'http://127.0.0.1:8000'
const START = { latitude: 37.2296, longitude: -80.4139 }   // downtown Blacksburg

// §13: the active-walk screen must not imply the phone is following the walker.
const FORBIDDEN_ON_ACTIVE_WALK = [
  /\btracking\b/i, /\btracked\b/i, /\brecording your\b/i, /\bgps\b/i,
  /\blive location\b/i, /\bfollowing you\b/i,
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

// Capture every API payload for the privacy assertion.
const payloads = []
page.on('response', async (r) => {
  if (!r.url().includes('/api/')) return
  try { payloads.push({ url: r.url(), body: await r.text() }) } catch { /* streamed */ }
})

log('\n1-2  arrive and sign up')
await page.goto('/')
await page.getByLabel('First name').fill('Ada')
await page.getByLabel('Last name').fill('Walker')
await page.getByLabel('Email').fill(`ada+${Date.now()}@example.com`)
await page.getByRole('button', { name: 'Start walking' }).click()
await page.getByRole('heading', { name: /Hello, Ada/ }).waitFor({ timeout: 15000 })
check('registered and landed on the dashboard', true)
const who = await page.locator('.whoami').innerText()
check('shows "Walking as [Name]"', /Walking as\s+Ada Walker/.test(who), who)
check('offers a way to switch person', /Not you\?|Switch person/.test(who), who)

log('\n3    home dashboard')
const metricLabels = await page.locator('.metric-label').allTextContents()
check('three metrics present', metricLabels.length === 3, metricLabels.join(' | '))
check('households metric says "estimated"',
  metricLabels.some((t) => /estimated households/i.test(t)), metricLabels.join(' | '))
await page.locator('.metric').first().getByRole('button').click()
check('metric definition is available',
  (await page.locator('.definition').first().innerText()).length > 60)

log('\n4-5  generate, one-time location')
await page.getByRole('button', { name: 'Generate a Prayer Walk' }).click()
const explain = await page.locator('.card .lede').innerText()
check('location purpose explained before the prompt',
  /once/i.test(explain) && /not saved/i.test(explain), explain)
check('explanation disclaims tracking', /do not track you/i.test(explain))
await page.getByRole('button', { name: 'Use my location' }).click()

const geo = await page.evaluate(
  () => ({ once: window.__getCurrentPositionCalls, watches: window.__watchIds.length }))
check('location requested exactly once', geo.once === 1, JSON.stringify(geo))
check('no continuous location watch was started', geo.watches === 0, JSON.stringify(geo))

log('\n6-7  sizes offered, and changing size updates everything')
await page.locator('.sizes').waitFor({ timeout: 60000 })
const ticks = page.locator('.tick')
const tickCount = await ticks.count()
check('five size bands rendered', tickCount === 5, `saw ${tickCount}`)
const disabled = await page.locator('.tick.off').count()
check('unavailable sizes are shown but not selectable',
  disabled === (await page.locator('.tick[aria-disabled="true"]').count()))

const readFacts = async () => (await page.locator('.facts dd').allTextContents()).join(' / ')
await page.locator('.tick', { hasText: 'Medium' }).click()
const medium = await readFacts()
await page.locator('.tick', { hasText: 'Long' }).click()
const long = await readFacts()
check('changing size updates distance, time, coverage and households',
  medium !== long, `${medium} vs ${long}`)
check('route line is drawn', await page.locator('path.ln-route').count() > 0)

log('\n8-9  preview and start')
await page.locator('.tick', { hasText: 'Medium' }).click()
await page.getByRole('button', { name: 'Preview this walk' }).click()
await page.getByRole('heading', { name: 'Preview your walk' }).waitFor({ timeout: 20000 })
check('directions listed', await page.locator('.directions li').count() > 0)
await page.getByRole('button', { name: 'Start this walk' }).click()
await page.getByRole('heading', { name: 'Your walk' }).waitFor({ timeout: 15000 })

log('\n     active-walk screen language (§13)')
const activeText = await page.locator('main').innerText()
for (const re of FORBIDDEN_ON_ACTIVE_WALK) {
  check(`no match for ${re}`, !re.test(activeText),
    (activeText.match(re) || []).join())
}
// §13 requires the start/end location to be SHOWN, and forbids a live-location
// indicator or a moving user marker. So the assertion is not "no marker" — an
// earlier version asserted that and was simply wrong — it is that the only marker
// is the route's fixed start/end, and that it does not move.
const markerKinds = await page.locator('.marker').evaluateAll(
  (els) => els.map((e) => e.getAttribute('data-kind')))
check('start/end location is shown',
  markerKinds.length === 1 && markerKinds[0] === 'route-start-end',
  JSON.stringify(markerKinds))
const pos1 = await page.locator('.marker circle').getAttribute('cx')
await page.waitForTimeout(1200)
const pos2 = await page.locator('.marker circle').getAttribute('cx')
check('the marker does not move', pos1 === pos2, `${pos1} -> ${pos2}`)
check('no geolocation watch is active',
  await page.evaluate(() => !window.__watchIds || window.__watchIds.length === 0))

log('\n10-11 finish and confirm')
await page.getByRole('button', { name: 'Finish Walk' }).click()
await page.getByRole('heading', { name: /Did you complete the route as shown/ }).waitFor()
check('three confirmation paths offered', await page.locator('.choice').count() === 3)
const choices = (await page.locator('.choice strong').allTextContents()).join(' | ')
check('offers mark-complete, review-and-edit, and did-not-complete',
  /mark it complete/i.test(choices) && /Review and edit/i.test(choices)
  && /didn.t complete it/i.test(choices), choices)

// Review-and-edit must start from the plan and update the contribution live.
await page.locator('.choice', { hasText: 'Review and edit' }).click()
await page.locator('.map path.ln-picked').first().waitFor({ timeout: 15000 })
const beforeEdit = await page.locator('.facts dd').allTextContents()
// Click the invisible hit target for one specific street. Clicking the drawn line
// itself would land wherever its bounding-box centre happens to be, which is often a
// different street — the drawn paths carry pointer-events: none for that reason.
const pickedId = await page.locator('.map path.ln-picked').first()
  .evaluate((el) => el.getAttribute('d'))
const targetId = await page.evaluate(() => {
  const drawn = document.querySelector('.map path.ln-picked')
  const d = drawn && drawn.getAttribute('d')
  const hit = [...document.querySelectorAll('.map path.hit')]
    .find((h) => h.getAttribute('d') === d)
  return hit ? hit.getAttribute('data-id') : null
})
check('every selectable street has a tap target', targetId !== null, String(pickedId))
await page.locator(`.map path.hit[data-id="${targetId}"]`).click({ force: true })
const afterEdit = await page.locator('.facts dd').allTextContents()
check('editing updates the adjusted contribution',
  beforeEdit.join() !== afterEdit.join(), `${beforeEdit} vs ${afterEdit}`)
check('freehand drawing is not offered',
  await page.locator('canvas, [contenteditable="true"]').count() === 0)

await page.locator('.choice', { hasText: 'mark it complete' }).click()
await page.getByRole('button', { name: 'Submit contribution' }).click()
await page.getByRole('heading', { name: 'Thank you' }).waitFor({ timeout: 20000 })
check('completion confirmed', true)

log('\n12   dashboard reflects the walk')
await page.getByRole('button', { name: 'Back to home' }).click()
await page.getByRole('heading', { name: /Hello, Ada/ }).waitFor()
const pct = Number((await page.locator('.metric-value').first().innerText()).replace('%', ''))
check('percentage prayed for is above zero', pct > 0, `${pct}%`)

log('\n     progress map (§16)')
await page.getByRole('button', { name: 'Progress', exact: true }).click()
await page.locator('.legend').waitFor({ timeout: 30000 })
check('progress map renders required geometry',
  await page.locator('.map path').count() > 100)
check('map states what it excludes',
  await page.locator('details.fine').count() === 1)
check('town boundary drawn', await page.locator('path.ln-boundary').count() > 0)
const legend = await page.locator('.legend').innerText()
check('legend explains the colours',
  /Prayed for/i.test(legend) && /Not yet/i.test(legend), legend)

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

await browser.close()
log(`\n${failures === 0 ? 'ALL CHECKS PASSED' : `${failures} CHECK(S) FAILED`}`)
process.exit(failures === 0 ? 0 : 1)
