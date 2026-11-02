/**
 * probe.mjs — open the GLB probe page once and print what the models report.
 *
 * Thin driver over build-world's capture harness (tools/lib/harness.mjs), the
 * same browser/server plumbing its own tools use:
 *
 *   node probe.mjs --harness=<kit>/tools/lib/harness.mjs --port=5199 \
 *       --out=asset-report.json
 */
import { writeFileSync } from 'node:fs';

const args = Object.fromEntries(process.argv.slice(2).map((a) => {
  const i = a.indexOf('=');
  return i === -1 ? [a.replace(/^--/, ''), true] : [a.slice(2, i), a.slice(i + 1)];
}));

const H = await import(String(args.harness));

const server = await H.ensureServer({ port: Number(args.port ?? 5199), root: process.cwd() });
const browser = await H.launchBrowser();
const page = await H.newPage(browser, { w: 960, h: 540 });
const out = { ok: true };
try {
  await H.open(page, H.buildUrl({ port: Number(args.port ?? 5199), query: args.query ?? '' }));
  out.assetReport = await page.evaluate('window.__ASSET_REPORT__');
  out.renderInfo = await page.evaluate('window.__RENDER_INFO__');
  out.shots = await H.listShots(page);
} catch (e) {
  out.ok = false;
  out.fatal = String(e);
} finally {
  await browser.close();
  server?.kill();
}
writeFileSync(String(args.out ?? 'asset-report.json'), JSON.stringify(out, null, 1));
console.log(JSON.stringify(out, null, 1));