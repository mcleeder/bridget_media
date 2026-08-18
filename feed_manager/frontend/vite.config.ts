import { defineConfig } from 'vite'
import { svelte } from '@sveltejs/vite-plugin-svelte'

// Points at the backend during `npm run dev`. In production it serves on port
// 80 (config.FEED_MANAGER_PORT), but binding that locally is a nuisance, so
// dev runs `python -m feed_manager.app --port 8000`. Override with
// VITE_API_TARGET if it's not on localhost (e.g. the Pi's hostname).
const apiTarget = process.env.VITE_API_TARGET ?? 'http://localhost:8000'

// https://vite.dev/config/
export default defineConfig({
  plugins: [svelte()],
  server: {
    proxy: {
      '/api': apiTarget,
    },
  },
})
