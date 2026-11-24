'use strict';
// bots/test/no-grief.test.js — the no-grief rules, held to without a
// world.
//
// The ledger's rule is a heuristic (the server never says who placed a
// block), so the test pins down exactly what it does and does not
// claim: a block that appears near a person is theirs from then on; a
// block that appears near nobody is nobody's; a builder's own block is
// not "placed by a person" even when a person stands beside it; the
// keep-out radii hold; an invite opens them; the command table parses
// what PLAY.md promises and nothing else.
//
//   node --test test/no-grief.test.js

const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const { Ledger, parseCommand, buildGuard } = require('../src/humanity');

function blockLike(name, x, y, z, empty = false) {
  return { name, position: { x, y, z }, boundingBox: empty ? 'empty' : 'block' };
}

function airLike(x, y, z) {
  return blockLike('air', x, y, z, true);
}

function tmpLedger() {
  const file = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'aw-grief-')), 'builds.jsonl');
  return new Ledger(file);
}

test('a block that appears near a person is theirs', () => {
  const ledger = tmpLedger();
  const seen = ledger.observe(
    airLike(10, 70, 10),
    blockLike('dirt', 10, 70, 10),
    [{ name: 'Casey', distance: 3 }]
  );
  assert.ok(seen, 'the placement was recorded');
  assert.equal(seen.by, 'Casey');
  assert.equal(ledger.isPlaced(10, 70, 10).by, 'Casey');
});

test('a block that appears near nobody is nobody\u2019s', () => {
  const ledger = tmpLedger();
  const seen = ledger.observe(airLike(1, 2, 3), blockLike('dirt', 1, 2, 3), []);
  assert.equal(seen, null);
  assert.equal(ledger.isPlaced(1, 2, 3), null);
});

test('a builder\u2019s own block is not read as a person\u2019s', () => {
  const ledger = tmpLedger();
  ledger.placedByBot({ x: 5, y: 60, z: 5 });
  const seen = ledger.observe(
    airLike(5, 60, 5),
    blockLike('cobblestone', 5, 60, 5),
    [{ name: 'Casey', distance: 2 }]
  );
  assert.equal(seen, null);
});

test('four builders seeing one change record it once', () => {
  const ledger = tmpLedger();
  const human = [{ name: 'Casey', distance: 2 }];
  const first = ledger.observe(airLike(7, 8, 9), blockLike('oak_planks', 7, 8, 9), human);
  const second = ledger.observe(airLike(7, 8, 9), blockLike('oak_planks', 7, 8, 9), human);
  assert.ok(first);
  assert.equal(second, null, 'the duplicate sighting changes nothing');
});

test('a broken block stops being protected', () => {
  const ledger = tmpLedger();
  ledger.observe(airLike(2, 3, 4), blockLike('dirt', 2, 3, 4), [{ name: 'Casey', distance: 1 }]);
  ledger.observe(blockLike('dirt', 2, 3, 4), airLike(2, 3, 4), []);
  assert.equal(ledger.isPlaced(2, 3, 4), null);
});

test('mayDig refuses the placed block and the radius around it', () => {
  const ledger = tmpLedger();
  ledger.observe(airLike(0, 0, 0), blockLike('dirt', 0, 0, 0), [{ name: 'Casey', distance: 1 }]);
  assert.equal(ledger.mayDig(0, 0, 0).ok, false, 'the block itself');
  assert.equal(ledger.mayDig(3, 0, 0).ok, false, 'three blocks away is inside the radius');
  assert.equal(ledger.mayDig(5, 0, 0).ok, true, 'five blocks away is outside');
});

