import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// Served from the backend's /ui mount (see api/app.py's StaticFiles mount),
// so built asset URLs must be rooted under /ui/, not /.
export default defineConfig({
  base: '/ui/',
  plugins: [react(), tailwindcss()],
  server: {
    // api.ts fetches root-relative paths (/briefs, /briefs/{id}), so `npm
    // run dev` needs these proxied to a separately-running backend
    // (default docker compose port) or every fetch 404s against the Vite
    // dev server's own origin.
    proxy: {
      '/briefs': 'http://localhost:8000',
    },
  },
})
