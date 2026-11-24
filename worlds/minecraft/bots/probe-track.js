'use strict';
// bots/probe-track.js — does a crew member ever MOVE? Samples a named
// bot's position every 300 ms and prints every change (or a heartbeat
// every 10 s when it stands still). Read-only; 60 s.
//
//   node probe-track.js Pebble
const mineflayer = require('mineflayer');
const who = process.argv[2] || 'Pebble';
const bot = mineflayer.createBot({
  host: '192.168.0.78', port: 25565, username: 'ProbeT', auth: 'offline', version: '26.1',
});
const log = (...a) => console.log(new Date().toISOString().slice(11, 19), ...a);
bot.on('kicked', (r) => { log('kicked:', r); process.exit(1); });
setTimeout(() => { log('TIMEOUT (60 s)'); process.exit(0); }, 60000);
bot.once('spawn', async () => {
  await new Promise((r) => setTimeout(r, 6000));
  const find = () => Object.values(bot.entities).find(
    (x) => x && x.type === 'player' && x.username === who
  );
  let last = '';
  let quiet = 0;
  log('tracking', who);
  setInterval(() => {
    const e = find();
    if (!e) return;
    const p = e.position;
    const here = `${p.x.toFixed(1)},${p.y.toFixed(1)},${p.z.toFixed(1)}`;
    if (here !== last) {
      if (last) log('moved', last, '->', here);
      last = here;
      quiet = 0;
    } else if (++quiet % 33 === 0) {
      log('standing at', here, '(10 s)');
    }
  }, 300);
});
