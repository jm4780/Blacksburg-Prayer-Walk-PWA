/**
 * Build the map's label glyphs, from our own font, into our own origin.
 *
 * MapLibre renders vector-map labels from SDF glyph ranges, not from web fonts, so a
 * self-hosted map needs self-hosted glyphs. Without this step the only options are a
 * third-party glyph endpoint — which reintroduces exactly the runtime dependency the
 * Prayer Walk map system exists to remove, and which fails outdoors on bad signal —
 * or no street labels at all.
 *
 * Produces public/fonts/<stack>/<start>-<end>.pbf covering latin, which is every
 * character in a Blacksburg street name.
 *
 *   node scripts/build-glyphs.mjs
 */
import { mkdirSync, readFileSync, writeFileSync, existsSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import fontnik from 'fontnik'

const HERE = dirname(fileURLToPath(import.meta.url))
const OUT = join(HERE, '..', 'public', 'fonts')

// Latin, punctuation and the Latin-1 supplement. Blacksburg has no street whose name
// needs more, and every extra range is bytes a phone downloads on a hillside.
const RANGES = [[0, 255], [256, 511]]

const STACKS = [
  { name: 'Prayer Walk Regular', file: process.argv[2] || '/tmp/pw-fonts/Archivo-Regular.ttf' },
]

for (const stack of STACKS) {
  if (!existsSync(stack.file)) {
    console.error(`  missing ${stack.file} — run scripts/fetch-font.py first`)
    process.exit(1)
  }
  const buf = readFileSync(stack.file)
  const dir = join(OUT, stack.name)
  mkdirSync(dir, { recursive: true })
  for (const [start, end] of RANGES) {
    await new Promise((resolve, reject) => {
      fontnik.range({ font: buf, start, end }, (err, data) => {
        if (err) return reject(err)
        writeFileSync(join(dir, `${start}-${end}.pbf`), data)
        console.log(`  ${stack.name}/${start}-${end}.pbf  ${(data.length / 1024).toFixed(1)} KB`)
        resolve()
      })
    })
  }
}
