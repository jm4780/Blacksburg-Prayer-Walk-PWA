# Build scripts

## build-glyphs.mjs

Renders Archivo into MapLibre SDF glyph ranges for the map's street labels, into
`web/public/fonts/Prayer Walk Regular/`.

**The output is committed.** It is 88 KB, it is deterministic, and the map needs it at
runtime — so a fresh checkout works without anyone having to know this script exists.
It is not wired into `npm run build` because `fontnik` is a native dependency and
adding it to every install to regenerate a file that changes when the *typeface*
changes would be a poor trade.

Re-run it only if the map's typeface changes:

```bash
npm i --no-save fontnik
pip install fonttools brotli
python3 -c "
from fontTools.ttLib import TTFont
f = TTFont('node_modules/@fontsource/archivo/files/archivo-latin-500-normal.woff2')
f.flavor = None
f.save('/tmp/pw-fonts/Archivo-Regular.ttf')"
node scripts/build-glyphs.mjs
```
