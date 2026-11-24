'use strict';
// bots/src/humanity.js — the world's manners: how a builder behaves
// when a person is in it.
//
// Two things live here, and they are the two halves of the same rule:
//
// * **The commands.** A person may talk to the builders in chat, and a
//   short fixed list of phrases maps to goals ("follow me", "come
//   here") or to a skill asked for by family ("gather wood" is the
//   gatherer's wood skill, chosen through the reflex like any other
//   play). No model is on this path: the mapping is a table, so a
//   command lands in the same tick-budget as any other reflex choice.
//   Free text that matches no phrase is left alone (the mediator may
//   read it one day; it is not on the tick).
// * **The no-grief ledger.** Builders never break what a person placed,
//   never open a person's chest, never attack a player, and stay out of
//   a radius around a person's build unless invited. Nobody can watch
//   every block, so the ledger is the world's best knowledge: a block
//   that appears while a person is close enough to have placed it is
//   **theirs**, from then on. It is a heuristic — the server does not
//   say who placed a block — and it errs the only safe way: towards
//   protecting.
//
// What a person *says* is never written down (the kids' privacy rule).
// The log holds the command word and who answered it, never the free
// text around it.

const fs = require('node:fs');
const path = require('node:path');

// The names the world owns. A player who is not one of these is a
// person. The watcher is the spectator the viewer page joins as, and
// the probes are the world's own diagnostics: none of them is a person,
// and reading them as one would greet a human whenever somebody opened
// the world's window.
const AGENT_NAMES = new Set([
  'Pebble', 'Timber', 'Kite', 'Sprout',
  'Watcher',
  'Probe', 'Probe2', 'Probe3', 'Probe4', 'Probe5', 'Probe6', 'Probe7', 'Probe8',
]);

const isAgent = (name) => AGENT_NAMES.has(String(name || ''));

// The phrases, as one table. Each is matched against the whole chat
// line, case-insensitively, after a leading "Pebble," or "pebble:" is
// taken off (so a person can pick their builder). The `route` says who
// answers: 'all' for stop, 'nearest' for the positional ones, 'role'
// with the role that owns the job.
const COMMANDS = [
  { command: 'stop', match: /^stop$/i, route: 'all' },
  { command: 'follow', match: /^follow( me)?$/i, route: 'nearest' },
  { command: 'come', match: /^come( here)?$/i, route: 'nearest' },
  { command: 'help-build', match: /^help( me)? build(ing)?$/i, route: 'role', role: 'builder' },
  { command: 'gather-wood', match: /^gather( some)? wood$/i, route: 'role', role: 'gatherer' },
  { command: 'gather-stone', match: /^gather( some)? stone$/i, route: 'role', role: 'gatherer' },
  { command: 'what-doing', match: /^what\b.{0,30}\bdoing\??\s*$/i, route: 'nearest' },
  { command: 'go-home', match: /^go home$/i, route: 'nearest' },
  // The community's own door: what the crew is building, and a
  // person's request becoming a project proposal on the board.
  { command: 'what-building', match: /^what\b.{0,30}\b(building|growing|planting)\??\s*$/i, route: 'nearest' },
  { command: 'build-farm', match: /^build( us)?( a)? farm$/i, route: 'nearest' },
  { command: 'plant-trees', match: /^(plant|replant)( some)? trees?$/i, route: 'nearest' },
  { command: 'build-shelter', match: /^build( us)?( a)? (shelter|hut|house)$/i, route: 'nearest' },
  { command: 'build-chest', match: /^build( us)?( a)? chest$/i, route: 'nearest' },
  { command: 'help', match: /^help$/i, route: 'nearest' },
];

/** Pull "Pebble," / "pebble:" off the front, if it is there. */
function splitAddressee(text) {
  const found = String(text || '').match(/^\s*([A-Za-z][A-Za-z0-9_]{1,15})\s*[,:]\s*(.*)$/);
  if (!found) return { addressee: null, rest: String(text || '').trim() };
  return { addressee: found[1], rest: found[2].trim() };
}

