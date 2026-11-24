'use strict';
// bots/src/api.js — the world's vocabulary, and the sandbox a skill runs in.
//
// A skill is a small JavaScript function. It may only use the words
// below, and it runs in a context that contains the words and nothing
// else.
//
// Three doors, in order of strength:
//
// 1. **The static door** (the Python side, `agent_world_reflex.door`):
//    a skill that names an unknown word, or reaches for `require` or
//    `process`, is refused before it ever enters the library.
// 2. **The parse door**: the body is compiled by Node's own parser.
// 3. **The runtime door** (this file): the skill runs in a `vm` context
//    that has no `require`, no `process`, no `Buffer`, no `console`, no
//    `eval`, and no `new Function` (string code generation is off). The
//    API wrappers are built *inside* the context, so even reaching for
//    their `constructor` lands in the sandbox's realm, not the host's.
//
// The low-level work — walking, pathing, aiming, mining — stays in
// mineflayer's own planners: `mineflayer-pathfinder` plans the walk and
// `bot.dig` does the mining. This file is the thin skin over them.

const vm = require('node:vm');
const { Vec3 } = require('vec3');
const { pathfinder: pathfinderPlugin, Movements, goals } = require('mineflayer-pathfinder');

const TICK_MS = 50; // a Minecraft tick is 1/20 s

/**
 * Find the nearest block of the given names, searching by block id.
 *
 * mineflayer's search has two paths. A function matcher makes it scan
 * the neighbourhood block by block — and that scan has a budget it
 * spends on the canopy around a builder standing in a tree before it
 * ever reaches the ground, so "no stone within 24 blocks" on a stone
 * mountainside (probe7). A list of block ids makes it ask each chunk's
 * own type index instead, which has no budget to spend and finds the
 * same blocks whatever is overhead. So the names are resolved to ids
 * and the level filter — a block the builder cannot reach is not a
 * block it can work on — is applied to the results.
 */
function findByIds(bot, registry, names, maxDistance, feet, anyLevel, minY, maxY, exclude) {
  const ids = [];
  for (const name of names) {
    const block = registry.blocksByName[name];
    if (block) ids.push(block.id);
  }
  const skip = new Set(exclude || []);
  const spots = bot.findBlocks({ matching: ids, maxDistance, count: 96 });
  // The **nearest** candidate comes first. `findBlocks` returns its
  // matches in no particular order, and the order decided which tree
  // the gatherer walked to: on 2026-11-02 it walked to the spruce on
  // the hillside (y=83-86, thirteen blocks up) and refused the walk,
  // while six oak logs stood at the depot's own level — two of them
  // within two blocks of the gatherer's feet.
  const ordered = spots.slice().sort((a, b) => {
    const da = (a.x - feet.x) ** 2 + (a.y - feet.y) ** 2 + (a.z - feet.z) ** 2;
    const db = (b.x - feet.x) ** 2 + (b.y - feet.y) ** 2 + (b.z - feet.z) ** 2;
    return da - db;
  });
  for (const spot of ordered) {
    if (!anyLevel && Math.abs(spot.y - feet.y) > 2) continue;
    if (minY != null && spot.y < minY) continue;
    if (maxY != null && spot.y > maxY) continue;
    if (skip.size && skip.has(`${spot.x},${spot.y},${spot.z}`)) continue;
    const block = bot.blockAt(spot);
    if (block) return block;
  }
  return null;
}

/**
 * The items lying on the ground near the depot — the pile the crew's
 * own gathering leaves there.
 *
 * Dropped items are entities: ``type`` "object", the item's name, and
 * the position where it lies. This asks what is *there* before the
 * caller walks nine points to find out (see ``take_from_depot``).
 */
function groundItemsNear(bot, spot, radius, wanted) {
  const out = [];
  for (const entity of Object.values(bot.entities || {})) {
    if (!entity || !entity.position) continue;
    // A dropped item is an entity whose type is "other" and whose
    // name is just "item" — the KIND it carries lives in metadata
    // this layer does not read (probe-drop-fields.js, 2026-11-02:
    // type "other", name "item", displayName "Item"). Type-based
    // looks were blind to every drop ever made: the pile look
    // declined at once, the ring never walked, and the crew starved
    // beside its own deliveries. The wanted-list cannot be matched
    // here — the caller's inventory decides what a walk picked up.
    if (entity.name !== 'item' && entity.name !== 'Item') continue;
    if (Math.hypot(entity.position.x - spot.x, entity.position.z - spot.z) > radius) continue;
    out.push({ name: 'item', x: entity.position.x, y: entity.position.y, z: entity.position.z });
  }
  return out;
}

/**
 * The faces a block may be placed against, in order of preference: on
 * top of the ground first, a wall beside it next, under a ceiling last.
 */
const FACES = [
  new Vec3(0, 1, 0),
  new Vec3(1, 0, 0),
  new Vec3(-1, 0, 0),
  new Vec3(0, 0, 1),
  new Vec3(0, 0, -1),
  new Vec3(0, -1, 0),
];

/**
 * Teach a bot to walk.
 *
 * mineflayer-pathfinder is a plugin now: `bot.loadPlugin(pathfinder)`
 * gives the bot `bot.pathfinder`, and `goto` takes a goal. The
 * movements let the planner dig through a block on its way, which is
 * what a builder in a quarry needs.
 *
 * The guard, when there is one, reaches into the planner too: the
 * planner's `safeToBreak` is asked about every block it might dig on
 * its way, so the no-grief rule holds on the path as well as at the
 * workface. Without it, a builder walking home would dig a doorway
 * through somebody's house because the door was on the shortest path.
 */
