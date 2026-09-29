import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// The API lives in the FastAPI backend; proxy it so the UI can use same-origin
// paths and there is no CORS in development.
export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    proxy: {
      '/api': {
        target: process.env.STUDIO_API || 'http://127.0.0.1:8787',
        changeOrigin: true,
      },
    },
  },
});
