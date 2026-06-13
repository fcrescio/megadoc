import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

import { execSync } from 'child_process';

const gitHash = execSync('git rev-parse --short HEAD').toString().trim();

export default defineConfig({
  plugins: [react()],
  define: {
    __GIT_HASH__: JSON.stringify(gitHash),
  },
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
