#!/usr/bin/env node
/**
 * framecost.mjs — how much one frame of a GLB scene costs on this box, and
 * whether the kit's shutter (page.screenshot, 30 s default) can grab it at all.
 *
 * The kit's capture.mjs died on our 5.8 M-triangle agent-world export: two box
 * shots captured fine (5 k triangles, frustum-culled) and the room shot timed
 * out inside page.screenshot. This driver separates "the frame is slow" from
 * "the shutter is short": it times single renders per shot and then takes the
 * screenshot with a long timeout (default 180 s), so both numbers land in one
 * JSON file.
 *
 *   node framecost.mjs --harness=<kit>/tools/lib/harness.mjs --port=5199 \
 *       --out=framecost.json [--shots=world-wide] [--frames=3] [--shot-timeout=180000]
 *
 * Runs against the same page as probe.mjs (third_party/bw-glb: two symlinked
 * GLBs, our own lights/camera). Needs the kit's node_modules on the page's
 * node_modules path (run_bw_glb.sh makes that symlink).
 */
import { writeFileSync } from 'node:fs';

const args = Object.fromEntries(process.argv.slice(2).map((a) => {
  const i = a.indexOf('=');
  return i === -1 ? [a.replace(/^--/, ''), true] : [a.slice(2, i), a.slice(i + 1)];
}));

const H = await import(String(args.harness));
const PORT = Number(args.port ?? 5199);
const W = Number(args.w ?? 960);
const HH = Number(args.h ?? 540);
const FRAMES = Number(args.frames ?? 3);
const SHOT_TIMEOUT = Number(args['shot-timeout'] ?? 180000);

const server = await H.ensureServer({ port: PORT, root: process.cwd() });
const browser = await H.launchBrowser();
const page = await H.newPage(browser, { w: W, h: HH });
const out = { ok: true, port: PORT, size: `${W}x${HH}`, framesPerShot: FRAMES, shotTimeoutMs: SHOT_TIMEOUT, shots: [] };

try {
  await H.open(page, H.buildUrl({ port: PORT, query: args.query ?? '' }));
  out.renderInfoBoot = await H.renderInfo(page);
  const all = await H.listShots(page);
  const wanted = args.shots ? String(args.shots).split(',').map((s) => s.trim()) : all;
  for (const name of wanted) {
    const applied = await H.applyShot(page, name, 2);
    const entry = { shot: name, applied: !applied?.error };
    if (applied?.error) {
      entry.error = applied.error;
      out.ok = false;
      out.shots.push(entry);
      continue;
    }
    entry.renderMs = await page.evaluate((n) => {
      const t = [];
      for (let i = 0; i < n; i += 1) {
        const t0 = performance.now();
        window.__PUMP__(1);
        t.push(Math.round((performance.now() - t0) * 10) / 10);
      }
      return t;
    }, FRAMES);
    entry.print = await H.renderInfo(page);
    const t0 = Date.now();
    try {
      const buf = await page.screenshot({ type: 'png', timeout: SHOT_TIMEOUT });
      entry.shutterMs = Date.now() - t0;
      entry.pngBytes = buf.length;
    } catch (e) {
      entry.shutterMs = Date.now() - t0;
      entry.shutterError = String(e.message ?? e).split('\n')[0];
      out.ok = false;
    }
    entry.contextLost = await H.contextLost(page);
    out.shots.push(entry);
    console.log(name, 'render', JSON.stringify(entry.renderMs), 'ms; shutter', entry.shutterMs, 'ms', entry.shutterError ?? 'ok');
  }
} catch (e) {
  out.ok = false;
  out.fatal = String(e);
} finally {
  await browser.close();
  server?.kill();
}

writeFileSync(String(args.out ?? 'framecost.json'), JSON.stringify(out, null, 1));
console.log(JSON.stringify(out, null, 1));