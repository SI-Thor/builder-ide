// verify.mjs — the return screen, checked in a real browser (Playwright).
//   PATH=$HOME/.nvm/versions/node/v24.22.2/bin:$PATH node tools/return_screen/verify.mjs <base-url> <out-dir>
// What it checks, and writes to <out-dir>/verdict.json:
//   - each section screenshotted (desktop 1280x900), full page too
//   - phone-width layout (390x844) with no horizontal document overflow
//   - zero console errors / page errors on load and after interactions
//   - the interactions a returning human actually makes: pick the timeline,
//     preview a fork, answer a pending question, ask "what happened to X?",
//     mark seen — each leaves the page without errors
import { chromium } from 'playwright';
import { mkdirSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

const [base, outDir] = process.argv.slice(2);
mkdirSync(outDir, { recursive: true });
const verdict = { base, shots: [], console_errors: [], page_errors: [], checks: {} };

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
page.on('console', (m) => { if (m.type() === 'error') verdict.console_errors.push(m.text()); });
page.on('pageerror', (e) => verdict.page_errors.push(String(e)));

await page.goto(base, { waitUntil: 'networkidle' });
await page.waitForTimeout(1500);

// Casey has no recorded visit, so their window is the whole 25 h ledger —
// the rich view a first return actually sees. (TestHumanH was in the world
// 34 min ago; their window is short.) Exercise the picker, not the default.
await page.selectOption('#human-select', 'Casey');
await page.waitForTimeout(2500);

// every section, screenshotted
const sections = ['letter', 'beat-what-changed', 'beat-what-matters',
                  'beat-waiting', 'beat-undone', 'beat-next'];
for (const id of sections) {
  const el = page.locator('#' + id);
  await el.scrollIntoViewIfNeeded();
  await page.waitForTimeout(300);
  const file = `section-${id}.png`;
  await el.screenshot({ path: join(outDir, file) });
  verdict.shots.push(file);
}
await page.screenshot({ path: join(outDir, 'full-desktop.png'), fullPage: true });
verdict.shots.push('full-desktop.png');
verdict.checks.letter_words = await page.locator('#letter-words').textContent();
verdict.checks.mark_count = await page.locator('#scrubber g.mark').count();
verdict.checks.lane_rows = await page.locator('#scrubber-lanes .lane-row').count();
verdict.checks.counters = await page.locator('#threshold-counters .counter').count();

// interaction 1: ask the box
await page.locator('#beat-what-matters').scrollIntoViewIfNeeded();
await page.fill('#ask-input', 'what did Kite play in the last 3 hours?');
await page.click('#ask-form button');
await page.waitForSelector('#ask-answer .pulled', { timeout: 20000 });
verdict.checks.ask_pulled = (await page.locator('#ask-answer .pulled').textContent()).trim();
await page.screenshot({ path: join(outDir, 'interaction-ask.png') });
verdict.shots.push('interaction-ask.png');

// interaction 2: click the timeline -> sets the rewind point -> preview
const scrub = page.locator('#scrubber');
await scrub.scrollIntoViewIfNeeded();
await page.waitForTimeout(300);
const box = await scrub.boundingBox();  // measured after the ask answer settled the layout
await page.mouse.click(box.x + box.width * 0.5, box.y + box.height * 0.5);
await page.waitForTimeout(400);
verdict.checks.rewind_point_line = (await page.locator('#rewind-point-line').textContent()).trim();
await page.locator('#beat-undone').scrollIntoViewIfNeeded();
await page.waitForTimeout(200);
await page.click('#rewind-preview-btn');
await page.waitForSelector('#rewind-result .fork', { timeout: 20000 });
verdict.checks.fork = (await page.locator('#rewind-result .fork').textContent()).trim();
await page.screenshot({ path: join(outDir, 'interaction-rewind.png') });
verdict.shots.push('interaction-rewind.png');

// interaction 3: answer a pending precedent question (if one is shown)
await page.locator('#beat-waiting').scrollIntoViewIfNeeded();
const q = page.locator('#precedents .question button').first();
if (await q.count()) {
  await page.locator('#precedents .question .note').first().fill('answered during verification');
  await q.click();
  await page.waitForTimeout(2500);
  verdict.checks.precedent_answered = true;
  await page.screenshot({ path: join(outDir, 'interaction-precedent.png') });
  verdict.shots.push('interaction-precedent.png');
} else {
  verdict.checks.precedent_answered = false;
}

// interaction 4: mark seen
await page.locator('#mark-seen').click();
await page.waitForTimeout(2000);
verdict.checks.since_line_after = (await page.locator('#since-line').textContent()).trim();

// interaction 5: switch to the human whose window carries a pending question
// (Casey's whole-ledger window refuses 27% — under the stub's 50% bar;
//  TestHumanH's recent window refuses 52%, which asks)
await page.selectOption('#human-select', 'TestHumanH');
await page.waitForTimeout(2500);
await page.locator('#beat-waiting').scrollIntoViewIfNeeded();
const q2 = page.locator('#precedents .question button').first();
if (await q2.count()) {
  await page.locator('#precedents .question .note').first().fill('ruled from the verification pass');
  await q2.click();
  await page.waitForTimeout(3000);
  verdict.checks.precedent_answered = true;
  await page.screenshot({ path: join(outDir, 'interaction-precedent.png') });
  verdict.shots.push('interaction-precedent.png');
}

// phone width: no horizontal overflow
const phone = await browser.newPage({ viewport: { width: 390, height: 844 } });
phone.on('console', (m) => { if (m.type() === 'error') verdict.console_errors.push('phone: ' + m.text()); });
phone.on('pageerror', (e) => verdict.page_errors.push('phone: ' + String(e)));
await phone.goto(base, { waitUntil: 'networkidle' });
await phone.waitForTimeout(1500);
// the phone opens like a returning human would: on the human with a real
// window (the desktop pass may have just marked Casey seen seconds ago)
await phone.selectOption('#human-select', 'TestHumanH');
await phone.waitForTimeout(2500);
verdict.checks.phone_overflow = await phone.evaluate(
  () => document.documentElement.scrollWidth - document.documentElement.clientWidth);
await phone.screenshot({ path: join(outDir, 'phone-full.png'), fullPage: true });
verdict.shots.push('phone-full.png');
await phone.close();

await browser.close();
verdict.ok = verdict.console_errors.length === 0 && verdict.page_errors.length === 0
  && verdict.checks.phone_overflow <= 0 && verdict.checks.mark_count > 0;
writeFileSync(join(outDir, 'verdict.json'), JSON.stringify(verdict, null, 2));
console.log(JSON.stringify({ ok: verdict.ok, checks: verdict.checks,
  console_errors: verdict.console_errors, page_errors: verdict.page_errors }, null, 2));
