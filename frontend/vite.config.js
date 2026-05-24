import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',  // bind to all interfaces — required for Docker port mapping
    port: 5173,
    // Proxy API calls to Python backend during local dev.
    // In Docker, nginx handles the same routing.
    proxy: {
      '/sync':   'http://127.0.0.1:8000',
      '/query':  'http://127.0.0.1:8000',
      '/health': 'http://127.0.0.1:8000',
    },
  },
})
