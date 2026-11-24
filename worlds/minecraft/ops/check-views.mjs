// ops/check-views.mjs — do the pages really work, in a real browser?
//
// The 3D view once showed "null is not supported" and a blank canvas, and
// a 200 with live frames did not catch it. So this drives a browser: it
// opens the page, reads everything the console says, and looks at the
// pixels that were actually drawn.
//
//   node ops/check-views.mjs <url> [name]
//
// Prints a line per check and exits non-zero when a check fails.

import { createRequire } from 'node:module';
import path from 'node:path';
import os from 'node:os';

const PLAYWRIGHT_HOME = process.env.PLAYWRIGHT_HOME ||
  path.join(os.homedir(), 'lm-tools', 'playwright');
const require = createRequire(import.meta.url);
const { chromium } = require(path.join(PLAYWRIGHT_HOME, 'node_modules', 'playwright'));

const url = process.argv[2] || 'http://127.0.0.1:8080/';
const name = process.argv[3] || 'the page';

const failures = [];
const notes = [];

function check(ok, message, detail) {
  if (ok) {
    console.log(`  ok    ${message}`);
  } else {
    failures.push(message);
    console.log(`  FAIL  ${message}${detail ? ' — ' + detail : ''}`);
  }
}

// --- the page ---------------------------------------------------------------

const browser = await chromium.launch({
  args: ['--enable-unsafe-webgpu', '--use-angle=vulkan'],
});
const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });

const consoleLines = [];
const pageErrors = [];
const failedRequests = [];
const badResponses = [];

page.on('console', (m) => consoleLines.push(`[${m.type()}] ${m.text()}`));
page.on('pageerror', (e) => pageErrors.push(e.message));
page.on('requestfailed', (r) =>
  failedRequests.push(`${r.url()} ${r.failure()?.errorText}`)
);
page.on('response', (r) => {
  if (r.status() >= 400) badResponses.push(`${r.status()} ${r.url()}`);
});

await page.goto(url, { waitUntil: 'networkidle', timeout: 30000 }).catch((e) => {
  notes.push(`the page did not finish loading: ${e.message}`);
});
await page.waitForTimeout(6000);

const title = await page.title();
const bodyText = await page.evaluate(() => document.body.innerText.slice(0, 1200));
const shotPath = `/tmp/aw-${name.replace(/[^a-z0-9]+/gi, '-')}.png`;
const shot = await page.screenshot({ path: shotPath });

console.log(`\n${name}: ${url}`);
console.log(`  title  ${title}`);
check(pageErrors.length === 0, 'no page errors', pageErrors.join(' | '));
check(
  !consoleLines.some((l) => /not supported/i.test(l)) &&
    !/not supported/i.test(bodyText),
  'nothing says a version is not supported',
  consoleLines.filter((l) => /not supported/i.test(l)).join(' | ')
);
check(failedRequests.length === 0, 'no failed requests', failedRequests.join(' | '));
check(badResponses.length === 0, 'no error responses', badResponses.join(' | '));

// What this page must actually show.
if (url.endsWith('/')) {
  check(
    /drawn as|Minecraft/.test(bodyText),
    'the page says how the world is being drawn',
    bodyText.slice(0, 120)
  );
  check(
    !/the 3D view cannot draw/i.test(bodyText),
    'the page is not the "cannot draw this" message'
  );
} else if (url.endsWith('/ascii')) {
  const frame = await page.evaluate(() => {
    const pre = document.querySelector('pre');
    return pre ? pre.textContent : '';
  });
  check(frame.trim().length > 40, 'the text view has a frame', `${frame.length} characters`);
} else if (url.endsWith('/voices')) {
  check(
    /voice|agent/i.test(bodyText),
    'the voices page says what it is for',
    bodyText.slice(0, 120)
  );
}

// --- the pixels -------------------------------------------------------------

// The browser decodes its own screenshot, so no image library is needed.
const b64 = shot.toString('base64');
const pixels = await page.evaluate(async (data) => {
  const img = new Image();
  img.src = 'data:image/png;base64,' + data;
  await img.decode();
  const canvas = document.createElement('canvas');
  canvas.width = img.width;
  canvas.height = img.height;
  const ctx = canvas.getContext('2d');
  ctx.drawImage(img, 0, 0);
  const { data: pixels } = ctx.getImageData(0, 0, canvas.width, canvas.height);
  const counts = new Map();
  let total = 0;
  for (let i = 0; i < pixels.length; i += 4) {
    const key = (pixels[i] << 16) | (pixels[i + 1] << 8) | pixels[i + 2];
    counts.set(key, (counts.get(key) || 0) + 1);
    total += 1;
  }
  let biggest = 0;
  for (const count of counts.values()) biggest = Math.max(biggest, count);
  return {
    width: canvas.width,
    height: canvas.height,
    total,
    colours: counts.size,
    biggestShare: biggest / total,
  };
}, b64);

console.log(
  `  pixels ${pixels.width}x${pixels.height}, ${pixels.colours} colours, biggest ${(
    pixels.biggestShare * 100
  ).toFixed(1)}%`
);
check(pixels.colours > 50, 'the canvas is not one flat colour', `${pixels.colours} colours`);
check(
  pixels.biggestShare < 0.97,
  'the canvas is not almost one colour',
  `${(pixels.biggestShare * 100).toFixed(1)}%`
);

// A canvas of the right size is the 3D view's own; the other pages are text.
const canvasSize = await page.evaluate(() => {
  const canvas = document.querySelector('canvas');
  if (!canvas) return null;
  return { width: canvas.width, height: canvas.height };
});
if (canvasSize) {
  check(
    canvasSize.width > 0 && canvasSize.height > 0,
    'the canvas has a size',
    `${canvasSize.width}x${canvasSize.height}`
  );
}

console.log(`  text   ${bodyText.replace(/\n+/g, ' | ').slice(0, 200)}`);
console.log(`  shot   ${shotPath}`);

if (notes.length) {
  for (const note of notes) console.log(`  note   ${note}`);
}
// Every console error is a failure. (Correction, 2026-11-01: this check
// used to excuse "Computed radius is NaN" warnings as an empty-section
// artifact of three.js. They were not. They were the browser's fallback
// box for name-less entities — BoxGeometry(undefined, undefined,
// undefined) — a dozen per load; viewer/src/server.js now leaves those
// entities out. The playtest note in docs/ has the diagnosis.)
const consoleErrors = consoleLines.filter((l) => l.startsWith('[error]'));
check(
  consoleErrors.length === 0,
  'no console errors',
  consoleErrors.slice(0, 3).join(' | ')
);

await browser.close();

console.log('');
if (failures.length) {
  console.log(`${name}: ${failures.length} checks failed`);
  process.exit(1);
}
console.log(`${name}: all checks passed`);
