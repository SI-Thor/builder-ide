'use strict';
// bots/test/council.test.js — the planner, offline.
//
// The council is deterministic: the same world reads propose the same
// projects, in the same order of need. These checks pin that order —
// chest before forest, forest before farm — and the two doors every
// proposal faces: the validator's verdict, and one project of a kind
// at a time.

const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { Board } = require('../src/board');
const { Council, needs, buildProposal } = require('../src/council');
const { GATHERABLE_NAMES, isGatherable } = require('../src/materials');

function tmpBoard() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'council-'));
  return new Board(path.join(dir, 'board.jsonl'), null, () => {});
}

// A world of fixtures: the caller says what stands, the look reports it.
function stubWorld({
  chest = false,
  logs = 20,
  farmland = false,
  spot = { x: 3, y: 71, z: 0 },
  plantSpots = [],
  plot,
} = {}) {
  // A default farm plot: a 5x5 of tillable ground beside water.
  const defaultPlot = plot || {
    x: 8, y: 70, z: 8,
    blocks: Array.from({ length: 25 }, (_, i) => [
      { name: 'farmland', x: 6 + (i % 5), y: 70, z: 6 + Math.floor(i / 5) },
      { name: 'wheat', x: 6 + (i % 5), y: 71, z: 6 + Math.floor(i / 5) },
    ]).flat(),
  };
  return {
    depot: () => ({ x: 0, y: 70, z: 0 }),
    chestAt: () => chest,
    countBlocks: () => logs,
    farmlandNear: () => farmland,
    standableNear: () => spot,
    plantableSpots: () => plantSpots,
    farmPlot: () => defaultPlot,
    pathBlocks: () => [{ name: 'cobblestone', x: 1, y: 70, z: 0 }],
    surfaceAt: () => 70,
  };
}

test('the order of need: chest, then forest, then farm', () => {
  const board = tmpBoard();
  const world = stubWorld({ chest: false, logs: 0, farmland: false, plantSpots: Array.from({ length: 8 }, (_, i) => ({ x: i, y: 70, z: 0 })) });
  const list = needs(board, world);
  assert.deepEqual(list.map((p) => p.kind), ['depot-chest', 'replant', 'farm']);
});

test('a chest standing at the depot retires that need', () => {
  const board = tmpBoard();
  const world = stubWorld({ chest: true, logs: 30, farmland: false });
  const list = needs(board, world);
  assert.deepEqual(list.map((p) => p.kind), ['farm']);
});

test('a forest of eight trunks retires the replant', () => {
  const board = tmpBoard();
  const world = stubWorld({ chest: true, logs: 9, farmland: true });
  assert.deepEqual(needs(board, world), []);
});

test('the council proposes through the validator, one of a kind', async () => {
  const board = tmpBoard();
  const council = new Council(board, stubWorld({ chest: false, logs: 30, farmland: true }), {
    playerBuilds: () => new Map(),
    log: () => {},
  });
  const did = await council.tick({ allowModel: false });
  assert.equal(did.proposed.length, 1);
  const project = board.get(did.proposed[0]);
  assert.equal(project.kind, 'depot-chest');
  assert.equal(project.status, 'ratified');

  // The next tick does not propose a second chest: the need is on the
  // board already.
  const again = await council.tick({ allowModel: false });
  assert.equal(again.proposed.length, 0);
});