test('mayPlace holds a wider radius than mayDig, and an invite opens it', () => {
  const ledger = tmpLedger();
  ledger.observe(airLike(0, 0, 0), blockLike('dirt', 0, 0, 0), [{ name: 'Casey', distance: 1 }]);
  assert.equal(ledger.mayPlace('Timber', 0, 0, 0).ok, false, 'on the build');
  assert.equal(ledger.mayPlace('Timber', 6, 0, 0).ok, false, 'six away is inside the build radius');
  assert.equal(ledger.mayPlace('Timber', 9, 0, 0).ok, true, 'nine away is outside');
  ledger.invite('Timber', 'Casey', 1);
  assert.equal(ledger.invited('Timber').player, 'Casey');
  assert.equal(ledger.mayPlace('Timber', 0, 0, 0).ok, true, 'the invite opens the radius');
  assert.equal(ledger.mayPlace('Pebble', 0, 0, 0).ok, false, 'only the invited builder');
});

test('an invite lapses', () => {
  const ledger = tmpLedger();
  ledger.invite('Timber', 'Casey', -1); // already past
  assert.equal(ledger.invited('Timber'), null);
});

test('a chest a person placed is a player chest', () => {
  const ledger = tmpLedger();
  ledger.observe(airLike(1, 1, 1), blockLike('chest', 1, 1, 1), [{ name: 'Casey', distance: 2 }]);
  assert.equal(ledger.isPlayerChest(1, 1, 1), true);
  assert.equal(ledger.isPlayerChest(50, 50, 50), false);
});

test('the ledger survives a restart', () => {
  const file = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'aw-grief-')), 'builds.jsonl');
  const first = new Ledger(file);
  first.observe(airLike(4, 4, 4), blockLike('stone', 4, 4, 4), [{ name: 'Magnus', distance: 2 }]);
  const again = new Ledger(file);
  assert.equal(again.isPlaced(4, 4, 4).by, 'Magnus');
});

test('the guard wires the ledger to the api\u2019s questions', () => {
  const ledger = tmpLedger();
  const guard = buildGuard({
    ledger,
    botName: 'Timber',
    humansNear: () => [{ name: 'Casey', distance: 2 }],
  });
  guard.observe(airLike(8, 8, 8), blockLike('cobblestone', 8, 8, 8));
  assert.equal(guard.mayDig({ x: 8, y: 8, z: 8 }).ok, false);
  assert.equal(guard.isPlayerChest({ x: 8, y: 8, z: 8 }), true, 'any placed block answers the chest question');
});

// --- the command table -------------------------------------------------------

const CASES = [
  ['follow me', 'follow'],
  ['follow', 'follow'],
  ['Follow Me', 'follow'],
  ['stop', 'stop'],
  ['come here', 'come'],
  ['come', 'come'],
  ['help me build', 'help-build'],
  ['help build', 'help-build'],
  ['gather wood', 'gather-wood'],
  ['gather some stone', 'gather-stone'],
  ['what are you doing?', 'what-doing'],
  ['what are you doing', 'what-doing'],
  ["what's he doing", 'what-doing'],
  ['what is it doing', 'what-doing'],
  ['go home', 'go-home'],
  ['help', 'help'],
  ['Pebble, follow me', 'follow'],
  ['pebble: stop', 'stop'],
  ['Timber, help me build', 'help-build'],
];

test('the command table parses what PLAY.md promises', () => {
  for (const [line, command] of CASES) {
    const parsed = parseCommand(line);
    assert.ok(parsed, `"${line}" should parse`);
    assert.equal(parsed.command, command, `"${line}"`);
  }
});

test('free text is not a command', () => {
  for (const line of [
    'hello there',
    'nice wall!',
    'follow the white rabbit',
    'what a day',
    'what are you doing tomorrow',
    'can you gather some iron',
    '',
    'stop it',
    'come on',
  ]) {
    assert.equal(parseCommand(line), null, `"${line}" must not parse`);
  }
});

test('an addressee is carried, and a stranger\u2019s name is ignored by the router\u2019s caller', () => {
  const parsed = parseCommand('Pebble, follow me');
  assert.equal(parsed.addressee, 'Pebble');
  const nobody = parseCommand('Nobody, follow me');
  assert.ok(nobody, 'it parses; the router finds no such builder and lets it fall');
});
