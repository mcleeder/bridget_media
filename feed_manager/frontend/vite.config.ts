import { defineConfig } from 'vite'
import { svelte } from '@sveltejs/vite-plugin-svelte'

// Points at the Flask backend during `npm run dev`. Override with
// VITE_API_TARGET if it's not running on localhost (e.g. the Pi's hostname).
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
