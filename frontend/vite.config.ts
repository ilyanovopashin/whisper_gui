import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  const backendUrl = env.VITE_BACKEND_URL ?? 'http://localhost:8000';

  return {
    plugins: [react()],
    server: {
      port: 5173,
      host: '0.0.0.0',
      proxy: {
        '/api': {
          target: backendUrl,
          changeOrigin: true
        },
        '/jobs': {
          target: backendUrl,
          changeOrigin: true
        }
      }
    },
    preview: {
      port: 4173,
      host: '0.0.0.0'
    }
  };
});
