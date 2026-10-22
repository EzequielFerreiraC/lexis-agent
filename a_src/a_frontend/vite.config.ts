import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

// Em desenvolvimento o Vite faz proxy de /api para a API local (lexis serve). Em produção a própria API serve o build.
export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    proxy: { '/api': { target: 'http://127.0.0.1:8000', changeOrigin: false } },
  },
  build: { outDir: 'dist', target: 'es2022', sourcemap: false },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    css: false,
    restoreMocks: true,
    unstubGlobals: true,
    include: ['src/**/*.test.{ts,tsx}'],
  },
});
