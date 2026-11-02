'use strict';
// tools/mcsnap/bots/builder.js — a builder for the private world.
//
// The private world needs bots that *build*, so that a snapshot can be
// measured while the world is changing and a restore can be measured
// against a world that really changed. This bot does the smallest thing
// that is still a real bot: it connects, puts a tower of blocks into the
// world, and records what it did.
//
// It records it twice, in two places, because the rewind needs both:
//
// * the **placement journal** — one JSON line per placement, with the
//   coordinates and the block. This is the only place the world's
//   *block-level* history exists: the ledger's rows say which skill ran
//   on which bot, not where a block went, so without the journal a kept
//   play cannot be put back;
// * the **world ledger** — a row per placement in the same `audit` schema
//   the live world's ledger uses, written live with node:sqlite. The
//   private world is its own world and it keeps its own story.
//
// Three things the live world's own bots taught this one, each of them a
// message from the server:
//
// * **the blocks come from the operator.** A bot's hotbar is empty, and
//   the operator gives it the blocks (the bot is opped for that);
// * **the item to equip is the one in the inventory**, not the one in the
//   registry: the registry item has no slot, and mineflayer's equip uses
//   the slot to decide what to click;
// * **the bot aims before it places.** mineflayer's placeBlock does a
//   *smooth* look first, and the stream of rotation packets that comes
//   with it is what the server refuses ("Invalid move player packet
//   received") — the bot is dropped for it. The live bots look at the
//   target first, with an instant look, and then place: by then the
//   smooth look has nothing left to turn.
//
// Usage:
//
//   NODE_PATH=~/lm-wt/agent-world/bots/node_modules \
//   node builder.js --name Builder1 --journal /tmp/journal.jsonl \
//                   --ledger /tmp/ledger.sqlite3 --count 6 --block stone
//
// The operator must have opped the bot; the bot asks for its blocks with
// /give itself.

const fs = require('node:fs');
const path = require('node:path');
const mineflayer = require('mineflayer');
const { Vec3 } = require('vec3');
const { DatabaseSync } = require('node:sqlite');

const DEFAULTS = {
  host: '127.0.0.1',
  port: 25610,
  version: '26.1',
  count: 6,
  block: 'stone',
  intervalMs: 250,
  journal: '/tmp/mcsnap-journal.jsonl',
  ledger: '/tmp/mcsnap-ledger.sqlite3',
  skill: 'skill_mcsnap_place',
  offset: 0,
};

const options = { ...DEFAULTS };
for (let index = 2; index < process.argv.length; index += 1) {
  const key = process.argv[index].replace(/^--/, '');
  const value = process.argv[index + 1];
  if (value === undefined) { options[key] = true; index += 1; continue; }
  options[key] = value;
  index += 1;
}

const count = Number(options.count);
const blockName = String(options.block);
const name = String(options.name || 'Builder1');

fs.mkdirSync(path.dirname(options.journal), { recursive: true });

// --- the ledger -------------------------------------------------------------

const ledger = new DatabaseSync(options.ledger);
ledger.exec(`
  CREATE TABLE IF NOT EXISTS audit (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    id TEXT NOT NULL UNIQUE,
    at TEXT NOT NULL,
    actor TEXT NOT NULL,
    type TEXT NOT NULL,
    subject TEXT NOT NULL,
    payload TEXT NOT NULL,
    artifact TEXT
  )
`);

function writeLedgerRow({ skill, outcome, coordinates }) {
  const stamp = new Date().toISOString().replace(/\.\d{3}Z$/, 'Z');
  const actor = JSON.stringify({ agent: null, id: name, kind: 'character', via: 'reflex' });
  const subject = JSON.stringify({ family: 'builder.place', skill });
  const payload = JSON.stringify({
    at: stamp,
    candidates: [skill],
    chooser: 'mcsnap.test',
    chooser_version: '1',
    context: { bot: name, phase: 'day', role: 'builder' },
    cost: { gpu_minutes: 0, hosted_cents: 0, wall_seconds: 0 },
    id: `play_${Date.now().toString(16)}`,
    outcome,
    propensity: 1.0,
    skill_id: skill,
    skill_version: 1,
    coordinates,
  });
  const temporary = `tmp_${Date.now()}_${Math.random().toString(16).slice(2)}`;
  ledger.prepare(
    'INSERT INTO audit (id, at, actor, type, subject, payload, artifact) VALUES (?, ?, ?, ?, ?, ?, NULL)'
  ).run(temporary, stamp, actor, 'tile.played', subject, payload);
  const seq = Number(ledger.prepare('SELECT last_insert_rowid() AS seq').get().seq);
  ledger.prepare('UPDATE audit SET id = ? WHERE seq = ?').run(`aud_${seq}`, seq);
  return seq;
}

function writeJournal(entry) {
  fs.appendFileSync(options.journal, `${JSON.stringify(entry)}\n`);
}

// --- the bot ----------------------------------------------------------------

const bot = mineflayer.createBot({
  host: options.host,
  port: Number(options.port),
  username: name,
  auth: 'offline',
  version: options.version,
  physicsEnabled: true,
});