/** One chat line to a command, or null. Never throws, never logs. */
function parseCommand(text) {
  const { addressee, rest } = splitAddressee(text);
  if (!rest) return null;
  for (const entry of COMMANDS) {
    if (entry.match.test(rest)) {
      return { command: entry.command, route: entry.route, role: entry.role || null, addressee };
    }
  }
  return null;
}

/** The one-page answer to "help", said aloud by whoever heard it. */
const HELP_LINE =
  "I can: follow me · stop · come here · gather wood · gather stone · help me build · what are you doing? · what are you building? · build a farm · plant trees · build a chest · build a shelter · go home";

// --- the no-grief ledger -----------------------------------------------------

const REACH = 6; // a block that appears this close to a person is theirs
const DIG_KEEP_OUT = 4; // no digging this close to a placed block
const BUILD_KEEP_OUT = 8; // no building this close to a placed block

/**
 * What the world believes a person placed, and who is invited where.
 *
 * Every builder in the process shares one ledger (they are one process,
 * and they all see the same world). Blocks a *builder* placed are
 * remembered too, so a build going up beside a standing person is not
 * mistaken for the person's. The ledger is appended to a file outside
 * the repo, so a restart does not forget whose house is whose.
 */
class Ledger {
  constructor(file) {
    this.file = file;
    this.placed = new Map(); // "x,y,z" -> { name, by, at }
    this.own = new Map(); // "x,y,z" -> at (a builder placed it)
    this.invites = new Map(); // bot -> { player, until }
    if (file) {
      try {
        for (const line of fs.readFileSync(file, 'utf8').split('\n')) {
          if (!line.trim()) continue;
          try {
            const row = JSON.parse(line);
            if (row.kind === 'placed' && row.pos) this.placed.set(row.pos, row);
          } catch (err) {
            // A torn line at the tail is a crash mid-write; skip it.
          }
        }
      } catch (err) {
        // No ledger yet: nothing has ever been placed by a person.
      }
    }
  }

  _append(row) {
    if (!this.file) return;
    try {
      fs.mkdirSync(path.dirname(this.file), { recursive: true });
      fs.appendFileSync(this.file, JSON.stringify(row) + '\n');
    } catch (err) {
      // The ledger on disk is a bonus; the one in memory is the rule.
    }
  }

  /** A block appeared. If a person was close enough, it is theirs. */
  observe(oldBlock, newBlock, humansNear) {
    if (!newBlock || !newBlock.position) return null;
    const key = `${newBlock.position.x},${newBlock.position.y},${newBlock.position.z}`;
    const wasEmpty =
      !oldBlock ||
      !oldBlock.boundingBox ||
      oldBlock.boundingBox === 'empty' ||
      oldBlock.name === 'air' ||
      oldBlock.name === 'cave_air' ||
      oldBlock.name === 'void_air';
    const isEmpty =
      !newBlock.boundingBox || newBlock.boundingBox === 'empty' || newBlock.name === 'air';
    if (isEmpty) {
      this.placed.delete(key);
      this.own.delete(key);
      return null;
    }
    if (!wasEmpty) return null; // a change, not an appearance
    if (this.own.has(key)) return null; // one of ours
    if (this.placed.has(key)) return null; // another builder already saw it
    if (!humansNear || !humansNear.length) return null;
    const by = humansNear.sort(
      (a, b) => a.distance - b.distance
    )[0];
    const row = {
      kind: 'placed',
      pos: key,
      name: newBlock.name,
      by: by.name,
      at: new Date().toISOString(),
    };
    this.placed.set(key, row);
    this._append(row);
    return row;
  }

  /** A builder placed this: remember it, so it is not misread later. */
  placedByBot(position) {
    if (!position) return;
    this.own.set(`${position.x},${position.y},${position.z}`, Date.now());
    // The memory is only needed until the block-update it guards against
    // has long passed; a slow leak is still a leak.
    if (this.own.size > 4096) {
      const cutoff = Date.now() - 30 * 60 * 1000;
      for (const [key, at] of this.own) if (at < cutoff) this.own.delete(key);
    }
  }

