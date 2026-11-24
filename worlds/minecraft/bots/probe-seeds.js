'use strict';
// bots/probe-seeds.js — 40+ stems broken by the gatherer, 0 seeds
// (every run "5 grass broken, 0 of 14", 2026-11-02 19:16-20:12Z) while
// the console's own loot roll of short_grass at (8,71,-8) yields a
// seed. What is the gatherer actually breaking — and does standing IN
// the cell collect the drop? This probe breaks eight nearby stems of
// whatever kind it finds, one cell at a time, and counts.
//   node probe-seeds.js
const mineflayer = require('mineflayer');
const { Vec3 } = require('vec3');
const bot = mineflayer.createBot({
  host: '192.168.0.78', port: 25565, username: 'ProbeSd', auth: 'offline', version: '26.1',
});
const log = (...a) => console.log(new Date().toISOString().slice(11, 19), ...a);
bot.on('kicked', (r) => { log('kicked:', r); process.exit(1); });
setTimeout(() => { log('TIMEOUT'); process.exit(1); }, 150000);
bot.once('spawn', async () => {
  await new Promise((r) => setTimeout(r, 8000));
  const count = (n) => bot.inventory.items().filter((i) => i.name === n)
    .reduce((s, i) => s + i.count, 0);
  const names = ['short_grass', 'tall_grass', 'grass', 'fern'];
  const ids = names.map((n) => bot.registry.blocksByName[n] && bot.registry.blocksByName[n].id).filter(Boolean);
  let seeds0 = count('wheat_seeds');
  log('start at', bot.entity.position.floored().toString(), 'seeds', seeds0);
  const spots = bot.findBlocks({ matching: ids, maxDistance: 48, count: 12 });
  log('stems found:', spots.length, spots.slice(0, 8).map((p) => {
    const b = bot.blockAt(p);
    return `${b ? b.name : '?'}@${p.x},${p.y},${p.z}`;
  }).join(' '));
  const { pathfinder, Movements, goals } = require('mineflayer-pathfinder');
  bot.loadPlugin(pathfinder);
  const movements = new Movements(bot);
  movements.canDigBlocks = true;
  bot.pathfinder.setMovements(movements);
  let broken = 0;
  for (const p of spots.slice(0, 8)) {
    const b = bot.blockAt(p);
    if (!b || b.boundingBox !== 'empty') continue;
    try {
      // stand IN the cell above the stem's floor, the collector's own way
      await Promise.race([
        bot.pathfinder.goto(new goals.GoalNear(p.x, p.y, p.z, 0)),
        new Promise((res) => setTimeout(res, 12000)),
      ]);
    } catch (err) { /* dig anyway */ }
    try {
      await bot.dig(b);
      broken += 1;
      await new Promise((r) => setTimeout(r, 1500));
      log(`broke ${b.name} at ${p.x},${p.y},${p.z} — seeds now ${count('wheat_seeds')}`);
    } catch (err) {
      log('dig failed:', String(err.message || err).slice(0, 80));
    }
  }
  log(`DONE: ${broken} broken, seeds ${seeds0} -> ${count('wheat_seeds')}`);
  process.exit(0);
});
