'use strict';
// bots/probe-path.js — the walk from inside: while gotoNear runs, print
// position, velocity, the planner's current path (first nodes), and the
// dig target, three times a second. Read-only apart from the walk
// itself (guarded like the crew's own).
//
//   node probe-path.js 9 62 0
const mineflayer = require('mineflayer');
const { givePathfinding, gotoNear } = require('./src/api');

const goal = { x: Number(process.argv[2] || 9), y: Number(process.argv[3] || 62), z: Number(process.argv[4] || 0) };
const bot = mineflayer.createBot({
  host: '192.168.0.78', port: 25565, username: 'ProbeP', auth: 'offline', version: '26.1',
});
const log = (...a) => console.log(new Date().toISOString().slice(11, 19), ...a);
bot.on('kicked', (r) => { log('kicked:', r); process.exit(1); });
setTimeout(() => { log('TIMEOUT'); process.exit(1); }, 120000);

const PERSON = [[5, 67, 2], [4, 66, 2]];
const guard = {
  mayDig: (p) => {
    for (const [x, y, z] of PERSON) {
      if (Math.sqrt((x - p.x) ** 2 + (y - p.y) ** 2 + (z - p.z) ** 2) <= 4) {
        return { ok: false, why: 'probe: near a person build' };
      }
    }
    return { ok: true };
  },
};

bot.once('spawn', async () => {
  givePathfinding(bot, guard);
  await new Promise((r) => setTimeout(r, 8000));
  log('probe at', bot.entity.position.toString(), 'goal', JSON.stringify(goal));
  let n = 0;
  const t = setInterval(() => {
    n += 1;
    const p = bot.entity.position;
    const v = bot.entity.velocity;
    const path = bot.pathfinder && bot.pathfinder.path ? bot.pathfinder.path : null;
    const head = path && path.length
      ? path.slice(0, 4).map((v2) => `${v2.x},${v2.y},${v2.z}`).join('>') : 'none';
    const dig = bot.targetDigBlock ? `dig:${bot.targetDigBlock.name}` : '-';
    log(
      `p ${p.x.toFixed(1)},${p.y.toFixed(1)},${p.z.toFixed(1)}`,
      `v ${v.x.toFixed(2)},${v.y.toFixed(2)},${v.z.toFixed(2)}`,
      dig, `path[${path ? path.length : 0}] ${head}`
    );
    if (n > 80) clearInterval(t);
  }, 300);
  const started = Date.now();
  try {
    await gotoNear(bot, goal.x, goal.y, goal.z, 2, 30000);
    log(`ARRIVED in ${((Date.now() - started) / 1000).toFixed(1)} s`);
  } catch (err) {
    log(`FAILED after ${((Date.now() - started) / 1000).toFixed(1)} s:`, String((err && err.message) || err));
  }
  clearInterval(t);
  process.exit(0);
});
