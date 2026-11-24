'use strict';
// gym/bot/gym-bot.js — the gym's bot: one mineflayer client on the private
// world, with an HTTP door for the Python environment.
//
// It reuses the world's own pieces — the Agent class, its api, its sandbox
// and its measure — so the gym plays the world's game rather than a copy of
// it. What it does **not** reuse is the reflex: the gym's agent is told
// what to do from Python, so this bridge carries a reflex that asks
// nothing and records nothing. Nothing here writes to the live world.
//
//   node gym/bot/gym-bot.js --port 25630 --bridge-port 25640
//
// The doors:
//
//   GET  /health              is the bot in the world
//   GET  /skills              the library the bridge can run
//   GET  /observation?grid=N  the world's state facts (+ an optional grid)
//   POST /reset               a new episode: the bag and counters cleared
//   POST /step {"skill_id"}   run one skill and measure what it did

const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');

const { Agent } = require('../../bots/src/agent');
const { gotoNear } = require('../../bots/src/api');
const { Log } = require('../../bots/src/log');

/**
 * Vec3, from the world's own installed copy.
 *
 * The gym's checkout has no ``node_modules`` of its own -- the world's
 * copy is shared (gym/ops/gym-world.sh setup links it), and Node only
 * looks for a module in the directories above the one that asks. So the
 * direct name is tried first and the shared copy is the fallback.
 */
function loadVec3() {
  try {
    return require('vec3').Vec3;
  } catch (err) {
    return require('../../bots/node_modules/vec3').Vec3;
  }
}

const { Vec3 } = loadVec3();

const REPO = path.resolve(__dirname, '..', '..');

/**
 * A promise that cannot wait for ever.
 *
 * The episode boundary is the one place where a hang would cost the
 * whole run, so every step of it is capped: a toss that the server never
 * confirms, a walk that never arrives. A cap that fires is recorded as
 * what it is (the walk home did not finish) and the episode starts
 * where the agent stands.
 */
function withTimeout(promise, ms, fallback) {
  return Promise.race([
    Promise.resolve(promise).catch(() => fallback),
    new Promise((resolve) => {
      const timer = setTimeout(() => resolve(fallback), ms);
      if (timer.unref) timer.unref();
    }),
  ]);
}

const DEFAULTS = {
  host: process.env.AW_GYM_HOST || '127.0.0.1',
  port: Number(process.env.AW_GYM_PORT || 25630),
  version: process.env.AW_MINECRAFT_VERSION || '26.1',
  bridgePort: Number(process.env.AW_GYM_BRIDGE_PORT || 25640),
  name: process.env.AW_GYM_BOT || 'Pupil',
  role: process.env.AW_GYM_ROLE || 'gatherer',
  skills: process.env.AW_GYM_SKILLS || path.join(REPO, 'runtime', 'skills'),
  logFile:
    process.env.AW_GYM_LOG || path.join(REPO, 'runtime', 'logs', 'gym-bot.jsonl'),
  grid: Number(process.env.AW_GYM_GRID || 0),
};

// How many blocks above and below the agent the optional grid covers.
// The order is dy (bottom to top), then dz, then dx — the Python side
// reshapes the flat list as (height, width, width), so the two sides must
// agree on it, and they do.
const GRID_HEIGHT = 3;

function parseArgs(argv) {
  const out = Object.assign({}, DEFAULTS);
  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === '--port') out.port = Number(argv[++i]);
    else if (argv[i] === '--bridge-port') out.bridgePort = Number(argv[++i]);
    else if (argv[i] === '--host') out.host = String(argv[++i]);
    else if (argv[i] === '--version') out.version = String(argv[++i]);
    else if (argv[i] === '--name') out.name = String(argv[++i]);
    else if (argv[i] === '--role') out.role = String(argv[++i]);
    else if (argv[i] === '--skills') out.skills = String(argv[++i]);
    else if (argv[i] === '--log') out.logFile = String(argv[++i]);
    else if (argv[i] === '--grid') out.grid = Number(argv[++i]);
  }
  return out;
}

/** The library: one JSON file per skill, as the reflex's library writes them. */
function loadLibrary(root) {
  const out = {};
  let files = [];
  try {
    files = fs.readdirSync(root).filter((f) => f.endsWith('.json'));
  } catch (err) {
    console.error(`the library is not there (${root}): ${err.message}`);
    process.exit(1);
  }
  for (const file of files) {
    try {
      const skill = JSON.parse(fs.readFileSync(path.join(root, file), 'utf8'));
      if (skill && skill.id && skill.body) out[skill.id] = skill;
    } catch (err) {
      console.error(`skipped ${file}: ${err.message}`);
    }
  }
  return out;
}