test("a person's block inside the site denies it at the council door", async () => {
  const board = tmpBoard();
  const playerBuilds = () => new Map([['4,71,1', { by: 'Casey', name: 'coarse_dirt' }]]);
  const council = new Council(board, stubWorld({ chest: false, logs: 30, farmland: true }), {
    playerBuilds,
    log: () => {},
  });
  const did = await council.tick({ allowModel: false });
  const project = board.get(did.proposed[0]);
  assert.equal(project.status, 'abandoned');
  assert.match(project.verdict.reason, /Casey's/);
});

test("a busy owner's need waits: one project per role", async () => {
  const board = tmpBoard();
  const council = new Council(board, stubWorld({ chest: true, logs: 30, farmland: false }), {
    playerBuilds: () => new Map(),
    log: () => {},
  });
  await council.tick({ allowModel: false }); // the farm goes to the farmer
  // The forest need (also the farmer's) must not stack behind it.
  const world = stubWorld({ chest: true, logs: 0, farmland: false, plantSpots: [{ x: 5, y: 70, z: 5 }] });
  const other = new Council(board, world, { playerBuilds: () => new Map(), log: () => {} });
  const did = await other.tick({ allowModel: false });
  assert.equal(did.proposed.length, 0);
});

test('the shelter comes last, after the chest and the forest', async () => {
  const board = tmpBoard();
  // The chest is done, the forest is done, the farm is done: only the
  // shelter remains.
  for (const kind of ['depot-chest', 'replant', 'farm']) {
    const p = board.propose({ kind, title: kind, site: { x: 0, y: 70, z: 0 }, scope: { blocks: [{ name: 'chest', x: 0, y: 70, z: 0 }] }, owner: 'farmer' });
    board.validated(p.id, { type: 'allow' });
    board.started(p.id);
    board.finish(p.id);
  }
  const council = new Council(board, stubWorld({ chest: true, logs: 30, farmland: true }), {
    playerBuilds: () => new Map(),
    log: () => {},
  });
  const did = await council.tick({ allowModel: false });
  assert.equal(did.proposed.length, 1);
  const project = board.get(did.proposed[0]);
  assert.equal(project.kind, 'shelter');
  // The hut is 23 blocks (a cobble ring two high with a door gap, a
  // plank roof over all nine): well inside the 64-block bound, proved.
  assert.equal(project.scope.blocks.length, 23, `scope was ${project.scope.blocks.length}`);
});

test('every bill names only what the gatherer can carry', () => {
  // The validator's "gatherable" set and the supply duty's list were
  // two lists, and they disagreed: the farm's bill named a
  // `wooden_hoe`, which the validator approved and the supply chain
  // could never deliver, so the farm waited at the site for a hoe that
  // was never coming. One list now (materials.js), and this test is
  // the proof that the council's bills stay inside it.
  const world = stubWorld({
    chest: false,
    logs: 30,
    farmland: false,
    plantSpots: Array.from({ length: 8 }, (_, i) => ({ x: i, y: 70, z: 0 })),
  });
  const kinds = [
    ['depot-chest', {}],
    ['replant', {}],
    ['farm', {}],
    ['path', { to: { x: 10, y: 70, z: 10, title: 'the ridge' } }],
    ['shelter', {}],
  ];
  for (const [kind, extras] of kinds) {
    const proposal = buildProposal(kind, world, extras);
    assert.ok(proposal, `${kind} has no proposal`);
    for (const name of Object.keys(proposal.materials || {})) {
      assert.ok(
        isGatherable(name),
        `the ${kind} bill names ${name}, which the gatherer cannot carry ` +
          `(deliverable: ${GATHERABLE_NAMES.join(', ')})`,
      );
    }
  }
});

test('a project that places nothing is given up on', async () => {
  // The stall-abandon watch only started its clock when a project's
  // placed count *changed*. A project whose first block never came
  // therefore never started the clock and was never abandoned: it sat
  // on the board forever, and its role was busy, so the council could
  // not move on to anything else.
  const board = tmpBoard();
  const council = new Council(board, stubWorld({ chest: false, logs: 30, farmland: true }), {
    playerBuilds: () => new Map(),
    log: () => {},
    stallAbandonMs: 5, // the window, in the test's own time
  });
  const did = await council.tick({ allowModel: false });
  assert.equal(did.proposed.length, 1);
  const id = did.proposed[0];
  board.started(id);

  // The first tick that sees the project running starts its clock.
  await council.tick({ allowModel: false });
  await new Promise((resolve) => setTimeout(resolve, 20));
  const later = await council.tick({ allowModel: false });
  assert.deepEqual(later.abandoned, [id], `the stuck project was not given up on`);
  assert.equal(board.get(id).status, 'abandoned');
});
