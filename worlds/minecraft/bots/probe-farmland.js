'use strict';
// bots/probe-farmland.js — is there farmland near the depot, or is the
// look lying?
//
// The council retires the farm need when `farmlandNear` says yes, and
// the world has no farmland within forty blocks of the depot (probe-
// stock.js) — so either the look sees something else, or it is
// matching the wrong block id.
//
//   node bots/probe-farmland.js

const mineflayer = require('mineflayer');

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
setTimeout(() => { log('TIMEOUT'); process.exit(1); }, 90000);

bot.once('spawn', async () => {
  await sleep(10000);
  const spawn = bot.spawnPoint || bot.entity.position;
  const depot = { x: Math.floor(spawn.x), y: Math.floor(spawn.y), z: Math.floor(spawn.z) };
  log('depot', JSON.stringify(depot));

  const entry = bot.registry.blocksByName['farmland'];
  log('registry entry for farmland:', entry ? `id=${entry.id} name=${entry.name}` : 'NONE');
  const id = entry && entry.id;
  const spots = id ? bot.findBlocks({ matching: [id], maxDistance: 56, count: 8 }) : [];
  log('findBlocks returned', spots.length);
  for (const s of spots) {
    const block = bot.blockAt(s);
    const d = Math.round(Math.hypot(s.x - depot.x, s.z - depot.z));
    log('   ', `at ${s.x},${s.y},${s.z}`, 'block name:', block ? block.name : 'null',
        'distance from the depot:', d, d <= 32 ? '(within 32)' : '');
  }
  const near = spots.filter((s) => Math.hypot(s.x - depot.x, s.z - depot.z) <= 32);
  log('farmlandNear would answer:', near.length ? 'YES' : 'no');
  process.exit(0);
});
