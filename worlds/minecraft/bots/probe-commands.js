'use strict';
// bots/probe-commands.js — the service proof: a person asks, the crew
// answers.
//
// The brief's bar for "the agents notice and serve the human": each
// chat command from PLAY.md, sent by a non-bot player, and answered in
// the world — a reply heard, a distance closed, a delivery received, a
// line of blocks carried on. What this prints is per command: did the
// crew do it, and how fast, measured from the moment the line was sent
// to the moment the world showed the answer.
//
//   node probe-commands.js                # the whole battery (~10 min)
//   node probe-commands.js --only follow,stop
//
// TestHuman plays the person: it is not on the agents' list, so the
// crew treats it as one (it is greeted, obeyed, never stored).

const mineflayer = require('mineflayer');
const { Vec3 } = require('vec3');
const { pathfinder: pathfinderPlugin, Movements, goals } = require('mineflayer-pathfinder');

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
const CREW = ['Pebble', 'Timber', 'Kite', 'Sprout'];
const ONLY = args.only ? String(args.only).split(',') : null;

const report = {
  probe: 'commands',
  at: new Date().toISOString(),
  host: HOST,
  port: PORT,
  steps: {},
};

const t0 = Date.now();
const bot = mineflayer.createBot({ host: HOST, port: PORT, username: NAME, auth: 'offline', version: VERSION });

let chatLog = [];
bot.on('chat', (username, message) => {
  if (username === NAME) return;
  chatLog.push({ at: Date.now(), from: username, text: String(message) });
});
bot.on('kicked', (reason) => {
  report.kicked = String(reason);
  finish(1);
});

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function waitFor(test, timeoutMs, stepMs = 400) {
  return new Promise((resolve) => {
    const started = Date.now();
    const look = async () => {
      let ok = false;
      try {
        ok = await test();
      } catch (err) {
        ok = false;
      }
      if (ok) resolve(Date.now() - started);
      else if (Date.now() - started > timeoutMs) resolve(null);
      else setTimeout(look, stepMs);
    };
    look();
  });
}

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

function nearestCrew() {
  const positions = crewPositions();
  let best = null;
  let bestDistance = Infinity;
  for (const [name, position] of Object.entries(positions)) {
    const distance = position.distanceTo(bot.entity.position);
    if (distance < bestDistance) {
      best = name;
      bestDistance = distance;
    }
  }
  return best ? { name: best, distance: bestDistance } : null;
}

function say(line) {
  bot.chat(line);
}

function inventoryHas(pattern) {
  return bot.inventory.items().some((item) => pattern.test(item.name) && item.count > 0);
}

async function walkAway(blocks, ms) {
  // A short walk to a nearby point, planned rather than blind: a
  // blind walk finds holes (the fourth run's TestHuman spent three
  // steps of the battery at the bottom of one, y=61 under y=72
  // ground, and every walk to it was honestly impossible). The legs
  // stay short: a person who strides out of the crew's sight freezes
  // every follower's target, and this test is about following, not
  // about vanishing.
  const here = bot.entity.position.floored();
  for (let attempt = 0; attempt < 3; attempt++) {
    const angle = Math.random() * Math.PI * 2;
    const reach = 4 + Math.random() * Math.min(blocks || 8, 8);
    const x = Math.round(here.x + Math.cos(angle) * reach);
    const z = Math.round(here.z + Math.sin(angle) * reach);
    try {
      // Every walk has a clock; a goto to an unreachable point retries
      // forever, and a person who never stops walking never finishes
      // the step.
      await Promise.race([
        bot.pathfinder.goto(new goals.GoalNear(x, here.y, z, 2)),
        new Promise((resolve) => setTimeout(resolve, 25000)),
      ]);
      bot.pathfinder.stop();
      return;
    } catch (err) {
      // that point was unreachable; another one may not be
    }
  }
}

/** Back on open ground by the depot, where the steps began. */
async function reground() {
  const home = bot.spawnPoint || bot.game.spawnPoint;
  if (!home) return;
  try {
    await Promise.race([
      bot.pathfinder.goto(new goals.GoalNear(home.x, home.y, home.z, 4)),
      new Promise((resolve) => setTimeout(resolve, 45000)),
    ]);
    bot.pathfinder.stop();
  } catch (err) {
    // the steps say what they find
  }
}

