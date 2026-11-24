'use strict';
// bots/src/index.js — the community.
//
// Four builders, one per role, all in the same world. Each tick every
// builder asks the reflex what to do; the reflex batches those questions
// into one call to the decision model.
//
//   node src/index.js                     # the four builders
//   node src/index.js --names Pebble,Timber
//   node src/index.js --tick 3000        # a slower world
//
// The bots connect in **offline mode**: the world is LAN-only and the
// whitelist is the door, so the builders need no accounts.

const path = require('node:path');
const { Agent, ROLES } = require('./agent');
const { Reflex } = require('./reflex');
const { Log } = require('./log');
const { Ledger, buildGuard, isAgent, watchArrivals, REACH } = require('./humanity');

const DEFAULTS = {
  host: process.env.AW_HOST || '192.168.0.78',
  port: Number(process.env.AW_PAPER_PORT || 25565),
  version: process.env.AW_MINECRAFT_VERSION || '26.1',
  reflexHost: process.env.AW_REFLEX_HOST || '127.0.0.1',
  reflexPort: Number(process.env.AW_REFLEX_PORT || 8110),
  logFile: process.env.AW_BOT_LOG || '/home/caseydigennaro/lm-wt/agent-world/runtime/logs/bots.jsonl',
  tickMs: Number(process.env.AW_TICK_MS || 2000),
  // What the world believes a person placed. Outside the repo on
  // purpose: it is the world's memory of whose build is whose, not a
  // document of it.
  ledgerFile:
    process.env.AW_PLAYER_BUILDS ||
    path.join(__dirname, '..', '..', 'runtime', 'logs', 'player-builds.jsonl'),
};

// The community: a name, a role, and what the role is for.
const CREW = [
  { name: 'Pebble', role: 'gatherer' },
  { name: 'Timber', role: 'builder' },
  { name: 'Kite', role: 'scout' },
  { name: 'Sprout', role: 'farmer' },
];

