'use strict';
// bots/probe5.js — what the depot is, and what mineflayer really does.
//
// Five questions, one join:
//
//   1. Where is the depot? The spawn packet gives a point; is that the
//      block the builder stands on, or the block it stands on top of?
//   2. Does mineflayer really call a block search's matcher with a block
//      that has no position? (The world's `find_block` died on exactly
//      that, every single time.)
//   3. What does `bot.placeBlock` want? A block type, or a block to build
//      against?
//   4. Does a tossed item leave the bag, and where does it land?
//   5. Does a builder pick an item up again by walking over it?
//
// The last three are one round trip: mine a block, carry it, put it
// down, take it back. That is the depot economy in miniature.
//
//   node probe5.js

const mineflayer = require('mineflayer');
const { Vec3 } = require('vec3');
const { pathfinder: pathfinderPlugin, Movements, goals } = require('mineflayer-pathfinder');

const bot = mineflayer.createBot({
  host: process.env.AW_HOST || '192.168.0.78',
  port: Number(process.env.AW_PAPER_PORT || 25565),
  username: 'Probe5',
  auth: 'offline',
  version: '26.1',
});

const log = (...args) => console.log(...args);
const wait = (ms) => new Promise((r) => setTimeout(r, ms));

bot.on('error', (e) => log('error:', e.message));
bot.on('kicked', (r) => log('kicked:', r));

setTimeout(() => {
  log('TIMEOUT: no spawn');
  process.exit(1);
}, 90000);

/** Walk within `distance` of a point, with a deadline. */
async function gotoNear(x, y, z, distance = 1, timeout = 15000) {
  let timer = null;
  try {
    await Promise.race([
      bot.pathfinder.goto(new goals.GoalNear(x, y, z, distance)),
      new Promise((_, reject) => {
        timer = setTimeout(() => reject(new Error('the walk took too long')), timeout);
      }),
    ]);
    return true;
  } catch (err) {
    log('  walk failed:', err.message);
    return false;
  } finally {
    if (timer) clearTimeout(timer);
    try {
      bot.pathfinder.stop();
    } catch (err) {
      /* no goal set */
    }
  }
}

bot.once('spawn', async () => {
  log('spawned at', bot.entity.position);
  log('spawnPoint  ', bot.spawnPoint);
  bot.loadPlugin(pathfinderPlugin);
  const movements = new Movements(bot);
  movements.canDigBlocks = true;
  bot.pathfinder.setMovements(movements);
  await wait(3000);

  // --- 1. the depot ----------------------------------------------------------
  const sp = bot.spawnPoint;
  for (let dy = -2; dy <= 2; dy++) {
    const b = bot.blockAt(new Vec3(sp.x, sp.y + dy, sp.z));
    log(`  block at spawn y${dy >= 0 ? '+' : ''}${dy}:`, b ? b.name : 'null');
  }
  log('  bot feet y :', bot.entity.position.y, '| block y:', Math.floor(bot.entity.position.y));
  const under = bot.blockAt(bot.entity.position.floored().offset(0, -1, 0));
  log('  under the bot:', under && under.name);

  // --- 2. the matcher with a positionless block -----------------------------
  let seen = { total: 0, noPosition: 0, named: 0 };
  const found = bot.findBlocks({
    matching: (block) => {
      seen.total += 1;
      if (!block) return false;
      if (!block.position) {
        seen.noPosition += 1;
        if (block.name === 'oak_log' || block.name === 'stone' || block.name === 'dirt') {
          seen.named += 1;
        }
        return false;
      }
      return block.name === 'oak_log';
    },
    maxDistance: 24,
  });
  log('matcher calls:', seen.total, '| with no position:', seen.noPosition,
      '| of which named matches:', seen.named);
  log('oak_log positions found:', found.length);

  // --- 3. mine something we can carry ---------------------------------------
  const feet = bot.entity.position.floored();
  const target = bot.findBlock({
    matching: (b) =>
      !!b && !!b.position &&
      (b.name === 'dirt' || b.name === 'grass_block' || b.name === 'sand' || b.name === 'gravel') &&
      Math.abs(b.position.y - feet.y) <= 2,
    maxDistance: 12,
  });
  log('block to mine:', target && target.name, target && target.position.toString());
  if (!target) {
    log('nothing to mine; stopping here');
    bot.quit();
    process.exit(0);
  }
  const p = target.position;
  await gotoNear(p.x, p.y, p.z, 2);
  log('  distance to the block:', bot.entity.position.distanceTo(p).toFixed(2));
  try {
    await bot.lookAt(p.offset(0.5, 0.5, 0.5), true);
    await bot.dig(bot.blockAt(p));
    log('  dig sent');
  } catch (e) {
    log('  dig failed:', e.message);
  }
  await wait(1500);
  await gotoNear(p.x, p.y, p.z, 1);
  await wait(1500);
  const bag = bot.inventory.items().map((i) => `${i.name}x${i.count}`);
  log('bag after the dig:', bag);
  const item = bot.inventory.items()[0];
  if (!item) {
    log('nothing in the bag; the dig produced no item');
    bot.quit();
    process.exit(0);
  }

  // --- 4. place it again, the way mineflayer wants --------------------------
  const cobbleType = bot.registry.blocksByName[item.name];
  log('registry block type .position:', cobbleType && cobbleType.position);
  const spot = bot.entity.position.floored();
  const where = new Vec3(spot.x + 2, spot.y, spot.z);
  const support = bot.blockAt(where.offset(0, -1, 0));
  log('placing', item.name, 'at', where.toString(), '| support:', support && support.name);
  try {
    await bot.equip(item, 'hand');
    // mineflayer places a block against a neighbour: the neighbour and
    // the face to put the new one on.
    await bot.placeBlock(support, new Vec3(0, 1, 0));
    await wait(600);
    const now = bot.blockAt(where);
    log('  block there now:', now && now.name);
  } catch (e) {
    log('  place failed:', e.message);
  }

  // --- 5. the toss: does the item leave the bag, and where does it land? ----
  const before = bot.inventory.count(item.name, null);
  try {
    await bot.toss(bot.registry.itemsByName[item.name], null, 1);
    log('  toss sent');
  } catch (e) {
    log('  toss failed:', e.message);
  }
  await wait(800);
  const after = bot.inventory.count(item.name, null);
  log('  bag before the toss:', before, '| after:', after);
  const drops = Object.values(bot.entities).filter(
    (e) => e && e.position && (e.name === 'item' || e.name === 'Item' || e.name === 'item_stack')
  );
  log('  dropped items:', drops.length);
  for (const d of drops.slice(0, 4)) {
    log('    ', d.name, d.position.toString(),
        'distance', d.position.distanceTo(bot.entity.position).toFixed(2),
        'from spawn', d.position.distanceTo(sp).toFixed(2));
  }

  // --- 6. pick it up again by walking over it -------------------------------
  if (drops.length) {
    const d = drops[0];
    await gotoNear(d.position.x, d.position.y, d.position.z, 0);
    await wait(1200);
    log('  bag after walking over it:', bot.inventory.count(item.name, null));
  }

  bot.quit();
  process.exit(0);
});
