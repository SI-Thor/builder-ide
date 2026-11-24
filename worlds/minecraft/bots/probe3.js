'use strict';
// bots/probe3.js — what does a dropped item look like to the client?
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
bot.on('error', (e) => console.log('error:', e.message));
bot.once('spawn', async () => {
  bot.loadPlugin(pathfinderPlugin);
  bot.pathfinder.setMovements(new Movements(bot));
  await new Promise((r) => setTimeout(r, 2500));
  const found = bot.findBlock({ matching: (b) => b.name === 'oak_log', maxDistance: 48 });
  if (!found) { console.log('no log'); process.exit(0); }
  const p = found.position;
  await bot.pathfinder.goto(new goals.GoalNear(p.x, p.y, p.z, 2)).catch((e) => console.log('path:', e.message));
  await bot.lookAt(p.offset(0.5, 0.5, 0.5), true);
  await bot.dig(bot.blockAt(p));
  console.log('mined');
  await new Promise((r) => setTimeout(r, 1500));
  const entities = Object.values(bot.entities);
  console.log('entities:', entities.length);
  for (const e of entities) {
    console.log('  name=', e.name, '| displayName=', e.displayName, '| type=', e.type,
      '| pos=', e.position && [Math.floor(e.position.x), Math.floor(e.position.y), Math.floor(e.position.z)],
      '| metadata=', e.metadata && e.metadata.length);
  }
  console.log('inventory:', bot.inventory.items().map((i) => `${i.name}x${i.count}`));
  bot.quit();
  process.exit(0);
});
