// The playtest driver: headless Chromium (Playwright) opens the viewer, waits
// for the room to hot-load, and runs the in-page capsule walk.
//
//   node playtest.mjs <viewer-url> <qa-report-out.json> <room_id>
//
// Runs on the Thor against the aarch64 Chromium Playwright already holds.
import { chromium } from 'playwright';
import { writeFileSync } from 'node:fs';

const [url, out, room] = process.argv.slice(2);
const browser = await chromium.launch({
  args: ['--enable-unsafe-swiftshader', '--no-sandbox'],
});
const page = await browser.newPage({ viewport: { width: 1280, height: 720 } });
const errors = [];
page.on('pageerror', (e) => errors.push(String(e)));

await page.goto(`${url}?room=${room}`);
await page.waitForFunction(
  () => window.__roomState && window.__roomState.status === 'loaded',
  null,
  { timeout: 60000 }
);
const report = await page.evaluate(() => window.__playtest());
await page.screenshot({ path: out.replace(/\.json$/, '.png') });
report.console_errors = errors;
report.room_arg = room;
writeFileSync(out, JSON.stringify(report, null, 1));
console.log(JSON.stringify({
  room: report.room_id, ok: report.ok,
  findings: report.findings.length,
  frame_p95: report.metrics.frame_ms_p95,
  renderer: (report.renderer || '').slice(0, 60),
}));
await browser.close();