function parseArgs(argv) {
  // Start from the defaults: the world's addresses, the log, the tick.
  const out = Object.assign({}, DEFAULTS);
  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === '--names') out.names = String(argv[++i] || '').split(',');
    else if (argv[i] === '--tick') out.tick = Number(argv[++i] || DEFAULTS.tickMs);
    else if (argv[i] === '--host') out.host = argv[++i];
    else if (argv[i] === '--port') out.port = Number(argv[++i]);
    else if (argv[i] === '--version') out.version = argv[++i];
    else if (argv[i] === '--log') out.logFile = argv[++i];
  }
  return out;
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const log = new Log(args.logFile);
  const reflex = new Reflex({ host: args.reflexHost, port: args.reflexPort });

  // The no-grief ledger: one for the whole community (they are one
  // process, and they all see the same world).
  const ledger = new Ledger(args.ledgerFile);

  let crew = CREW;
  if (args.names && args.names.length) {
    crew = CREW.filter((c) => args.names.includes(c.name));
    if (!crew.length) {
      console.error('no builder matches those names; the community is: ' + CREW.map((c) => c.name).join(', '));
      process.exit(1);
    }
  }

  log.note({ event: 'world_opened', crew: crew.map((c) => ({ name: c.name, role: c.role })) });
  console.log(`the community is opening: ${crew.map((c) => `${c.name} (${c.role})`).join(', ')}`);

  const agents = [];
  let attempt = 0;
  for (const member of crew) {
    // Paper throttles connections from one address (bukkit.yml's
    // connection-throttle, 4 s), and every builder here comes from the
    // same one. So the community walks in rather than all at once.
    if (attempt) await new Promise((r) => setTimeout(r, 6000));
    attempt += 1;
    const agent = new Agent({
      name: member.name,
      role: member.role,
      host: args.host,
      port: args.port,
      version: args.version,
      reflex,
      log,
      tickMs: args.tick,
      offset: attempt - 1,
      guard: buildGuard({
        ledger,
        botName: member.name,
        // The people, as this builder sees them, near a given point.
        // A player's position lives on their entity (the player list
        // carries none of its own) — the same lesson the nearest-routing
        // learned the hard way: read player.position and every
        // observation throws where no one is looking.
        humansNear: (position) => {
          if (!agent.bot || !agent.bot.players || !position) return [];
          const out = [];
          for (const player of Object.values(agent.bot.players)) {
            if (!player || !player.username) continue;
            const entity = player.entity;
            if (!entity || !entity.position) continue;
            if (player.username === member.name || isAgent(player.username)) continue;
            out.push({
              name: player.username,
              distance: entity.position.distanceTo(position),
            });
          }
          return out;
        },
      }),
    });
    try {
      // Paper throttles connections from one address, and the first
      // attempt can land inside the throttle window (a restart of the
      // crew is exactly that). A builder that fails its first join and
      // gives up is a builder the world never sees again — its
      // reconnect loop only arms once it is running — so the join
      // itself is retried.
      for (let attempt = 0; ; attempt++) {
        try {
          await agent.connect();
          break;
        } catch (err) {
          if (attempt >= 2) throw err;
          await new Promise((r) => setTimeout(r, 20000));
        }
      }
      agents.push(agent);
      agent.start();
      console.log(`  ${member.name} joined as ${member.role}: ${ROLES[member.role]}`);
    } catch (err) {
      console.error(`  ${member.name} could not join: ${err.message || err}`);
    }
  }

  // The crew knows itself, so a command heard four times is answered
  // once, by the builder it was for.
  for (const agent of agents) agent.community = agents;

  // -- the community's own work -------------------------------------------------
  //
  // The board (projects with scope, site, materials, owner, status),
  // the validator's word on every proposal, the council that picks
  // what the world needs next (deterministic first; a DeepInfra model
  // may propose, never decide), and the project service that walks a
  // ratified plan. All four live in this process, the one process that
  // sees the world; the board's event log sits beside the no-grief
  // ledger, and its snapshot at runtime/board.json is the one file a
  // returning human's page reads.
  const { Board } = require('./board');
  const { Council, buildProposal } = require('./council');
  const { WorldLook } = require('./worldlook');
  const { ProjectService } = require('./projects');
  const { validate } = require('./validator');

  const runtimeDir = path.join(__dirname, '..', '..', 'runtime');
  const board = new Board(
    process.env.AW_BOARD_LOG || path.join(runtimeDir, 'logs', 'board.jsonl'),
    process.env.AW_BOARD_SNAPSHOT || path.join(runtimeDir, 'board.json'),
    (row) => log.note(row)
  );
  const playerBuilds = () => {
    const guard = agents[0] && agents[0].guard;
    return guard && guard.ledger ? guard.ledger.placed : new Map();
  };
  const worldLook = new WorldLook(() => agents, agents[0] ? agents[0].guard : null, playerBuilds);
  const council = new Council(board, worldLook, {
    playerBuilds,
    log: (row) => log.note(row),
  });
  const projects = new ProjectService({ board, log: (row) => log.note(row) });

  /** A person's request becomes a project proposal through the
   *  validator — the same door the council's proposals face. A deny is
   *  said plainly; an ask on a person's own proposal is answered by
   *  the asking; the project waits on the board for its owner. */
  const proposeFromHuman = (kind, from) => {
    if (board.list().some((p) => p.kind === kind && p.status !== 'abandoned' && p.status !== 'done')) {
      const there = board.list().find((p) => p.kind === kind && p.status !== 'abandoned');
      return `${there ? there.title : kind} is already on the board (${there ? there.status : '?'})`;
    }
    const proposal = buildProposal(kind, worldLook);
    if (!proposal) return `I looked, ${from}, and found no ground here for a ${kind.replace('-', ' ')}`;
    const verdict = validate(proposal, null, {
      playerBuilds: council.playerBuilds(),
    });
    if (verdict.type === 'deny') return `not that one, ${from}: ${verdict.reason}`;
    const project = board.propose(Object.assign({}, proposal, { proposer: from }));
    board.validated(project.id, { ...verdict, type: 'allow' }); // the person asked; the ask is answered
    log.note({ event: 'human_proposed', from, project: project.id, kind });
    return `on the board, ${from}: ${project.title} — the crew will pick it up`;
  };

  // The drift pause file, read by the world itself (the reflex already
  // reads it at its decision seam; a held agent must not route around
  // the hold through the project service either). Read-only, cached
  // briefly, and a missing or malformed file is never a pause.
  const pauseFile = process.env.AW_DRIFT_PAUSE || path.join(runtimeDir, 'drift-pause.json');
  const pauseState = { at: 0, holds: new Map() };
  const pauseFor = (name) => {
    const fs = require('node:fs');
    const now = Date.now();
    if (now - pauseState.at > 5000) {
      pauseState.at = now;
      pauseState.holds = new Map();
      try {
        const doc = JSON.parse(fs.readFileSync(pauseFile, 'utf8'));
        const clock = now / 1000;
        for (const [actor, entry] of Object.entries(doc || {})) {
          if (!entry || typeof entry !== 'object') continue;
          if (entry.until != null && Number(entry.until) < clock) continue;
          pauseState.holds.set(actor, entry);
        }
      } catch (err) {
        // No pause was ever invented from a read error.
      }
    }
    return pauseState.holds.get(name) || pauseState.holds.get('world') || null;
  };

  const shared = { board, world: worldLook, council, projects, proposeFromHuman, pauseFor };
  for (const agent of agents) agent.shared = shared;
  council.start();

  // The greeting: the scout notices arrivals (that is the job), and any
  // builder greets when the scout is not in. Once per person per ten
  // minutes — a greeting on every reconnect is a doorman, not a
  // neighbour. The greeting says what the community is working on and
  // offers a hand in it, because a person who drops in unattended
  // should learn the work in one line.
  const greeted = new Map();
  const stopArrivals = watchArrivals(agents[0].bot, {
    isHuman: (name) => !isAgent(name) && name !== agents[0].name,
    onArrival: (name) => {
      const last = greeted.get(name) || 0;
      if (Date.now() - last < 10 * 60 * 1000) return;
      greeted.set(name, Date.now());
      const greeter = agents.find((a) => a.role === 'scout') || agents[0];
      greeter.say(
        `Welcome, ${name}! We're ${agents.map((a) => a.name).join(', ')} — a crew that keeps building this place. ` +
          `Right now: ${board.headline()}. ` +
          "Want a hand in it? Say 'help me build', or tell me 'build a farm' / 'plant trees'. 'help' has the rest.",
        { force: true }
      );
    },
  });

  if (!agents.length) {
    console.error('nobody joined. Is the world up? (ops/paper.sh status)');
    process.exit(1);
  }

  const report = setInterval(() => {
    const plays = agents.reduce((sum, a) => sum + a.plays, 0);
    const wins = agents.reduce((sum, a) => sum + a.wins, 0);
    const losses = agents.reduce((sum, a) => sum + a.losses, 0);
    const rate = plays ? Math.round((wins / plays) * 100) : 0;
    console.log(
      `  ${new Date().toISOString().slice(11, 19)}  ` +
        `${agents.length} builders  ${plays} plays  ${wins} won  ${losses} lost  (${rate}%)`
    );
  }, 30000);

  const shutdown = () => {
    clearInterval(report);
    stopArrivals();
    council.stop();
    for (const agent of agents) agent.stop();
    log.note({ event: 'world_closed' });
    log.close();
    setTimeout(() => process.exit(0), 1500);
  };
  process.on('SIGINT', shutdown);
  process.on('SIGTERM', shutdown);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
