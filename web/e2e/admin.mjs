/**
 * Admin interface check (Phase 3.1 §7).
 *
 * §7 asks whether each administration capability is *usable*, not merely present. The
 * cheapest honest test of that is: does every tab render something a person can read,
 * without throwing?
 *
 * It caught a real one. Tab state and payload state were separate, so React rendered
 * the newly-selected tab against the *previous* tab's data for one frame — clearing it
 * inside the effect is too late — and switching to Connectors handed the pilot summary
 * to a component expecting `rows`. The whole admin app white-screened.
 *
 * Needs an administrator token, which cannot be granted over HTTP by design:
 *
 *   UPDATE participants SET is_admin = true WHERE email_normalized = '…';
 *   node e2e/admin.mjs <token> [baseUrl]
 */
import { chromium, devices } from 'playwright'

const TOKEN = process.argv[2]
const BASE = process.argv[3] ?? 'http://127.0.0.1:8000'
if (!TOKEN) {
  console.error('usage: node e2e/admin.mjs <admin-token> [baseUrl]')
  process.exit(2)
}

const TABS = ['Walks', 'Manual edits', 'Feedback', 'Reservations', 'Duplicates',
              'Route failures', 'Connectors', 'Network', 'Deployment', 'Audit log']

const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' })
const ctx = await browser.newContext({ ...devices['Pixel 7'], baseURL: BASE })
const page = await ctx.newPage()

let errors = 0
page.on('pageerror', (e) => { errors++; console.log('  PAGE ERROR', e.message) })

await page.addInitScript((t) => localStorage.setItem('bpw.token', t), TOKEN)
await page.goto('/#/admin')
await page.getByRole('button', { name: 'Admin', exact: true }).click()
await page.locator('.metrics').first().waitFor({ timeout: 30000 })
console.log('  PASS  Pilot summary renders')

let failures = 0
for (const t of TABS) {
  await page.getByRole('button', { name: t, exact: true }).click()
  await page.waitForTimeout(1000)
  const text = await page.locator('main').innerText()
  const ok = text.length > 40
  if (!ok) failures++
  console.log(`  ${ok ? 'PASS' : 'FAIL'}  ${t}`)
}

if (errors) { failures++; console.log(`  FAIL  ${errors} page errors while switching tabs`) }
else console.log('  PASS  no page errors while switching tabs')

await browser.close()
console.log(failures === 0 ? '\nALL ADMIN CHECKS PASSED' : `\n${failures} FAILED`)
process.exit(failures === 0 ? 0 : 1)
