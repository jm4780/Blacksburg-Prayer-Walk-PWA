/**
 * Screenshots of the walker-facing flow, on a phone.
 *
 *   node e2e/screenshots.mjs [outDir] [baseUrl] [--legacy]
 *
 * `--legacy` drives the pre-Phase-3.5 flow (sign-up wall, named size bands, SVG map)
 * so the same script can produce the "before" half of a comparison from an older
 * checkout. Without it, the current flow.
 */
import { chromium, devices } from 'playwright'

const OUT = process.argv[2] ?? '/tmp/shots'
const BASE = process.argv[3] ?? 'http://127.0.0.1:8000'
const LEGACY = process.argv.includes('--legacy')

const b = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' })
const ctx = await b.newContext({
  ...devices['Pixel 7'], permissions: ['geolocation'],
  geolocation: { latitude: 37.2296, longitude: -80.4139 }, baseURL: BASE,
})
const p = await ctx.newPage()
const shot = async (name) => {
  await p.screenshot({ path: `${OUT}/${name}.png`, fullPage: true })
  console.log(`  ${OUT}/${name}.png`)
}
const mapSettled = async (t = 40000) => {
  await p.locator('.maplibre[data-ready="true"], .map').first().waitFor({ timeout: t })
  await p.waitForTimeout(2500)
}

if (LEGACY) {
  // ---- the flow as it stood before Phase 3.5 -------------------------------
  await p.goto('/')
  await p.getByLabel('First name').fill('Ada')
  await p.getByLabel('Last name').fill('Walker')
  await p.getByLabel('Email').fill(`shot+${Date.now()}@example.com`)
  await shot('01-first-screen')
  await p.getByRole('button', { name: 'Start walking' }).click()
  await p.getByRole('heading', { name: /Hello/ }).waitFor({ timeout: 20000 })
  await shot('02-dashboard')
  await p.getByRole('button', { name: 'Generate a Prayer Walk' }).click()
  await shot('03-choose-a-walk')
  await p.getByRole('button', { name: 'Use my location' }).click()
  await p.locator('.sizes').waitFor({ timeout: 120000 })
  await p.locator('.tick', { hasText: 'Medium' }).click()
  await p.waitForTimeout(1500)
  await shot('04-the-walk')
  await p.getByRole('button', { name: 'Preview this walk' }).click()
  await p.getByRole('heading', { name: 'Preview your walk' }).waitFor({ timeout: 40000 })
  await p.getByRole('button', { name: 'Start this walk' }).click()
  await p.getByRole('heading', { name: 'Your walk' }).waitFor()
  await shot('05-active-walk')
  await p.getByRole('button', { name: 'Finish Walk' }).click()
  await p.getByRole('heading', { name: /Did you complete/ }).waitFor()
  await p.locator('.choice', { hasText: 'Review and edit' }).click()
  await p.waitForTimeout(3000)
  await shot('06-confirm')
  await p.locator('.choice', { hasText: 'mark it complete' }).click()
  await p.getByRole('button', { name: 'Submit contribution' }).click()
  await p.getByRole('heading', { name: 'Thank you' }).waitFor({ timeout: 30000 })
  await p.getByRole('button', { name: 'Back to home' }).click()
  await p.getByRole('button', { name: 'Progress', exact: true }).click()
  await p.locator('.legend').waitFor({ timeout: 40000 })
  await p.waitForTimeout(2000)
  await shot('07-progress')
} else {
  // ---- the Phase 3.5 flow --------------------------------------------------
  await p.goto('/')
  await p.locator('.dash-pct-value').waitFor({ timeout: 30000 })
  await mapSettled()
  await shot('01-first-screen')                       // mission control, signed out
  await p.getByRole('button', { name: /Explore/ }).click()
  await mapSettled()
  await shot('01b-map-expanded')
  await p.getByRole('button', { name: /Close/ }).click()
  await p.getByRole('button', { name: /Begin today's walk/ }).click()
  await p.locator('.mission h2').waitFor({ timeout: 120000 })
  await mapSettled()
  await shot('02-dashboard')                          // kept name for pairing
  await shot('03-choose-a-walk')
  await p.locator('.timeslider').fill('75')
  await p.waitForResponse((r) => r.url().includes('minutes=75') && r.status() === 200,
                          { timeout: 120000 })
  await p.waitForFunction(() => !document.querySelector('.mission.stale'),
                          null, { timeout: 40000 })
  await mapSettled()
  await shot('04-the-walk')                           // a 75-minute recommendation
  await p.locator('.timeslider').fill('45')
  await p.waitForResponse((r) => r.url().includes('minutes=45') && r.status() === 200,
                          { timeout: 120000 })
  await p.waitForFunction(() => !document.querySelector('.mission.stale'),
                          null, { timeout: 40000 })
  await p.getByRole('button', { name: 'Walk this' }).click()
  await p.locator('.identity').waitFor({ timeout: 20000 })
  await shot('05-identity-asked-late')
  await p.getByLabel('First name').fill('Ada')
  await p.getByLabel('Last name').fill('Walker')
  await p.getByLabel('Email').fill(`shot+${Date.now()}@example.com`)
  await p.getByRole('button', { name: 'Save and start' }).click()
  await p.getByRole('heading', { name: 'Preview your walk' }).waitFor({ timeout: 60000 })
  await p.getByRole('button', { name: 'Start this walk' }).click()
  await p.getByRole('heading', { name: 'Your walk' }).waitFor()
  await mapSettled()
  await shot('06-active-walk')
  await p.getByRole('button', { name: 'Finish Walk' }).click()
  await p.getByRole('heading', { name: /Did you complete/ }).waitFor()
  await p.locator('.choice', { hasText: 'Review and edit' }).click()
  await mapSettled()
  await shot('07-confirm')
  await p.locator('.choice', { hasText: 'mark it complete' }).click()
  await p.getByRole('button', { name: 'Submit contribution' }).click()
  await p.getByRole('heading', { name: 'Thank you' }).waitFor({ timeout: 40000 })
  await p.getByRole('button', { name: 'Back to home' }).click()
  await mapSettled()
  await shot('08-progress')                           // the town total, moved
}

await b.close()
