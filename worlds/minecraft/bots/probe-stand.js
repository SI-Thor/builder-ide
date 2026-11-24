'use strict';
// bots/probe-wedge.js — is a crew member wedged? Prints the blocks
// around a named bot's body (feet, head, above, the four sides and
// the diagonals at feet level), plus its ground state. Read-only.
//
//   node probe-wedge.js Pebble
const mineflayer = require('mineflayer');
const { Vec3 } = require('vec3');
const who = process.argv[2] || 'Pebble';
const bot = mineflayer.createBot({
  host: '192.168.0.78', port: 25565, username: 'ProbeW', auth: 'offline', version: '26.1',
});
const log = (...a) => console.log(new Date().toISOString().slice(11, 19), ...a);
bot.on('kicked', (r) => { log('kicked:', r); process.exit(1); });
setTimeout(() => { log('TIMEOUT'); process.exit(1); }, 60000);
bot.once('spawn', async () => {
  await new Promise((r) => setTimeout(r, 8000));
  const e = Object.values(bot.entities).find(
    (x) => x && x.type === 'player' && x.username === who
  );
  if (!e) { log(who, 'not found; players:', Object.values(bot.entities).filter((x) => x.type === 'player').map((x) => x.username).join(',')); process.exit(0); }
  const p = e.position;
  const f = new Vec3(Math.floor(p.x), Math.floor(p.y), Math.floor(p.z));
  log(who, 'at', p.x.toFixed(1), p.y.toFixed(1), p.z.toFixed(1), 'onGround', e.onGround);
  const name = (v) => { const b = bot.blockAt(v); return b ? b.name : '?'; };
  log('below feet :', name(f.offset(0, -1, 0)));
  log('feet       :', name(f), ' head:', name(f.offset(0, 1, 0)), ' above:', name(f.offset(0, 2, 0)));
  for (const [dx, dz] of [[1, 0], [-1, 0], [0, 1], [0, -1], [1, 1], [1, -1], [-1, 1], [-1, -1]]) {
    log(`side ${dx},${dz}  : feet`, name(f.offset(dx, 0, dz)), ' head', name(f.offset(dx, 1, dz)), ' up1', name(f.offset(dx, 2, dz)));
  }
  process.exit(0);
});
