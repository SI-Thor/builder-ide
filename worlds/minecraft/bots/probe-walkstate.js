'use strict';
// bots/probe-follow.js — what is the follower actually asked to do?
// Listens to the planner's own path_update events (status, length,
// the first nodes' break/place work) and samples the follower state
// (isMoving/isMining/isBuilding) while gotoNear runs.
//
//   node probe-follow.js 9 62 0
const mineflayer = require('mineflayer');
const { givePathfinding, gotoNear } = require('./src/api');

const goal = { x: Number(process.argv[2] || 9), y: Number(process.argv[3] || 62), z: Number(process.argv[4] || 0) };
const bot = mineflayer.createBot({
  host: '192.168.0.78', port: 25565, username: 'ProbeF', auth: 'offline', version: '26.1',
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
  bot.on('path_update', (r) => {
    const path = r.path || [];
    const head = path.slice(0, 3).map((n) => {
      const work = [];
      if (n.toBreak && n.toBreak.length) work.push(`break${n.toBreak.length}`);
      if (n.toPlace && n.toPlace.length) work.push(`place${n.toPlace.length}`);
      return `(${n.x},${n.y},${n.z}${work.length ? ':' + work.join('+') : ''})`;
    }).join(' ');
    log(`path_update status=${r.status} len=${path.length} cost=${r.cost} ${head}`);
  });
  await new Promise((r) => setTimeout(r, 8000));
  log('probe at', bot.entity.position.toString(), 'goal', JSON.stringify(goal));
  let n = 0;
  const t = setInterval(() => {
    n += 1;
    const p = bot.entity.position;
    log(
      `p ${p.x.toFixed(1)},${p.y.toFixed(1)},${p.z.toFixed(1)}`,
      `moving=${bot.pathfinder.isMoving()} mining=${bot.pathfinder.isMining()} building=${bot.pathfinder.isBuilding()}`
    );
    if (n > 60) clearInterval(t);
  }, 500);
  const started = Date.now();
  try {
    await gotoNear(bot, goal.x, goal.y, goal.z, 3, 30000);
    log(`ARRIVED in ${((Date.now() - started) / 1000).toFixed(1)} s`);
  } catch (err) {
    log(`FAILED after ${((Date.now() - started) / 1000).toFixed(1)} s:`, String((err && err.message) || err));
  }
  clearInterval(t);
  process.exit(0);
});
