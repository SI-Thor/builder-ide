'use strict';
// bots/probe-human.js — the join proof: a person walks in.
//
// The brief's bar is "joining works, proved by a client, not by
// config". This is that client: a mineflayer bot named TestHuman that
// joins the way a person does (its name is not on the agents' list),
// waits to be greeted, moves, talks, breaks a block and places one
// back. What it prints is the evidence: times, distances, block names.
//
//   node probe-human.js                     # the whole proof
//   node probe-human.js --wait-greeting 0   # skip the greeting wait
//
// The privacy check it enables: after it chats a line of marked free
// text, that line must appear nowhere in runtime/logs/bots.jsonl
// (checked by ops/playtest.sh, not here — the probe is the person, and
// a person does not read the world's diary).

const mineflayer = require('mineflayer');
const { Vec3 } = require('vec3');

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
const GREETING_WAIT = Number(args['wait-greeting'] === undefined ? 40000 : args['wait-greeting']);

const report = {
  probe: 'human-join',
  at: new Date().toISOString(),
  name: NAME,
  host: HOST,
  port: PORT,
  version: VERSION,
  steps: {},
  ok: {},
};

const t0 = Date.now();
const bot = mineflayer.createBot({ host: HOST, port: PORT, username: NAME, auth: 'offline', version: VERSION });

const saw = [];
bot.on('chat', (username, message) => {
  if (username !== NAME) saw.push({ at: Date.now() - t0, from: username, text: String(message) });
});
bot.on('kicked', (reason) => {
  report.kicked = String(reason);
  console.log(JSON.stringify(report, null, 2));
  process.exit(1);
});
bot.on('error', (err) => {
  report.error = String(err.message || err);
});

function done() {
  report.chatHeard = saw;
  report.allOk = Object.values(report.ok).every(Boolean);
  console.log(JSON.stringify(report, null, 2));
  bot.quit('the proof is made');
  setTimeout(() => process.exit(report.allOk ? 0 : 2), 1500);
}

