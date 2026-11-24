'use strict';
// bots/probe-find.js — what does a bot standing at the ramp site see
// for stone? The ramp's quarry (find_block stone/cobblestone, 24,
// min_y 49, any_level) returned nothing from Timber's own steps, while
// probe-column.js read stone at y58-62 in the site's own columns.
// Read-only.
const mineflayer = require('mineflayer');
const bot = mineflayer.createBot({
  host: '192.168.0.78', port: 25565, username: 'ProbeF', auth: 'offline', version: '26.1',
});
const log = (...a) => console.log(...a);
bot.on('kicked', (r) => { log('kicked:', r); process.exit(1); });
setTimeout(() => { log('TIMEOUT'); process.exit(1); }, 90000);
bot.once('spawn', async () => {
  await new Promise((r) => setTimeout(r, 9000));
  // stand where Timber's step stands: the first ramp block (-2,62,-4)
  const target = new (require('vec3').Vec3)(-2, 62, -4);
  // tp is not available; read from current position (spawn is close)
  const feet = bot.entity.position.floored();
  log('probe at', JSON.stringify(feet), 'distance to site', feet.distanceTo(target).toFixed(1));
  const ids = ['stone', 'cobblestone']
    .map((n) => bot.registry.blocksByName[n] && bot.registry.blocksByName[n].id)
    .filter(Boolean);
  const spots = bot.findBlocks({ matching: ids, maxDistance: 32, count: 96 });
  log('stone/cobble spots within 32:', spots.length);
  spots
    .slice(0, 8)
    .forEach((s) => log('  spot', s.x, s.y, s.z, (bot.blockAt(s) || {}).name,
      'dist', feet.distanceTo(s).toFixed(1)));
  process.exit(0);
});
