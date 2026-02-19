import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { readFileSync } from 'fs'
import { resolve } from 'path'

// Read API_PORT from root .env
let apiPort = '5001'
try {
  const envFile = readFileSync(resolve(__dirname, '..', '.env'), 'utf-8')
  const match = envFile.match(/^API_PORT=(\d+)/m)
  if (match) apiPort = match[1]
} catch {}

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5000,
    strictPort: true,
    allowedHosts: true,
    proxy: {
      '/api': {
        target: `http://127.0.0.1:${apiPort}`,
        changeOrigin: true,
      }
    }
  }
})
