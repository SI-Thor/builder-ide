'use strict';
// tools/mcsnap/bots/probe.js — read the world back, block by block.
//
// The snapshot is a copy of files and the restore is a swap of files.
// Neither one says what the world *looks like* afterwards — only what
// the files hash to, and a region file's hash moves whenever a chunk is
// written again, whatever the blocks in it are.
//
// This bot is the eye. It connects, stands where it is told to stand,
// and asks the server what block is at each coordinate. With it the
// experiment can say "after the restore the block the builder put at
// 4,71,2 is gone, and the one it put at 4,70,2 is back", which is the
// question the brief actually asks.
//
// Usage:
//
//   NODE_PATH=~/lm-wt/agent-world/bots/node_modules \
//   node probe.js --points points.json --out probe.json
//
// The points file is a JSON list of {"x":..,"y":..,"z":..,"expect":"stone"}.
// "expect" is optional and is only carried through to the result, so the
// caller can see the whole picture in one place.
//
// The operator must have opped the bot: it moves itself with /tp, and
// the chunk a block lives in is only sent to a client that is close
// enough to be told about it.

const fs = require('node:fs');
const mineflayer = require('mineflayer');
const { Vec3 } = require('vec3');

const DEFAULTS = {
  host: '127.0.0.1',
  port: 25610,
  version: '26.1',
  name: 'Prober',
  points: '/tmp/mcsnap-points.json',
  out: '/tmp/mcsnap-probe.json',
  settleMs: 700,
};

const options = { ...DEFAULTS };
for (let index = 2; index < process.argv.length; index += 1) {
  const key = process.argv[index].replace(/^--/, '');
  const value = process.argv[index + 1];
  if (value === undefined) { options[key] = true; index += 1; continue; }
  options[key] = value;
  index += 1;
}

function sleep(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

const bot = mineflayer.createBot({
  host: options.host,
  port: Number(options.port),
  username: String(options.name),
  auth: 'offline',
  version: options.version,
  physicsEnabled: true,
});

async function probe(points) {
  const found = [];
  for (const point of points) {
    const x = Number(point.x);
    const y = Number(point.y);
    const z = Number(point.z);
    try {
      // Stand next to the point and wait for the chunk to arrive. A
      // block the client has not been told about reads as **unknown**,
      // and an unknown block is not the same thing as an empty one:
      // reading it as air would say a block is missing when the client
      // simply has not seen it yet. So the probe waits for the block to
      // become known, and only then reads it.
      bot.chat(`/tp ${String(options.name)} ${x + 2} ${y} ${z}`);
      await sleep(Number(options.settleMs));
      let block = bot.blockAt(new Vec3(x, y, z));
      const deadline = Date.now() + 8000;
      while (!block && Date.now() < deadline) {
        await sleep(200);
        block = bot.blockAt(new Vec3(x, y, z));
      }
      const name = block && block.name !== 'air' ? block.name : 'air';
      found.push({ x, y, z, block: name, expect: point.expect || null });
      process.stdout.write(`${x},${y},${z} = ${name}\n`);
    } catch (error) {
      found.push({ x, y, z, block: null, expect: point.expect || null, error: error.message });
      process.stdout.write(`${x},${y},${z} = error: ${error.message}\n`);
    }
  }
  return found;
}

bot.on('spawn', async () => {
  await sleep(1500);
  let points = [];
  try {
    points = JSON.parse(fs.readFileSync(options.points, 'utf8'));
  } catch (error) {
    process.stdout.write(`could not read the points: ${error.message}\n`);
  }
  if (!Array.isArray(points)) points = [];
  const found = await probe(points);
  fs.writeFileSync(options.out, JSON.stringify(found, null, 2), 'utf8');
  process.stdout.write(`probed ${found.length} points\n`);
  await sleep(300);
  bot.quit();
  setTimeout(() => process.exit(0), 400);
});

bot.on('error', (error) => process.stdout.write(`bot error: ${error.message}\n`));
bot.on('kicked', (reason) => process.stdout.write(`kicked: ${JSON.stringify(reason)}\n`));
bot.on('end', () => process.stdout.write('bot ended\n'));
