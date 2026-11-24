'use strict';
// bots/src/worldlook.js — the world, as the council sees it.
//
// The council must not propose a chest on a hillside of air or a farm
// in a quarry, so it reads the world before it proposes. It reads
// through whichever builder is nearest the depot (they all see the
// same world, but chunks load around *players* — a look through a
// builder far from the depot reads nulls, and nulls are "unknown",
// never "empty").
//
// Every look is honest about what it cannot see: a column outside the
// loaded chunks yields null, the needs-check treats null as "not
// found", and a proposal built on nulls does not happen. A council
// that proposed into fog would ratify a scope the builders cannot
// place; this one waits until someone walks there.

const Vec3 = require('vec3').Vec3;

const AIR = (block) =>
  !block || block.name === 'air' || block.name === 'cave_air' || block.name === 'void_air';

class WorldLook {
  /**
   * @param {() => Array} agents the live agents (each with .bot)
   * @param {object|null} guard one agent's guard (for chest checks)
   * @param {() => Map} playerBuilds the no-grief ledger's placed map,
   *   so a site search never plans a block the workface would refuse
   */
  constructor(agents, guard = null, playerBuilds = null) {
    this.agents = agents;
    this.guard = guard;
    this.playerBuilds = playerBuilds || (() => new Map());
    this.keepOut = 8; // BUILD_KEEP_OUT from humanity.js, held here too
  }

  /** Is a point inside a person's build radius? (A plan that includes
   *  such a point plans a block the api will refuse; better not to
   *  plan it.) */
  _nearPlayerBuild(x, y, z) {
    const placed = this.playerBuilds();
    if (!placed || !placed.size) return false;
    const r2 = (this.keepOut + 1) * (this.keepOut + 1);
    for (const key of placed.keys()) {
      const [px, py, pz] = key.split(',').map(Number);
      const dx = px - x, dy = py - y, dz = pz - z;
      if (dx * dx + dy * dy + dz * dz <= r2) return true;
    }
    return false;
  }

  _bot() {
    let best = null;
    let bestDistance = Infinity;
    for (const agent of this.agents()) {
      if (!agent.bot || !agent.bot.entity) continue;
      const spawn = agent.bot.spawnPoint || agent.bot.entity.position;
      const d = agent.bot.entity.position.distanceTo(spawn);
      if (d < bestDistance) {
        best = agent.bot;
        bestDistance = d;
      }
    }
    return best;
  }

  depot() {
    const bot = this._bot();
    if (!bot) return { x: 0, y: 70, z: 0 };
    const spot = bot.spawnPoint || bot.entity.position;
    return { x: Math.floor(spot.x), y: Math.floor(spot.y), z: Math.floor(spot.z) };
  }

  blockAt(x, y, z) {
    const bot = this._bot();
    if (!bot) return null;
    try {
      return bot.blockAt(new Vec3(x, y, z));
    } catch (err) {
      return null;
    }
  }

  /** The y of the top standable block in a column, or null. */
  surfaceAt(x, z) {
    const bot = this._bot();
    if (!bot) return null;
    const top = Math.floor((bot.entity ? bot.entity.position.y : 70) + 12);
    for (let y = top; y >= top - 40; y--) {
      const block = this.blockAt(x, y, z);
      if (!block) continue; // outside the loaded chunks: unknown
      if (AIR(block) || block.boundingBox === 'empty') continue;
      // Any tree's canopy is not the ground: spruce leaves counted as
      // surface made the whole spawn slope read as a y69 plateau
      // (probe, 2026-11-02) and the ramp planner refuse a gully it
      // could not see.
      if (block.name.endsWith('_leaves') || block.name.endsWith('_log')) continue;
      return y;
    }
    return null;
  }

  /** The lowest cell a crew member stands on, or null. The pit the
   *  gatherer cannot walk out of is where the gatherer stands — the
   *  spawn pocket by the depot, rimmed by the old wall (day one:
   *  every restart landed the crew at its floor and the walks out
   *  died at the rim). */
  lowestStand() {
    let lowest = null;
    for (const agent of this.agents()) {
      if (!agent.bot || !agent.bot.entity) continue;
      const p = agent.bot.entity.position;
      if (!lowest || p.y < lowest.y) {
        lowest = { x: Math.floor(p.x), y: Math.floor(p.y), z: Math.floor(p.z) };
      }
    }
    return lowest;
  }

