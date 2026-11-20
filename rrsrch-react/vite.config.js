import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// The source keeps JSX in .js files (from Create React App), so esbuild parses them as JSX.
export default defineConfig({
  plugins: [react()],
  esbuild: { loader: 'jsx', include: /src\/.*\.jsx?$/, exclude: [] },
  optimizeDeps: { esbuildOptions: { loader: { '.js': 'jsx' } } },
  build: { outDir: 'build' },
  // as CRA's "proxy" did: the API (server.js) on :3001
  server: { port: 3000, proxy: { '/api': { target: 'http://localhost:3001', changeOrigin: true, xfwd: true } } },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: './src/setupTests.js',
    testTimeout: 15000,   // the getByRole-heavy page tests pass in ~1s alone but pass 5s on a loaded machine
  },
});
