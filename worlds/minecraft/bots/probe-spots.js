'use strict';
// bots/probe20.js — pick standable, workable spots near the depot.
//
// The three wedged builders need to be somewhere the world's skills can
// work: solid ground, two blocks of air, and — for the gatherer — stone
// or a tree within reach, for the farmer grass. The probe joins (its
// own position is saved from the last probe), loads the neighbourhood,
// and grades a grid of spots around the depot.
//
//   node bots/probe20.js

const mineflayer = require('mineflayer');
const { Vec3 } = require('vec3');

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
setTimeout(() => { log('TIMEOUT'); process.exit(1); }, 90000);

bot.once('spawn', async () => {
  await sleep(9000);
  const here = bot.entity.position.floored();
  log('joining from', here.toString());
  const find = (names, cx, cz, r = 12) => {
    const ids = names
      .map((n) => bot.registry.blocksByName[n])
      .filter(Boolean)
      .map((b) => b.id);
    const spots = bot.findBlocks({ matching: ids, maxDistance: r, count: 8, position: new Vec3(cx, here.y, cz) });
    return spots.length;
  };
  const grade = (x, z) => {
    for (let y = 80; y >= 60; y--) {
      const below = bot.blockAt(new Vec3(x, y - 1, z));
      const feet = bot.blockAt(new Vec3(x, y, z));
      const head = bot.blockAt(new Vec3(x, y + 1, z));
      if (!below || !feet || !head) continue;
      const solid = below.boundingBox === 'block';
      const clear = (feet.name === 'air' || feet.name === 'cave_air') &&
                    (head.name === 'air' || head.name === 'cave_air');
      if (solid && clear) {
        const stone = find(['stone', 'andesite', 'diorite', 'granite', 'cobblestone'], x, z);
        const wood = find(['oak_log', 'spruce_log', 'birch_log'], x, z);
        const grass = find(['tall_grass', 'grass_block', 'dirt', 'grass'], x, z);
        return { x, y, z, ground: below.name, stone, wood, grass };
      }
    }
    return null;
  };
  // a grid around the watcher's view centre (the depot is near 0,-7)
  const spots = [];
  for (let x = -20; x <= 20; x += 4) {
    for (let z = -24; z <= 8; z += 4) {
      const g = grade(x, z);
      if (g) spots.push(g);
    }
  }
  for (const s of spots) {
    log(`(${s.x},${s.y},${s.z}) ground=${s.ground} stone-near=${s.stone} wood-near=${s.wood} grass-near=${s.grass}`);
  }
  process.exit(0);
});
