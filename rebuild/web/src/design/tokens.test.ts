/**
 * The stylesheet may only spend what the token file mints. A `var(--c-...)`
 * with nothing behind it does not fail loudly in a browser: it silently falls
 * back to nothing, and a panel loses its background on someone's phone.
 */

import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import { cssVariables } from './tokens'

describe('design tokens', () => {
  const css = readFileSync(resolve(__dirname, 'app.css'), 'utf8')
  const emitted = new Set(
    [...cssVariables().matchAll(/(--[a-z0-9-]+):/g)].map((m) => m[1]),
  )

  it('backs every variable the stylesheet reads', () => {
    const used = new Set([...css.matchAll(/var\((--[a-z0-9-]+)/g)].map((m) => m[1]))
    const missing = [...used].filter((v) => !emitted.has(v))
    expect(missing).toEqual([])
  })

  it('leaves no colour hard-coded in the stylesheet', () => {
    // A mask is a stencil, not a colour: #000 there means "keep this pixel".
    // White and transparent are values rather than brand colours, and
    // rgb(var(--x) / a) is a token being given an alpha.
    const paint = css
      .split('\n')
      .filter((line) => !line.includes('mask-image'))
      .join('\n')
    const literals = [...paint.matchAll(/#[0-9a-fA-F]{3,8}\b/g)].map((m) => m[0])
    expect(literals).toEqual([])
  })
})
