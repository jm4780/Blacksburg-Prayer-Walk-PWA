import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'

export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: 'autoUpdate',
      includeAssets: ['icon.svg'],
      manifest: {
        name: 'Blacksburg Prayer Walk',
        short_name: 'Prayer Walk',
        description: 'Pray for Blacksburg, one street at a time.',
        theme_color: '#1f3d2b',
        background_color: '#faf9f6',
        display: 'standalone',
        orientation: 'portrait',
        start_url: '/',
        scope: '/',
        icons: [
          { src: 'icon.svg', sizes: 'any', type: 'image/svg+xml', purpose: 'any maskable' },
        ],
      },
      workbox: {
        globPatterns: ['**/*.{js,css,html,svg}'],
        // The app shell is precached so an installed PWA opens with no network.
        // API responses are NOT cached: a stale completion state would show a walker
        // streets that someone else has since prayed for, and silently rewarding a
        // duplicate walk is worse than an honest offline message.
        navigateFallback: '/index.html',
        runtimeCaching: [],
      },
      devOptions: { enabled: false },
    }),
  ],
  // MapLibre's GeoJSON parsing runs in a module worker (see MapView.tsx). Vite's
  // default worker output is an IIFE, which cannot be loaded with {type:'module'}.
  worker: { format: 'es' },
  server: {
    port: 5173,
    proxy: { '/api': 'http://127.0.0.1:8000' },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: [],
  },
})
