import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
// The approved design's typefaces, self-hosted rather than pulled from Google Fonts
// at runtime. A PWA that precaches its shell should not need a third-party CDN to
// render text, and this app is used outdoors on whatever signal a phone has.
// Only the weights the design uses, and only the latin subset — the unscoped
// imports pull Vietnamese, Cyrillic and Greek too, which triples the precache for
// glyphs this app will never render.
import '@fontsource/archivo/latin-400.css'
import '@fontsource/archivo/latin-500.css'
import '@fontsource/archivo/latin-600.css'
import '@fontsource/archivo/latin-700.css'
import '@fontsource/archivo/latin-800.css'
import '@fontsource/ibm-plex-mono/latin-400.css'
import '@fontsource/ibm-plex-mono/latin-500.css'
import './styles.css'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
