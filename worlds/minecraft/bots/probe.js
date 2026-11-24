'use strict';
// bots/probe.js — a one-off probe of the action layer.
//
// Not part of the world: a small script that joins, looks at a tree, and
// says what mineflayer said when it tried to dig. It exists so the
// failures in bots/src/api.js can be read rather than guessed at.
//
//   node probe.js

const mineflayer = require('mineflayer');
const { Vec3 } = require('vec3');

const bot = mineflayer.createBot({
  host: process.env.AW_HOST || '192.168.0.78',
  port: Number(process.env.AW_PAPER_PORT || 25565),
  username: 'Probe',
  auth: 'offline',
  version: '26.1',
});

bot.on('error', (e) => console.log('error:', e.message));
bot.on('end', (r) => console.log('end:', r));

bot.once('spawn', async () => {
  console.log('spawned at', bot.entity.position);
  await new Promise((r) => setTimeout(r, 3000));
  console.log('inventory:', bot.inventory.items().map((i) => `${i.name}x${i.count}`));

  const found = bot.findBlock({
    matching: (b) => b.name === 'oak_log',
    maxDistance: 48,
  });
  console.log('found a log:', found && found.position, found && found.name);

  const ground = bot.blockAt(bot.entity.position.floored());
  console.log('block under the bot:', ground && ground.name);

  if (found) {
    const p = found.position;
    const distance = bot.entity.position.distanceTo(p);
    console.log('distance to the log:', distance.toFixed(2));
    try {
      await bot.lookAt(p.offset(0.5, 0.5, 0.5), true);
      console.log('looking at', bot.entity.look && bot.entity.look.yaw);
      const hit = bot.blockAt(p);
      console.log('blockAt the log:', hit && hit.name);
      await bot.dig(hit);
      console.log('digged it');
    } catch (err) {
      console.log('dig failed:', err.message);
    }
  }

  console.log('inventory after:', bot.inventory.items().map((i) => `${i.name}x${i.count}`));
  bot.quit();
  process.exit(0);
});