function givePathfinding(bot, guard) {
  const applyGuard = () => {
    try {
      const movements = bot.pathfinder ? bot.pathfinder.movements : null;
      if (!movements) return;
      const plain = movements.safeToBreak.bind(movements);
      movements.safeToBreak = (block) => {
        if (!plain(block)) return false;
        if (!block || !block.position) return true;
        // The road never digs below the community's floor — the
        // workface's own rule (no dig under y=48) held at the skills
        // while the planner tunnelled the crew to bedrock beneath it
        // (the playable round's Pebble, and 2026-11-02's Timber at
        // y38, Sprout at y21, Timber again at y32 — a bot below the
        // floor has no legal dig up and no walk budget to climb, an
        // operator tp for each). A bot ALREADY below the floor keeps
        // its whole dig freedom: the ban is what would trap it there
        // forever, and digging up is the only way home.
        if (
          block.position.y < 48 &&
          bot.entity &&
          bot.entity.position.y >= 48
        ) {
          return false;
        }
        if (!guard) return true;
        return guard.mayDig(block.position).ok;
      };
    } catch (err) {
      // The planner's own rule stands; the api's guard still holds.
    }
  };
  if (bot.pathfinder && typeof bot.pathfinder.goto === 'function') {
    applyGuard();
    return;
  }
  bot.loadPlugin(pathfinderPlugin);
  const movements = new Movements(bot);
  movements.canDigBlocks = true;
  movements.allow1by1towers = false;
  movements.allowParkour = false;
  bot.pathfinder.setMovements(movements);
  applyGuard();
}

/** Cancel a walk, if one is running, and give the cancellation a moment
 * to land. A stop that arrives while the next walk is starting stops
 * that one instead, and a builder whose every walk is stopped before it
 * begins is a builder that stands still forever (probe7: "Path was
 * stopped before it could be completed", two milliseconds in). */
async function stopWalking(bot) {
  try {
    bot.pathfinder.stop();
  } catch (err) {
    // Nothing was running; nothing to stop.
  }
  await new Promise((resolve) => setTimeout(resolve, 150));
}

/**
 * How long a walk may run: the caller's timeout, plus 1.5 s for every
 * block beyond twelve. A near walk keeps the tight deadline it always
 * had; a far walk — the scout's 24-block survey, the gatherer's climb
 * home from a dig — needs the extra room, and the stall watcher below
 * keeps a walk that cannot start from grinding through any of it.
 */
function walkBudget(bot, x, y, z, timeout) {
  const p = bot.entity.position;
  const far = Math.sqrt((x - p.x) ** 2 + (y - p.y) ** 2 + (z - p.z) ** 2);
  return timeout + Math.max(0, far - 12) * 1500;
}

const STALL_MS = 3200; // no net progress for this long → the walk is wedged
const STALL_PROGRESS = 1.0; // blocks of net progress that disprove a stall

/**
 * One attempt: the planner's own goto, under a stall watcher.
 *
 * Resolves 'arrived' when the goal is reached, 'error:…' when the
 * planner itself gives up (NoPath and friends), 'timeout' when the
 * walk's whole budget is spent, and 'stalled' when the bot stops
 * making progress — the signature of a bot pressed against a block it
 * cannot step over: the planner finds a path, its follower cannot make
 * the first move, and the walk would otherwise hang to its deadline
 * having moved nothing (probe17: fifty-eight seconds, zero blocks).
 */
function attemptWalk(bot, x, y, z, distance, deadline) {
  return new Promise((resolve) => {
    let done = false;
    let timer = null;
    let checkpoint = bot.entity.position.clone();
    const arrived = () => bot.entity.position.distanceTo(new Vec3(x, y, z)) <= distance + 0.5;
    const finish = (value) => {
      if (done) return;
      done = true;
      clearInterval(watcher);
      if (timer) clearTimeout(timer);
      resolve(value);
    };
    bot.pathfinder.goto(new goals.GoalNear(x, y, z, distance)).then(
      () => finish('arrived'),
      (err) => finish('error:' + String((err && err.message) || err))
    );
    const rearm = () => {
      if (timer) clearTimeout(timer);
      timer = setTimeout(() => finish('stalled'), STALL_MS);
    };
    timer = setTimeout(() => finish('stalled'), STALL_MS);
    const watcher = setInterval(() => {
      if (arrived()) {
        finish('arrived');
        return;
      }
      // A dig under way is progress. The planner digs through a wall on
      // its way (that is what canDigBlocks is for), and a dig takes
      // seconds in which the feet do not move: the stall watcher read
      // that as wedged, nudged the dig away, and the next attempt began
      // the same dig to be nudged again — a gatherer in the depot gully
      // could not start a single walk (2026-11-02, probe-wedge: standing
      // free on stone, five walks, five "could not start", every path
      // beginning with a wall). The walk's own deadline still bounds it.
      if (bot.targetDigBlock) {
        checkpoint = bot.entity.position.clone();
        rearm();
        return;
      }
      if (bot.entity.position.distanceTo(checkpoint) >= STALL_PROGRESS) {
        checkpoint = bot.entity.position.clone();
        rearm();
      }
      if (Date.now() >= deadline) finish('timeout');
    }, 1200);
  });
}

/**
 * The un-wedge. A bot pressed against a face reports itself off the
 * ground while it presses, so even a jump will not fire (probe18), and
 * every planner retry goes nowhere. Raw controls away from the face do
 * work — a step back opens the pocket — so the bot backs off, sidesteps
 * both ways, and lets the next attempt plan from a clean standstill.
 */
async function nudge(bot) {
  await stopWalking(bot);
  for (const control of ['back', 'left', 'right']) {
    bot.setControlState(control, true);
    await new Promise((resolve) => setTimeout(resolve, 400));
    bot.setControlState(control, false);
  }
  // A step-up: half the wedges are a one-block lip the sidesteps never
  // climb, and a jump plus a stride opens them.
  bot.setControlState('jump', true);
  bot.setControlState('forward', true);
  await new Promise((resolve) => setTimeout(resolve, 600));
  bot.setControlState('forward', false);
  bot.setControlState('jump', false);
  await new Promise((resolve) => setTimeout(resolve, 250));
}

