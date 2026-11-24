'use strict';
// bots/probe6.js — where is the ground?
//
// The world's spawn point turned out to be on a tree canopy: the spawn
// packet says (0, 70, 0) and the block under it is azalea leaves. Every
// builder joins up in the trees, and a skill that looks for dirt or stone
// at the builder's own level finds nothing.
//
// So: survey the ground around the spawn, and say where a flat, open,
// reachable patch of it is. The answer decides where the world's spawn
// should be moved to.
//
//   node probe6.js

const mineflayer = require('mineflayer');
const { Vec3 } = require('vec3');

const bot = mineflayer.createBot({
  host: process.env.AW_HOST || '192.168.0.78',
  port: Number(process.env.AW_PAPER_PORT || 25565),
  username: 'Probe5',
  auth: 'offline',
  version: '26.1',
});

const log = (...args) => console.log(...args);
const wait = (ms) => new Promise((r) => setTimeout(r, ms));

const GROUND = new Set(['grass_block', 'dirt', 'coarse_dirt', 'podzol', 'sand', 'red_sand',
  'gravel', 'stone', 'andesite', 'diorite', 'granite', 'terracotta', 'snow_block', 'clay']);

bot.on('error', (e) => log('error:', e.message));

setTimeout(() => {
  log('TIMEOUT: no spawn');
  process.exit(1);
}, 60000);

bot.once('spawn', async () => {
  await wait(4000);
  const sp = bot.spawnPoint;
  const R = 24;
  const TOP = 88;
  const BOTTOM = 50;

  const column = (x, z) => {
    for (let y = TOP; y >= BOTTOM; y--) {
      const b = bot.blockAt(new Vec3(x, y, z));
      if (!b) continue;
      if (b.name === 'air' || b.name === 'cave_air' || b.name === 'void_air') continue;
      if (b.name === 'azalea_leaves' || b.name === 'cherry_leaves' || b.name === 'oak_leaves' ||
          b.name === 'birch_leaves' || b.name === 'spruce_leaves' || b.name === 'jungle_leaves' ||
          b.name === 'acacia_leaves' || b.name === 'dark_oak_leaves') {
        continue; // leaves are canopy, not ground
      }
      return { y, name: b.name };
    }
    return null;
  };

  const tops = new Map();
  const names = new Map();
  for (let dx = -R; dx <= R; dx++) {
    for (let dz = -R; dz <= R; dz++) {
      const x = sp.x + dx;
      const z = sp.z + dz;
      const c = column(x, z);
      if (!c) continue;
      tops.set(`${x},${z}`, c);
      names.set(c.name, (names.get(c.name) || 0) + 1);
    }
  }
  log('columns read:', tops.size);
  log('what the ground is made of:');
  for (const [name, n] of [...names.entries()].sort((a, b) => b[1] - a[1]).slice(0, 12)) {
    log(`   ${String(n).padStart(4)}  ${name}`);
  }

  // A flat patch: the same ground height over a 5x5, with the ground
  // itself being something to stand on and build on.
  const flat = [];
  for (const [key, c] of tops) {
    if (!GROUND.has(c.name)) continue;
    const [x, z] = key.split(',').map(Number);
    let same = true;
    for (let ix = -2; ix <= 2 && same; ix++) {
      for (let iz = -2; iz <= 2 && same; iz++) {
        const other = tops.get(`${x + ix},${z + iz}`);
        if (!other || other.y !== c.y || !GROUND.has(other.name)) same = false;
      }
    }
    if (same) flat.push({ x, z, y: c.y, name: c.name });
  }
  flat.sort((a, b) => (Math.hypot(a.x - sp.x, a.z - sp.z)) - (Math.hypot(b.x - sp.x, b.z - sp.z)));
  log('flat 5x5 ground patches:', flat.length);
  for (const f of flat.slice(0, 12)) {
    log(`   x=${f.x} z=${f.z} y=${f.y} (${f.name}) — ${Math.hypot(f.x - sp.x, f.z - sp.z).toFixed(1)} blocks from the spawn`);
  }

  // What is the spawn column made of, from the top down?
  log('spawn column from the top:');
  for (let y = TOP; y >= BOTTOM; y--) {
    const b = bot.blockAt(new Vec3(sp.x, y, sp.z));
    if (b && b.name !== 'air') log(`   y=${y} ${b.name}`);
  }

  bot.quit();
  process.exit(0);
});