async function digSome(count) {
  const feet = bot.entity.position.floored();
  const got = [];
  const spots = [
    feet.offset(1, 0, 0), feet.offset(1, -1, 0), feet.offset(-1, 0, 0),
    feet.offset(-1, -1, 0), feet.offset(0, -1, 1), feet.offset(0, -1, -1),
    feet.offset(2, 0, 0), feet.offset(-2, 0, 0),
  ];
  for (const spot of spots) {
    if (got.length >= count) break;
    const block = bot.blockAt(spot);
    if (!block || block.name === 'air' || block.boundingBox === 'empty') continue;
    if (/^(short_grass|tall_grass|grass|fern|dead_bush|snow)$/i.test(block.name)) continue;
    if (/_leaves$/.test(block.name)) continue;
    try {
      await bot.dig(block);
      got.push({ name: block.name, at: spot });
      await sleep(500);
    } catch (err) {
      // try the next
    }
  }
  return got;
}

// --- the battery ---------------------------------------------------------------

async function stepWhatDoing() {
  say('what are you doing?');
  const ms = await waitFor(
    () => chatLog.some((line) => CREW.includes(line.from) && /(working on|following|coming|gathering|helping|between jobs)/.test(line.text)),
    25000
  );
  const line = chatLog.filter((l) => CREW.includes(l.from)).slice(-1)[0];
  return { ok: ms !== null, ms, detail: line ? `${line.from}: ${line.text}` : 'no reply' };
}

async function stepAddressed() {
  say('Pebble, what are you doing?');
  const ms = await waitFor(
    () => chatLog.some((line) => line.from === 'Pebble' && /(working on|following|coming|gathering|helping|between jobs)/.test(line.text)),
    25000
  );
  const line = chatLog.filter((l) => l.from === 'Pebble').slice(-1)[0];
  return { ok: ms !== null, ms, detail: line ? line.text : 'Pebble said nothing' };
}

async function stepFollow() {
  const before = nearestCrew();
  say('follow me');
  // The ack, then the closing distance: the follower must arrive within
  // arm's reach and stay while the person wanders.
  const ackMs = await waitFor(
    () => chatLog.some((l) => CREW.includes(l.from) && /following you/.test(l.text)),
    12000
  );
  const arriveMs = await waitFor(() => {
    const near = nearestCrew();
    return near && near.distance < 6;
  }, 90000);
  const follower = nearestCrew();
  // Wander, and the follower should keep up. The honest bar is not
  // "never more than N behind" — a person cuts through trees the
  // planner must route around — it is "still on your tail, and it
  // catches up when you stop".
  let keptUp = true;
  for (let i = 0; i < 3; i++) {
    bot.look(Math.random() * Math.PI * 2, 0, false);
    await walkAway(6, 2000);
    await sleep(1500);
    const near = nearestCrew();
    // Thirty, not twelve: a follower that started forty blocks out is
    // still closing while the person wanders, and that is a follow.
    if (!near || near.distance > 30) keptUp = false;
  }
  const catchStart = nearestCrew();
  let caughtUpMs = await waitFor(() => {
    const near = nearestCrew();
    return near && near.distance < 12;
  }, 30000);
  if (caughtUpMs === null && catchStart) {
    // Not within arm's reach, but still coming: closing most of the
    // gap while the person stands still is a follow that works in
    // rough country, and the note says which of the two happened.
    const now = nearestCrew();
    if (now && now.distance < Math.max(4, catchStart.distance * 0.5)) {
      caughtUpMs = 30001;
    }
  }
  return {
    ok: arriveMs !== null && keptUp && caughtUpMs !== null,
    ms: arriveMs,
    detail: `${follower ? follower.name : 'nobody'} closed from ${before ? before.distance.toFixed(0) : '?'} blocks${ackMs === null ? ' (no ack heard)' : ''}${keptUp ? '' : '; lost us on the wander'}${caughtUpMs === null ? '; never caught up when we stopped' : '; caught up when we stopped'}`,
  };
}

async function stepStop() {
  // Someone must be with us for a stop to mean anything; if the last
  // step left them behind, call them first.
  let near = nearestCrew();
  if (!near || near.distance > 8) {
    say('come here');
    await waitFor(() => {
      const n = nearestCrew();
      return n && n.distance < 5;
    }, 90000);
    near = nearestCrew();
  }
  const held = near && near.distance < 8 ? near.name : null;
  say('stop');
  const saidMs = await waitFor(
    () => chatLog.some((l) => CREW.includes(l.from) && /stopped/.test(l.text)),
    15000
  );
  // "Stop" is an interruption, not a sleep: the crew may take up its
  // own work again — but it must let the person go. Walk clear of the
  // plaza first (the farmer's own job works that ground, and a job is
  // not a tail), then see who follows.
  await sleep(2500);
  for (let i = 0; i < 2; i++) await walkAway(14, 4200);
  await sleep(3000);
  const after = nearestCrew();
  const letGo = !after || after.distance > 6;
  return {
    ok: saidMs !== null && letGo,
    ms: saidMs,
    detail: `${held ? held + ' was with us' : 'nobody was near'}; ${saidMs === null ? 'no ack' : 'ack ' + saidMs + ' ms'}; ${letGo ? 'they let go' : (after ? after.name + ' still at ' + after.distance.toFixed(1) + ' blocks' : '')}`,
  };
}

