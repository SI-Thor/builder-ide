'use strict';
// bots/probe-site.js — the ground around the shelter site (6,67,11),
// as a height grid, plus the eight neighbours of the stuck wall cell
// (5,69,10). Read-only.
//   node probe-site.js
const mineflayer = require('mineflayer');
const { Vec3 } = require('vec3');
const bot = mineflayer.createBot({
  host: '192.168.0.78', port: 25565, username: 'ProbeT', auth: 'offline', version: '26.1',
});
const log = (...a) => console.log(...a);
bot.on('kicked', (r) => { log('kicked:', r); process.exit(1); });
setTimeout(() => { log('TIMEOUT'); process.exit(1); }, 90000);
bot.once('spawn', async () => {
  await new Promise((r) => setTimeout(r, 8000));
  const AIRS = new Set(['air', 'cave_air', 'void_air']);
  const height = (x, z) => {
    for (let y = 78; y >= 58; y--) {
      const b = bot.blockAt(new Vec3(x, y, z));
      if (b && !AIRS.has(b.name) && !b.name.endsWith('_grass') && b.name !== 'fern'
        && !b.name.includes('sapling') && !b.name.includes('standing')) return y;
    }
    return -1;
  };
  // warm-up
  for (let x = -2; x <= 12; x++) for (let z = 4; z <= 16; z++) height(x, z);
  await new Promise((r) => setTimeout(r, 2500));
  log('digit = surface height - 64 (leaves count as ground here); . = nothing');
  process.stdout.write('z\\x ');
  for (let x = 0; x <= 12; x++) process.stdout.write(String(x % 10));
  log();
  for (let z = 4; z <= 16; z++) {
    process.stdout.write(String(z).padStart(3) + ' ');
    for (let x = 0; x <= 12; x++) {
      const h = height(x, z);
      process.stdout.write(h < 0 ? '.' : String(Math.min(9, Math.max(0, h - 64))));
    }
    log();
  }
  const c = new Vec3(5, 69, 10);
  for (const [dx, dy, dz] of [[0, 0, 0], [0, -1, 0], [0, 1, 0], [1, 0, 0], [-1, 0, 0], [0, 0, 1], [0, 0, -1], [1, -1, 0], [-1, -1, 0], [0, -1, 1], [0, -1, -1]]) {
    const b = bot.blockAt(c.offset(dx, dy, dz));
    log(`(${c.x + dx},${c.y + dy},${c.z + dz})`, b ? b.name : 'null');
  }
  process.exit(0);
});
