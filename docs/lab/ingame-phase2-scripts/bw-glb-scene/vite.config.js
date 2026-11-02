import { defineConfig } from 'vite';

// The harness spawns `vite --port <port> --strictPort --host 127.0.0.1` with this
// directory as cwd, so the config's `root` is what the browser gets. Keeping our
// own root here means build-world's kit clone stays untouched (its vite.config.js
// points at example/); the kit is only used for tools/ and node_modules.
export default defineConfig({
  root: '.',
  server: {
    host: '127.0.0.1',
    strictPort: true,
    hmr: false,
    fs: { allow: ['..', '../..'] },
  },
  build: { target: 'es2022' },
})