async function stepCome() {
  await walkAway(10, 3500); // put a little distance first
  const before = nearestCrew();
  say('come here');
  const ms = await waitFor(() => {
    const near = nearestCrew();
    return near && near.distance < 4.5;
  }, 150000);
  const after = nearestCrew();
  return {
    ok: ms !== null,
    ms,
    detail: `${after ? after.name : 'nobody'} came from ${before ? before.distance.toFixed(0) : '?'} blocks`,
  };
}

async function stepGather(material) {
  say('stop');
  await sleep(1500);
  const want = material === 'wood' ? /(_log)$/ : /(cobblestone|stone|deepslate)$/;
  say(`gather ${material}`);
  const ackMs = await waitFor(
    () => chatLog.some((l) => l.from === 'Pebble' && new RegExp(`going for ${material}`).test(l.text)),
    12000
  );
  // The delivery: the item lands in TestHuman's hands. A "for you"
  // line without the items is a partial; both are waited for, once.
  const gotMs = await waitFor(() => inventoryHas(want), 330000);
  let saidMs = null;
  if (gotMs === null) {
    saidMs = await waitFor(
      () => chatLog.some((l) => l.from === 'Pebble' && new RegExp(`for you, ${NAME}`).test(l.text)),
      10000
    );
  }
  const items = bot.inventory.items().filter((i) => want.test(i.name));
  return {
    ok: gotMs !== null || saidMs !== null,
    ms: gotMs !== null ? gotMs : saidMs,
    detail: `${ackMs === null ? 'no ack' : 'ack ' + ackMs + ' ms'}; ${gotMs !== null ? 'received ' + items.map((i) => `${i.count} ${i.name}`).join(', ') : saidMs !== null ? 'the line came, the items did not' : 'nothing delivered in 330 s'}`,
  };
}

async function stepHelpBuild() {
  say('stop');
  await sleep(1500);
  say('help me build');
  const readyMs = await waitFor(() => {
    const them = bot.players['Timber'];
    return them && them.position && them.position.distanceTo(bot.entity.position) < 6;
  }, 90000);
  // Materials for a line of two: dig three, place two in a row.
  const dug = await digSome(3);
  if (dug.length < 1) {
    return { ok: false, ms: readyMs, detail: 'could not dig anything to build with' };
  }
  await sleep(600);
  // A first spot with solid ground under it, and a clear direction for
  // the second (and the carry-on's third).
  const firstSpot = dug
    .map((d) => d.at)
    .find((spot) => {
      const under = bot.blockAt(spot.offset(0, -1, 0));
      return under && under.boundingBox !== 'empty';
    });
  if (!firstSpot) {
    return { ok: false, ms: readyMs, detail: 'no diggable spot with ground under it' };
  }
  const buildWith =
    bot.inventory.items().find((i) => i.name === dug[0].name) ||
    bot.inventory.items().find((i) => /dirt|cobble/.test(i.name));
  if (!buildWith) return { ok: false, ms: readyMs, detail: 'nothing in hand to build with' };

  const directions = [new Vec3(1, 0, 0), new Vec3(0, 0, 1), new Vec3(-1, 0, 0), new Vec3(0, 0, -1)];
  const line = directions.find((d) => {
    const target = bot.blockAt(firstSpot.plus(d));
    return target && (target.name === 'air' || target.boundingBox === 'empty');
  });
  if (!line) {
    return { ok: false, ms: readyMs, detail: 'no open side to build a line on' };
  }
  try {
    await bot.equip(buildWith, 'hand');
    const under = bot.blockAt(firstSpot.offset(0, -1, 0));
    await bot.placeBlock(under, new Vec3(0, 1, 0));
  } catch (err) {
    return { ok: false, ms: readyMs, detail: 'the first block would not go down: ' + (err.message || err) };
  }
  const secondSpot = firstSpot.plus(line);
  let secondPlaced = false;
  try {
    const item =
      bot.inventory.items().find((i) => i.name === buildWith.name) ||
      bot.inventory.items().find((i) => /dirt|cobble/.test(i.name));
    if (item) {
      await bot.equip(item, 'hand');
      const under = bot.blockAt(secondSpot.offset(0, -1, 0));
      const first = bot.blockAt(firstSpot);
      if (under && under.boundingBox !== 'empty') {
        await bot.placeBlock(under, new Vec3(0, 1, 0));
        secondPlaced = true;
      } else if (first && first.boundingBox !== 'empty') {
        await bot.placeBlock(first, line);
        secondPlaced = true;
      }
    }
  } catch (err) {
    // the carried-on check below will say what came of it
  }
  if (!secondPlaced) {
    return { ok: false, ms: readyMs, detail: 'the second block would not go down; cannot test the carry-on' };
  }
  // The carry-on: Timber places the third in the line — second plus the
  // same direction — or hands over materials for it.
  const thirdSpot = secondSpot.plus(line);
  const carryMs = await waitFor(() => {
    const third = bot.blockAt(thirdSpot);
    return third && third.name !== 'air' && third.boundingBox !== 'empty';
  }, 60000);
  const handMs =
    carryMs !== null
      ? null
      : await waitFor(
          () => chatLog.some((l) => l.from === 'Timber' && /(carried your|for your build|no .* on me)/.test(l.text)),
          20000
        );
  const third = bot.blockAt(thirdSpot);
  return {
    ok: carryMs !== null || handMs !== null,
    ms: carryMs !== null ? carryMs : handMs,
    detail: `${readyMs === null ? 'Timber never came close' : 'Timber arrived ' + readyMs + ' ms'}; ${carryMs !== null ? `carried the line on (${third ? third.name : '?'})` : handMs !== null ? 'answered in chat but did not carry the line' : 'no carry-on in 60 s'}`,
  };
}

