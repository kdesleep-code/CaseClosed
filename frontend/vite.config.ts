import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const pfxPath = path.resolve(__dirname, '..', 'certs', 'caseclosed-dev.pfx')
const pdfjsPublicPath = path.resolve(__dirname, 'public', 'pdfjs')
const pdfjsDistPath = path.resolve(__dirname, 'node_modules', 'pdfjs-dist')
const https =
  fs.existsSync(pfxPath)
    ? {
        pfx: fs.readFileSync(pfxPath),
      }
    : undefined

function copyPdfjsAssets() {
  const assetDirs = ['cmaps', 'standard_fonts']
  for (const dirname of assetDirs) {
    const source = path.join(pdfjsDistPath, dirname)
    const destination = path.join(pdfjsPublicPath, dirname)
    if (!fs.existsSync(source)) continue
    fs.rmSync(destination, { recursive: true, force: true })
    fs.mkdirSync(path.dirname(destination), { recursive: true })
    fs.cpSync(source, destination, { recursive: true })
  }
}

function pdfjsAssetsPlugin() {
  return {
    name: 'caseclosed-pdfjs-assets',
    buildStart() {
      copyPdfjsAssets()
    },
    configureServer() {
      copyPdfjsAssets()
    },
  }
}

// https://vite.dev/config/
export default defineConfig({
  plugins: [pdfjsAssetsPlugin(), react()],
  server: {
    https,
    proxy: {
      '/api': 'http://127.0.0.1:8000',
    },
  },
})
