'use strict';
// tools/mcsnap/bots/replay.js — put the kept work back, block by block.
//
// This is the other half of the rewind: the snapshot restores the world
// to an earlier moment, and the work the human chose to keep is put back
// on top of it. Only the placements can be put back — a mined block
// cannot, and the plan says so — and this script does exactly what the
// plan says, in the plan's order.
//
// It reads the plan's `reappliable` list, so the script has no opinion of
// its own about what should be replayed.
//
// Usage:
//
//   NODE_PATH=~/lm-wt/agent-world/bots/node_modules \
//   node replay.js --plan plan.json --name Rewinder --journal /tmp/replayed.jsonl
//
// The operator must have opped the bot; the bot asks for creative mode
// itself with /gamemode.

const fs = require('node:fs');
const path = require('node:path');
const mineflayer = require('mineflayer');
const { Vec3 } = require('vec3');

const DEFAULTS = {
  host: '127.0.0.1',
  port: 25610,
  version: '26.1',
  name: 'Rewinder',
  plan: '/tmp/mcsnap-plan.json',
  journal: '/tmp/mcsnap-replayed.jsonl',
  timeoutMs: 30000,
};

const options = { ...DEFAULTS };
for (let index = 2; index < process.argv.length; index += 1) {
  const key = process.argv[index].replace(/^--/, '');
  const value = process.argv[index + 1];
  if (value === undefined) { options[key] = true; index += 1; continue; }
  options[key] = value;
  index += 1;
}

const plan = JSON.parse(fs.readFileSync(options.plan, 'utf8'));
const ops = Array.isArray(plan) ? plan : (plan.reappliable || []);
fs.mkdirSync(path.dirname(options.journal), { recursive: true });

const bot = mineflayer.createBot({
  host: options.host,
  port: Number(options.port),
  username: String(options.name),
  auth: 'offline',
  version: options.version,
});

function sleep(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

function blockAt(x, y, z) {
  const block = bot.blockAt(new Vec3(x, y, z));
  return block && block.name !== 'air' ? block : null;
}

async function equip(blockName) {
  const item = bot.registry.itemsByName[blockName];
  if (!item) throw new Error(`the server has no item called ${blockName}`);
  try {
    await bot.equip(item.id, 'hand');
  } catch (error) {
    bot.chat(`/give ${String(options.name)} ${blockName} ${ops.length + 2}`);
    await sleep(800);
    await bot.equip(item.id, 'hand');
  }
}

async function replay() {
  await sleep(1500);
  bot.chat('/gamemode creative');
  await sleep(500);
  process.stdout.write(`replaying ${ops.length} placements\n`);

  let done = 0;
  let skipped = 0;
  let failed = 0;
  for (const op of ops) {
    const { x, y, z } = op;
    const blockName = op.block || 'stone';
    try {
      await equip(blockName);
      // Stand within reach: two blocks to the side of the target.
      bot.chat(`/tp ${String(options.name)} ${x + 2} ${y} ${z}`);
      await sleep(400);
      if (blockAt(x, y, z)) {
        skipped += 1;
        process.stdout.write(`already there: ${x},${y},${z}\n`);
        continue;
      }
      const reference = blockAt(x, y - 1, z);
      if (!reference) {
        failed += 1;
        process.stdout.write(`no reference under ${x},${y},${z}\n`);
        continue;
      }
      await bot.placeBlock(reference, 'top');
      done += 1;
      const entry = {
        at: new Date().toISOString(),
        bot: String(options.name),
        op: 'place',
        block: blockName,
        x, y, z,
        replayed: true,
        seq: op.seq,
      };
      fs.appendFileSync(options.journal, `${JSON.stringify(entry)}\n`);
      process.stdout.write(`replayed ${blockName} at ${x},${y},${z}\n`);
      await sleep(150);
    } catch (error) {
      failed += 1;
      process.stdout.write(`replay failed at ${x},${y},${z}: ${error.message}\n`);
    }
  }
  process.stdout.write(`done: ${done} replayed, ${skipped} already there, ${failed} failed\n`);
  await sleep(500);
  bot.quit();
  setTimeout(() => process.exit(failed > 0 ? 1 : 0), 500);
}

bot.on('spawn', () => {
  replay().catch((error) => {
    process.stdout.write(`replay failed: ${error.stack}\n`);
    bot.quit();
    process.exit(1);
  });
});

bot.on('error', (error) => process.stdout.write(`bot error: ${error.message}\n`));
bot.on('kicked', (reason) => process.stdout.write(`kicked: ${JSON.stringify(reason)}\n`));
bot.on('end', () => process.stdout.write('bot ended\n'));
