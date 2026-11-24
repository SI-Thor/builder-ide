'use strict';
// bots/probe-route.js — the builder cannot walk from the pit to the
// shelter site ("cannot reach ... 16.8 away" every tick, 2026-11-02
// 19:46Z). This probe walks the route in segments with a hard timeout
// each, so the segment that breaks the planner is named. Read-only
// except its own footsteps (digs allowed on the way, same rules).
//   node probe-route.js
const mineflayer = require('mineflayer');
const { pathfinder, Movements, goals } = require('mineflayer-pathfinder');
const { Vec3 } = require('vec3');
const bot = mineflayer.createBot({
  host: '192.168.0.78', port: 25565, username: 'ProbeR2', auth: 'offline', version: '26.1',
});
const log = (...a) => console.log(new Date().toISOString().slice(11, 19), ...a);
bot.on('kicked', (r) => { log('kicked:', r); process.exit(1); });
setTimeout(() => { log('GLOBAL TIMEOUT'); process.exit(1); }, 240000);

bot.once('spawn', async () => {
  await new Promise((r) => setTimeout(r, 6000));
  bot.loadPlugin(pathfinder);
  const movements = new Movements(bot);
  movements.canDigBlocks = true;
  movements.allow1by1towers = false;
  movements.allowParkour = false;
  bot.pathfinder.setMovements(movements);

  const timed = (label, goal, ms) => Promise.race([
    bot.pathfinder.goto(goal).then(() => `${label} ARRIVED at ${bot.entity.position.floored().toString()}`),
    new Promise((resolve) => setTimeout(() => resolve(`${label} TIMEOUT after ${ms / 1000}s (still at ${bot.entity.position.floored().toString()})`), ms)),
  ]).catch((err) => `${label} THREW: ${String(err.message || err).slice(0, 90)}`);

  const near = (x, y, z, r) => new goals.GoalNear(x, y, z, r);
  log('start', bot.entity.position.floored().toString());
  log(await timed('A terrace (chest)', near(-2, 68, -5, 1), 30000));
  log(await timed('B surface z8', near(5, 67, 8, 2), 30000));
  log(await timed('C site-adjacent', near(5, 68, 9, 2), 30000));
  log(await timed('D the wall cell', near(5, 69, 10, 2), 30000));
  process.exit(0);
});