  /** A staircase of steps from (x0,y0,z0) — a standing level, the
   *  trapped agent's own feet, not surfaceAt (the pit's own column can
   *  carry an overhang, and its topmost solid is the roof, not the
   *  floor) — up to the standing level at (x1,z1). Each step is a
   *  cell carved down to the current standing level, so the stand on
   *  it is one block up — terraform, not construction: the old wall
   *  itself becomes the staircase. An empty list means the line
   *  already walks; null means it cannot be planned honestly (ground
   *  unknown, or the rise needs more carving than the caps allow).
   *  Whether the community owes a ramp at all is the board's word — a
   *  done ramp stays on the board and the tick does not re-propose a
   *  kind it already carries. */
  rampSteps(x0, y0, z0, x1, z1, { maxSteps = 10, maxCarve = 6 } = {}) {
    const goal = this.surfaceAt(x1, z1);
    if (goal == null || y0 >= goal) return [];
    const plan = [];
    const walk = (x, z, feet) => {
      // One cell: its natural top T stands at T+1. At or below the
      // current stand it walks; above it, the step's target top is the
      // current stand, so standing on the carved cell is feet+1 — a
      // single block of gain, whatever the wall was made of.
      const top = this.surfaceAt(x, z);
      if (top == null) return null; // unknown ground: no honest scope
      if (top <= feet) return { feet: top + 1, carve: 0 };
      if (top - feet > maxCarve) return null; // a taller face is a different project
      return { feet: feet + 1, carve: top - feet };
    };
    let feet = y0;
    const line = Math.max(Math.abs(x1 - x0), Math.abs(z1 - z0));
    // The line first, then the cells around the goal, where the last
    // of the climb usually lives (the wall stands at the line's end,
    // and the steps that climb it are beside the goal, not on it).
    // Later passes re-walk the cells tallest-first, because a dip on
    // the line can undo a gain and the wall's own cells are the
    // steps: each carved cell gives one block of standing, once.
    const ring = [
      [0, 1], [1, 0], [0, -1], [-1, 0], [1, 1], [1, -1], [-1, 1], [-1, -1],
    ].map(([dx, dz]) => [x1 + dx, z1 + dz]);
    const cells = [];
    for (let s = 1; s < Math.max(1, line); s++) {
      const x = Math.round(x0 + ((x1 - x0) * s) / line);
      const z = Math.round(z0 + ((z1 - z0) * s) / line);
      // The goal's own column is never a step: carved down to a
      // standing level it would be the chest itself, dug out of its
      // terrace (the first live plan had exactly that cell in it,
      // caught only by the validator's deny, b058).
      if (x === x1 && z === z1) continue;
      cells.push([x, z]);
    }
    cells.push(...ring);
    const inPlan = new Set();
    for (let pass = 0; pass < 3 && feet < goal; pass++) {
      const order = pass === 0
        ? cells
        : cells
          .slice()
          .sort(
            (a, b) =>
              (this.surfaceAt(b[0], b[1]) ?? -99) - (this.surfaceAt(a[0], a[1]) ?? -99)
          );
      for (const [x, z] of order) {
        if (feet >= goal) break;
        if (inPlan.has(`${x},${z}`)) continue;
        // A person's build keep-out is refused ground, not unknown
        // ground: the cell is skipped (the plan routes around it), and
        // if what remains cannot climb, the refusal is honest. The
        // first live proposal learned this: TestHumanH's two blocks
        // stand on the gully's east rim, and the validator denied a
        // ramp whose first steps walked through them (b058, 2026-11-02
        // 14:29 UTC).
        if (this._nearPlayerBuild(x, feet, z)) continue;
        const step = walk(x, z, feet);
        if (step === null) {
          if (pass === 0) return null; // unknown ground: no honest scope
          continue;
        }
        if (step.carve > 0) {
          // a step carved into a cell that stood too high: its target
          // top is the current stand, so the next stand is one up
          plan.push({ x, z, top: feet });
          inPlan.add(`${x},${z}`);
          if (plan.length > maxSteps) return null;
        }
        feet = step.feet;
      }
    }
    return feet >= goal ? plan : null;
  }

