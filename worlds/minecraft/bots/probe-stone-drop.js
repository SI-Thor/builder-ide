'use strict';
// bots/probe-stone-drop.js — does a stone DIG yield a drop server-side?
// Day two proved the loot table fine (`loot give Kite mine 0 20 0 air`
// -> 1 cobblestone) while real digs (pickaxe or bare hand) gave nothing.
// This probe stands in the crew's own pit, places two stone blocks on
// the floor beside its feet (console-given), digs one with a pickaxe
// and one bare-handed, and reports inventory before/after each dig —
// the inventory is the server's own record, and at feet-adjacent range
// the server auto-picks-up any drop entity. Read-only except its own
// two placed-then-dug stone blocks (net world change: none if drops
// work, two stone lost if they do not — measurement cost).
//
//   console once the probe is online:  give ProbeS wooden_pickaxe 1
//                                      give ProbeS stone 4
//   node probe-stone-drop.js
const mineflayer = require('mineflayer');
const { Vec3 } = require('vec3');
const bot = mineflayer.createBot({
  host: '192.168.0.78', port: 25565, username: 'ProbeS', auth: 'offline', version: '26.1',
});
const log = (...a) => console.log(new Date().toISOString().slice(11, 19), ...a);
bot.on('kicked', (r) => { log('kicked:', r); process.exit(1); });
setTimeout(() => { log('TIMEOUT'); process.exit(1); }, 150000);

const count = (name) => bot.inventory.items()
  .filter((i) => i.name === name).reduce((s, i) => s + i.count, 0);
const entitiesNear = (p, r) => Object.values(bot.entities).filter(
  (e) => e && e.position && (e.name === 'item' || e.name === 'Item')
    && e.position.distanceTo(p) < r
);

