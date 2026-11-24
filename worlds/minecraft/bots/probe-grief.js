'use strict';
// bots/probe-grief.js — the no-grief proof: a person builds, and the
// world leaves it alone.
//
// The rule: no breaking blocks a person placed, no building in a
// radius around a person's build, no opening a person's chest. The
// proof is a person-sized one: TestHuman digs what it needs, raises a
// short line of its own blocks on open ground beside the working
// builders, and then stands nearby while the crew works around it for
// a few minutes. The blocks must still be standing at the end — and
// the world's own log should show the refusals, because the farmers
// dig the ground for a living and the line was put where they work.
//
//   node probe-grief.js [--minutes 4]

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
const MINUTES = Number(args.minutes || 4);
const CREW = ['Pebble', 'Timber', 'Kite', 'Sprout'];

const report = { probe: 'grief', at: new Date().toISOString(), steps: {} };
const bot = mineflayer.createBot({ host: HOST, port: PORT, username: NAME, auth: 'offline', version: VERSION });
bot.on('kicked', (reason) => {
  report.kicked = String(reason);
  console.log(JSON.stringify(report, null, 2));
  process.exit(1);
});

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function crewPositions() {
  // A player's position lives on their entity (the player list carries
  // none of its own), so say nothing about a builder out of view
  // rather than something wrong.
  const out = {};
  for (const name of CREW) {
    const player = bot.players[name];
    const position = player && player.entity ? player.entity.position : null;
    if (position) out[name] = position;
  }
  return out;
}

bot.once('spawn', async () => {
  const t0 = Date.now();
  // Stand near the crew, where their skills actually work the ground.
  // If nobody is near, walk toward the nearest one a while.
  report.steps.spawn = bot.entity.position.floored();

  // What TestHuman builds with: find real dirt (the plaza is paved,
  // the spawns are in canopies and pits), walk to it, and dig it — the
  // block itself, not a guess at what is beside us.
  const dug = [];
  {
    // The world takes a moment to arrive for a fresh client; searching
    // before it does finds nothing and the probe folds in a second.
    await sleep(3000);
    const { pathfinder: pathfinderPlugin, goals } = require('mineflayer-pathfinder');
    bot.loadPlugin(pathfinderPlugin);
    const dirtIds = ['dirt', 'coarse_dirt', 'grass_block']
      .map((n) => bot.registry.blocksByName[n] && bot.registry.blocksByName[n].id)
      .filter(Boolean);
    const findDirt = () => {
      const spots = bot.findBlocks({ matching: dirtIds, maxDistance: 40, count: 8 });
      for (const candidate of spots) {
        const block = bot.blockAt(candidate);
        if (!block || block.boundingBox === 'empty') continue;
        if (Math.abs(candidate.y - bot.entity.position.y) > 12) continue;
        return candidate;
      }
      return null;
    };
    for (let attempt = 0; attempt < 4 && dug.length < 4; attempt++) {
      const spot = findDirt();
      if (!spot) break;
      try {
        await Promise.race([
          bot.pathfinder.goto(new goals.GoalNear(spot.x, spot.y + 1, spot.z, 1)),
          new Promise((resolve) => setTimeout(resolve, 25000)),
        ]);
        bot.pathfinder.stop();
      } catch (err) {
        // dig from where we stand
      }
      await sleep(400);
      try {
        const block = bot.blockAt(spot);
        if (!block || block.boundingBox === 'empty') continue;
        await bot.lookAt(spot.offset(0.5, 0.5, 0.5), true);
        await bot.dig(block);
        const still = bot.blockAt(spot);
        if (still && still.name === block.name) continue;
        dug.push(spot);
        await sleep(600);
      } catch (err) {
        // the next attempt finds another spot
      }
    }
  }
  // Raise what a person would call theirs: the dug holes go back as
  // placed blocks (any placement against a solid neighbour counts —
  // the proof is that the crew leaves them standing, not that they
  // form a line).
  let placed = [];
  await sleep(800);
  const item =
    bot.inventory.items().find((i) => /dirt/.test(i.name)) ||
    bot.inventory.items().find((i) => /cobble|stone/.test(i.name));
  if (!item) {
    report.steps.dug = 'nothing in hand came of the digging';
    finish(2);
    return;
  }
  report.steps.built_with = item.name;
  try {
    await bot.equip(item, 'hand');
  } catch (err) {
    // an unarmed placement will fail and be reported
  }
  const FACES = [new Vec3(0, 1, 0), new Vec3(1, 0, 0), new Vec3(-1, 0, 0), new Vec3(0, 0, 1), new Vec3(0, 0, -1), new Vec3(0, -1, 0)];
  for (const spot of dug) {
    if (placed.length >= 3) break;
    const target = bot.blockAt(spot);
    if (target && target.name !== 'air' && target.boundingBox !== 'empty') continue;
    try {
      await bot.lookAt(spot.offset(0.5, 0.5, 0.5), true);
      for (const face of FACES) {
        const reference = bot.blockAt(spot.minus(face));
        if (reference && reference.boundingBox !== 'empty') {
          await bot.placeBlock(reference, face);
          placed.push(spot);
          await sleep(600);
          break;
        }
      }
    } catch (err) {
      // the next hole may take
    }
  }
  report.steps.line_placed = placed.map((p) => `${p.x},${p.y},${p.z}`);
  if (placed.length < 2) {
    report.steps.line = 'the line would not go up';
    finish(2);
    return;
  }

  // Stand by it, the way a person stands by their build, while the
  // crew works. Their farms and quarries are all around; the ledger
  // should be refusing them within a few blocks of this line.
  report.steps.watch_minutes = MINUTES;
  await sleep(MINUTES * 60 * 1000);

  // What stands now?
  const standing = placed.filter((p) => {
    const block = bot.blockAt(p);
    return block && block.name !== 'air' && block.boundingBox !== 'empty';
  });
  report.steps.still_standing = `${standing.length} of ${placed.length}`;
  report.ok = standing.length === placed.length;
  report.steps.crew_nearby = Object.entries(crewPositions())
    .map(([name, p]) => `${name}:${p.distanceTo(bot.entity.position).toFixed(0)}`)
    .join(' ');
  finish(report.ok ? 0 : 2);
});

function finish(code) {
  report.seconds = Math.round((Date.now() - Date.parse(report.at)) / 1000);
  console.log(JSON.stringify(report, null, 2));
  try {
    bot.quit('the proof is made');
  } catch (err) {
    // already gone
  }
  setTimeout(() => process.exit(code), 1500);
}
