'use strict';
// bots/probe4.js — why is the mined block not in the bag?
//
// A small diagnostic: join, find a block of dirt near the spawn, walk
// right up to it, mine it, and then say what the client can see — the
// inventory, the block, and the entities lying about.
//
//   node probe4.js

const mineflayer = require('mineflayer');
const { Vec3 } = require('vec3');
const { pathfinder: pathfinderPlugin, Movements, goals } = require('mineflayer-pathfinder');

const bot = mineflayer.createBot({
  host: process.env.AW_HOST || '192.168.0.78',
  port: Number(process.env.AW_PAPER_PORT || 25565),
  username: 'Probe',
  auth: 'offline',
  version: '26.1',
});

const log = (...args) => console.log(...args);

bot.on('error', (e) => log('error:', e.message));
bot.on('kicked', (r) => log('kicked:', r));
bot.on('end', (r) => log('end:', r));

setTimeout(() => {
  log('TIMEOUT: no spawn');
  process.exit(1);
}, 45000);

bot.once('spawn', async () => {
  clearTimeout(0);
  log('spawned at', bot.entity.position);
  bot.loadPlugin(pathfinderPlugin);
  bot.pathfinder.setMovements(new Movements(bot));
  await new Promise((r) => setTimeout(r, 3000));

  const start = bot.entity.position.floored();
  const dirt = bot.findBlock({
    matching: (b) => b.name === 'dirt' || b.name === 'grass_block',
    maxDistance: 12,
  });
  log('target block:', dirt && dirt.name, dirt && dirt.position);
  if (!dirt) {
    process.exit(1);
  }

  const p = dirt.position;
  try {
    await bot.pathfinder.goto(new goals.GoalNear(p.x, p.y, p.z, 1));
    log('walked to', bot.entity.position, 'distance', bot.entity.position.distanceTo(p).toFixed(2));
  } catch (e) {
    log('walk failed:', e.message);
  }

  const before = bot.inventory.items().map((i) => `${i.name}x${i.count}`);
  log('inventory before:', before);

  try {
    await bot.lookAt(p.offset(0.5, 0.5, 0.5), true);
    await bot.dig(bot.blockAt(p));
    log('dig sent');
  } catch (e) {
    log('dig failed:', e.message);
  }

  for (const wait of [1000, 2000, 3000]) {
    await new Promise((r) => setTimeout(r, wait));
    log(
      `after ${wait}ms more: inventory=`,
      bot.inventory.items().map((i) => `${i.name}x${i.count}`),
      'block there:',
      (bot.blockAt(p) || {}).name
    );
  }

  const drops = Object.values(bot.entities).filter(
    (e) => e && e.position && (e.name === 'item' || e.name === 'Item' || e.name === 'item_stack')
  );
  log('drop entities:', drops.length);
  for (const d of drops.slice(0, 5)) {
    log('   ', d.name, d.position.toString(), 'dist', d.position.distanceTo(bot.entity.position).toFixed(2));
  }
  const others = Object.values(bot.entities).filter((e) => e && e.position && e.type && e.type !== 'player' && e.type !== 'object');
  log('other entities:', others.map((e) => `${e.name}/${e.type}`).slice(0, 8));

  bot.quit();
  process.exit(0);
});
