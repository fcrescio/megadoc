import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    proxy: {
      '/documents': {
        target: 'http://api:8080',
      },
      '/jobs': {
        target: 'http://api:8080',
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: true,
  },
})
