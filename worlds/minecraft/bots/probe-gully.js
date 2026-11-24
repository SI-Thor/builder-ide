'use strict';
// bots/probe-gully.js — the depot gully, read as a height grid. Prints
// every crew member's position and the ground height of every column
// around the depot, so a ramp out of the gully can be planned from the
// world's own ground. Read-only. A warm-up pass loads the sections
// before the recorded pass (the first scan of 2026-11-02 read fresh
// chunks and missed the upper half of columns mid-load).
//
//   node probe-gully.js
const mineflayer = require('mineflayer');
const { Vec3 } = require('vec3');
const bot = mineflayer.createBot({
  host: '192.168.0.78', port: 25565, username: 'ProbeG', auth: 'offline', version: '26.1',
});
const log = (...a) => console.log(...a);
bot.on('kicked', (r) => { log('kicked:', r); process.exit(1); });
setTimeout(() => { log('TIMEOUT'); process.exit(1); }, 120000);
bot.once('spawn', async () => {
  await new Promise((r) => setTimeout(r, 10000));
  const AIRS = new Set(['air', 'cave_air', 'void_air']);
  const SKIPPABLE = (n) => AIRS.has(n) || n.endsWith('_grass') || n === 'fern'
    || n.includes('sapling') || n.includes('standing');
  const groundHeight = (x, z) => {
    for (let y = 78; y >= 58; y--) {
      const b = bot.blockAt(new Vec3(x, y, z));
      if (b && !SKIPPABLE(b.name)) return y;
    }
    return -1;
  };
  const x0 = -12, x1 = 6, z0 = -10, z1 = 18;
  // warm-up pass (loads sections), then the recorded pass
  for (let x = x0; x <= x1; x++) for (let z = z0; z <= z1; z++) groundHeight(x, z);
  await new Promise((r) => setTimeout(r, 3000));
  for (const name of ['Pebble', 'Timber', 'Kite', 'Sprout']) {
    const e = Object.values(bot.entities).find(
      (x) => x && x.type === 'player' && x.username === name
    );
    if (e) log(name, 'at', e.position.x.toFixed(1), e.position.y.toFixed(1), e.position.z.toFixed(1));
  }
  log('digit = ground height - 60; x runs', x0, '..', x1, '(".") = nothing solid');
  process.stdout.write('z\\x ');
  for (let x = x0; x <= x1; x++) process.stdout.write(String(Math.abs(x) % 10));
  log();
  for (let z = z0; z <= z1; z++) {
    process.stdout.write(String(z).padStart(3) + ' ');
    for (let x = x0; x <= x1; x++) {
      const h = groundHeight(x, z);
      process.stdout.write(h < 0 ? '.' : String(Math.min(9, h - 60)));
    }
    log();
  }
  for (const [x, z, what] of [[-2, -5, 'chest'], [2, -1, 'depot()'], [-10, 0, 'farm b044'], [-7, 15, 'spawn']]) {
    log(what, '(', x, ',', z, ') ground', groundHeight(x, z),
      'block', (bot.blockAt(new Vec3(x, 62, z)) || { name: '?' }).name);
  }
  process.exit(0);
});
