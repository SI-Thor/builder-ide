'use strict';
// bots/probe-drop.js — what does a dug block leave in a hand? (diagnostic)
const mineflayer = require('mineflayer');
const { Vec3 } = require('vec3');
const NAME = process.argv[2] || 'TestHuman6';
const bot = mineflayer.createBot({ host: '192.168.0.78', port: 25565, username: NAME, auth: 'offline', version: '26.1' });
bot.once('spawn', async () => {
  const feet = bot.entity.position.floored();
  for (const offset of [new Vec3(1, 0, 0), new Vec3(1, -1, 0), new Vec3(-1, 0, 0), new Vec3(0, -1, 1)]) {
    const block = bot.blockAt(feet.plus(offset));
    if (!block || block.name === 'air' || block.boundingBox === 'empty') continue;
    if (/^(short_grass|tall_grass|grass|fern|dead_bush)$/.test(block.name)) continue;
    if (/_leaves$/.test(block.name)) continue;
    console.log('digging', block.name, 'at', feet.plus(offset).toArray().join(','));
    try { await bot.dig(block); } catch (err) { console.log('dig threw:', err.message); }
    for (let i = 0; i < 8; i++) {
      await new Promise((r) => setTimeout(r, 700));
      const items = bot.inventory.items();
      console.log(`t+${(i + 1) * 0.7}s hand:`, items.map((it) => `${it.count} ${it.name}`).join(', ') || '(empty)');
      if (items.length) break;
    }
    break;
  }
  const drops = Object.values(bot.entities).filter((e) => e && e.name && /item/i.test(e.name));
  console.log('item entities visible:', drops.length, drops.slice(0, 3).map((d) => d.name));
  bot.quit('done');
  setTimeout(() => process.exit(0), 1200);
});
