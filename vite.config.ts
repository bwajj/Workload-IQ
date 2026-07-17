import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// The Vite dev server (5173) proxies /api calls to the Flask API on 5001.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:5001',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
  },
});
