'use strict';
// bots/test/projects.test.js — the executors' doors, offline.
//
// The executors walk a ratified plan through the api; offline, the api
// is a stub that answers what the test says the world holds. What is
// pinned here: the supply target (what a project still wants), the
// idempotence (a block already standing is not placed again), and the
// drift door (a block outside the ratified scope is denied, not
// placed). The walking itself is live-world work; its pieces are the
// same api calls the skills have always used.

const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { Board } = require('../src/board');
const { supplyTarget, missingBlocks, projectPlace } = require('../src/projects');

function tmpBoard() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'projects-'));
  return new Board(path.join(dir, 'board.jsonl'), null, () => {});
}

test('the supply target names what an active project still wants', () => {
  const board = tmpBoard();
  const a = board.propose({
    kind: 'path', title: 'a path', site: { x: 10, y: 70, z: 0 },
    scope: { blocks: [{ name: 'cobblestone', x: 1, y: 70, z: 0 }] },
    materials: { cobblestone: 4 }, owner: 'builder',
  });
  board.validated(a.id, { type: 'allow' });
  board.started(a.id);
  board.stagedMaterials(a.id, { cobblestone: 3 });

  const target = supplyTarget(board);
  assert.equal(target.project.id, a.id);
  assert.deepEqual(target.wants, [{ name: 'cobblestone', count: 1 }]);

  board.stagedMaterials(a.id, { cobblestone: 4 });
  assert.equal(supplyTarget(board), null);
});

test('a done project wants nothing', () => {
  const board = tmpBoard();
  const a = board.propose({
    kind: 'path', title: 'a path', site: { x: 10, y: 70, z: 0 },
    scope: { blocks: [{ name: 'cobblestone', x: 1, y: 70, z: 0 }] },
    materials: { cobblestone: 4 }, owner: 'builder',
  });
  board.validated(a.id, { type: 'allow' });
  board.started(a.id);
  board.finish(a.id);
  assert.equal(supplyTarget(board), null);
});

test('a block already standing is not in the missing list', () => {
  const project = {
    id: 'b001',
    scope: {
      blocks: [
        { name: 'cobblestone', x: 1, y: 70, z: 0 },
        { name: 'cobblestone', x: 2, y: 70, z: 0 },
      ],
    },
  };
  const agent = {
    api: { block_at: (x, y, z) => (`${x},${y},${z}` === '1,70,0' ? 'cobblestone' : 'air') },
  };
  const missing = missingBlocks(agent, project);
  assert.equal(missing.length, 1);
  assert.equal(missing[0].x, 2);
});

test('a placement outside the ratified scope is denied and named', async () => {
  const board = tmpBoard();
  const project = board.propose({
    kind: 'path', title: 'a path', site: { x: 10, y: 70, z: 0 },
    scope: { blocks: [{ name: 'cobblestone', x: 1, y: 70, z: 0 }] },
    materials: {}, owner: 'builder',
  });
  const notes = [];
  const agent = {
    name: 'Timber',
    guard: { mayPlace: () => ({ ok: true }) },
    log: { note: (row) => notes.push(row) },
    shared: { board },
    api: {
      place: async () => {
        throw new Error('the api was asked to place drift');
      },
    },
  };
  const verdict = await projectPlace(agent, project, 'cobblestone', 9, 70, 9);
  assert.equal(verdict.ok, false);
  assert.match(verdict.detail, /build drift/);
  assert.ok(notes.some((n) => n.event === 'edit_denied'));
});

test('a planned placement goes through, and the board hears it', async () => {
  const board = tmpBoard();
  const project = board.propose({
    kind: 'depot-chest', title: 'a chest', site: { x: 3, y: 71, z: 0 },
    scope: { blocks: [{ name: 'chest', x: 3, y: 71, z: 0 }] },
    materials: { oak_log: 2 }, owner: 'builder',
  });
  const placedAt = [];
  const agent = {
    name: 'Timber',
    guard: { mayPlace: () => ({ ok: true }) },
    log: { note: () => {} },
    shared: { board },
    api: {
      place: async (name, x, y, z) => {
        placedAt.push({ name, x, y, z });
        return { ok: true, detail: `placed ${name}` };
      },
    },
  };
  const verdict = await projectPlace(agent, project, 'chest', 3, 71, 0);
  assert.equal(verdict.ok, true);
  assert.equal(placedAt.length, 1);
  assert.equal(placedAt[0].name, 'chest');
  assert.equal(board.get(project.id).placed, 1); // the last block: progress is written
});
