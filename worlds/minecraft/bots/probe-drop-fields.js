'use strict';
// bots/probe-drop-fields.js — what does a dropped item LOOK like to
// mineflayer? Digs one dirt-level block beside the spawner and prints
// the resulting entity's type/name/displayName and metadata, so the
// pile readers (groundItemsNear, pickup_near) filter on fields that
// actually exist.
const mineflayer = require('mineflayer');
const { Vec3 } = require('vec3');
const bot = mineflayer.createBot({
  host: '192.168.0.78', port: 25565, username: 'ProbeD', auth: 'offline', version: '26.1',
});
const log = (...a) => console.log(new Date().toISOString().slice(11, 19), ...a);
bot.on('kicked', (r) => { log('kicked:', r); process.exit(1); });
setTimeout(() => { log('TIMEOUT'); process.exit(1); }, 45000);
bot.once('spawn', async () => {
  await new Promise((r) => setTimeout(r, 6000));
  const p = bot.entity.position;
  let f = null;
  let block = null;
  for (let y = Math.floor(p.y) + 2; y > Math.floor(p.y) - 6 && !block; y -= 1) {
    const at = bot.blockAt(new Vec3(Math.floor(p.x) + 2, y, Math.floor(p.z)));
    if (at && at.name !== 'air' && at.name !== 'cave_air' && at.name !== 'void_air') { f = new Vec3(Math.floor(p.x) + 2, y, Math.floor(p.z)); block = at; }
  }
  log('digging', block && block.name, 'at', f.toString());
  try {
    await bot.lookAt(f.offset(0.5, 0.5, 0.5), true);
    await bot.dig(block);
  } catch (e) { log('dig error:', String(e)); }
  await new Promise((r) => setTimeout(r, 3000));
  let n = 0;
  for (const e of Object.values(bot.entities || {})) {
    if (!e || !e.position) continue;
    if (e.type === 'player') continue;
    if (e.position.distanceTo(p) > 8) continue;
    n += 1;
    let item = null;
    try { item = e.metadata && e.metadata.find((m) => m && m.itemCount != null); } catch (err) {}
    log('entity type=', JSON.stringify(e.type), 'name=', JSON.stringify(e.name),
        'displayName=', JSON.stringify(e.displayName), 'objectType=', JSON.stringify(e.objectType),
        'metadata item=', item ? JSON.stringify({ name: item.itemName || (item.item && item.item.name), count: item.itemCount }) : 'none');
  }
  log('non-player entities near:', n);
  process.exit(0);
});
