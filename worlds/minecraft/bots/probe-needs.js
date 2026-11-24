'use strict';
// bots/probe-needs.js — ask the world the council's own questions.
//
// The council proposes from three questions about the world: is there a
// chest at the depot, is the forest back, is there farmland near the
// depot. When the council proposes nothing, one of those is answering
// "no need" — and the board says nothing about which.
//
// The probe joins (as Probe5), lets the chunks settle, and asks with
// the world's own code: bots/src/worldlook.js for the looks, and
// bots/src/council.js's buildProposal for the proposals. It also scans
// a grid for farmland and wheat, because the looks read through the
// loaded chunks and a chunk that is not loaded is not "empty" — it is
// "unknown", and the two answers are different.
//
//   node bots/probe-needs.js

const mineflayer = require('mineflayer');
const { Vec3 } = require('vec3');
const { WorldLook } = require('./src/worldlook');
const { buildProposal, needs } = require('./src/council');

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
setTimeout(() => { log('TIMEOUT'); process.exit(1); }, 180000);

bot.once('spawn', async () => {
  await sleep(12000);
  const world = new WorldLook(() => [{ bot }], null, () => new Map());
  const depot = world.depot();
  log('depot', JSON.stringify(depot), 'probe at', bot.entity.position.toString());

  log('--- the three needs, as the world look answers them ---');
  log('a chest at the depot?', world.chestAt(depot.x, depot.y, depot.z, 12));
  log('trunks within 64:', world.countBlocks(['oak_log', 'spruce_log', 'birch_log'], depot.x, depot.y, depot.z, 64));
  log('farmland within 32?', world.farmlandNear(depot.x, depot.y, depot.z, 32));

  log('--- a grid scan for farmland and wheat within 32 of the depot ---');
  const wanted = ['farmland', 'wheat'];
  let found = 0;
  for (let dx = -32; dx <= 32; dx += 1) {
    for (let dz = -32; dz <= 32; dz += 1) {
      for (let dy = 50; dy <= 100; dy += 1) {
        const block = bot.blockAt(new Vec3(depot.x + dx, dy, depot.z + dz));
        if (!block) continue;
        if (!wanted.includes(block.name)) continue;
        found += 1;
        if (found <= 20) log('   ', block.name, `${depot.x + dx},${dy},${depot.z + dz}`);
      }
    }
  }
  log('farmland/wheat blocks in the scan:', found);

  log('--- where the crew is ---');
  for (const e of Object.values(bot.entities)) {
    if (e && e.name && e.position && ['Pebble', 'Timber', 'Kite', 'Sprout'].includes(e.name)) {
      log('   ', e.name, e.position.toString(), 'from the depot',
        Math.round(Math.hypot(e.position.x - depot.x, e.position.z - depot.z)));
    }
  }

  log('--- the proposals ---');
  const board = { list: () => [] };
  for (const kind of ['depot-chest', 'replant', 'farm']) {
    const p = buildProposal(kind, world, {});
    log(kind, p ? `site ${JSON.stringify(p.site)} materials ${JSON.stringify(p.materials)}` : 'NO PROPOSAL');
  }
  log('needs():', JSON.stringify(needs(board, world).map((p) => p.kind)));

  process.exit(0);
});
