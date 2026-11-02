#!/usr/bin/env node
/**
 * shim-diag.mjs — why (or whether) the capture shim reached __READY__ on the
 * viewer page. Open the page ONCE, wait, and report the shim's own state plus
 * the console log: is window.__THREE__ there, was WebGLRenderer.render hooked,
 * what does __RENDER_INFO__ say, how many canvases the page has.
 *
 *   node shim-diag.mjs --harness=<kit>/tools/lib/harness.mjs --port=8288 \
 *       --out=shim-diag.json [--wait=25000]
 *
 * It deliberately does NOT wait for __READY__: when ready never comes, this is
 * the file that says why. Needs the viewer copy's server already running.
 */
import { writeFileSync } from 'node:fs';

const args = Object.fromEntries(process.argv.slice(2).map((a) => {
  const i = a.indexOf('=');
  return i === -1 ? [a.replace(/^--/, ''), true] : [a.slice(2, i), a.slice(i + 1)];
}));

const H = await import(String(args.harness));
const PORT = Number(args.port ?? 8288);
const browser = await H.launchBrowser();
const page = await H.newPage(browser, { w: Number(args.w ?? 960), h: Number(args.h ?? 540) });
const out = { port: PORT };

try {
  await page.goto(H.buildUrl({ port: PORT }), { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.waitForTimeout(Number(args.wait ?? 25000));
  out.diag = await page.evaluate(() => ({
    three: typeof window.__THREE__,
    hasWebGLRenderer: !!(window.__THREE__ && window.__THREE__.WebGLRenderer),
    hooked: !!(
      window.__THREE__ &&
      window.__THREE__.WebGLRenderer &&
      window.__THREE__.WebGLRenderer.prototype.__gateShim
    ),
    ready: typeof window.__READY__ === 'undefined' ? 'undefined' : window.__READY__,
    info: window.__RENDER_INFO__ ?? null,
    shots: Object.keys(window.__SHOTS__ ?? {}),
    canvases: document.querySelectorAll('canvas').length,
  }));
} catch (e) {
  out.fatal = String(e);
}
out.logs = page.__logs.slice(0, 60);
await browser.close();
writeFileSync(String(args.out ?? 'shim-diag.json'), JSON.stringify(out, null, 1));
console.log(JSON.stringify(out, null, 1));