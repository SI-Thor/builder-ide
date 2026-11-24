'use strict';
// bots/test/board.test.js — the project board, offline.
//
// The board is an append-only log replayed into state; the snapshot is
// a projection. These checks pin the fold: propose -> validate ->
// start -> progress -> test -> issue -> fix -> done, the fingerprint,
// the headline a person is told, and the replay across a "restart".

const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { Board, fingerprint } = require('../src/board');

function tmp() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'board-'));
  return {
    log: path.join(dir, 'board.jsonl'),
    snap: path.join(dir, 'board.json'),
    notes: [],
    note(row) {
      this.notes.push(row);
    },
  };
}

function chestProject(board) {
  return board.propose({
    kind: 'depot-chest',
    title: 'a chest at the depot',
    need: 'goods on the ground',
    site: { x: 3, y: 71, z: 0, r: 4 },
    scope: { blocks: [{ name: 'chest', x: 3, y: 71, z: 0 }] },
    materials: { oak_log: 2 },
    owner: 'builder',
  });
}

test('a project walks its life', () => {
  const t = tmp();
  const board = new Board(t.log, t.snap, (row) => t.note(row));
  const p = chestProject(board);
  assert.equal(p.status, 'proposed');
  board.validated(p.id, { type: 'allow', reason: 'allowed', matched_precedents: [], rule_matches: [] });
  assert.equal(board.get(p.id).status, 'ratified');
  board.started(p.id);
  assert.equal(board.get(p.id).status, 'active');
  board.progress(p.id, 1);
  assert.equal(board.get(p.id).placed, 1);
  board.sendToTest(p.id);
  assert.equal(board.get(p.id).status, 'testing');
  board.fileIssue(p.id, '1 of 1 planned blocks missing');
  const withIssue = board.get(p.id);
  assert.equal(withIssue.status, 'active'); // an issue reopens the work
  assert.equal(withIssue.issues.length, 1);
  board.fixIssue(p.id, 1);
  board.sendToTest(p.id);
  board.finish(p.id);
  assert.equal(board.get(p.id).status, 'done');
  assert.ok(board.get(p.id).clean);
});

test('a denied proposal is abandoned, a held one waits', () => {
  const t = tmp();
  const board = new Board(t.log, t.snap, (row) => t.note(row));
  const a = board.propose({ kind: 'farm', title: 'a', site: { x: 0, y: 70, z: 0 }, scope: { blocks: [{ name: 'farmland', x: 0, y: 70, z: 0 }] }, owner: 'farmer' });
  board.validated(a.id, { type: 'deny', reason: 'no', matched_precedents: [], rule_matches: ['kind:known'] });
  assert.equal(board.get(a.id).status, 'abandoned');
  const b = board.propose({ kind: 'shelter', title: 'b', site: { x: 0, y: 70, z: 0 }, scope: { blocks: [{ name: 'cobblestone', x: 0, y: 70, z: 0 }] }, owner: 'builder' });
  board.validated(b.id, { type: 'ask_human', reason: 'which ground?', matched_precedents: [], rule_matches: [] });
  assert.equal(board.get(b.id).status, 'held');
  assert.ok(!board.forOwner('builder'), 'a held project is not served');
});

test('the log replays: a restart forgets nothing', () => {
  const t = tmp();
  const board = new Board(t.log, t.snap, (row) => t.note(row));
  const p = chestProject(board);
  board.validated(p.id, { type: 'allow' });
  board.started(p.id);
  board.progress(p.id, 1);
  const again = new Board(t.log, t.snap, t.note);
  assert.equal(again.get(p.id).status, 'active');
  assert.equal(again.get(p.id).placed, 1);
  assert.equal(again.get(p.id).title, 'a chest at the depot');
});

test('the snapshot carries the counts the watch reads', () => {
  const t = tmp();
  const board = new Board(t.log, t.snap, (row) => t.note(row));
  const p = chestProject(board);
  board.validated(p.id, { type: 'allow' });
  board.started(p.id);
  board.progress(p.id, 1);
  board.fileIssue(p.id, 'one missing');
  const snap = JSON.parse(fs.readFileSync(t.snap, 'utf8'));
  assert.equal(snap.counts.active, 1);
  assert.equal(snap.counts.open_issues, 1);
  assert.equal(snap.counts.blocks_placed, 1);
  assert.ok(snap.fingerprint.startsWith('board/1:'));
});

test('the headline names the work and its share', () => {
  const t = tmp();
  const board = new Board(t.log, t.snap, (row) => t.note(row));
  assert.match(board.headline(), /nothing in hand/);
  const p = board.propose({
    kind: 'path',
    title: 'a path to the farm',
    site: { x: 10, y: 70, z: 0 },
    scope: { blocks: [{ name: 'cobblestone', x: 1, y: 70, z: 0 }, { name: 'cobblestone', x: 2, y: 70, z: 0 }] },
    owner: 'builder',
  });
  board.validated(p.id, { type: 'allow' });
  board.started(p.id);
  board.progress(p.id, 1);
  assert.equal(board.headline(), 'a path to the farm (1/2)');
});

test('the fingerprint moves when the board does', () => {
  const t = tmp();
  const board = new Board(t.log, t.snap, (row) => t.note(row));
  const a = board.propose({ kind: 'farm', title: 'a', site: null, scope: { blocks: [] }, owner: 'farmer' });
  const b = board.propose({ kind: 'farm', title: 'b', site: null, scope: { blocks: [] }, owner: 'farmer' });
  assert.notEqual(fingerprint([a, b]), fingerprint([a]));
});

test('board events reach the world log (the drift detector reads it)', () => {
  const t = tmp();
  const board = new Board(t.log, t.snap, (row) => t.note(row));
  chestProject(board);
  assert.ok(t.notes.some((n) => n.event === 'board' && n.board_event === 'proposed'));
});
