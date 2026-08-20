import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// base: './' so the built assets resolve correctly when FastAPI serves
// frontend/dist from '/'. The dev proxy forwards same-origin /api calls to the
// control plane on :8080 so the client only ever talks to /api/... .
export default defineConfig({
  base: './',
  plugins: [react()],
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:8080',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
  },
});
