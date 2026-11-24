'use strict';
// bots/probe-ramp.js — what would the council's ramp planner decide,
// from the live world? Joins as a probe (it lands at the world spawn,
// the gully floor), builds the real WorldLook around its own bot, and
// prints rampSteps(spawn -> the done depot chest). Read-only.
//
//   node probe-ramp.js
const path = require('path');
const mineflayer = require('mineflayer');
const { WorldLook } = require('./src/worldlook');
const bot = mineflayer.createBot({
  host: '192.168.0.78', port: 25565, username: 'ProbeR', auth: 'offline', version: '26.1',
});
const log = (...a) => console.log(...a);
bot.on('kicked', (r) => { log('kicked:', r); process.exit(1); });
setTimeout(() => { log('TIMEOUT'); process.exit(1); }, 120000);
bot.once('spawn', async () => {
  await new Promise((r) => setTimeout(r, 12000)); // let the sections load
  const agent = { bot };
  const world = new WorldLook(() => [agent], null, () => new Map());
  log('world spawnPoint:', JSON.stringify(bot.spawnPoint));
  const crew = ['Pebble', 'Timber', 'Kite', 'Sprout']
    .map((n) => Object.values(bot.entities).find(
      (e) => e && e.type === 'player' && e.username === n
    ))
    .filter(Boolean);
  if (!crew.length) { log('no crew visible'); process.exit(0); }
  let low = crew[0];
  for (const e of crew) if (e.position.y < low.position.y) low = e;
  const me = {
    x: Math.floor(low.position.x),
    y: Math.floor(low.position.y),
    z: Math.floor(low.position.z),
  };
  const chest = { x: -2, z: -5 }; // b037's site (the done depot chest)
  log('lowest crew stand:', JSON.stringify(me),
    '(', low.username, ')');
  // warm the corridor's sections
  for (let x = -6; x <= 6; x++) {
    for (let z = -8; z <= 12; z++) world.surfaceAt(x, z);
  }
  await new Promise((r) => setTimeout(r, 3000));
  const blocks = world.rampSteps(me.x, me.y, me.z, chest.x, chest.z);
  log('rampSteps ->', JSON.stringify(blocks, null, 1));
  process.exit(0);
});
