import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: 'dist-app',
    rollupOptions: { input: 'app.html' },
  },
  server: {
    proxy: { '/api': 'http://localhost:8000' },
  },
});
