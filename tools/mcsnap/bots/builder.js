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
// Usage:
//
//   NODE_PATH=~/lm-wt/agent-world/bots/node_modules \
//   node builder.js --name Builder1 --journal /tmp/journal.jsonl \
//                   --ledger /tmp/ledger.sqlite3 --count 6 --block stone
//
// The operator must have opped the bot; the bot asks for creative mode
// and the blocks itself with /gamemode and /give.

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
});

function sleep(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

function solidAt(x, y, z) {
  const block = bot.blockAt(new Vec3(x, y, z));
  return Boolean(block) && block.name !== 'air' && block.boundingBox === 'block';
}

/** The y of the first solid ground under a column. */
function groundBelow(x, z) {
  const feet = Math.floor(bot.entity.position.y);
  for (let y = feet - 1; y > feet - 12; y -= 1) {
    if (solidAt(x, y, z)) return y;
  }
  return feet - 1;
}

async function equipBlock() {
  const item = bot.registry.itemsByName[blockName];
  if (!item) throw new Error(`the server has no item called ${blockName}`);
  try {
    await bot.equip(item.id, 'hand');
  } catch (error) {
    // Creative mode's hotbar can be empty for a bot; ask for the block.
    bot.chat(`/give ${name} ${blockName} ${count + 2}`);
    await sleep(800);
    await bot.equip(item.id, 'hand');
  }
}

async function build() {
  await sleep(8000);            // let the chunks arrive, and give the
                                  // operator the moment it needs to op the bot
  bot.chat('/gamemode creative');
  await sleep(500);
  const position = bot.entity.position;
  // Each builder gets its own tower: they all spawn at the world spawn,
  // so the offset is what keeps their work apart.
  const offset = Number(options.offset || 0);
  const towerX = Math.floor(position.x) + 2 + offset * 4;
  const towerZ = Math.floor(position.z);
  const groundY = groundBelow(towerX, towerZ);

  await equipBlock();

  let placed = 0;
  for (let index = 0; index < count; index += 1) {
    const y = groundY + 1 + index;
    const reference = bot.blockAt(new Vec3(towerX, y - 1, towerZ));
    if (!reference) {
      process.stdout.write(`no reference block at ${towerX},${y - 1},${towerZ}\n`);
      break;
    }
    try {
      await bot.placeBlock(reference, 'top');
    } catch (error) {
      process.stdout.write(`place failed at ${towerX},${y},${towerZ}: ${error.message}\n`);
      break;
    }
    const at = new Date().toISOString();
    const coordinates = { x: towerX, y, z: towerZ };
    const seq = writeLedgerRow({
      skill: String(options.skill),
      outcome: {
        detail: `placed ${blockName} at ${towerX},${y},${towerZ}`,
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
      x: towerX,
      y,
      z: towerZ,
      skill: String(options.skill),
      seq,
    });
    placed += 1;
    process.stdout.write(
      `placed ${blockName} at ${towerX},${y},${towerZ} (ledger seq ${seq})\n`
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
bot.on('kicked', (reason) => process.stdout.write(`kicked: ${JSON.stringify(reason)}\n`));
bot.on('end', () => process.stdout.write('bot ended\n'));
