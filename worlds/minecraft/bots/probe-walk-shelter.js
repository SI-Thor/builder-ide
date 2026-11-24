'use strict';
// bots/probe-walk-shelter.js — why can't the builder reach the
// shelter's wall cell (5,69,10) from the pit it spawns in? Timber's
// placements time out with no answer ("Server did not answer the
// placement"), which is the server silently refusing an out-of-reach
// place; the walk before it fails quietly. This probe joins, walks
// the same route with the same rules (dig allowed, no towers, no
// parkour, y=48 floor for a bot above it), and prints what the
// planner actually says. Read-only except its own digs on the way.
//   node probe-walk-shelter.js
const mineflayer = require('mineflayer');
const { pathfinder, Movements, goals } = require('mineflayer-pathfinder');
const { Vec3 } = require('vec3');
const bot = mineflayer.createBot({
  host: '192.168.0.78', port: 25565, username: 'ProbeP', auth: 'offline', version: '26.1',
});
const log = (...a) => console.log(new Date().toISOString().slice(11, 19), ...a);
bot.on('kicked', (r) => { log('kicked:', r); process.exit(1); });
setTimeout(() => { log('TIMEOUT'); process.exit(1); }, 180000);

bot.once('spawn', async () => {
  await new Promise((r) => setTimeout(r, 6000));
  bot.loadPlugin(pathfinder);
  const movements = new Movements(bot);
  movements.canDigBlocks = true;
  movements.allow1by1towers = false;
  movements.allowParkour = false;
  bot.pathfinder.setMovements(movements);
  const target = new Vec3(5, 69, 10);
  log('start at', bot.entity.position.floored().toString(), '-> goal near', target.toString());
  for (const [label, range] of [['range2', 2], ['range3', 3]]) {
    const t0 = Date.now();
    try {
      await bot.pathfinder.goto(new goals.GoalNear(target.x, target.y, target.z, range));
      log(label, 'ARRIVED in', ((Date.now() - t0) / 1000).toFixed(1), 's at',
        bot.entity.position.floored().toString(),
        'dist', bot.entity.position.distanceTo(target).toFixed(1));
      break;
    } catch (err) {
      log(label, 'threw after', ((Date.now() - t0) / 1000).toFixed(1), 's:', String(err.message || err).slice(0, 120));
    }
  }
  const at = bot.blockAt(target);
  log('cell (5,69,10) is', at ? at.name : 'null', '| below:', (bot.blockAt(new Vec3(5, 68, 10)) || {}).name);
  // and what a placement does from here, one try, five seconds
  const item = bot.inventory.items().find((i) => i.name === 'dirt');
  if (item && bot.entity.position.distanceTo(target) < 4.5) {
    try {
      await bot.equip(item, 'hand');
      await bot.lookAt(target.offset(0.5, 0.5, 0.5), true);
      const ref = bot.blockAt(new Vec3(5, 68, 10));
      const t0 = Date.now();
      await bot.placeBlock(ref, new Vec3(0, 1, 0));
      log('placeBlock answered in', Date.now() - t0, 'ms; cell now:', bot.blockAt(target).name);
      if (bot.blockAt(target).name === 'dirt') {
        await bot.dig(bot.blockAt(target)); // leave no trace
        log('probe dirt removed');
      }
    } catch (err) {
      log('placeBlock threw:', String(err.message || err).slice(0, 140));
    }
  } else {
    log('no placement test (no dirt or out of reach', bot.entity.position.distanceTo(target).toFixed(1) + ')');
  }
  process.exit(0);
});
