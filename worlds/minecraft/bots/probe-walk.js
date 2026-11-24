'use strict';
// bots/probe-walk.js — drive the crew's own gotoNear on the hunt's
// own goals, with the same stall watcher, and watch it from outside:
// position + the block being dug, twice a second. The guard here is
// the same rule the crew runs (no digging within 4 of a person's
// build), so the probe can never mine a neighbour's block.
//
//   node probe-walk.js 9 62 0
const mineflayer = require('mineflayer');
const { givePathfinding, gotoNear } = require('./src/api');

const goal = { x: Number(process.argv[2] || 9), y: Number(process.argv[3] || 62), z: Number(process.argv[4] || 0) };
const bot = mineflayer.createBot({
  host: '192.168.0.78', port: 25565, username: 'ProbeWK', auth: 'offline', version: '26.1',
});
const log = (...a) => console.log(new Date().toISOString().slice(11, 19), ...a);
bot.on('kicked', (r) => { log('kicked:', r); process.exit(1); });
setTimeout(() => { log('TIMEOUT'); process.exit(1); }, 120000);

// the two blocks a visitor placed on 2026-11-02 (player-builds.jsonl)
const PERSON = [[5, 67, 2], [4, 66, 2]];
const guard = {
  mayDig: (p) => {
    for (const [x, y, z] of PERSON) {
      const d = Math.sqrt((x - p.x) ** 2 + (y - p.y) ** 2 + (z - p.z) ** 2);
      if (d <= 4) return { ok: false, why: 'probe: near a person build' };
    }
    return { ok: true };
  },
};

bot.once('spawn', async () => {
  givePathfinding(bot, guard);
  await new Promise((r) => setTimeout(r, 8000));
  const p0 = bot.entity.position;
  log('probe at', p0.x.toFixed(1), p0.y.toFixed(1), p0.z.toFixed(1), 'goal', JSON.stringify(goal));
  let last = '';
  const t = setInterval(() => {
    const p = bot.entity.position;
    const dig = bot.targetDigBlock;
    const here = `${p.x.toFixed(1)},${p.y.toFixed(1)},${p.z.toFixed(1)}`;
    const line = dig ? `digging ${dig.name} at ${dig.position}` : here;
    if (line !== last) { log(line); last = line; }
  }, 500);
  const started = Date.now();
  try {
    await gotoNear(bot, goal.x, goal.y, goal.z, 2, 30000);
    log(`ARRIVED in ${((Date.now() - started) / 1000).toFixed(1)} s at`, bot.entity.position.toString());
  } catch (err) {
    log(`FAILED after ${((Date.now() - started) / 1000).toFixed(1)} s:`, String((err && err.message) || err));
  }
  clearInterval(t);
  process.exit(0);
});
