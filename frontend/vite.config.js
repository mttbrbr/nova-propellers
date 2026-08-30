import react from '@vitejs/plugin-react';
import { env } from 'node:process';
import { defineConfig } from 'vite';

export default defineConfig({
  cacheDir: env.VITE_CACHE_DIR || '.vite-cache',
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://backend:8000',
        changeOrigin: true,
      },
    },
  },
  preview: {
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://backend:8000',
        changeOrigin: true,
      },
    },
  },
});
