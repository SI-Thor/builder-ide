'use strict';
// bots/probe-steady.js — a person in the room, for the steady half
// hour.
//
// The brief's bar: "TPS >= 19.5 for 30 min with TestHuman active". A
// client parked at spawn is not active; this one wanders a few blocks
// every half minute, digs and places a block every few minutes, and
// asks the crew what they are doing now and then — the load of a
// curious person, not a load generator. It prints where it is every
// time it moves, so the steady log and the server's own tick counts
// can be read against each other.
//
//   node probe-steady.js --minutes 31

const mineflayer = require('mineflayer');

const args = {};
for (let i = 2; i < process.argv.length; i++) {
  const found = process.argv[i].match(/^--([a-z-]+)(?:=(.*))?$/);
  if (!found) continue;
  // `--name X` and `--name=X` both work: a valueless flag takes the
  // next argument when it is not a flag itself.
  if (found[2] === undefined) {
    const next = process.argv[i + 1];
    if (next && !next.startsWith('--')) {
      args[found[1]] = next;
      i += 1;
    } else {
      args[found[1]] = true;
    }
  } else {
    args[found[1]] = found[2];
  }
}

const HOST = args.host || process.env.AW_HOST || '192.168.0.78';
const PORT = Number(args.port || process.env.AW_PAPER_PORT || 25565);
const VERSION = args.version || process.env.AW_MINECRAFT_VERSION || '26.1';
const NAME = args.name || 'TestHuman';
const MINUTES = Number(args.minutes || 31);
const CREW = ['Pebble', 'Timber', 'Kite', 'Sprout'];

const bot = mineflayer.createBot({ host: HOST, port: PORT, username: NAME, auth: 'offline', version: VERSION });
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const started = Date.now();
let moves = 0;
let digs = 0;
let chats = 0;

bot.on('kicked', (reason) => {
  console.log(`[steady] kicked at ${Math.round((Date.now() - started) / 1000)}s: ${reason}`);
  process.exit(1);
});
bot.on('chat', (username, message) => {
  if (CREW.includes(username)) chats += 0; // heard, never stored
});

bot.once('spawn', async () => {
  console.log(`[steady] ${NAME} is in the world at ${bot.entity.position.floored()} for ${MINUTES} minutes`);
  const until = Date.now() + MINUTES * 60 * 1000;
  let beat = 0;
  while (Date.now() < until && !bot.ended) {
    beat += 1;
    // Every beat (30 s): turn somewhere new and walk a few blocks.
    bot.look(Math.random() * Math.PI * 2, 0, false);
    bot.setControlState('forward', true);
    if (beat % 3 === 0) bot.setControlState('jump', true);
    await sleep(2200);
    bot.clearControlStates();
    moves += 1;
    // Every fourth beat (2 min): work the ground a little.
    if (beat % 4 === 0) {
      const feet = bot.entity.position.floored();
      for (const offset of [[1, 0, 0], [-1, 0, 0], [1, -1, 0], [0, -1, 1]]) {
        const block = bot.blockAt(feet.offset(offset[0], offset[1], offset[2]));
        if (!block || block.name === 'air' || block.boundingBox === 'empty') continue;
        try {
          await bot.dig(block);
          digs += 1;
          await sleep(600);
          const item = bot.inventory.items().find((i) => i.name === block.name);
          const under = bot.blockAt(feet.offset(offset[0], offset[1] - 1, offset[2]));
          if (item && under && under.boundingBox !== 'empty') {
            await bot.equip(item, 'hand');
            await bot.placeBlock(under, new (require('vec3').Vec3)(0, 1, 0));
          }
          break;
        } catch (err) {
          // the next offset may work
        }
      }
    }
    // Every tenth beat (5 min): ask the crew what they are doing.
    if (beat % 10 === 0) {
      bot.chat('what are you doing?');
      chats += 1;
    }
    console.log(
      `[steady] ${Math.round((Date.now() - started) / 1000)}s at ${bot.entity.position.floored().toArray().join(',')} moves=${moves} digs=${digs} chats=${chats}`
    );
    await sleep(30000 - 2200);
  }
  console.log(`[steady] the half hour is up: moves=${moves} digs=${digs} chats=${chats}`);
  bot.quit('the hour is up');
  setTimeout(() => process.exit(0), 1500);
});
