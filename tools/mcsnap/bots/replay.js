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
  // The physics has to be on: the server drops a bot that spawns in the
  // air to the ground, and a bot that does not track its own fall sends
  // the stale position with its next chat — which the server refuses
  // ("Invalid move player packet received") and drops the bot for.
  physicsEnabled: true,
});

function sleep(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

function blockAt(x, y, z) {
  const block = bot.blockAt(new Vec3(x, y, z));
  return block && block.name !== 'air' ? block : null;
}

async function equip(blockName) {
  // The item to equip is the one **in the inventory**, not the one in
  // the registry: the registry item has no slot, and mineflayer's equip
  // uses the slot to decide what to click.
  const held = () => bot.inventory.items().find((entry) => entry.name === blockName);
  if (!bot.registry.itemsByName[blockName]) {
    throw new Error(`the server has no item called ${blockName}`);
  }
  if (!held()) {
    bot.chat(`/give ${String(options.name)} ${blockName} ${ops.length + 2}`);
    await sleep(1200);
  }
  const item = held();
  if (!item) throw new Error(`no ${blockName} in the inventory`);
  await bot.equip(item, 'hand');
}

/**
 * Put the bot where it can reach the block, and know that it is there.
 *
 * The bot is teleported next to the target and then **again**: teleported
 * once, it falls most of the way to the ground while the chunk arrives,
 * and a block eight metres up is then out of reach — the server refuses
 * the placement and says nothing back, so the placement times out.
 */
async function standBeside(x, y, z) {
  bot.chat(`/tp ${String(options.name)} ${x + 1} ${y} ${z}`);
  await sleep(700);
  const target = new Vec3(x, y, z);
  if (bot.entity.position.distanceTo(target) > 3.5) {
    bot.chat(`/tp ${String(options.name)} ${x + 1} ${y} ${z}`);
    await sleep(200);
  }
  return bot.entity.position.distanceTo(target);
}

async function replay() {
  await sleep(1500);
  bot.chat('/gamemode creative');
  await sleep(500);
  process.stdout.write(`replaying ${ops.length} placements\n`);

  let done = 0;
  let skipped = 0;
  let failed = 0;
  let verified = 0;
  for (const op of ops) {
    const { x, y, z } = op;
    const blockName = op.block || 'stone';
    try {
      await equip(blockName);
      const distance = await standBeside(x, y, z);
      process.stdout.write(`standing ${distance.toFixed(2)} blocks from ${x},${y},${z}\n`);
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
      // The placement is made with an **instant** look: mineflayer's own
      // placeBlock does a smooth look first, and the rotation packets it
      // sends are what the server refuses ("Invalid move player packet
      // received") — the bot is dropped for it.
      try {
        await bot._placeBlockWithOptions(reference, new Vec3(0, 1, 0), {
          forceLook: true,
          swingArm: 'right',
        });
      } catch (error) {
        // The server refuses a placement it cannot reach and answers
        // nothing, so the placement times out. Stand there again and try
        // once more before calling it a failure.
        process.stdout.write(`first attempt failed at ${x},${y},${z}: ${error.message}\n`);
        await standBeside(x, y, z);
        await sleep(300);
        await bot._placeBlockWithOptions(reference, new Vec3(0, 1, 0), {
          forceLook: true,
          swingArm: 'right',
        });
      }
      done += 1;
      // Read the block back. The point of the rewind is that the world
      // ends up with the block in it, so the only honest answer is the
      // one the server gives when it is asked.
      const readBack = bot.blockAt(new Vec3(x, y, z));
      const placedBlock = readBack && readBack.name !== 'air' ? readBack.name : 'air';
      if (placedBlock === blockName) verified += 1;
      const entry = {
        at: new Date().toISOString(),
        bot: String(options.name),
        op: 'place',
        block: blockName,
        x, y, z,
        replayed: true,
        seq: op.seq,
        verified: placedBlock,
      };
      fs.appendFileSync(options.journal, `${JSON.stringify(entry)}\n`);
      process.stdout.write(`replayed ${blockName} at ${x},${y},${z} (read back ${placedBlock})\n`);
      await sleep(350);
    } catch (error) {
      failed += 1;
      process.stdout.write(`replay failed at ${x},${y},${z}: ${error.message}\n`);
    }
  }
  process.stdout.write(`done: ${done} replayed, ${skipped} already there, ${failed} failed, ${verified} read back as the expected block\n`);
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
