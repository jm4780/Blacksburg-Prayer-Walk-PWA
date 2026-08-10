import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { App } from './App'
import { cssVariables } from './design/tokens'
import './design/app.css'

// The tokens are the source of truth. CSS reads them, the map reads them.
const styleEl = document.createElement('style')
styleEl.textContent = cssVariables()
document.head.prepend(styleEl)

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)

if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch(() => {
      // No service worker means no install to the home screen. The app still runs.
    })
  })
}