/**
 * Walk to within `distance` blocks of a point.
 *
 * The deadline matters: the planner retries an unreachable goal for as
 * long as it likes, and a builder that waits forever on a log it can
 * never reach is a builder that has stopped working. So every walk has
 * a clock (scaled to how far the walk is), and a walk that runs out of
 * time is a failure the skill can hear about.
 *
 * A walk that *cannot start* — a bot wedged against a cobble line, or
 * standing in water its planner will not swim out of — is worse than a
 * slow one: it burns the whole deadline, records an honest but useless
 * loss, and starts the same doomed walk again next tick. That is how
 * three builders spent an afternoon playing the same walk 20 seconds at
 * a time and never moving a block. So the walk watches its own
 * progress: when it stops for three seconds, the bot backs off (one
 * nudge), tries again, and after two nudges gives up early — the
 * skill hears a failure it can act on, and the walk that could not
 * start has cost seconds, not the whole clock.
 */
/** A stop that lands while a walk is starting kills that walk, and the
 * planner reports it as a rejection rather than a verdict (probe7's
 * "Path was stopped before it could be completed", two milliseconds
 * in). It is an interruption, not an answer: retry it like a stall. */
const STOP_RACE = /stopped before it could be completed|path was stopped/i;

async function gotoNear(bot, x, y, z, distance = 2, timeout = 20000) {
  const deadline = Date.now() + walkBudget(bot, x, y, z, timeout);
  const within = () => bot.entity.position.distanceTo(new Vec3(x, y, z)) <= distance + 0.5;
  let reason = null;
  let nudges = 0;
  try {
    while (Date.now() < deadline) {
      if (within()) return;
      let outcome = await attemptWalk(bot, x, y, z, distance, deadline);
      if (outcome === 'arrived') return;
      if (outcome.startsWith('error:')) {
        const message = outcome.slice(6);
        if (!STOP_RACE.test(message)) throw new Error(message);
        outcome = 'stalled';
      }
      // A stall buys one nudge. A stall is not always a wedge: on the
      // depot gully's rim the follower reports moving and mines nothing
      // while the feet do not advance a block — a step-up it cannot
      // time — and the nudge's back-off-and-jump is what realigns it
      // (probe-follow, 2026-11-02: stuck twice at the same 1-up step,
      // freed on the second nudge, arrived in 13.2 s). Three stalls
      // were not enough for the crew on that same ground, so a walk
      // now carries five nudges; the whole budget still ends it.
      if (outcome === 'timeout') {
        reason = 'the walk took too long';
        break;
      }
      if (++nudges > 5) {
        reason = 'the walk could not start';
        break;
      }
      await nudge(bot);
    }
  } finally {
    if (!within()) await stopWalking(bot);
  }
  throw new Error(reason || 'the walk could not start');
}

/** What a tree is made of: the spawn column may be inside one. */
const CANOPY = new Set([
  'oak_leaves', 'birch_leaves', 'spruce_leaves', 'jungle_leaves',
  'acacia_leaves', 'dark_oak_leaves', 'cherry_leaves', 'azalea_leaves',
  'flowering_azalea_leaves', 'mangrove_leaves', 'pale_oak_leaves',
]);

/**
 * Where the community's depot is.
 *
 * The world spawn: every builder appears there and every builder can
 * find it, without anyone telling them where it is. The spawn point
 * itself can be up in a tree's canopy (the spawn packet names a column,
 * not a floor), so the depot is the first solid ground in that column
 * from the top down that is not part of a tree — leaves and trunks are
 * skipped, so the depot is where a builder can stand, whatever grows
 * above it.
 */
function depotSpot(bot) {
  const spot = bot.spawnPoint || bot.entity.position;
  const x = Math.floor(spot.x);
  const z = Math.floor(spot.z);
  const start = Math.floor(spot.y);
  const air = (block) =>
    !block || block.name === 'air' || block.name === 'cave_air' || block.name === 'void_air';
  const tree = (block) => CANOPY.has(block.name) || block.name.endsWith('_log');
  for (let y = start + 8; y >= start - 24; y--) {
    const block = bot.blockAt(new Vec3(x, y, z));
    if (!block) continue;
    // Grass, ferns and snow are not a floor: a goal standing on them
    // can never be reached, and a builder that walks to an unreachable
    // goal walks to wherever it gave up instead (probe7). Only a block
    // with a bounding box is ground.
    if (block.boundingBox === 'empty') continue;
    if (air(block) || tree(block)) continue;
    return { x, y: y + 1, z };
  }
  return { x, y: start, z };
}

/** The vocabulary: the words a skill may use, and what they do.
 *
 * The guard is the no-grief rule (see humanity.js). It is optional so
 * the tests and the probes can run without a person in the world; the
 * builders never run without one.
 */
const OPEN_GUARD = {
  mayDig: () => ({ ok: true }),
  mayPlace: () => ({ ok: true }),
  isPlayerChest: () => false,
  ownPlacement: () => {},
};