bot.once('spawn', async () => {
  await new Promise((r) => setTimeout(r, 5000));
  const feet = bot.entity.position.floored();
  log('feet', feet.x, feet.y, feet.z);

  // wait for the console's gives (they only arrive while online)
  for (let i = 0; i < 20 && (count('wooden_pickaxe') < 1 || count('stone') < 2); i++) {
    await new Promise((r) => setTimeout(r, 3000));
  }
  log('start: pickaxe', count('wooden_pickaxe'), 'stone', count('stone'),
    'cobble', count('cobblestone'));
  if (count('stone') < 2) { log('no stone given — aborting'); process.exit(1); }

  const stoneItem = bot.inventory.items().find((i) => i.name === 'stone');

  // A slope, not a pit: the cell beside the feet may be solid. Find an
  // air cell with a solid block below it, nearest first, so the dig
  // stays within the server's item-pickup reach.
  const findSpot = () => {
    const cands = [];
    for (let dx = -2; dx <= 2; dx++) for (let dz = -2; dz <= 2; dz++) {
      for (const dy of [0, 1]) {
        const spot = new Vec3(feet.x + dx, feet.y + dy, feet.z + dz);
        const floor = new Vec3(spot.x, spot.y - 1, spot.z);
        const sb = bot.blockAt(spot); const fb = bot.blockAt(floor);
        if (sb && fb && sb.name === 'air' && fb.boundingBox !== 'empty'
          && feet.distanceTo(spot) >= 1 && feet.distanceTo(spot) <= 2.4) cands.push({ spot, floor, d: feet.distanceTo(spot) });
      }
    }
    cands.sort((a, b) => a.d - b.d);
    return cands;
  };

  // place with fallback — a refused placement (own-cell, race with a
  // bot) costs nothing; the next candidate cell is tried
  const placeAt = async () => {
    const cands = findSpot().slice(0, 6);
    for (const c of cands) {
      try {
        await bot.equip(stoneItem, 'hand');
        await bot.placeBlock(bot.blockAt(c.floor), new Vec3(0, 1, 0));
        return c;
      } catch (err) {
        log('  place refused at', `${c.spot.x},${c.spot.y},${c.spot.z}:`, String(err.message || err).slice(0, 80));
      }
    }
    return null;
  };
  const spots = findSpot();
  if (spots.length < 1) { log('no air cell with solid floor nearby'); process.exit(1); }
  log('placement cells:', spots.slice(0, 4).map((s) => `${s.spot.x},${s.spot.y},${s.spot.z} d=${s.d.toFixed(1)}`).join(' | '));

  // -- dig A: with the pickaxe ------------------------------------------------
  const placedA = await placeAt();
  if (!placedA) { log('no placement worked for A'); process.exit(1); }
  const spotA = placedA.spot;
  log('A placed:', bot.blockAt(spotA).name, `${spotA.x},${spotA.y},${spotA.z}`);
  const pick = bot.inventory.items().find((i) => i.name === 'wooden_pickaxe');
  if (pick) await bot.equip(pick, 'hand');
  log('A hand:', bot.heldItem ? bot.heldItem.name : 'empty');
  const cobA0 = count('cobblestone');
  try { await bot.dig(bot.blockAt(spotA)); log('A dig resolved'); }
  catch (err) { log('A dig threw:', String(err.message || err)); }
  await new Promise((r) => setTimeout(r, 3000));
  log('A after: cobble', count('cobblestone'), '(was', cobA0 + ')',
    'entities<4:', entitiesNear(spotA, 4).length,
    'block now:', bot.blockAt(spotA).name);

  // -- dig B: bare-handed -----------------------------------------------------
  const placedB = await placeAt();
  if (!placedB) { log('no placement worked for B'); process.exit(1); }
  const spotB = placedB.spot;
  log('B placed:', bot.blockAt(spotB).name, `${spotB.x},${spotB.y},${spotB.z}`);
  await bot.unequip('hand');
  log('B hand:', bot.heldItem ? bot.heldItem.name : 'empty');
  const cobB0 = count('cobblestone');
  try { await bot.dig(bot.blockAt(spotB)); log('B dig resolved'); }
  catch (err) { log('B dig threw:', String(err.message || err)); }
  await new Promise((r) => setTimeout(r, 3000));
  log('B after: cobble', count('cobblestone'), '(was', cobB0 + ')',
    'entities<4:', entitiesNear(spotB, 4).length,
    'block now:', bot.blockAt(spotB).name);

  // -- dig C: at reach distance, then path onto the cell ----------------------
  // The day-two quarry dug at reach: no auto-pickup out there, and
  // mineflayer sees no item entities on 26.1 (phases A/B both logged
  // entities<4: 0 — even after a drop the server auto-picked-up). So:
  // place far, dig far, CHAT the cell for a console-side entity check,
  // then walk onto the cell and see the cobble arrive.
  const far = (() => {
    const cands = [];
    for (let dx = -4; dx <= 4; dx++) for (let dz = -4; dz <= 4; dz++) {
      const spot = new Vec3(feet.x + dx, feet.y, feet.z + dz);
      const floor = new Vec3(spot.x, spot.y - 1, spot.z);
      const sb = bot.blockAt(spot); const fb = bot.blockAt(floor);
      const d = feet.distanceTo(spot);
      if (sb && fb && sb.name === 'air' && fb.boundingBox !== 'empty' && d >= 2.6 && d <= 3.6) {
        cands.push({ spot, floor, d });
      }
    }
    cands.sort((a, b) => a.d - b.d);
    return cands[0];
  })();
  if (!far) { log('no far cell — skipping C'); process.exit(0); }
  try {
    await bot.equip(stoneItem, 'hand');
    await bot.placeBlock(bot.blockAt(far.floor), new Vec3(0, 1, 0));
    log('C placed:', bot.blockAt(far.spot).name, `${far.spot.x},${far.spot.y},${far.spot.z}`, 'd', far.d.toFixed(1));
    const pick2 = bot.inventory.items().find((i) => i.name === 'wooden_pickaxe');
    if (pick2) await bot.equip(pick2, 'hand');
    const cobC0 = count('cobblestone');
    await bot.dig(bot.blockAt(far.spot));
    log('C dig resolved; cobble', count('cobblestone'), '(was', cobC0 + ')');
    bot.chat(`CHECKC ${far.spot.x} ${far.spot.y} ${far.spot.z}`);
    await new Promise((r) => setTimeout(r, 8000));
    log('C after 8s standing still: cobble', count('cobblestone'), 'entities<6:', entitiesNear(far.spot, 6).length);
    const { pathfinder, Movements, goals } = require('mineflayer-pathfinder');
    bot.loadPlugin(pathfinder);
    const movements = new Movements(bot);
    bot.pathfinder.setMovements(movements);
    await bot.pathfinder.goto(new goals.GoalNear(far.spot.x, far.spot.y, far.spot.z, 1));
    await new Promise((r) => setTimeout(r, 2500));
    log('C after walking onto the cell: cobble', count('cobblestone'),
      'block there:', bot.blockAt(far.spot).name);
  } catch (err) {
    log('C failed:', String(err.message || err));
  }

  log('PROBE DONE');
  process.exit(0);
});