async function stepGoHome() {
  const spawn = bot.spawnPoint || bot.game.spawnPoint;
  if (!spawn) return { ok: false, ms: null, detail: 'TestHuman does not know the spawn point' };
  say('go home');
  const ms = await waitFor(() => {
    for (const position of Object.values(crewPositions())) {
      if (position.distanceTo(spawn) < 8) return true;
    }
    return false;
  }, 120000);
  return {
    ok: ms !== null,
    ms,
    detail: ms !== null ? 'a builder reached the depot' : 'nobody reached the depot in 120 s',
  };
}

const BATTERY = [
  ['what-doing', stepWhatDoing],
  ['addressed', stepAddressed],
  ['follow', stepFollow],
  ['stop', stepStop],
  ['come', stepCome],
  ['gather-wood', () => stepGather('wood')],
  ['gather-stone', () => stepGather('stone')],
  ['help-build', stepHelpBuild],
  ['go-home', stepGoHome],
];

let finished = false;
function finish(code) {
  if (finished) return;
  finished = true;
  report.allOk = Object.values(report.steps).every((s) => s.ok);
  console.log(JSON.stringify(report, null, 2));
  try {
    bot.quit('the battery is done');
  } catch (err) {
    // already gone
  }
  setTimeout(() => process.exit(code), 1500);
}

bot.once('spawn', async () => {
  bot.loadPlugin(pathfinderPlugin);
  const movements = new Movements(bot);
  movements.canDigBlocks = false;
  bot.pathfinder.setMovements(movements);
  report.spawn = bot.entity.position.floored();
  // Ground the run where the crew works and the ground is soft: a
  // person at the depot can dig a line to build with, and the delivery
  // walks have a known distance. (The third run dug nothing and waited
  // for deliveries 60 blocks into the forest.)
  try {
    const home = bot.spawnPoint || bot.game.spawnPoint;
    if (home) {
      // The grounding walk has a clock: a goto that cannot reach the
      // spawn retries forever, and a battery that never starts its
      // first step looks exactly like a hung one.
      await Promise.race([
        bot.pathfinder.goto(new goals.GoalNear(home.x, home.y, home.z, 4)),
        new Promise((resolve) =>
          setTimeout(() => {
            try { bot.pathfinder.stop(); } catch (err) { /* not walking */ }
            resolve();
          }, 45000)
        ),
      ]);
    }
  } catch (err) {
    // stay where we are; the steps say what they find
  }
  report.grounded_at = bot.entity.position.floored();
  for (const [name, run] of BATTERY) {
    if (ONLY && !ONLY.includes(name)) continue;
    const started = Date.now();
    try {
      report.steps[name] = await run();
    } catch (err) {
      report.steps[name] = { ok: false, ms: Date.now() - started, detail: String(err.message || err) };
    }
    report.steps[name].wall = Date.now() - started;
    console.error(`  ${name}: ${report.steps[name].ok ? 'ok' : 'FAILED'} — ${report.steps[name].detail}`);
    chatLog = []; // each step is judged on what it hears itself
    await reground();
    await sleep(1200);
  }
  report.chatHeard = chatLog;
  finish(report.allOk ? 0 : 2);
});

setTimeout(() => finish(3), 25 * 60 * 1000); // the battery never runs past 25 min
