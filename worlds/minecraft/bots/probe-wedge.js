'use strict';
// bots/probe17.js — can the planner un-wedge the bot, given time?
//
// A bot that spawns at the saved depot position stands pressed against
// a cobble face: raw controls cover 0.02 blocks and a 20 s planner
// deadline expires with zero displacement. This probe gives the
// planner a far east goal and 45 s, reporting every two seconds, to
// answer whether the wedge is escapable at all — and how long it takes.
//
//   node bots/probe17.js

const mineflayer = require('mineflayer');
const { pathfinder: pathfinderPlugin, Movements, goals } = require('mineflayer-pathfinder');

const bot = mineflayer.createBot({
  host: process.env.AW_HOST || '192.168.0.78',
  port: Number(process.env.AW_PAPER_PORT || 25565),
  username: 'Probe8',
  auth: 'offline',
  version: '26.1',
});

const log = (...a) => console.log(new Date().toISOString().slice(11, 19), ...a);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

bot.on('error', (e) => log('error:', e.message));
bot.on('kicked', (r) => { log('kicked:', r); process.exit(1); });
setTimeout(() => { log('TIMEOUT'); process.exit(1); }, 75000);

bot.once('spawn', async () => {
  await sleep(5000);
  const start = bot.entity.position.clone();
  log('wedge pos', start.floored().toString());

  bot.loadPlugin(pathfinderPlugin);
  const movements = new Movements(bot);
  movements.canDigBlocks = true;
  movements.allow1by1towers = false;
  movements.allowParkour = false;
  movements.canSwim = true;
  bot.pathfinder.setMovements(movements);

  const goal = start.offset(12, 0, 0);
  const t0 = Date.now();
  const ticker = setInterval(() => {
    log('  t+' + ((Date.now() - t0) / 1000).toFixed(0) + 's at', bot.entity.position.floored().toString());
  }, 2000);
  try {
    await bot.pathfinder.goto(new goals.GoalNear(goal.x, goal.y, goal.z, 2));
    clearInterval(ticker);
    log('reached in', ((Date.now() - t0) / 1000).toFixed(1), 's');
  } catch (err) {
    clearInterval(ticker);
    log('failed in', ((Date.now() - t0) / 1000).toFixed(1), 's:', String(err && err.message));
  }
  process.exit(0);
});
