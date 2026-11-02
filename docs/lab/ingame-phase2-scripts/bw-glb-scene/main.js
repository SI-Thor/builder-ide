/**
 * GLB into build-world's three.js kit — what the kit needs us to write ourselves.
 *
 * The kit (skills/build-world/engines/threejs) ships NO model loading: no
 * GLTFLoader wrapper, no asset manifest, no material rework. So a GLB scene is
 * bring-your-own `three/examples/jsm/loaders/GLTFLoader.js` plus your own
 * placement. What the kit DOES own is the capture contract, which this page
 * implements by hand against the harness in tools/lib/harness.mjs:
 *
 *   window.__SHOTS__       named, reproducible framings
 *   window.__APPLY_SHOT__  pose the camera for a named shot
 *   window.__PUMP__(n)     render n frames (the harness's settle/lockstep clock)
 *   window.__PRESENT__(n)  yield to the compositor without rendering
 *   window.__RENDER_INFO__ what the renderer did
 *   window.__READY__       only after every asset resolved
 *
 * Two models load, both SYMLINKED (never copied — the SimReady set is CC-BY-4.0
 * and stays out of repos):
 *   assets/box_long_a08.glb  -> ~/lm-wt/simready-survey/data/glb/box_long_a08.glb
 *                               (our critic reference set, SimReady, CC-BY-4.0)
 *   assets/books_room.glb    -> ~/lm-wt/world-stream-scratch/bakeA/source_textured.glb
 *                               (an agent-world scene export from the
 *                                reference-books-room runs)
 *
 * The probe records, per model: load time, mesh count, triangle count, world
 * AABB, and `bottomOffset` = AABB min Y as exported. That number is the same
 * measurement topview's `inspect nodes` calls grounding/bottomOffset — so the
 * two tool reports can be compared on the same objects.
 */
import * as THREE from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';

const canvas = document.getElementById('game');
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, powerPreference: 'high-performance' });
renderer.setPixelRatio(1);
renderer.setSize(canvas.clientWidth || 960, canvas.clientHeight || 540, false);
renderer.outputColorSpace = THREE.SRGBColorSpace;

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x101010);
scene.add(new THREE.HemisphereLight(0x8899aa, 0x222222, 0.9));
const sun = new THREE.DirectionalLight(0xffffff, 1.6);
sun.position.set(4, 8, 5);
scene.add(sun);
const params = new URLSearchParams(location.search);
if (params.get('lightdim') === '1') sun.intensity = 0.4; // the gate's positive control

const ground = new THREE.Mesh(
  new THREE.PlaneGeometry(80, 80),
  new THREE.MeshStandardMaterial({ color: 0x303030, roughness: 1 }),
);
ground.rotation.x = -Math.PI / 2;
scene.add(ground);

const camera = new THREE.PerspectiveCamera(40, 16 / 9, 0.05, 500);

const MODELS = [
  { name: 'simready-box_long_a08', url: './assets/box_long_a08.glb', x: 0 },
  { name: 'agent-world-books-room', url: './assets/books_room.glb', x: 8 },
];

const report = { models: [], kit: { gltfLoader: 'three/examples/jsm GLTFLoader (our code)', placement: 'our code' } };

function trianglesOf(root) {
  let tris = 0;
  let meshes = 0;
  root.traverse((o) => {
    if (!o.isMesh) return;
    meshes += 1;
    const g = o.geometry;
    tris += g.index ? g.index.count / 3 : (g.attributes.position?.count ?? 0) / 3;
  });
  return { meshes, triangles: Math.round(tris) };
}

const loader = new GLTFLoader();
await Promise.all(MODELS.map(async (m) => {
  const t0 = performance.now();
  try {
    const gltf = await loader.loadAsync(m.url);
    const root = gltf.scene;
    root.position.x += m.x;
    scene.add(root);
    const box = new THREE.Box3().setFromObject(root);
    const { meshes, triangles } = trianglesOf(root);
    report.models.push({
      name: m.name,
      url: m.url,
      loadMs: Math.round(performance.now() - t0),
      meshes,
      triangles,
      boundsMin: box.min.toArray().map((v) => Math.round(v * 1000) / 1000),
      boundsMax: box.max.toArray().map((v) => Math.round(v * 1000) / 1000),
      bottomOffset: Math.round(box.min.y * 1000) / 1000, // same ground measure as topview `inspect nodes`
    });
  } catch (err) {
    report.models.push({ name: m.name, url: m.url, error: String(err) });
    console.error('asset load failed', m.name, err);
  }
}));

const SHOTS = {
  'box-wide': {
    doc: 'the critic-reference box, whole object in frame',
    pos: [1.6, 1.2, 1.6], look: [0, 0.5, 0], fov: 40,
  },
  'box-detail': {
    doc: 'box corner and ground contact edge',
    pos: [0.7, 0.5, 0.7], look: [0, 0.25, 0], fov: 32,
  },
  'world-wide': {
    doc: 'the agent-world room export with the box beside it',
    pos: [12, 5, 9], look: [8, 1, 0], fov: 55,
  },
};
window.__SHOTS__ = SHOTS;

function render() {
  renderer.render(scene, camera);
}
function pose(name) {
  const s = SHOTS[name];
  if (!s) return { error: `unknown shot ${name}` };
  camera.position.set(s.pos[0], s.pos[1], s.pos[2]);
  camera.lookAt(s.look[0], s.look[1], s.look[2]);
  camera.fov = s.fov;
  camera.updateProjectionMatrix();
  render();
  return {};
}
window.__APPLY_SHOT__ = pose;
window.__PUMP__ = (n) => {
  for (let i = 0; i < n; i += 1) render();
  return Promise.resolve({ frames: n });
};
// baseline.mjs's compositor handshake (harness `present`): yield frames WITHOUT
// rendering, so the screenshot RPC cannot race the last render.
window.__PRESENT__ = (n) => new Promise((r) => requestAnimationFrame(() => r({ presented: n })));
Object.defineProperty(window, '__RENDER_INFO__', {
  get: () => ({
    calls: renderer.info.render.calls,
    triangles: renderer.info.render.triangles,
    geometries: renderer.info.memory.geometries,
    textures: renderer.info.memory.textures,
  }),
});
window.__ASSET_REPORT__ = report;
window.__GLB_POSITIONS__ = () => report.models.map((m) => m.boundsMin);

// Two frames before READY so the first screenshot is not a half-compiled frame.
pose('world-wide');
render();
render();
window.__READY__ = true;
console.info('ASSET_REPORT', JSON.stringify(report));