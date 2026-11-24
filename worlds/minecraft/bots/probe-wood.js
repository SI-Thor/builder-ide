'use strict';
// bots/probe-wood.js — where is the wood? A one-shot look at the logs
// (and saplings, and leaves) around the depot, at every level, so the
// community's wood economy is a fact and not a guess.
//
//   node probe-wood.js [radius]
//
// Prints counts by type and the nearest few positions. Exits alone.

const mineflayer = require('mineflayer');

const host = process.env.AW_HOST || '192.168.0.78';
const port = Number(process.env.AW_PAPER_PORT || 25565);
const radius = Number(process.argv[2] || 96);

const bot = mineflayer.createBot({
  host, port, username: 'Probe9', auth: 'offline', version: '26.1',
});

bot.once('spawn', async () => {
  const want = ['oak_log', 'spruce_log', 'birch_log', 'oak_leaves', 'oak_sapling'];
  const ids = want.map((n) => bot.registry.blocksByName[n] && bot.registry.blocksByName[n].id).filter(Boolean);
  let lastAt = '';
  const scan = () => {
    const here = `${bot.entity.position.x.toFixed(0)},${bot.entity.position.y.toFixed(0)},${bot.entity.position.z.toFixed(0)}`;
    if (here === lastAt) return;
    lastAt = here;
    // let the chunks around a teleport settle before reading them
    setTimeout(() => {
      const found = bot.findBlocks({ matching: ids, maxDistance: radius, count: 512 });
      const by = {};
      const nearest = [];
      for (const p of found) {
        const b = bot.blockAt(p);
        if (!b) continue;
        by[b.name] = (by[b.name] || 0) + 1;
        if (b.name.endsWith('_log')) {
          nearest.push({ x: p.x, y: p.y, z: p.z, d: Math.round(bot.entity.position.distanceTo(p)) });
        }
      }
      nearest.sort((a, b) => a.d - b.d);
      console.log(`at ${here}: ${JSON.stringify(by)} nearest ${JSON.stringify(nearest.slice(0, 4))}`);
    }, 3000);
  };
  scan();
  setInterval(scan, 6000);
});

bot.once('error', (err) => {
  console.error('probe failed:', err.message);
  process.exit(1);
});
