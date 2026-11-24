'use strict';
// bots/probe2.js — does the pathfinder work, and does a dig collect?
const mineflayer = require('mineflayer');
const { Vec3 } = require('vec3');
require('mineflayer-pathfinder');

const bot = mineflayer.createBot({
  host: process.env.AW_HOST || '192.168.0.78',
  port: Number(process.env.AW_PAPER_PORT || 25565),
  username: 'Probe',
  auth: 'offline',
  version: '26.1',
});
bot.on('error', (e) => console.log('error:', e.message));
bot.once('spawn', async () => {
  await new Promise((r) => setTimeout(r, 2500));
  console.log('has pathTo?', typeof bot.pathTo);
  const found = bot.findBlock({
    matching: (b) => b.name === 'oak_log',
    maxDistance: 48,
  });
  console.log('log at', found && found.position);
  const p = found.position;
  try {
    const t0 = Date.now();
    await bot.pathTo(p.offset(0.5, 1, 0.5), { distance: 2, timeout: 10000 });
    console.log('pathTo ok in', Date.now() - t0, 'ms; now at', bot.entity.position);
  } catch (e) {
    console.log('pathTo failed:', e.message);
  }
  try {
    await bot.lookAt(p.offset(0.5, 0.5, 0.5), true);
    await bot.dig(bot.blockAt(p));
    console.log('dig sent');
  } catch (e) {
    console.log('dig failed:', e.message);
  }
  await new Promise((r) => setTimeout(r, 2500));
  console.log('block still there?', (bot.blockAt(p) || {}).name);
  console.log('inventory:', bot.inventory.items().map((i) => `${i.name}x${i.count}`));
  const dropped = Object.values(bot.entities).filter(
    (e) => e.objectType === 'item' || e.name === 'item'
  );
  console.log('items on the ground:', dropped.length);
  bot.quit();
  process.exit(0);
});
