'use strict';
// bots/probe-table.js — do table windows still open for a mineflayer
// client since the 09:31 crash-restart? Day two's pickaxe was crafted
// at a table (16:41Z); today every windowOpen times out (chest AND
// table). Bare-handed, at reach, one table: the pit bench (-4,64,-6).
//   node probe-table.js
const mineflayer = require('mineflayer');
const { Vec3 } = require('vec3');
const { pathfinder, Movements, goals } = require('mineflayer-pathfinder');
const bot = mineflayer.createBot({
  host: '192.168.0.78', port: 25565, username: 'ProbeW2', auth: 'offline', version: '26.1',
});
const log = (...a) => console.log(new Date().toISOString().slice(11, 19), ...a);
bot.on('kicked', (r) => { log('kicked:', r); process.exit(1); });
setTimeout(() => { log('TIMEOUT'); process.exit(1); }, 90000);
bot.once('spawn', async () => {
  await new Promise((r) => setTimeout(r, 6000));
  const table = bot.blockAt(new Vec3(-4, 64, -6));
  log('table block:', table ? table.name : 'null');
  bot.loadPlugin(pathfinder);
  const movements = new Movements(bot);
  movements.canDigBlocks = true;
  bot.pathfinder.setMovements(movements);
  await Promise.race([
    bot.pathfinder.goto(new goals.GoalNear(-4, 64, -6, 1)),
    new Promise((r) => setTimeout(r, 15000)),
  ]).catch(() => {});
  log('standing at', bot.entity.position.floored().toString(),
    'dist', bot.entity.position.distanceTo(new Vec3(-4, 64.5, -6)).toFixed(1));
  try { await bot.unequip('hand'); } catch (err) {}
  try {
    const win = await bot.openCraftingTable(table);
    log('TABLE WINDOW OPENED; slots:', win.craftingSlots ? win.craftingSlots.length : '?');
    win.close();
  } catch (err) {
    log('table FAILED:', String(err.message || err).slice(0, 120));
  }
  // the chest too, same client, for the record
  try {
    const chest = bot.blockAt(new Vec3(-2, 68, -5));
    await Promise.race([
      bot.pathfinder.goto(new goals.GoalNear(-2, 68, -5, 1)),
      new Promise((r) => setTimeout(r, 15000)),
    ]).catch(() => {});
    const c = await bot.openContainer(chest);
    log('CHEST WINDOW OPENED; items:', c.containerItems().length);
    c.close();
  } catch (err) {
    log('chest FAILED:', String(err.message || err).slice(0, 120));
  }
  process.exit(0);
});
