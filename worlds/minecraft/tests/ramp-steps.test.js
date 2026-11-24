'use strict';
// tests/ramp-steps.test.js — the gully ramp's scope builder, on the
// columns the probe read from the live world (probe-column.js,
// 2026-11-02 ~14:20 UTC: the gully floor y61-64 around the depot, the
// old mossy wall 2-4 high along z=-4/-5, the chest terrace at y68).
//
//   node tests/ramp-steps.test.js
//
// Prints one line per case and exits non-zero on the first failure.
// The column map below is those probes, verbatim: [x,z] -> topmost
// solid y (grass skipped, the way surfaceAt reads).
const { WorldLook } = require('../bots/src/worldlook');

// From the probe: surfaces where read. The floating mossy cobble
// (y66 over the gully floor) is what surfaceAt sees — topmost solid.
const GULLY = new Map([
  ['5,6', 66], ['1,0', 63], ['-1,11', 64], ['-2,-5', 68], ['2,-1', 66],
  ['0,-3', 63], ['-1,-4', 66], ['0,-1', 66], ['-3,-1', 64], ['-6,0', 64],
  ['0,-4', 68], ['1,-4', 66], ['-1,-5', 68], ['0,-5', 68], ['-2,-6', 68],
  ['1,-5', 68],
]);

function stubWorld(map, placed) {
  const look = Object.create(WorldLook.prototype);
  look.keepOut = 8; // the constructor's value (the stub skips it)
  look.surfaceAt = (x, z) => (map.has(`${x},${z}`) ? map.get(`${x},${z}`) : null);
  look.blockAt = (x, y, z) => {
    const top = map.get(`${x},${z}`);
    if (top == null) return null;
    return y <= top
      ? { name: 'stone', boundingBox: 'solid' }
      : { name: 'air', boundingBox: 'empty' };
  };
  look.playerBuilds = () => placed || new Map();
  return look;
}

let failed = 0;
function check(name, ok, detail) {
  console.log(`${ok ? 'ok  ' : 'FAIL'} ${name}${detail ? ` — ${detail}` : ''}`);
  if (!ok) failed = 1;
}

// 1. The real gully: Kite stands at (5, y62, 6); the chest sits at
//    (-2, 68, -5). Unknown columns off the line are honestly null —
//    the planner must refuse (null), not invent ground.
const world = stubWorld(GULLY);
const blocks = world.rampSteps(5, 62, 6, -2, -5);
check('the gully refuses unknown ground', blocks === null,
  blocks ? `planned ${blocks.length} blocks over unread ground` : 'null as designed');

// 2. The same walk on a map where every column between is known —
//    a plain at the gully floor (surface 62, so a bot standing at
//    feet 62 walks it: stand = surface + 1) with the probed wall and
//    chest columns standing at the line's end. Every step is a cell
//    carved to the standing level (one block of gain each), the tops
//    ascend, and the count is inside the cap.
const FULL = new Map(GULLY);
for (let x = -12; x <= 6; x++) {
  for (let z = -10; z <= 18; z++) {
    if (FULL.has(`${x},${z}`)) continue;
    // Unknown columns: the terrace stands around the chest (every
    // probed column within a few of it read 66-68), the plain runs
    // everywhere else.
    FULL.set(`${x},${z}`, Math.abs(z + 5) <= 3 && Math.abs(x + 2) <= 2 ? 68 : 62);
  }
}
const full = stubWorld(FULL);
const plan = full.rampSteps(5, 62, 6, -2, -5);
check('a known gully plans steps', Array.isArray(plan) && plan.length >= 1,
  plan ? `${plan.length} steps: ${plan.map((s) => `${s.x},${s.z}->${s.top}`).join(' ')}` : 'null');
if (Array.isArray(plan)) {
  const ascends = plan.every((s, i) => i === 0 || s.top > plan[i - 1].top);
  const capped = plan.length <= 10;
  check('every step gains exactly one standing block', ascends);
  check('the plan is inside the 10-step cap', capped);
}

// 3. Flat, walkable ground: the empty list — no need.
const flat = stubWorld(new Map([['0,0', 62], ['1,0', 62], ['2,0', 62], ['3,0', 62]]));
const none = flat.rampSteps(0, 63, 0, 3, 0);
check('walkable ground plans nothing', Array.isArray(none) && none.length === 0,
  `got ${JSON.stringify(none)}`);

// 4. A sheer wall with no air for footing: honestly unplannable.
const wall = new Map([['0,0', 62], ['1,0', 70], ['2,0', 70], ['3,0', 70]]);
const sheer = stubWorld(wall).rampSteps(0, 63, 0, 3, 0);
check('a sheer wall is honestly unplannable', sheer === null,
  `got ${JSON.stringify(sheer)}`);

// 5. The visitor's rim (TestHumanH's two coarse_dirt, 5,67,2 and
//    4,66,2, from runtime/logs/player-builds.jsonl): no step may be
//    planned inside their keep-out, and the chest's own column is
//    never a step — the first live plan broke both rules and the
//    validator caught the first (b058, 2026-11-02 14:29 UTC).
const VISITOR = new Map([['5,67,2', 'coarse_dirt'], ['4,66,2', 'coarse_dirt']]);
const guarded = stubWorld(FULL, VISITOR);
const around = guarded.rampSteps(5, 62, 6, -2, -5);
check('a plan exists around the visitor keep-out', Array.isArray(around) && around.length >= 1,
  Array.isArray(around) ? `${around.length} steps: ${around.map((s) => `${s.x},${s.z}->${s.top}`).join(' ')}` : 'null');
if (Array.isArray(around)) {
  const nearVisitor = around.filter(
    (s) => Math.hypot(s.x - 5, s.top - 67, s.z - 2) <= 9
      || Math.hypot(s.x - 4, s.top - 66, s.z - 2) <= 9
  );
  check('no step inside the visitor keep-out', nearVisitor.length === 0,
    nearVisitor.map((s) => `${s.x},${s.z}`).join(' '));
  const carvesChest = around.some((s) => s.x === -2 && s.z === -5);
  check("the chest's own column is never a step", !carvesChest);
}

process.exit(failed);
