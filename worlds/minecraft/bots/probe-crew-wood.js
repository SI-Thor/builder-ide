'use strict';
// bots/probe-crew-wood.js — two facts in one look: where the crew
// stands (players are entities by username, not name — probe-needs
// missed them), and where the nearest logs stand, with the ground
// under each trunk (is the tree base walkable at the depot's own
// level, or only up the hill?).  Read-only; it never digs.
//
//   node probe-crew-wood.js
const mineflayer = require('mineflayer');
const { Vec3 } = require('vec3');
const bot = mineflayer.createBot({
  host: '192.168.0.78', port: 25565, username: 'ProbeCW', auth: 'offline', version: '26.1',
});
const log = (...a) => console.log(new Date().toISOString().slice(11, 19), ...a);
bot.on('kicked', (r) => { log('kicked:', r); process.exit(1); });
setTimeout(() => { log('TIMEOUT'); process.exit(1); }, 90000);
bot.once('spawn', async () => {
  await new Promise((r) => setTimeout(r, 10000));
  for (const e of Object.values(bot.entities)) {
    if (e && e.type === 'player' && e.username && e.position
        && ['Pebble', 'Timber', 'Kite', 'Sprout'].includes(e.username)) {
      const p = e.position;
      log('crew', e.username, Math.round(p.x), Math.round(p.y), Math.round(p.z));
    }
  }
  const id = bot.registry.blocksByName['oak_log'].id;
  const sid = bot.registry.blocksByName['spruce_log'].id;
  const spots = bot.findBlocks({ matching: [id, sid], maxDistance: 96, count: 400 });
  log('logs found:', spots.length);
  spots.slice(0, 0);
  const byCol = new Map();
  for (const s of spots) {
    const k = s.x + ',' + s.z;
    if (!byCol.has(k)) byCol.set(k, { x: s.x, z: s.z, minY: s.y, maxY: s.y, n: 0 });
    const c = byCol.get(k);
    c.minY = Math.min(c.minY, s.y); c.maxY = Math.max(c.maxY, s.y); c.n += 1;
  }
  const cols = [...byCol.values()].sort((a, b) => (a.x ** 2 + a.z ** 2) - (b.x ** 2 + b.z ** 2));
  for (const c of cols.slice(0, 10)) {
    let ground = null;
    for (let y = 100; y > 40; y -= 1) {
      const b = bot.blockAt(new Vec3(c.x, y, c.z));
      if (b && b.name !== 'air' && !b.name.endsWith('_log') && !b.name.endsWith('_leaves')) { ground = { y, name: b.name }; break; }
    }
    log('trunk', c.x, c.z, 'logs', c.n, 'y', c.minY + '-' + c.maxY, 'ground under', ground ? ground.y + ' ' + ground.name : '?');
  }
  process.exit(0);
});