bot.once('spawn', async () => {
  report.steps.join_seconds = Number(((Date.now() - t0) / 1000).toFixed(1));
  report.steps.spawn = bot.entity.position.floored();
  report.steps.server_version = bot.version;
  report.ok.join = true;

  // 1. the greeting: the crew notices a person. The nearest-builder
  // rule means one line, from one builder, within GREETING_WAIT.
  if (GREETING_WAIT > 0) {
    const greet = await waitFor(
      () => saw.some((line) => line.text.includes(NAME) && /welcome/i.test(line.text)),
      GREETING_WAIT,
      500
    );
    report.steps.greeting_ms = greet ? saw.find((l) => /welcome/i.test(l.text)).at : null;
    report.ok.greeting = Boolean(greet);
  }

  // 2. moving like a person: walk forward a moment, and the world
  // should see the position change. A spawn against a tree canopy
  // blocks one direction; a person turns and tries another.
  let moved = 0;
  for (let tryIndex = 0; tryIndex < 3 && moved < 1.5; tryIndex++) {
    const before = bot.entity.position.clone();
    bot.look(tryIndex * 2.4, 0, false);
    await sleep(300);
    bot.setControlState('forward', true);
    bot.setControlState('jump', true);
    await sleep(2500);
    bot.clearControlStates();
    moved = Math.max(moved, before.distanceTo(bot.entity.position));
  }
  report.steps.moved_blocks = Number(moved.toFixed(1));
  report.ok.moving = moved > 1.5;

  // 3. talking: a line of free text, marked so the privacy check can
  // look for it in the world's log and find nothing.
  const marker = 'zq' + Math.random().toString(36).slice(2, 8);
  const words = `hello from the test seat ${marker}`;
  bot.chat(words);
  report.steps.said = words;
  await sleep(3000);
  report.ok.chatting = true; // sent; the check that it is NOT stored is ops-side

  // 4. breaking a block, the way a survival player does: look at it,
  // dig it, and keep what it gave. (A dig is a packet, not a promise:
  // the server refuses one at a block you are not looking at, and
  // mineflayer does not notice — so the look comes first and the
  // block's disappearance is checked after, the same rule the world's
  // own api holds its skills to.)
  const feet = bot.entity.position.floored();
  let broken = null;
  const candidates = [
    feet.offset(0, -1, 0), feet.offset(1, -1, 0), feet.offset(1, 0, 0),
    feet.offset(-1, -1, 0), feet.offset(0, -1, 1), feet.offset(0, -1, -1),
  ];
  for (const spot of candidates) {
    const block = bot.blockAt(spot);
    if (!block || block.name === 'air' || block.boundingBox === 'empty') continue;
    if (/^(short_grass|tall_grass|grass|fern|dead_bush)$/.test(block.name)) continue;
    if (/_leaves$/.test(block.name)) continue; // drops saplings, not itself
    try {
      await bot.lookAt(spot.offset(0.5, 0.5, 0.5), true);
      await bot.dig(block);
      await sleep(500);
      const still = bot.blockAt(spot);
      if (still && still.name === block.name) continue; // it never broke
      broken = { name: block.name, at: spot };
      break;
    } catch (err) {
      // out of reach or wrong tool class; try the next
    }
  }
  report.steps.broke = broken ? broken.name : null;
  report.ok.breaking = Boolean(broken);

  // 5. placing one back: the item the dig gave, set down in the hole.
  let placed = false;
  if (broken) {
    // The drop lands beside us and the server hands it over when we
    // are close: that takes a few seconds, not a fixed beat.
    let item = null;
    for (let i = 0; i < 10 && !item; i++) {
      await sleep(500);
      item =
        bot.inventory.items().find((i) => i.name === broken.name) ||
        bot.inventory.items().find((i) => /dirt|cobble|stone/.test(i.name));
    }
    if (!item) {
      report.steps.place_error = 'nothing in hand came of the dig';
    } else {
      // Digging the block under our feet leaves us standing in the
      // hole; a person steps out before putting the ground back.
      const inside =
        bot.entity.position.floored().offset(0, 0, 0).equals(broken.at) ||
        (Math.abs(bot.entity.position.x - broken.at.x - 0.5) < 0.7 &&
          Math.abs(bot.entity.position.z - broken.at.z - 0.5) < 0.7 &&
          Math.abs(bot.entity.position.y - broken.at.y) < 1.2);
      if (inside) {
        bot.setControlState('forward', true);
        bot.setControlState('jump', true);
        await sleep(1300);
        bot.clearControlStates();
        await sleep(400);
      }
      const FACES = [
        [0, 1, 0], [1, 0, 0], [-1, 0, 0], [0, 0, 1], [0, 0, -1], [0, -1, 0],
      ];
      try {
        await bot.equip(item, 'hand');
        await bot.lookAt(broken.at.offset(0.5, 0.5, 0.5), true);
        // The hole goes back the way holes do: against whichever solid
        // neighbour it has, the ground under it first.
        for (const [fx, fy, fz] of FACES) {
          const reference = bot.blockAt(broken.at.offset(-fx, -fy, -fz));
          if (!reference || reference.boundingBox === 'empty') continue;
          await bot.placeBlock(reference, new Vec3(fx, fy, fz));
          placed = true;
          break;
        }
      } catch (err) {
        report.steps.place_error = String(err.message || err);
      }
    }
  }
  report.steps.placed = placed;
  report.ok.placing = placed;

  report.steps.players = Object.keys(bot.players);
  done();
});

function waitFor(test, timeoutMs, stepMs) {
  return new Promise((resolve) => {
    const started = Date.now();
    const look = () => {
      if (test()) resolve(true);
      else if (Date.now() - started > timeoutMs) resolve(false);
      else setTimeout(look, stepMs);
    };
    look();
  });
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