function buildApi(bot, counters, guard = OPEN_GUARD) {
  const registry = bot.registry;
  // The depot: the chest the community shares. The gatherer fills it,
  // the builder empties it. It is why four builders are a community and
  // not four strangers.
  let openChest = null;

  const blockAt = (x, y, z) => {
    const block = bot.blockAt(new Vec3(Math.floor(x), Math.floor(y), Math.floor(z)));
    return block || null;
  };

  const api = {
    // --- what the bot can see ------------------------------------------------
    position: () => {
      const p = bot.entity.position;
      return { x: Math.floor(p.x), y: Math.floor(p.y), z: Math.floor(p.z) };
    },
    health: () => bot.health,
    food: () => bot.food,
    time_of_day: () => Math.round((bot.time.timeOfDay / 24000) * 1000) / 1000,
    light: () => {
      // An estimate, not a query: if there is a solid block overhead the
      // bot is in the dark, otherwise it can see the sky.
      const p = bot.entity.position.floored();
      const above = bot.blockAt(p.offset(0, 2, 0));
      return above && above.name !== 'air' ? 0 : 15;
    },
    inventory: () =>
      bot.inventory.items().map((item) => ({ name: item.name, count: item.count })),
    inventory_count: (name) => {
      const item = bot.inventory.items().find((i) => i.name === name);
      return item ? item.count : 0;
    },
    block_at: (x, y, z) => {
      const block = blockAt(x, y, z);
      return block ? block.name : null;
    },
    find_block: (query) => {
      const q = query || {};
      const names = q.names || (q.name ? [q.name] : null);
      const maxDistance = q.max_distance || q.maxDistance || 32;
      const feet = bot.entity.position.floored();
      // A block the builder cannot stand next to is not a block it can
      // work on: a log five blocks up a tree is found, aimed at and
      // then not mined, because the server refuses a dig that is out of
      // reach. So the candidates are the ones at the builder's own
      // level, unless the query asks for any level.
      const anyLevel = q.any_level === true;
      // A search may bound itself in the world: min_y / max_y. The
      // depth-minding searches use it (surface stone, not bedrock).
      const minY = Number.isFinite(q.min_y) ? q.min_y : null;
      const maxY = Number.isFinite(q.max_y) ? q.max_y : null;
      // `exclude` (["x,y,z", ...]): candidates a caller already tried
      // and was refused — the guard's keep-out can own the nearest
      // tree, and the honest gather moves on to the next one instead
      // of mining the same refusal forever.
      const exclude = Array.isArray(q.exclude) ? q.exclude : null;
      let found = null;
      if (names) {
        found = findByIds(bot, registry, names, maxDistance, feet, anyLevel, minY, maxY, exclude);
      } else {
        // Any block at all: the name-less search keeps the function
        // matcher, which scans the neighbourhood itself.
        found = bot.findBlock({
          matching: (block) => {
            if (!block || !block.position) return false;
            if (block.name === 'air') return false;
            if (minY != null && block.position.y < minY) return false;
            if (maxY != null && block.position.y > maxY) return false;
            if (anyLevel) return true;
            return Math.abs(block.position.y - feet.y) <= 2;
          },
          maxDistance,
        });
      }
      if (!found) return null;
      return {
        x: found.position.x,
        y: found.position.y,
        z: found.position.z,
        name: found.name,
      };
    },
    depot: () => {
      // The depot is the world spawn: the one place every builder can
      // find without being told where it is, and the one place they all
      // appear. It needs nothing built first — it is already there.
      const spot = depotSpot(bot);
      return { x: spot.x, y: spot.y, z: spot.z };
    },
    leave_at_depot: async (name, count) => {
      const spot = depotSpot(bot);
      // The chest first. A pile on the ground is a race: whichever
      // builder (or watcher) walks the depot sweeps it up, and goods
      // placed there were "delivered" and gone in the same minute (the
      // playtest's own finding). A chest the world placed — never a
      // person's — holds the delivery for whoever it was for.
      const chest = findByIds(bot, registry, ['chest'], 12, spot, true);
      if (chest && !guard.isPlayerChest(chest.position)) {
        try {
          await gotoNear(bot, chest.position.x, chest.position.y, chest.position.z, 1);
          if (openChest) {
            openChest.close();
            openChest = null;
          }
          // Bare-handed before the window (a use with a held block is
          // a place, not an open — probe-chest.js timed out holding
          // its own dirt, 2026-11-02).
          try {
            await bot.unequip('hand');
          } catch (err) {
            // Nothing was held.
          }
          const container = await bot.openContainer(chest);
          await new Promise((resolve) => setTimeout(resolve, 400));
          let put = 0;
          const items = name
            ? bot.inventory.items().filter((i) => i.name === name)
            : bot.inventory.items();
          for (const item of items) {
            const wanted = name ? Math.min(Number(count) || item.count, item.count) : item.count;
            try {
              await container.deposit(item.type, null, wanted);
              put += 1;
            } catch (err) {
              // The chest can be full; the rest go back to the pile way.
            }
          }
          try {
            container.close();
          } catch (err) {
            // Already closed.
          }
          if (put) {
            await gotoNear(bot, spot.x, spot.y, spot.z + 3, 1, 5000).catch(() => {});
            return { ok: true, detail: `left ${put} stack(s) in the depot chest` };
          }
        } catch (err) {
          // The chest would not open: the pile way below still works.
        }
      }
      try {
        await gotoNear(bot, spot.x, spot.y, spot.z, 0);
      } catch (err) {
        // Walk as close as the planner allows and carry on: the item
        // lands at the bot's feet either way.
      }
      await new Promise((resolve) => setTimeout(resolve, 300));
      // Toss looking up: a drop thrown forward lands two blocks from
      // the depot and rolls, and the taker's small ring may miss it.
      await bot.lookAt(bot.entity.position.offset(0, 6, 0), true);
      if (name === undefined || name === null) {
        // No name, no argument: leave everything, in one standing —
        // walking away between items walks back over the pile, and a
        // bot that picks up what it just left is how the depot stayed
        // empty while everyone kept delivering to it.
        for (const item of bot.inventory.items()) {
          try {
            await bot.toss(item.type, null, item.count);
          } catch (err) {
            // One item that will not leave stays in the bag; the rest go.
          }
        }
      } else {
        const item = registry.itemsByName[name];
        if (!item) return { ok: false, detail: `there is no item called ${name}` };
        const have = bot.inventory.count(name, null);
        if (!have) return { ok: false, detail: `the bot has no ${name} to leave` };
        const wanted = Math.min(Number(count) || have, have);
        await bot.toss(item, null, wanted);
      }
      // Step aside, south, and stop: standing on the pile (or walking
      // back over it) takes it straight back into the bag.
      try {
        await gotoNear(bot, spot.x, spot.y, spot.z + 3, 1, 5000);
      } catch (err) {
        // The pile keeps whatever distance it can get.
      }
      return { ok: true, detail: 'left it at the depot' };
    },
    take_from_depot: async (nameOrNames) => {
      const wanted = (
        Array.isArray(nameOrNames) ? nameOrNames : [nameOrNames]
      ).filter((n) => typeof n === 'string' && n);
      if (!wanted.length) return { ok: false, detail: 'nothing was asked for' };
      const spot = depotSpot(bot);
      const before = new Map(wanted.map((n) => [n, bot.inventory.count(n, null)]));
      // The chest first, the same chest leave_at_depot fills: a
      // delivery that went into the chest is taken from the chest, not
      // hunted on the ground where another builder may already carry it
      // away.
      const chest = findByIds(bot, registry, ['chest'], 12, spot, true);
      if (chest && !guard.isPlayerChest(chest.position)) {
        try {
          await gotoNear(bot, chest.position.x, chest.position.y, chest.position.z, 1);
          if (openChest) {
            openChest.close();
            openChest = null;
          }
          // Bare-handed before the window (a use with a held block is
          // a place, not an open — probe-chest.js timed out holding
          // its own dirt, 2026-11-02).
          try {
            await bot.unequip('hand');
          } catch (err) {
            // Nothing was held.
          }
          const container = await bot.openContainer(chest);
          await new Promise((resolve) => setTimeout(resolve, 400));
          const held = container.containerItems();
          let taken = null;
          for (const name of wanted) {
            const there = held.filter((i) => i.name === name);
            if (!there.length) continue;
            const count = there.reduce((s, i) => s + i.count, 0);
            try {
              await container.withdraw(there[0].type, null, count);
              taken = { ok: true, name, count, detail: `took ${count} ${name} from the depot chest` };
              break;
            } catch (err) {
              // This one would not leave the chest; the next name may.
            }
          }
          try {
            container.close();
          } catch (err) {
            // Already closed.
          }
          if (taken) return taken;
        } catch (err) {
          // No chest, or it would not open: the ground way below.
        }
      }
      // The pile on the ground: the items lying near the depot, which
      // the crew's own gathering leaves there. The walk below is
      // expensive — nine points around the depot, each one a walk that
      // may fail — and it used to be paid on every call, whether or
      // not there was anything to pick up. That made a supply run take
      // 68 to 164 seconds, and a long step is a long silence: the drift
      // detector read the gatherer's work as a stall and held the very
      // bot the community was waiting on (2026-11-02, 09:11–09:14 UTC).
      //
      // So: look before walking. If nothing of what was asked for lies
      // on the ground near the depot, say so at once.
      const pile = groundItemsNear(bot, spot, 8, wanted);
      if (!pile.length) {
        return { ok: false, detail: `the depot has no ${wanted.join(', ')}` };
      }
      // One ring around the depot, walked once: the pickup has no filter,
      // so a single pass collects the whole pile whatever it is, and the
      // first wanted item that appears ends the walk. (Asking once per
      // item made a builder pace the depot for minutes while the
      // gatherers swept the pile back up behind it.) The points that
      // hold something come first; the rest of the ring is walked only
      // if the pile is still there.
      const ring = [
        [0, 0], [2, 0], [-2, 0], [0, 2], [0, -2],
        [2, 2], [-2, -2], [2, -2], [-2, 2],
      ];
      const points = ring
        .map(([dx, dz]) => ({
          dx,
          dz,
          near: pile.some(
            (item) =>
              Math.abs(item.x - (spot.x + dx)) <= 2 &&
              Math.abs(item.z - (spot.z + dz)) <= 2
          ),
        }))
        .sort((a, b) => (a.near === b.near ? 0 : a.near ? -1 : 1));
      for (const { dx, dz } of points) {
        try {
          await gotoNear(bot, spot.x + dx, spot.y, spot.z + dz, 1);
        } catch (err) {
          // Some points are out of reach; the next one may not be.
        }
        await new Promise((resolve) => setTimeout(resolve, 400));
        for (const name of wanted) {
          const now = bot.inventory.count(name, null);
          if (now > before.get(name)) {
            return { ok: true, name, count: now, detail: `the bot has ${now} ${name}` };
          }
        }
      }
      return { ok: false, detail: `the depot has no ${wanted.join(', ')}` };
    },
    find_chest: () => {
      // A person's chest is not the community's: it is found, and then
      // left alone. (The depot chest was placed by the world, so it is
      // not in the ledger.)
      const feet = bot.entity.position.floored();
      const found = findByIds(bot, registry, ['chest', 'trapped_chest'], 32, feet, true);
      if (!found) return null;
      if (guard.isPlayerChest(found.position)) {
        return { player_chest: true, x: found.position.x, y: found.position.y, z: found.position.z };
      }
      return { x: found.position.x, y: found.position.y, z: found.position.z };
    },
    nearby_players: () =>
      Object.values(bot.players)
        .filter((p) => p && p.position && p.username !== bot.username)
        .map((p) => ({
          name: p.username,
          distance: Math.round(p.position.distanceTo(bot.entity.position) * 10) / 10,
        })),
    look_at: async (x, y, z) => {
      await bot.lookAt(new Vec3(x, y, z), true);
      return { ok: true };
    },

    // --- what the bot may do -------------------------------------------------
    dig: async (x, y, z) => {
      const block = blockAt(x, y, z);
      if (!block) return { ok: false, detail: 'there is no block there' };
      if (block.name === 'air' || block.name === 'cave_air' || block.name === 'void_air') {
        return { ok: false, detail: 'there is nothing to mine there' };
      }
      // The depth floor. Through the playable round the crew mined
      // itself to bedrock and spent hours there (Pebble, 72 below the
      // depot, docs/playtest-2026-11-02-playable.md) — the nearest stone
      // is down, and a gatherer with no floor under its search digs its
      // own trap. No skill mines below y=48: the quarry rim and the
      // hillsides carry all the stone a path needs. The planner is not
      // bound by this (a walk out of a pit digs upward through blocks
      // above the floor) — this is the workface's rule, not the road's.
      if (block.position.y < 48) {
        return {
          ok: false,
          detail: 'too deep: the community mines no lower than y=48 — look on the hillsides',
        };
      }
      // A person's block is never mined, however good it looks. This is
      // the workface of the no-grief rule: every skill digs through
      // here, so every skill is held to it.
      const verdict = guard.mayDig(block.position);
      if (!verdict.ok) {
        return { ok: false, detail: `not mining that: ${verdict.why}` };
      }
      // Safe-keeping: what cannot regrow from the world never goes
      // underground. A death below costs the whole inventory —
      // inventories do not survive a respawn (Sprout's hoe, in the pit,
      // 2026-11-02) — so the seeds and the hoe are banked at the depot
      // chest before any deep dig, and the work that needs them takes
      // them back out. keepInventory stays untouched: it changes the
      // world for human players too, and that is Casey's call, not the
      // workface's. The banking fails soft — a chest that will not open
      // never stops the dig.
      if (block.position.y < 58) {
        for (const precious of ['wheat_seeds', 'wooden_hoe']) {
          if (bot.inventory.items().some((i) => i.name === precious)) {
            try {
              await api.leave_at_depot(precious);
            } catch (err) {
              // The chest would not open; the dig goes on.
            }
          }
        }
      }
      try {
        await approach(bot, block.position);
        await bot.lookAt(block.position.offset(0.5, 0.5, 0.5), true);
        const bagBefore = bot.inventory.items().reduce((s, i) => s + i.count, 0);
        await bot.dig(block);
        // The dig is a packet, not a promise: the server refuses one
        // that is out of reach, and mineflayer does not notice. So the
        // builder looks at the block afterwards and says so when it is
        // still there. A dig that silently did nothing is how a
        // builder "mines" for hours and carries nothing.
        await new Promise((resolve) => setTimeout(resolve, 400));
        const still = blockAt(
          block.position.x,
          block.position.y,
          block.position.z
        );
        if (still && still.name === block.name) {
          return { ok: false, detail: `the ${block.name} did not break` };
        }
        counters.mined += 1;
        // The block is broken but the item is on the ground: walk onto
        // it so it is actually collected. Otherwise a builder "mined"
        // for hours and never carried anything, and the world would
        // look like it was working while it was not.
        const collected = await collectAt(bot, block.position);
        // The bag is the truth, not the walk: a collection that
        // chased the wrong entity (or none) still "returns true"
        // while the drop lies on the slope — the gatherer mined five
        // logs for an empty bag this way (2026-11-02 20:44Z).
        const bagAfter = bot.inventory.items().reduce((s, i) => s + i.count, 0);
        const gained = bagAfter > bagBefore;
        return {
          ok: true,
          detail: gained
            ? `mined ${block.name} and collected it`
            : `mined ${block.name}, but the drop is still out there`,
        };
      } catch (err) {
        return { ok: false, detail: String((err && err.message) || err) };
      }
    },
    place: async (name, x, y, z) => {
      const item = bot.inventory.items().find((i) => i.name === name);
      if (!item) return { ok: false, detail: `the bot has no ${name}` };
      const position = new Vec3(Math.floor(x), Math.floor(y), Math.floor(z));
      // The build-side of the no-grief rule: a builder builds beside a
      // person's build only when the person invited it.
      const verdict = guard.mayPlace(position);
      if (!verdict.ok) {
        return { ok: false, detail: `not building there: ${verdict.why}` };
      }
      // Step out of the target cell first. The collector stands IN the
      // cell it harvested (range 0 picks the drop up; the builder then
      // fills that same cell with the plan's block) — and the server
      // silently refuses to place a block where a player stands: the
      // placement times out with no answer (b069's wall cell, 2026-11-02
      // 19:16Z, four timeouts on one block). One step aside, then place.
      const feet = bot.entity.position.floored();
      if (
        feet.x === position.x && feet.z === position.z
        && Math.abs(feet.y - position.y) <= 1
      ) {
        await gotoNear(bot, position.x + 1, position.y, position.z, 1, 6000).catch(() => {});
      }
      const target = bot.blockAt(position);
      if (
        target &&
        target.name !== 'air' &&
        target.name !== 'cave_air' &&
        target.name !== 'void_air'
      ) {
        return { ok: false, detail: `there is already a ${target.name} there` };
      }
      // mineflayer does not place a block at a point; it places against
      // a neighbour's face. So the neighbour is found — the ground under
      // the target first, then a wall beside it — and the face is the one
      // that points at the target.
      let reference = null;
      let face = null;
      for (const direction of FACES) {
        const neighbour = bot.blockAt(position.minus(direction));
        if (
          neighbour &&
          neighbour.boundingBox !== 'empty' &&
          neighbour.name !== 'air'
        ) {
          reference = neighbour;
          face = direction;
          break;
        }
      }
      if (!reference) return { ok: false, detail: 'there is nothing to build against there' };
      try {
        await approach(bot, position);
        await bot.equip(item, 'hand');
        await bot.lookAt(position.offset(0.5, 0.5, 0.5), true);
        await bot.placeBlock(reference, face);
        counters.placed += 1;
        guard.ownPlacement(position);
        return { ok: true, detail: `placed ${name}` };
      } catch (err) {
        return { ok: false, detail: String((err && err.message) || err) };
      }
    },
    move_to: async (x, y, z, distance) => {
      try {
        await gotoNear(bot, x, y, z, distance || 2);
        return { ok: true, detail: `walked to ${x}, ${y}, ${z}` };
      } catch (err) {
        return { ok: false, detail: String((err && err.message) || err) };
      }
    },
    /** Walk over the item drops lying near a point, so the server's
     *  pickup hands them to the bot. A delivery is a toss: the item
     *  lands where it skids, two blocks from the owner who waited for
     *  it, and nobody's inventory changes while both stand there
     *  (2026-11-02: b037 staged two logs for eleven minutes before
     *  this existed). Returns how many drops were walked over. */
    pickup_near: async (x, z, radius) => {
      // By TYPE, not name: item entities' `name` is unreliable across
      // mineflayer versions (probe-stock reads them by type), and a
      // name filter matched nothing at b037's site on 2026-11-02
      // while two delivered logs lay in despawn's reach.
      const drops = Object.values(bot.entities).filter((e) => {
        if (!e || !e.position) return false;
        if (e.name !== 'item' && e.name !== 'Item') return false;
        return Math.hypot(e.position.x - x, e.position.z - z) <= (radius || 8);
      });
      let walked = 0;
      for (const d of drops.slice(0, 4)) {
        try {
          await gotoNear(bot, d.position.x, d.position.y, d.position.z, 0, 8000);
        } catch (err) {
          continue; // this one is out of reach; the next may not be
        }
        await new Promise((resolve) => setTimeout(resolve, 900));
        walked += 1;
      }
      return walked;
    },
    equip: async (name) => {
      const item = bot.inventory.items().find((i) => i.name === name);
      if (!item) return { ok: false, detail: `the bot has no ${name}` };
      try {
        await bot.equip(item, 'hand');
        return { ok: true, detail: `holding ${name}` };
      } catch (err) {
        return { ok: false, detail: String((err && err.message) || err) };
      }
    },
    craft: async (name, count) => {
      const wanted = count || 1;
      const item = registry.itemsByName[name];
      if (!item) return { ok: false, detail: `there is no item called ${name}` };
      // A 3x3 recipe needs a bench: chest, hoe — anything three columns
      // wide. mineflayer's recipesFor takes the table block, and
      // without one those recipes are simply invisible ("there is no
      // recipe for chest", 2026-11-02 — the recipe existed; the table
      // did not). The nearest bench within reach is used; a missing
      // bench is said plainly so the caller can place one.
      const tableId = registry.blocksByName['crafting_table']
        ? registry.blocksByName['crafting_table'].id
        : null;
      // The inventory first: what crafts in the 2x2 (planks, sticks —
      // shapeless) needs no window but the bot's own, and the TABLE
      // window does not open on this protocol today (21:25-21:47Z,
      // every table craft timing out on windowOpen while the same
      // planks and sticks crafted in-inventory at 21:03). The table is
      // for the 3x3 recipes that cannot happen without it.
      let recipes = bot.recipesFor(item.id, null, wanted, null);
      let tableBlock = null;
      if (!recipes.length) {
        tableBlock = tableId
          ? bot.findBlock({ matching: tableId, maxDistance: 16 })
          : null;
        if (tableBlock) {
          try {
            await gotoNear(bot, tableBlock.position.x, tableBlock.position.y, tableBlock.position.z, 3, 10000);
          } catch (err) {
            // The walk is best effort; the craft below says its own
            // truth if the window still will not open.
          }
        }
        recipes = bot.recipesFor(item.id, null, wanted, tableBlock || null);
      }
      if (!recipes.length) {
        return {
          ok: false,
          detail: tableBlock
            ? `there is no recipe for ${name} even at the bench`
            : `there is no recipe for ${name} without a crafting table nearby`,
        };
      }
      try {
        await bot.craft(recipes[0], wanted, tableBlock || undefined);
        return { ok: true, detail: `crafted ${wanted} ${name}` };
      } catch (err) {
        return { ok: false, detail: String((err && err.message) || err) };
      }
    },
    attack: async (name) => {
      const target = Object.values(bot.entities).find(
        (e) => e && e.name === name && e.position
      );
      if (!target) return { ok: false, detail: `there is no ${name} to attack` };
      // Never a person. Whatever a skill asks for, a player is not it.
      if (target.type === 'player' || target.username) {
        return { ok: false, detail: 'the builders never attack a player' };
      }
      try {
        await bot.attack(target);
        return { ok: true, detail: `attacked ${name}` };
      } catch (err) {
        return { ok: false, detail: String((err && err.message) || err) };
      }
    },
    wait: async (ticks) => {
      const ms = Math.min(Math.max(Number(ticks) || 0, 0) * TICK_MS, 10000);
      await new Promise((resolve) => setTimeout(resolve, ms));
      return { ok: true };
    },
    open_chest: async () => {
      try {
        if (openChest) {
          openChest.close();
          openChest = null;
        }
        const block = findByIds(
          bot,
          registry,
          ['chest', 'trapped_chest'],
          32,
          bot.entity.position.floored(),
          true
        );
        if (!block) return { ok: false, detail: 'there is no chest nearby' };
        // Never a person's chest: not opened, not emptied, not touched.
        if (guard.isPlayerChest(block.position)) {
          return { ok: false, detail: 'that chest is a player\u2019s; leaving it alone' };
        }
        await approach(bot, block.position);
        openChest = await bot.openContainer(block);
        return { ok: true, detail: 'the chest is open' };
      } catch (err) {
        openChest = null;
        return { ok: false, detail: String((err && err.message) || err) };
      }
    },
    deposit: async (name, count) => {
      if (!openChest) return { ok: false, detail: 'no chest is open' };
      const item = registry.itemsByName[name];
      if (!item) return { ok: false, detail: `there is no item called ${name}` };
      const have = bot.inventory.count(name, null);
      if (!have) return { ok: false, detail: `the bot has no ${name}` };
      const wanted = Math.min(Number(count) || have, have);
      try {
        await openChest.deposit(item, null, wanted);
        return { ok: true, detail: `put ${wanted} ${name} in the chest` };
      } catch (err) {
        return { ok: false, detail: String((err && err.message) || err) };
      }
    },
    withdraw: async (name, count) => {
      if (!openChest) return { ok: false, detail: 'no chest is open' };
      const item = registry.itemsByName[name];
      if (!item) return { ok: false, detail: `there is no item called ${name}` };
      const wanted = Math.min(Number(count) || 1, openChest.containerItems().length
        ? openChest.containerItems().filter((i) => i.name === name).reduce((s, i) => s + i.count, 0)
        : 0);
      if (!wanted) return { ok: false, detail: `the chest has no ${name}` };
      try {
        await openChest.withdraw(item, null, wanted);
        return { ok: true, detail: `took ${wanted} ${name} from the chest` };
      } catch (err) {
        return { ok: false, detail: String((err && err.message) || err) };
      }
    },
  };
  return api;
}

