'use strict';
// bots/probe-chest.js — the depot chest has never received a deposit
// (its Items read [] while goods pile on the ground and get swept).
// Can a bot open it and deposit at all on this protocol? The probe
// joins, takes one dirt from the console, opens the chest, deposits,
// reads the chest's own view back, then takes the dirt out again —
// the world is exactly as it was.
//   console first:  give ProbeC dirt 1
//   node probe-chest.js
const mineflayer = require('mineflayer');
const { Vec3 } = require('vec3');
const bot = mineflayer.createBot({
  host: '192.168.0.78', port: 25565, username: 'ProbeC', auth: 'offline', version: '26.1',
});
const log = (...a) => console.log(new Date().toISOString().slice(11, 19), ...a);
bot.on('kicked', (r) => { log('kicked:', r); process.exit(1); });
setTimeout(() => { log('TIMEOUT'); process.exit(1); }, 90000);
bot.once('spawn', async () => {
  await new Promise((r) => setTimeout(r, 6000));
  const count = (n) => bot.inventory.items().filter((i) => i.name === n).reduce((s, i) => s + i.count, 0);
  for (let i = 0; i < 10 && count('dirt') < 1; i++) await new Promise((r) => setTimeout(r, 2000));
  log('dirt in hand:', count('dirt'));
  const chestBlock = bot.blockAt(new Vec3(-2, 68, -5));
  log('chest block:', chestBlock ? chestBlock.name : 'null');
  try {
    await bot.unequip('hand');
    log('hand emptied; heldItem:', bot.heldItem ? bot.heldItem.name : 'empty');
    const chest = await bot.openContainer(chestBlock);
    log('chest OPENED; container slots:', chest.containerItems().length,
      chest.containerItems().slice(0, 4).map((i) => `${i.name}x${i.count}`).join(' '));
    const dirt = bot.registry.itemsByName.dirt;
    await chest.deposit(dirt, null, 1);
    await new Promise((r) => setTimeout(r, 600));
    log('after deposit — chest sees:', chest.containerItems().map((i) => `${i.name}x${i.count}`).join(' '),
      '| my dirt:', count('dirt'));
    await chest.withdraw(dirt, null, 1);
    await new Promise((r) => setTimeout(r, 600));
    log('after withdraw — chest sees:', chest.containerItems().length, 'items | my dirt:', count('dirt'));
    chest.close();
    log('chest closed cleanly');
  } catch (err) {
    log('chest FAILED:', String(err.message || err).slice(0, 160));
  }
  process.exit(0);
});
