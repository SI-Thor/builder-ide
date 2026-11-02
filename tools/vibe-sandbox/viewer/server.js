// The hot-load viewer's server: three static roots, no dependencies.
//
//   /            the viewer page (this directory)
//   /three/      the agent-world viewer's three.js copy (reuse, not a second download)
//   /outbox/     the pipeline's outbox (manifest.json + the room GLBs)
//
// Started by the runner (or by hand): node tools/vibe-sandbox/viewer/server.js
const http = require('http');
const fs = require('fs');
const path = require('path');

const LANE = path.resolve(__dirname, '..');
const OUTBOX = path.join(LANE, '../../artifacts/vibe-sandbox/outbox');
const THREE = path.join(process.env.HOME, 'lm-wt/agent-world/viewer/node_modules/three');
const PORT = Number(process.env.VIEWER_PORT || 8129);

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.json': 'application/json',
  '.glb': 'model/gltf-binary',
  '.png': 'image/png',
};

const server = http.createServer((req, res) => {
  const url = decodeURIComponent(req.url.split('?')[0]);
  let root, rel;
  if (url === '/' ) { root = __dirname; rel = 'index.html'; }
  else if (url.startsWith('/three/')) { root = THREE; rel = url.slice('/three/'.length); }
  else if (url.startsWith('/outbox/')) { root = OUTBOX; rel = url.slice('/outbox/'.length); }
  else { root = __dirname; rel = url; }
  const file = path.normalize(path.join(root, rel));
  if (!file.startsWith(root)) { res.writeHead(403); res.end(); return; }
  fs.readFile(file, (err, data) => {
    if (err) { res.writeHead(404); res.end('not found'); return; }
    res.writeHead(200, { 'Content-Type': MIME[path.extname(file)] || 'application/octet-stream' });
    res.end(data);
  });
});
server.listen(PORT, '127.0.0.1', () => console.log(`viewer on http://127.0.0.1:${PORT}`));
