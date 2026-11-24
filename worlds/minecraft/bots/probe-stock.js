'use strict';
// bots/probe-stock.js — what the community can actually lay hands on.
//
// The wood question, measured: the spruce is on a hillside 13 blocks
// above the depot (506 spruce_log at y=83-86, x=-3, z=7), so the
// question is what stands **at the depot's own level**: planks in the
// wall the community built, cobblestone, dirt, and whatever is lying
// on the ground as a pile.
//
//   node bots/probe-stock.js [radius]

const mineflayer = require('mineflayer');
const { Vec3 } = require('vec3');

const bot = mineflayer.createBot({
  host: process.env.AW_HOST || '192.168.0.78',
  port: Number(process.env.AW_PAPER_PORT || 25565),
  username: 'Probe5',
  auth: 'offline',
  version: '26.1',
});

const log = (...a) => console.log(new Date().toISOString().slice(11, 19), ...a);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

bot.on('error', (e) => log('error:', e.message));
bot.on('kicked', (r) => { log('kicked:', r); process.exit(1); });
setTimeout(() => { log('TIMEOUT'); process.exit(1); }, 120000);

bot.once('spawn', async () => {
  await sleep(10000);
  const spawn = bot.spawnPoint || bot.entity.position;
  const depot = { x: Math.floor(spawn.x), y: Math.floor(spawn.y), z: Math.floor(spawn.z) };
  const radius = Number(process.argv[2] || 32);
  log('depot', JSON.stringify(depot), 'radius', radius);

  const wanted = ['oak_planks', 'spruce_planks', 'oak_log', 'spruce_log', 'cobblestone',
    'stone', 'dirt', 'coarse_dirt', 'grass_block', 'oak_sapling', 'wheat_seeds', 'farmland'];
  const counts = {};
  const low = [];
  for (let dx = -radius; dx <= radius; dx += 1) {
    for (let dz = -radius; dz <= radius; dz += 1) {
      for (let dy = 30; dy <= 100; dy += 1) {
        const block = bot.blockAt(new Vec3(depot.x + dx, dy, depot.z + dz));
        if (!block || !wanted.includes(block.name)) continue;
        counts[block.name] = (counts[block.name] || 0) + 1;
        if (low.length < 12 && (block.name === 'oak_planks' || block.name === 'oak_log')) {
          low.push(`${block.name}@${depot.x + dx},${dy},${depot.z + dz}`);
        }
      }
    }
  }
  log('blocks near the depot (y 30-100):', JSON.stringify(counts));
  log('the first planks/logs:', low.join(' '));

  // The pile: the items lying on the ground near the depot.
  const pile = [];
  for (const e of Object.values(bot.entities || {})) {
    if (!e || !e.position) continue;
    if (e.type !== 'object' && e.type !== 'item') continue;
    const name = e.name || e.displayName;
    if (!name) continue;
    const d = Math.hypot(e.position.x - depot.x, e.position.z - depot.z);
    if (d > 16) continue;
    pile.push(`${name}@${Math.round(e.position.x)},${Math.round(e.position.y)},${Math.round(e.position.z)}`);
  }
  log('items lying within 16 of the depot:', pile.length, pile.slice(0, 12).join(' '));

  process.exit(0);
});
