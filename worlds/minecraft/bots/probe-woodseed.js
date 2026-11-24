'use strict';
// bots/probe-woodseed.js — day three's bootstrapping question: is there
// wood for the farm's hoe, and any tall-grass seed patch left, within
// the crew's walking reach of the depot? Read-only.
//   node probe-woodseed.js
const mineflayer = require('mineflayer');
const bot = mineflayer.createBot({
  host: '192.168.0.78', port: 25565, username: 'ProbeW', auth: 'offline', version: '26.1',
});
const log = (...a) => console.log(...a);
bot.on('kicked', (r) => { log('kicked:', r); process.exit(1); });
setTimeout(() => { log('TIMEOUT'); process.exit(1); }, 90000);
bot.once('spawn', async () => {
  await new Promise((r) => setTimeout(r, 8000));
  const logs = bot.findBlocks({
    matching: Object.values(bot.registry.blocks)
      .filter((b) => b.name.endsWith('_log')).map((b) => b.id),
    maxDistance: 96, count: 40,
  });
  const grass = bot.findBlocks({
    matching: (bot.registry.blocksByName.short_grass || {}).id,
    maxDistance: 96, count: 40,
  });
  const byDist = (a, b) => bot.entity.position.distanceTo(a) - bot.entity.position.distanceTo(b);
  logs.sort(byDist); grass.sort(byDist);
  const f = (p) => `${p.x},${p.y},${p.z}@${bot.entity.position.distanceTo(p).toFixed(0)}`;
  log('logs within 96:', logs.length, logs.slice(0, 6).map(f).join(' '));
  log('short_grass within 96:', grass.length, grass.slice(0, 6).map(f).join(' '));
  process.exit(0);
});
