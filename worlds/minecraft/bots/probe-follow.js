'use strict';
// bots/probe-follow.js — does a dynamic GoalFollow actually track?
// (diagnostic for the playable round's follow command)
const mineflayer = require('mineflayer');
const { pathfinder: pathfinderPlugin, Movements, goals } = require('mineflayer-pathfinder');

const target = process.argv[2] || 'TestHuman';
const bot = mineflayer.createBot({ host: '192.168.0.78', port: 25565, username: 'FollowerX', auth: 'offline', version: '26.1' });
bot.once('spawn', async () => {
  bot.loadPlugin(pathfinderPlugin);
  const movements = new Movements(bot);
  movements.canDigBlocks = false;
  bot.pathfinder.setMovements(movements);
  await new Promise((r) => setTimeout(r, 3000));
  const entity = bot.players[target] && bot.players[target].entity;
  if (!entity) { console.log('no entity for', target); process.exit(1); }
  bot.pathfinder.setGoal(new goals.GoalFollow(entity, 3), true);
  console.log('goal set, dynamic');
  for (let i = 0; i < 24; i++) {
    await new Promise((r) => setTimeout(r, 2500));
    const e2 = bot.players[target] && bot.players[target].entity;
    const d = e2 ? bot.entity.position.distanceTo(e2.position).toFixed(1) : 'unseen';
    const goal = bot.pathfinder.goal ? 'set' : 'null';
    console.log(`${i * 2.5}s dist=${d} goal=${goal} pos=${bot.entity.position.floored().toArray().join(',')}`);
  }
  bot.quit();
  process.exit(0);
});