  /** A standable spot near (x, z): ground with two airs above it. */
  standableNear(x, y, z, radius) {
    for (let r = 0; r <= radius; r++) {
      for (let dx = -r; dx <= r; dx++) {
        for (let dz = -r; dz <= r; dz++) {
          if (Math.max(Math.abs(dx), Math.abs(dz)) !== r) continue;
          const ground = this.surfaceAt(x + dx, z + dz);
          if (ground == null) continue;
          const at = this.blockAt(x + dx, ground + 1, z + dz);
          const above = this.blockAt(x + dx, ground + 2, z + dz);
          if (AIR(at) && AIR(above) && ground >= y - 12) {
            if (this._nearPlayerBuild(x + dx, ground, z + dz)) continue;
            return { x: x + dx, y: ground + 1, z: z + dz };
          }
        }
      }
    }
    return null;
  }

  /** Count blocks by name in a cube the given radius, loaded parts only.
   *
   * Sampled every four blocks: trunks are columns and walls are runs,
   * so a four-block stride sees them; what it must not do is walk
   * half a million columns on the council's every tick. */
  countBlocks(names, x, y, z, radius) {
    const bot = this._bot();
    if (!bot) return 0;
    const set = new Set(names);
    let count = 0;
    for (let dx = -radius; dx <= radius; dx += 4) {
      for (let dz = -radius; dz <= radius; dz += 4) {
        for (let dy = -8; dy <= 24; dy += 4) {
          const block = this.blockAt(x + dx, y + dy, z + dz);
          if (block && set.has(block.name)) count += 1;
        }
      }
    }
    return count;
  }

  /** Is there a chest (not a person's) near the point? */
  /** Is there a crafting table within crafting reach of the point?
   *  The same 16 the craft-time check uses (api.craft's findBlock),
   *  so a bill that counts a bench is a bill for a site that has
   *  none — the bench at the depot serves every proposal near it. */
  benchNear(x, y, z) {
    const bot = this._bot();
    if (!bot) return false;
    const id = bot.registry.blocksByName['crafting_table']
      && bot.registry.blocksByName['crafting_table'].id;
    if (!id) return false;
    // findBlocks measures from the bot, not the point, so the search
    // reaches as far as the point itself plus the bench's 16.
    const from = bot.entity.position;
    const reach = Math.hypot(from.x - x, from.y - y, from.z - z) + 16;
    const spots = bot.findBlocks({ matching: [id], maxDistance: reach, count: 8 });
    return spots.some(
      (s) => Math.hypot(s.x - x, s.y - y, s.z - z) <= 16
    );
  }

  chestAt(x, y, z, radius) {
    const bot = this._bot();
    if (!bot) return false;
    const registry = bot.registry;
    const ids = ['chest', 'trapped_chest']
      .map((n) => registry.blocksByName[n] && registry.blocksByName[n].id)
      .filter(Boolean);
    if (!ids.length) return false;
    const spots = bot.findBlocks({
      matching: ids,
      maxDistance: radius + 16,
      count: 16,
    });
    for (const spot of spots) {
      if (Math.hypot(spot.x - x, spot.z - z) > radius) continue;
      if (this.guard && this.guard.isPlayerChest(spot)) continue;
      return true;
    }
    return false;
  }

  /** Is there farmland near the point? */
  farmlandNear(x, y, z, radius) {
    const bot = this._bot();
    if (!bot) return false;
    const id = bot.registry.blocksByName['farmland'] && bot.registry.blocksByName['farmland'].id;
    if (!id) return false;
    const spots = bot.findBlocks({ matching: [id], maxDistance: radius + 24, count: 8 });
    return spots.some((s) => Math.hypot(s.x - x, s.z - z) <= radius);
  }

  /** Spots that would take a sapling: grass or dirt with air above. */
  plantableSpots(x, y, z, radius, wanted) {
    const out = [];
    for (let r = 2; r <= radius && out.length < wanted; r++) {
      for (let dx = -r; dx <= r && out.length < wanted; dx++) {
        for (let dz = -r; dz <= r && out.length < wanted; dz++) {
          if (Math.max(Math.abs(dx), Math.abs(dz)) !== r) continue;
          const ground = this.surfaceAt(x + dx, z + dz);
          if (ground == null) continue;
          const block = this.blockAt(x + dx, ground, z + dz);
          const at = this.blockAt(x + dx, ground + 1, z + dz);
          if (!block || !['grass_block', 'dirt', 'coarse_dirt'].includes(block.name)) continue;
          if (!AIR(at)) continue;
          if (this._nearPlayerBuild(x + dx, ground, z + dz)) continue;
          out.push({ x: x + dx, y: ground, z: z + dz });
        }
      }
    }
    return out;
  }

