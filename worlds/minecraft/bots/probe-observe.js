'use strict';
// bots/probe-observe.js — does the no-grief observation chain work?
// Two clients: FreshEye stands off; TestHumanP digs and places beside
// itself. FreshEye runs the crew's exact listener (humanity.buildGuard
// over a real Ledger) and reports what it saw: block updates, humans
// near, ledger records.
const mineflayer = require('mineflayer');
const path = require('node:path');
const { Ledger, buildGuard, isAgent } = require('./src/humanity');

const eye = mineflayer.createBot({ host: '192.168.0.78', port: 25565, username: 'FreshEye', auth: 'offline', version: '26.1' });
const placer = mineflayer.createBot({ host: '192.168.0.78', port: 25565, username: 'TestHumanP', auth: 'offline', version: '26.1' });
const { Vec3 } = require('vec3');

const file = path.join(__dirname, '..', 'runtime', 'logs', 'observe-test.jsonl');
const ledger = new Ledger(file);
const guard = buildGuard({
  ledger,
  botName: 'FreshEye',
  humansNear: (position) => {
    const out = [];
    for (const player of Object.values(eye.players)) {
      if (!player || !player.username) continue;
      const entity = player.entity;
      if (!entity || !entity.position) continue;
      if (player.username === 'FreshEye' || isAgent(player.username)) continue;
      out.push({ name: player.username, distance: entity.position.distanceTo(position) });
    }
    return out;
  },
});

let updates = 0;
let humansSeen = 0;
let records = 0;
eye.on('blockUpdate', (oldBlock, newBlock) => {
  updates += 1;
  const row = guard.observe(oldBlock, newBlock);
  if (row) {
    records += 1;
    console.log('LEDGER:', JSON.stringify(row));
  }
});

eye.once('spawn', async () => {
  await new Promise((r) => setTimeout(r, 2500));
  // stand ~8 blocks from the placer
  const p = placer.entity ? placer.entity.position : null;
  if (p) {
    try { await eye.lookAt(p, true); } catch (err) { /* look is enough */ }
    eye.setControlState('back', true);
    await new Promise((r) => setTimeout(r, 1200));
    eye.clearControlStates();
  }
  const placerPos = placer.entity ? placer.entity.position.floored() : null;
  console.log('placer at', placerPos ? placerPos.toArray().join(',') : '?', 'eye at', eye.entity.position.floored().toArray().join(','));
  humansSeen = guard.humansNear(placerPos || eye.entity.position).length;
  console.log('humans near placer (per the guard):', humansSeen);
});

placer.once('spawn', async () => {
  await new Promise((r) => setTimeout(r, 6000)); // let the eye settle
  const feet = placer.entity.position.floored();
  let spot = null;
  for (const o of [[1, 0, 0], [1, -1, 0], [-1, 0, 0], [0, -1, 1], [0, 0, 1]]) {
    const b = placer.blockAt(feet.offset(o[0], o[1], o[2]));
    if (b && b.name !== 'air' && b.boundingBox !== 'empty' && !/_leaves$/.test(b.name) && !/^(short_grass|tall_grass|grass|fern)/.test(b.name)) {
      spot = feet.offset(o[0], o[1], o[2]);
      break;
    }
  }
  if (!spot) {
    console.log('placer: nothing to dig at', feet.toArray().join(','));
    finish();
    return;
  }
  try {
    await placer.lookAt(spot.offset(0.5, 0.5, 0.5), true);
    await placer.dig(placer.blockAt(spot));
    console.log('placer dug at', spot.toArray().join(','));
  } catch (err) {
    console.log('placer dig failed:', err.message);
  }
  await new Promise((r) => setTimeout(r, 2000));
  const item = placer.inventory.items().find((i) => /dirt|cobble|stone/.test(i.name));
  if (item) {
    try {
      await placer.equip(item, 'hand');
      for (const f of [new Vec3(0, 1, 0), new Vec3(1, 0, 0), new Vec3(-1, 0, 0), new Vec3(0, 0, 1)]) {
        const ref = placer.blockAt(spot.minus(f));
        if (ref && ref.boundingBox !== 'empty') {
          await placer.placeBlock(ref, f);
          console.log('placer PLACED at', spot.toArray().join(','));
          break;
        }
      }
    } catch (err) {
      console.log('placer place failed:', err.message);
    }
  } else {
    console.log('placer: no item in hand');
  }
  await new Promise((r) => setTimeout(r, 6000));
  finish();
});

function finish() {
  console.log('SUMMARY: blockUpdates seen by eye:', updates, '| ledger records:', records, '| humans near placer:', humansSeen);
  eye.quit();
  placer.quit();
  setTimeout(() => process.exit(0), 1200);
}
setTimeout(finish, 40000);
