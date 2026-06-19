import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const pfxPath = path.resolve(__dirname, '..', 'certs', 'caseclosed-dev.pfx')
const https =
  fs.existsSync(pfxPath)
    ? {
        pfx: fs.readFileSync(pfxPath),
      }
    : undefined

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    https,
    proxy: {
      '/api': 'http://127.0.0.1:8000',
    },
  },
})