/** Walk next to a block, if the bot is not close enough to work on it. */
async function approach(bot, position) {
  const distance = bot.entity.position.distanceTo(position);
  // Two blocks, not four: the server refuses a dig from further than
  // the builder's reach, and the drop is only picked up from close by.
  if (distance <= 2) return;
  try {
    await gotoNear(bot, position.x, position.y, position.z, 2, 12000);
  } catch (err) {
    // The planner could not get there. Mineflayer's dig is forgiving
    // about the exact distance, so carry on and let it try.
  }
}

/**
 * Walk onto the item that is lying where the block was.
 *
 * The drop appears at the block's own position, so the bot goes there
 * and waits: the server hands the item over when the bot is close
 * enough. Looking for the item entity instead is fragile — the entity
 * names have changed across versions — and the block's position is
 * known exactly.
 *
 * The range is 0, not 1: standing BESIDE the dug cell leaves the bot
 * at the edge of the server's pickup reach (probe-stone-drop.js,
 * 2026-11-02: a cobble entity lay at distance 1.0 for 3+ s while the
 * bot stood still; the run before, the same dig auto-picked-up). The
 * cell is air once the block is broken, so the bot stands inside it
 * and the drop has no escape. "Stone drops nothing" (day two) was
 * this: the digs were at reach, the drops landed on the ground, and
 * range-1 collection missed them — /loot mine and a feet-adjacent dig
 * both yield cobblestone.
 */
