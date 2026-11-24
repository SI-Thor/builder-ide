'use strict';
// bots/probe-column.js — what is actually in a column, named block by
// block (y 58..78). The grid probe's "first solid from above" read 69
// over a bot standing at y62: something covers the gully, and a ramp
// cannot be planned until the something is named. Read-only.
//
//   node probe-column.js x,z x,z ...
const mineflayer = require('mineflayer');
const { Vec3 } = require('vec3');
const cols = process.argv.slice(2).map((s) => s.split(',').map(Number));
const bot = mineflayer.createBot({
  host: '192.168.0.78', port: 25565, username: 'ProbeC', auth: 'offline', version: '26.1',
});
const log = (...a) => console.log(...a);
bot.on('kicked', (r) => { log('kicked:', r); process.exit(1); });
setTimeout(() => { log('TIMEOUT'); process.exit(1); }, 120000);
bot.once('spawn', async () => {
  await new Promise((r) => setTimeout(r, 10000));
  // warm the sections (two passes, spaced)
  for (const [x, z] of cols) for (let y = 58; y <= 78; y++) bot.blockAt(new Vec3(x, y, z));
  await new Promise((r) => setTimeout(r, 3000));
  for (const [x, z] of cols) {
    const parts = [];
    for (let y = 58; y <= 78; y++) {
      const b = bot.blockAt(new Vec3(x, y, z));
      parts.push(`${y}:${b ? b.name : '?'}`);
    }
    log(`column ${x},${z}:`, parts.join(' '));
  }
  process.exit(0);
});
