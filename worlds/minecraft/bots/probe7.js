'use strict';
// bots/probe7.js — why does the world's block search find nothing on a
// full mountainside?
//
// The builders said "no stone within 24 blocks" while standing on one.
// This probe asks the same question three ways — a function matcher
// with a counter, the same matcher without the level filter, and the
// same names as a list of block ids — and prints what each one sees.
//
// The answer it found: the function-matcher scan examined 4,437 blocks
// and was never handed a single one of the stone around it (the budget
// goes to the canopy), while the id list found stone through two
// layers of leaves on its first try. That is why api.js searches by
// block id now.
//
//   node probe7.js
const mineflayer = require('mineflayer');
const { Vec3 } = require('vec3');
const { pathfinder: pathfinderPlugin, Movements, goals } = require('mineflayer-pathfinder');
const bot = mineflayer.createBot({
  host: process.env.AW_HOST || '192.168.0.78',
  port: Number(process.env.AW_PAPER_PORT || 25565),
  username: 'Probe5', auth: 'offline', version: '26.1',
});
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
bot.on('error', (e) => console.log('error:', e.message));
setTimeout(() => { console.log('TIMEOUT'); process.exit(1); }, 90000);
bot.once('spawn', async () => {
  bot.loadPlugin(pathfinderPlugin);
  bot.pathfinder.setMovements(new Movements(bot));
  try {
    await Promise.race([
      bot.pathfinder.goto(new goals.GoalNear(-15, 64, 10, 1)),
      new Promise((_, rej) => setTimeout(() => rej(new Error('walk timeout')), 30000)),
    ]);
  } catch (e) { console.log('walk:', e.message); }
  await wait(1000);
  const feet = bot.entity.position.floored();
  console.log('standing at:', feet.toString());

  const names = ['stone', 'andesite', 'diorite', 'granite'];
  let calls = 0, noPos = 0, seen = 0, inLevel = 0;
  const filtered = bot.findBlock({
    matching: (b) => {
      calls += 1;
      if (!b || !b.position) { noPos += 1; return false; }
      if (names.includes(b.name)) {
        seen += 1;
        if (Math.abs(b.position.y - feet.y) <= 2) inLevel += 1;
      }
      return false;
    },
    maxDistance: 24,
  });
  console.log('filtered:', filtered && filtered.position.toString(), '| calls:', calls, '| noPos:', noPos, '| stone-family seen:', seen, '| in level:', inLevel);

  const byIds = bot.findBlock({
    matching: names.map((n) => bot.registry.blocksByName[n].id), maxDistance: 24 });
  console.log('by-id any level:', byIds && byIds.position.toString());

  // what is the ground made of, in a ring around this spot?
  const counts = {};
  for (let dx = -24; dx <= 24; dx += 3) {
    for (let dz = -24; dz <= 24; dz += 3) {
      let found = null;
      for (let y = feet.y + 4; y >= feet.y - 4; y--) {
        const b = bot.blockAt(new Vec3(feet.x + dx, y, feet.z + dz));
        if (b && b.name !== 'air' && !b.name.endsWith('_leaves')) { found = b.name; break; }
      }
      if (found) counts[found] = (counts[found] || 0) + 1;
    }
  }
  console.log('ground ring:', JSON.stringify(counts));
  bot.quit(); process.exit(0);
});