async function collectAt(bot, position) {
  for (let attempt = 0; attempt < 2; attempt++) {
    try {
      await gotoNear(bot, position.x, position.y, position.z, 0);
    } catch (err) {
      // The block's own cell cannot be stood beside — a trunk up a
      // face, a log on a ledge — but the DROP is not the block: it
      // falls to the ground below, where the feet can go. Chase the
      // entity, not the cell (2026-11-02: four spruce logs mined on
      // the terrace, "mined spruce_log" without "and collected it",
      // the bag empty, while the drops lay on the walkable ground).
      break;
    }
    // The server hands the item over when the bot is close enough; it
    // takes a moment, so the wait is generous.
    await new Promise((resolve) => setTimeout(resolve, 1200));
  }
  // If the item is still lying about, go to the item itself: the block
  // position is close, but "close" is not "inside the pickup range".
  return collectEntity(bot, position);
}

/** Walk to the dropped item nearest THE DIG (not the nearest anywhere:
 *  a stray seed three blocks over is not this dig's collection, and
 *  chasing it walks away from the log that just fell), so it is
 *  picked up. */
async function collectEntity(bot, near) {
  const drops = Object.values(bot.entities).filter(
    (e) => e && e.position && (e.name === 'item' || e.name === 'Item' || e.name === 'item_stack')
      && (!near || e.position.distanceTo(new Vec3(near.x, near.y, near.z)) < 8)
  );
  if (!drops.length) return false;
  const drop = drops.sort(
    (a, b) =>
      a.position.distanceTo(bot.entity.position) - b.position.distanceTo(bot.entity.position)
  )[0];
  try {
    await gotoNear(bot, drop.position.x, drop.position.y, drop.position.z, 0);
  } catch (err) {
    return false;
  }
  await new Promise((resolve) => setTimeout(resolve, 1500));
  return true;
}

/**
 * Build the sandbox.
 *
 * The context is created empty. The API wrappers are built inside it,
 * so the host object is never a property of anything the skill can reach.
 */
function createSandbox(hostApi) {
  const context = vm.createContext(
    {},
    {
      name: 'agent-world-skill',
      codeGeneration: { strings: false, wasm: false },
    }
  );

  const factory = vm.runInContext(
    `(function (host) {
       const api = {};
       for (const key of Object.keys(host)) {
         api[key] = (...args) => host[key](...args);
       }
       // Put the words on the context's own global, from inside the
       // context: a skill sees them as globals, and there is no way
       // back to the host object that made them.
       Object.assign(globalThis, api);
       return api;
     })`,
    context
  );
  const api = factory(hostApi);

  return {
    context,
    /**
     * Run one skill body. The body is the body of an async function,
     * which is what it is: a skill awaits its actions.
     */
    async run(body) {
      const script = new vm.Script(`(async () => {\n${body}\n})()`, {
        filename: 'skill.js',
      });
      return await script.runInContext(context, { timeout: 30000 });
    },
  };
}

module.exports = { buildApi, createSandbox, givePathfinding, gotoNear, nudge, TICK_MS };