  /** A 5x5 farm plot near water if there is one, else on open dirt.
   *  Every candidate centre is tried until one yields a 3x3 of
   *  tillable, unclaimed columns — the depot's water sits beside a
   *  departed visitor's two blocks, and the first centre is not the
   *  only farm in the world. */
  farmPlot(x, y, z, radius) {
    const bot = this._bot();
    if (!bot) return null;
    const centers = [];
    const waterId = bot.registry.blocksByName['water'] && bot.registry.blocksByName['water'].id;
    if (waterId) {
      const spots = bot.findBlocks({ matching: [waterId], maxDistance: radius + 24, count: 16 });
      for (const s of spots) {
        if (Math.hypot(s.x - x, s.z - z) <= radius) centers.push({ x: s.x + 2, z: s.z });
      }
    }
    const open = this.standableNear(x, y, z, radius);
    if (open) centers.push({ x: open.x, z: open.z });
    const farther = this.standableNear(x, y, z, radius + 12);
    if (farther) centers.push({ x: farther.x, z: farther.z });
    // A ring of candidates around the depot. The three centres above
    // are all *near the depot*, and the depot is where a visitor built
    // two blocks on 2026-11-02 — so the ground there is inside the
    // no-grief keep-out and the plot search found nothing, and the
    // community had no farm to plant (the council's need list came
    // back with the farm missing from it, and the board never said
    // why). A farm does not have to be in the depot's own square: it
    // has to be somewhere the crew can reach and the ground is free.
    for (const r of [10, 14, 18, 22, 26, 30, 34, 38]) {
      if (r > radius) break;
      for (const [dx, dz] of [[1, 0], [-1, 0], [0, 1], [0, -1], [1, 1], [-1, -1], [1, -1], [-1, 1]]) {
        centers.push({ x: x + dx * r, z: z + dz * r });
      }
    }

    for (const center of centers) {
      const blocks = [];
      let ok = 0;
      for (let dx = -2; dx <= 2; dx++) {
        for (let dz = -2; dz <= 2; dz++) {
          const ground = this.surfaceAt(center.x + dx, center.z + dz);
          if (ground == null) continue;
          const block = this.blockAt(center.x + dx, ground, center.z + dz);
          if (!block || !['grass_block', 'dirt', 'coarse_dirt'].includes(block.name)) continue;
          if (this._nearPlayerBuild(center.x + dx, ground, center.z + dz)) continue;
          ok += 1;
          blocks.push({ name: 'farmland', x: center.x + dx, y: ground, z: center.z + dz });
          blocks.push({ name: 'wheat', x: center.x + dx, y: ground + 1, z: center.z + dz });
        }
      }
      if (ok >= 9) return { x: center.x, y, z: center.z, blocks };
    }
    return null;
  }

  /** Cobblestone on the surface along the line to (tx, tz), one block
   *  every two, up to max. The y is the surface at plan time; the
   *  builder re-reads the world when it places. */
  pathBlocks(x, y, z, tx, tz, max) {
    const distance = Math.hypot(tx - x, tz - z);
    const steps = Math.min(Math.floor(distance / 2), max);
    const blocks = [];
    for (let i = 1; i <= steps; i++) {
      const px = Math.round(x + ((tx - x) * i) / steps);
      const pz = Math.round(z + ((tz - z) * i) / steps);
      const ground = this.surfaceAt(px, pz);
      if (ground == null) continue;
      const at = this.blockAt(px, ground, pz);
      if (!at) continue;
      if (this._nearPlayerBuild(px, ground, pz)) continue;
      if (['grass_block', 'dirt', 'coarse_dirt', 'sand', 'gravel'].includes(at.name)) {
        // Replace the walk-worn ground itself: the path sits *in* the
        // world, not on a step above it.
        blocks.push({ name: 'cobblestone', x: px, y: ground, z: pz });
      } else if (AIR(at)) {
        blocks.push({ name: 'cobblestone', x: px, y: ground, z: pz });
      }
    }
    return blocks;
  }
}

module.exports = { WorldLook };