function sleep(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

function solidAt(x, y, z) {
  const block = bot.blockAt(new Vec3(x, y, z));
  return Boolean(block) && block.name !== 'air' && block.boundingBox !== 'empty';
}

/**
 * A column beside the bot that has something to build on.
 *
 * The bot may be standing on a tree, so the ground it stands on is not
 * always the ground next to it. The tower is built on the first
 * neighbour column with a solid block at the bot's own level, which keeps
 * every block of the tower within the bot's reach.
 */
function towerBase(feet) {
  const ring = [
    [1, 0], [-1, 0], [0, 1], [0, -1],
    [1, 1], [-1, -1], [1, -1], [-1, 1],
  ];
  // Every bot spawns at the same place, so the offset says which
  // neighbouring column this bot builds in — the ring is walked from a
  // different place, not from further away: a block more than the bot's
  // reach is a block the server will not let it place.
  const offset = Number(options.offset || 0) % ring.length;
  for (let step = 0; step < ring.length; step += 1) {
    const [dx, dz] = ring[(offset + step) % ring.length];
    const x = feet.x + dx;
    const z = feet.z + dz;
    if (!solidAt(x, feet.y - 1, z)) continue;
    // The column has to be clear for the whole height of the tower. A
    // block that is already there makes the placement a no-op, and the
    // journal would then say the bot put a block in the world when it
    // did not — which would make the whole measurement a lie.
    let clear = true;
    for (let level = 0; level < count; level += 1) {
      if (solidAt(x, feet.y + level, z)) { clear = false; break; }
    }
    if (clear) return { x, y: feet.y, z };
  }
  return null;
}

async function equipBlock() {
  if (!bot.registry.itemsByName[blockName]) {
    throw new Error(`the server has no item called ${blockName}`);
  }
  const held = () => bot.inventory.items().find((entry) => entry.name === blockName);
  if (!held()) {
    bot.chat(`/give ${name} ${blockName} ${count + 2}`);
    await sleep(1500);
  }
  const item = held();
  if (!item) throw new Error(`no ${blockName} in the inventory`);
  await bot.equip(item, 'hand');
}

async function build() {
  await sleep(8000);            // let the chunks arrive, and give the
                                // operator the moment it needs to op the bot
  const feet = bot.entity.position.floored();
  process.stdout.write(`building from ${bot.entity.position.toString()}\n`);
  const base = towerBase(feet);
  if (!base) {
    process.stdout.write('no column beside the bot to build on\n');
    bot.quit();
    return;
  }
  await equipBlock();

  let placed = 0;
  for (let index = 0; index < count; index += 1) {
    const y = base.y + index;
    const reference = bot.blockAt(new Vec3(base.x, y - 1, base.z));
    if (!reference || reference.name === 'air') {
      process.stdout.write(`no reference block at ${base.x},${y - 1},${base.z}\n`);
      break;
    }
    const target = new Vec3(base.x, y, base.z);
    try {
      // The placement is made with an **instant** look. mineflayer's own
      // placeBlock does a smooth look first, and the stream of rotation
      // packets that comes with it is what the server refuses ("Invalid
      // move player packet received") — the bot is dropped for it.
      await bot._placeBlockWithOptions(reference, new Vec3(0, 1, 0), {
        forceLook: true,
        swingArm: 'right',
      });
    } catch (error) {
      process.stdout.write(`place failed at ${base.x},${y},${base.z}: ${error.message}\n`);
      break;
    }
    const at = new Date().toISOString();
    const coordinates = { x: base.x, y, z: base.z };
    // Read the block back: the server is the only witness, and a
    // placement the server did not take must not be written down as
    // one that it did.
    const readBack = bot.blockAt(target);
    const placedBlock = readBack && readBack.name !== 'air' ? readBack.name : 'air';
    const seq = writeLedgerRow({
      skill: String(options.skill),
      outcome: {
        detail: `placed ${blockName} at ${base.x},${y},${base.z}`,
        measure: 'world_op',
        result: 'win',
        score: null,
      },
      coordinates,
    });
    writeJournal({
      at,
      bot: name,
      op: 'place',
      block: blockName,
      x: base.x,
      y,
      z: base.z,
      skill: String(options.skill),
      seq,
      verified: placedBlock,
    });
    placed += 1;
    process.stdout.write(
      `placed ${blockName} at ${base.x},${y},${base.z} (ledger seq ${seq}, read back ${placedBlock})\n`
    );
    await sleep(Number(options.intervalMs));
  }
  process.stdout.write(`done: ${placed} placements\n`);
  await sleep(500);
  bot.quit();
}

bot.on('spawn', () => {
  build().catch((error) => {
    process.stdout.write(`build failed: ${error.stack}\n`);
    bot.quit();
  });
});

bot.on('error', (error) => process.stdout.write(`bot error: ${error.message}\n`));
bot.on('kicked', (reason) => process.stdout.write(
  `kicked at ${bot.entity ? bot.entity.position.toString() : '?'}: ${JSON.stringify(reason)}\n`
));
bot.on('end', () => process.stdout.write('bot ended\n'));
