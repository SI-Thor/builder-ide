'use strict';
// bots/probe-quarry.js — can anyone actually quarry here? The ramp's
// builder reports "equip ok, cobble in hand 0" over and over (17:08).
// This probe joins (the console gives it a pickaxe first), finds the
// same stone the quarry finds, equips, digs, and prints what the
// world actually gave back. Read-only except its own dig.
//
//   console first:  give ProbeQ wooden_pickaxe 1
//   node probe-quarry.js
const mineflayer = require('mineflayer');
const { Vec3 } = require('vec3');
const bot = mineflayer.createBot({
  host: '192.168.0.78', port: 25565, username: 'ProbeQ', auth: 'offline', version: '26.1',
});
const log = (...a) => console.log(...a);
bot.on('kicked', (r) => { log('kicked:', r); process.exit(1); });
setTimeout(() => { log('TIMEOUT'); process.exit(1); }, 120000);
bot.once('spawn', async () => {
  await new Promise((r) => setTimeout(r, 8000));
  const count = (name) => bot.inventory.items().filter((i) => i.name === name).reduce((s, i) => s + i.count, 0);
  // wait for the console's give (it can only arrive once we are online)
  for (let i = 0; i < 15 && count('wooden_pickaxe') < 1; i++) {
    await new Promise((r) => setTimeout(r, 2000));
  }
  log('inventory at start: pickaxe', count('wooden_pickaxe'), 'cobble', count('cobblestone'));
  const ids = ['stone', 'cobblestone']
    .map((n) => bot.registry.blocksByName[n] && bot.registry.blocksByName[n].id)
    .filter(Boolean);
  const spots = bot.findBlocks({ matching: ids, maxDistance: 24, count: 20 });
  const feet = bot.entity.position.floored();
  const near = spots.filter((s) => s.y >= 49).sort(
    (a, b) => feet.distanceTo(a) - feet.distanceTo(b)
  )[0];
  if (!near) { log('no stone above y49 within 24'); process.exit(0); }
  log('target', near.x, near.y, near.z, (bot.blockAt(near) || {}).name, 'dist', feet.distanceTo(near).toFixed(1));
  const pick = bot.inventory.items().find((i) => i.name === 'wooden_pickaxe');
  if (pick) { await bot.equip(pick, 'hand'); log('equipped wooden_pickaxe'); }
  else log('NO PICKAXE — dig would be bare-handed');
  const before = count('cobblestone');
  try {
    await bot.dig(bot.blockAt(near));
    log('bot.dig resolved');
  } catch (err) {
    log('bot.dig threw:', String(err.message || err));
  }
  await new Promise((r) => setTimeout(r, 2000));
  log('after dig: cobble', count('cobblestone'), '(was', before + ')');
  const drops = Object.values(bot.entities).filter(
    (e) => e && e.position && (e.name === 'item' || e.name === 'Item')
  );
  log('item entities visible:', drops.length, drops.slice(0, 3).map((d) => {
    const meta = d.metadata && d.metadata[7] && d.metadata[7].name ? ` (${d.metadata[7].name})` : '';
    return `${Math.round(d.position.x)},${Math.round(d.position.y)},${Math.round(d.position.z)}${meta}`;
  }));
  const still = bot.blockAt(new Vec3(near.x, near.y, near.z));
  log('block there now:', still ? still.name : 'null');
  process.exit(0);
});
