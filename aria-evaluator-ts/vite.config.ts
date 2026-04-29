import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { resolve } from 'node:path';

export default defineConfig({
  plugins: [react()],
  root: '.',
  publicDir: 'public',
  build: {
    outDir: 'dist/ui',
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    proxy: {
      '/api':         { target: 'http://localhost:3001', changeOrigin: true },
      '/reports':     { target: 'http://localhost:3001', changeOrigin: true },
      '/transcripts': { target: 'http://localhost:3001', changeOrigin: true },
      '/audio':       { target: 'http://localhost:3001', changeOrigin: true },
    },
  },
});