/**
 * The null reflex: the gym decides, so nothing is asked and nothing is
 * recorded. The world's own ledger stays the community's alone.
 */
const NULL_REFLEX = {
  async decide() {
    return { skill_id: null, reason: 'the gym decides, not the reflex' };
  },
  async play(record) {
    return { ok: true, id: record.id, recorded: false };
  },
};

function countGained(before, after) {
  let gained = 0;
  for (const [name, count] of Object.entries(after || {})) {
    const had = (before || {})[name] || 0;
    if (count > had) gained += count - had;
  }
  return gained;
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const library = loadLibrary(args.skills);
  const log = new Log(args.logFile);
  log.note({
    event: 'gym_bot_opening',
    name: args.name,
    role: args.role,
    host: args.host,
    port: args.port,
    library: Object.keys(library).length,
  });
  console.log(
    `the gym's bot is opening: ${args.name} (${args.role}) on ${args.host}:${args.port}, ` +
      `${Object.keys(library).length} skills in the library`
  );

  const agent = new Agent({
    name: args.name,
    role: args.role,
    host: args.host,
    port: args.port,
    version: args.version,
    reflex: NULL_REFLEX,
    log,
    tickMs: 0,
  });
  agent.onSpawn = () => {
    agent.startPosition = agent.bot.entity.position.clone();
    log.note({ event: 'gym_bot_spawned', position: agent.position() });
    console.log(`  ${args.name} joined the private world at ${JSON.stringify(agent.position())}`);
  };

  await agent.connect();

  // -- the world's facts -------------------------------------------------------

  function facts() {
    return agent.context();
  }

  function blockGrid(radius) {
    const width = radius * 2 + 1;
    const out = [];
    const pos = agent.bot.entity.position;
    const bx = Math.floor(pos.x);
    const by = Math.floor(pos.y);
    const bz = Math.floor(pos.z);
    for (let dy = 0; dy < GRID_HEIGHT; dy++) {
      for (let dz = -radius; dz <= radius; dz++) {
        for (let dx = -radius; dx <= radius; dx++) {
          let name = 'unknown';
          try {
            // mineflayer's blockAt takes a position, not three numbers:
            // the world's own api (bots/src/api.js) reads blocks the same
            // way, and an earlier version of this file passed bare
            // numbers, so every cell of the grid read "unknown".
            const block = agent.bot.blockAt(new Vec3(bx + dx, by + dy - 1, bz + dz));
            // A block the chunk does not hold is "unknown", never "air".
            name = block ? block.name : 'unknown';
          } catch (err) {
            name = 'unknown';
          }
          out.push(name);
        }
      }
    }
    return out;
  }

  function observationPayload(radius) {
    const payload = {
      ok: true,
      facts: facts(),
      position: agent.position(),
      inventory: agent.inventoryMap(),
    };
    if (radius > 0) payload.block_grid = blockGrid(radius);
    return payload;
  }

  function tossItem(item) {
    // mineflayer's ``toss(itemType, metadata, count)`` returns a promise
    // and takes no callback. An earlier version of this file wrapped it
    // in a callback-style promise and hung the reset for ever, because
    // the callback mineflayer never calls was the only way out.
    return withTimeout(
      Promise.resolve().then(() => agent.bot.toss(item.type, null, item.count)),
      5000,
      false,
    );
  }

  async function resetEpisode(radius) {
    agent.counters.mined = 0;
    agent.counters.placed = 0;
    if (agent.bot.health <= 0) {
      try {
        await withTimeout(Promise.resolve(agent.bot.respawn()), 5000, false);
      } catch (err) {
        log.note({ event: 'respawn_failed', detail: String(err.message || err) });
      }
    }
    const items = agent.bot.inventory.items();
    for (const item of items.slice()) {
      await tossItem(item);
    }
    // Back to the mark, the way the world's own builders walk: mineflayer
    // has no client-side teleport a server will accept, so the agent
    // walks home with the world's own pathfinder. The walk is capped, so
    // a wedged bot cannot hold the episode boundary open.
    if (agent.startPosition) {
      const mark = agent.startPosition;
      try {
        await withTimeout(
          gotoNear(agent.bot, Math.floor(mark.x), Math.floor(mark.y), Math.floor(mark.z), 3, 15000),
          20000,
          false,
        );
      } catch (err) {
        log.note({ event: 'walk_home_failed', detail: String(err.message || err) });
      }
    }
    log.note({ event: 'episode_reset', cleared: items.length, position: agent.position() });
    return observationPayload(radius);
  }

  async function runStep(skillId, radius) {
    const skill = library[skillId];
    if (!skill) {
      return { ok: false, error: `no skill with id ${skillId}` };
    }
    const inventoryBefore = agent.inventoryMap();
    const minedBefore = agent.counters.mined;
    const placedBefore = agent.counters.placed;
    const started = Date.now();
    const decision = {
      skill_id: skill.id,
      skill_version: skill.version || 1,
      body: skill.body,
      predict: skill.predict || { kind: 'none' },
      title: skill.title || skill.id,
      reason: 'the gym asked for it',
      candidates: [],
      propensity: null,
    };
    const record = await agent.play(decision, agent.context());
    const inventoryAfter = agent.inventoryMap();
    return {
      ok: true,
      skill_id: skill.id,
      outcome: record.outcome,
      wall_seconds: (Date.now() - started) / 1000,
      inventory_before: inventoryBefore,
      inventory_after: inventoryAfter,
      gained: countGained(inventoryBefore, inventoryAfter),
      mined: agent.counters.mined - minedBefore,
      placed: agent.counters.placed - placedBefore,
      dead: agent.bot ? agent.bot.health <= 0 : false,
      facts: facts(),
      position: agent.position(),
      inventory: inventoryAfter,
    };
  }

  // -- the door ----------------------------------------------------------------

  const server = http.createServer((req, res) => {
    const reply = (payload, status = 200) => {
      const body = JSON.stringify(payload);
      res.writeHead(status, { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(body) });
      res.end(body);
    };
    const read = () =>
      new Promise((resolve) => {
        const chunks = [];
        req.on('data', (chunk) => chunks.push(chunk));
        req.on('end', () => {
          const text = Buffer.concat(chunks).toString('utf8');
          try {
            resolve(text ? JSON.parse(text) : {});
          } catch (err) {
            resolve({});
          }
        });
      });

    const url = new URL(req.url, 'http://127.0.0.1');
    const radius = Number(url.searchParams.get('grid') || args.grid);

    (async () => {
      if (req.method === 'GET' && url.pathname === '/health') {
        return reply({
          ok: true,
          connected: Boolean(agent.bot && agent.bot.entity),
          name: agent.name,
          role: agent.role,
          position: agent.position(),
          library: Object.keys(library).length,
        });
      }
      if (req.method === 'GET' && url.pathname === '/skills') {
        return reply({
          ok: true,
          skills: Object.values(library).map((s) => ({
            id: s.id,
            family: s.family,
            version: s.version || 1,
            role: s.role,
            title: s.title,
            api: s.api || [],
            predict: s.predict || { kind: 'none' },
            status: s.status || 'active',
          })),
        });
      }
      if (req.method === 'GET' && url.pathname === '/observation') {
        if (!agent.bot || !agent.bot.entity) return reply({ ok: false, error: 'the bot is not in the world yet' }, 503);
        return reply(observationPayload(radius));
      }
      if (req.method === 'POST' && url.pathname === '/reset') {
        if (!agent.bot || !agent.bot.entity) return reply({ ok: false, error: 'the bot is not in the world yet' }, 503);
        await read();
        return reply(await resetEpisode(radius));
      }
      if (req.method === 'POST' && url.pathname === '/step') {
        if (!agent.bot || !agent.bot.entity) return reply({ ok: false, error: 'the bot is not in the world yet' }, 503);
        const payload = await read();
        const answer = await runStep(String(payload.skill_id || ''), radius);
        return reply(answer, answer.ok ? 200 : 400);
      }
      return reply({ ok: false, error: 'not found' }, 404);
    })().catch((err) => {
      reply({ ok: false, error: String((err && err.message) || err) }, 500);
    });
  });

  server.listen(args.bridgePort, '127.0.0.1', () => {
    console.log(`  the bridge is open on 127.0.0.1:${args.bridgePort}`);
  });

  const shutdown = () => {
    log.note({ event: 'gym_bot_closed' });
    log.close();
    try {
      agent.bot.quit('the gym is resting');
    } catch (err) {
      /* the bot is already gone */
    }
    setTimeout(() => process.exit(0), 800);
  };
  process.on('SIGINT', shutdown);
  process.on('SIGTERM', shutdown);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