  _near(x, y, z, radius) {
    const r2 = radius * radius;
    for (const [key, row] of this.placed) {
      const [px, py, pz] = key.split(',').map(Number);
      const dx = px - x, dy = py - y, dz = pz - z;
      if (dx * dx + dy * dy + dz * dz <= r2) return row;
    }
    return null;
  }

  isPlaced(x, y, z) {
    return this.placed.get(`${Math.floor(x)},${Math.floor(y)},${Math.floor(z)}`) || null;
  }

  /** May this builder dig at a point? */
  mayDig(x, y, z) {
    const itself = this.isPlaced(x, y, z);
    if (itself) {
      return { ok: false, why: `${itself.by} placed that ${itself.name}` };
    }
    const near = this._near(Math.floor(x), Math.floor(y), Math.floor(z), DIG_KEEP_OUT);
    if (near) {
      return { ok: false, why: `${near.by} built close by` };
    }
    return { ok: true };
  }

  /** May this builder place at a point? An invite opens the radius. */
  mayPlace(botName, x, y, z) {
    if (this.invited(botName)) return { ok: true };
    const near = this._near(Math.floor(x), Math.floor(y), Math.floor(z), BUILD_KEEP_OUT);
    if (near) {
      return { ok: false, why: `that is ${near.by}'s build; invite me with 'help me build'` };
    }
    return { ok: true };
  }

  /** Is this chest a person's? (Never open, never empty it.) */
  isPlayerChest(x, y, z) {
    const row = this.isPlaced(x, y, z);
    return Boolean(row);
  }

  /** "help me build": the player opens their build to this bot, for now. */
  invite(botName, player, minutes = 10) {
    this.invites.set(botName, { player, until: Date.now() + minutes * 60 * 1000 });
  }

  invited(botName) {
    const invite = this.invites.get(botName);
    if (!invite) return null;
    if (Date.now() > invite.until) {
      this.invites.delete(botName);
      return null;
    }
    return invite;
  }
}

/**
 * The guard the api is held to. One ledger, one view of the people.
 */
function buildGuard({ ledger, humansNear, botName }) {
  return {
    botName,
    ledger,
    mayDig: (position) => ledger.mayDig(position.x, position.y, position.z),
    mayPlace: (position) => ledger.mayPlace(botName, position.x, position.y, position.z),
    isPlayerChest: (position) => ledger.isPlayerChest(position.x, position.y, position.z),
    /** A block is appearing or changing; watch it for the person. */
    observe: (oldBlock, newBlock) => {
      const position = newBlock && newBlock.position;
      const near = position ? humansNear(position) : [];
      return ledger.observe(oldBlock, newBlock, near);
    },
    /** A builder placed a block: it is not evidence against itself. */
    ownPlacement: (position) => ledger.placedByBot(position),
    humansNear,
  };
}

/**
 * Watch who arrives, and tell the callback their name. Polling, not an
 * event: the join packet and the player list agree eventually, and a
 * poll that diffs the list works whatever the protocol calls it.
 */
function watchArrivals(bot, { isHuman, onArrival, intervalMs = 2000 }) {
  let seen = new Set();
  let timer = null;
  const look = () => {
    if (!bot || !bot.players) return;
    for (const player of Object.values(bot.players)) {
      if (!player || !player.username) continue;
      if (seen.has(player.username)) continue;
      seen.add(player.username);
      // The list starts empty for us, so the first look greets nobody:
      // everyone in it has been there all along.
      if (!look.first) continue;
      if (isHuman(player.username)) onArrival(player.username);
    }
    look.first = true;
  };
  look.first = false;
  look();
  timer = setInterval(look, intervalMs);
  return () => clearInterval(timer);
}

module.exports = {
  AGENT_NAMES,
  isAgent,
  parseCommand,
  HELP_LINE,
  Ledger,
  buildGuard,
  watchArrivals,
  REACH,
  DIG_KEEP_OUT,
  BUILD_KEEP_OUT,
};
