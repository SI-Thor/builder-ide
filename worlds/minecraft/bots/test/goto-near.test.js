'use strict';
// bots/test/goto-near.test.js — a walk that cannot start fails fast, and fails moving.
//
// The playtest of 2026-11-01 found three builders spending the whole
// afternoon playing the same doomed walk: pressed against a cobble
// face (or floating in a flooded cave), the planner finds a path, its
// follower cannot make the first move, mineflayer's physics reports
// the bot off the ground while it presses — so nothing moves, nothing
// errors, and the old gotoNear ground through its full deadline with
// zero displacement, every play, forever.
//
// The stub bot reproduces that wedge: its planner never settles, its
// follower walks into a wall and presses, and only raw controls away
// from the face move it — exactly what probes 16–18 measured on the
// live world. Each test marked OLD fails against the pre-fix code.
//
//   runtime/node/bin/node --test bots/test/goto-near.test.js
// (or: runtime/node/bin/node bots/test/goto-near.test.js)

const { test } = require('node:test');
const assert = require('node:assert');
const { Vec3 } = require('vec3');
const { gotoNear } = require('../src/api');

const SPEED = 4; // blocks per second, walking
const TICK = 50; // ms per stub physics tick

/**
 * A bot whose planner never settles and whose follower walks into the
 * wall and presses. `wallX` is an unclimbable wall spanning every z
 * (null: open ground). Raw controls always move the bot unless the
 * wall blocks the way.
 */
function stubBot(wallX) {
  const controls = {};
  const bot = {
    entity: { position: new Vec3(0, 70, 0) },
    setControlState: (c, v) => { controls[c] = v; },
    pathfinder: {
      stops: 0,
      stop() { this.stops += 1; bot.walking = false; bot.goal = null; },
      goto(goal) {
        bot.goal = goal;
        bot.walking = true;
        return new Promise(() => {}); // the wedge: no settle, no error
      },
    },
  };
  bot.timer = setInterval(() => {
    const p = bot.entity.position;
    let dx = 0;
    let dz = 0;
    if (controls.forward) dx += 1;
    if (controls.back) dx -= 1;
    if (controls.left) dz += 1;
    if (controls.right) dz -= 1;
    if (bot.walking && !dx && !dz && bot.goal) {
      // the follower walks toward the goal and is satisfied in range
      const near = p.distanceTo(bot.goal) <= 2;
      if (!near) {
        dx = Math.sign(bot.goal.x - p.x);
        dz = Math.sign(bot.goal.z - p.z);
      }
    }
    if (!dx && !dz) return;
    const step = (SPEED * TICK) / 1000;
    const nx = p.x + dx * step;
    const nz = p.z + dz * step;
    const crossesWall = wallX !== null && ((p.x < wallX && nx >= wallX) || (p.x > wallX && nx <= wallX));
    if (!crossesWall) p.x = nx;
    p.z = nz;
  }, TICK);
  return bot;
}

/** Run `fn` with a fresh stub, and stop its ticker whatever happens. */
async function withStub(wallX, fn) {
  const bot = stubBot(wallX);
  try {
    return await fn(bot);
  } finally {
    clearInterval(bot.timer);
  }
}

test('a wedged walk fails without grinding its whole budget — OLD: 20 s grinding, zero displacement', async () => {
  // Five nudges since 2026-11-02 (the gully rim's step-stick needs
  // two or three): a fully wedged walk runs its nudges out in ~23 s
  // against a 20 s budget — still bounded, still moving.
  await withStub(5, async (bot) => {
    const start = bot.entity.position.clone();
    const t0 = Date.now();
    await assert.rejects(
      () => gotoNear(bot, 10, 70, 0, 2, 20000),
      /the walk could not start/
    );
    const elapsed = Date.now() - t0;
    const moved = bot.entity.position.distanceTo(start);
    assert.ok(elapsed < 26000, `fail-fast took ${elapsed} ms, wanted under 26 s`);
    assert.ok(moved > 0.5, `the nudges moved ${moved.toFixed(2)} blocks, wanted more`);
  });
});

test('a walk that is making progress is left alone and arrives', async () => {
  await withStub(null, async (bot) => {
    bot.pathfinder.goto = function (goal) {
      bot.goal = goal;
      bot.walking = true;
      return new Promise(() => {}); // the planner is slow; the bot is not
    };
    const t0 = Date.now();
    await gotoNear(bot, 8, 70, 0, 2, 20000); // must not throw
    const elapsed = Date.now() - t0;
    assert.ok(elapsed < 8000, `the walk took ${elapsed} ms`);
    assert.ok(
      bot.entity.position.distanceTo(new Vec3(8, 70, 0)) <= 2.5,
      'the bot is not near the goal'
    );
  });
});

test('a stop-race rejection is retried, not obeyed', async () => {
  await withStub(null, async (bot) => {
    let calls = 0;
    bot.pathfinder.goto = function (goal) {
      bot.goal = goal;
      bot.walking = true;
      calls += 1;
      if (calls === 1) {
        // probe7's artifact: a stop lands as the walk starts, and the
        // planner reports the interruption as a rejection.
        return new Promise((_, reject) =>
          setTimeout(() => reject(new Error('Path was stopped before it could be completed!')), 100)
        );
      }
      return new Promise(() => {}); // then the walk proceeds
    };
    await gotoNear(bot, 8, 70, 0, 2, 20000); // must not throw
    assert.ok(calls >= 2, 'the walk was not retried');
    assert.ok(
      bot.entity.position.distanceTo(new Vec3(8, 70, 0)) <= 2.5,
      'the bot is not near the goal'
    );
  });
});
