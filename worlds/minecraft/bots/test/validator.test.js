'use strict';
// bots/test/validator.test.js — the local rule table, offline.
//
// The interface is builder-ide core/precedent's (store.py, validator.py
// at dac910a): validate(proposal, keys) -> {type, reason,
// matched_precedents, rule_matches}. These checks pin the ladder a
// proposal faces, and the per-edit door the builders place through.

const test = require('node:test');
const assert = require('node:assert');
const { validate, checkEdit, proposalKeys } = require('../src/validator');

const base = {
  kind: 'depot-chest',
  title: 'a chest at the depot',
  site: { x: 3, y: 71, z: 0, r: 4 },
  scope: { blocks: [{ name: 'chest', x: 3, y: 71, z: 0 }] },
  materials: { oak_log: 2 },
  owner: 'builder',
};

test('a small known project with gatherable materials is allowed', () => {
  const verdict = validate(base, proposalKeys(base));
  assert.equal(verdict.type, 'allow');
  assert.ok(verdict.rule_matches.includes('kind:known'));
  assert.ok(verdict.rule_matches.includes('scope:bounded'));
  assert.ok(verdict.matched_precedents.includes('prec-002-depot-ground-pile'));
});

test('a kind with no executor is denied', () => {
  const verdict = validate({ ...base, kind: 'rollercoaster' }, proposalKeys({ ...base, kind: 'rollercoaster' }));
  assert.equal(verdict.type, 'deny');
  assert.match(verdict.reason, /kind:unknown/);
});

test('an unbounded scope is denied', () => {
  const blocks = Array.from({ length: 65 }, (_, i) => ({ name: 'cobblestone', x: i, y: 70, z: 0 }));
  const verdict = validate({ ...base, kind: 'path', scope: { blocks } }, proposalKeys({ ...base, kind: 'path', scope: { blocks } }));
  assert.equal(verdict.type, 'deny');
  assert.match(verdict.reason, /scope:bounded/);
});

test('a site with no coordinates asks a human', () => {
  const verdict = validate({ ...base, site: { x: NaN, y: 71, z: 0 } }, proposalKeys(base));
  assert.equal(verdict.type, 'ask_human');
  assert.match(verdict.reason, /site:known/);
});

test('a site a thousand blocks out is denied', () => {
  const verdict = validate({ ...base, site: { x: 5000, y: 71, z: 0 } }, proposalKeys(base));
  assert.equal(verdict.type, 'deny');
});

test('a material the world cannot gather asks a human', () => {
  const verdict = validate({ ...base, materials: { diamond: 3 } }, proposalKeys({ ...base, materials: { diamond: 3 } }));
  assert.equal(verdict.type, 'ask_human');
  assert.match(verdict.reason, /materials:gatherable/);
});

test('the no-grief rule denies a site over a person block, whatever the keys', () => {
  const playerBuilds = new Map([['5,71,1', { by: 'Casey', name: 'coarse_dirt', at: '2026-11-02T00:00:00Z' }]]);
  const verdict = validate(base, proposalKeys(base), { playerBuilds, buildKeepOut: 8 });
  assert.equal(verdict.type, 'deny');
  assert.match(verdict.reason, /Casey's .* stands inside that site/);
  assert.ok(verdict.rule_matches.includes('nogrief:player-build'));
});

test('an empty scope asks a human (nothing to ratify)', () => {
  const verdict = validate({ ...base, scope: { blocks: [] } }, proposalKeys({ ...base, scope: { blocks: [] } }));
  assert.equal(verdict.type, 'ask_human');
});

// -- the per-edit door -----------------------------------------------------------

const project = {
  id: 'b001',
  scope: {
    blocks: [
      { name: 'cobblestone', x: 1, y: 70, z: 0 },
      { name: 'oak_planks', x: 2, y: 70, z: 0 },
    ],
  },
};
const openGuard = { mayPlace: () => ({ ok: true }) };

test('a planned block, placed as planned, is allowed', () => {
  const verdict = checkEdit(project, 'cobblestone', 1, 70, 0, openGuard);
  assert.deepEqual(verdict, { ok: true });
});

test('an edit outside the scope is build drift, denied by name', () => {
  const verdict = checkEdit(project, 'cobblestone', 9, 70, 9, openGuard);
  assert.equal(verdict.ok, false);
  assert.match(verdict.why, /build drift/);
});

test('the right place with the wrong material is drift too', () => {
  const verdict = checkEdit(project, 'cobblestone', 2, 70, 0, openGuard);
  assert.equal(verdict.ok, false);
  assert.match(verdict.why, /ratified as oak_planks/);
});

test('a person radius denies even a planned block', () => {
  const guard = { mayPlace: () => ({ ok: false, why: "that is Casey's build" }) };
  const verdict = checkEdit(project, 'cobblestone', 1, 70, 0, guard);
  assert.equal(verdict.ok, false);
  assert.match(verdict.why, /Casey's build/);
});
