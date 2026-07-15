import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// Served from the backend's /ui mount (see api/app.py's StaticFiles mount),
// so built asset URLs must be rooted under /ui/, not /.
export default defineConfig({
  base: '/ui/',
  plugins: [react(), tailwindcss()],
})
