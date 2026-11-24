'use strict';
// viewer/src/ascii.js — the Syzygy-style ASCII projection.
//
// The design note this follows (`docs/design/emitter-projector.md`) is
// that a view is a projector: it takes the shared state and renders it
// in its own medium. The text world is the medium of the *mind*, and
// the kernel that produces it has two properties the 3D view does not
// need:
//
//   * **integer** — the whole projection is integer arithmetic over a
//     fixed cosine table, so the same state always gives the same
//     characters;
//   * **deterministic** — no clock, no randomness, no floating point
//     creeping in through trigonometry.
//
// Two clients projecting the same state therefore produce identical
// bytes, which is what lets a human and a decision model look at the
// same thing.

const { Vec3 } = require('vec3');

// The cosine and sine of every degree, in thousandths. A table, so the
// arithmetic stays integer: this is the kernel's only trigonometry.
const TABLE = 1000;
const COS = new Int32Array(360);
const SIN = new Int32Array(360);
for (let degree = 0; degree < 360; degree++) {
  const radians = (degree * Math.PI) / 180;
  COS[degree] = Math.round(Math.cos(radians) * TABLE);
  SIN[degree] = Math.round(Math.sin(radians) * TABLE);
}

/** What a block looks like in the text world. */
const GLYPHS = {
  air: ' ',
  cave_air: ' ',
  void_air: ' ',
  stone: '#',
  cobblestone: '#',
  andesite: '#',
  diorite: '#',
  granite: '#',
  deepslate: '#',
  dirt: '.',
  coarse_dirt: '.',
  grass_block: '"',
  podzol: '.',
  sand: ':',
  sandstone: ':',
  gravel: ':',
  water: '~',
  lava: '!',
  oak_log: 'T',
  birch_log: 'T',
  spruce_log: 'T',
  jungle_log: 'T',
  acacia_log: 'T',
  dark_oak_log: 'T',
  oak_leaves: 't',
  birch_leaves: 't',
  spruce_leaves: 't',
  oak_planks: 'H',
  birch_planks: 'H',
  spruce_planks: 'H',
  chest: 'C',
  wheat: 'w',
  tall_grass: ',',
  grass: ',',
  snow: '*',
  ice: '*',
  glass: '-',
  coal_ore: 'o',
  iron_ore: 'o',
  gold_ore: 'o',
  diamond_ore: 'o',
  crafting_table: 'F',
  furnace: 'F',
  torch: 'i',
};

const DEFAULT_GLYPH = '?';

/**
 * Project the world around a bot into text.
 *
 * The kernel marches a ray per cell, in integer steps, and takes the
 * first non-air block it meets. It is a small, readable raycaster: not
 * a renderer, but the same information in a medium a person can read
 * at a glance and a model can read exactly.
 */
function project(bot, options = {}) {
  const width = options.width || 78;
  const height = options.height || 26;
  const maxDistance = options.maxDistance || 48;
  const fov = options.fov || 70; // degrees across the screen
  const eye = options.eyeHeight === undefined ? 2 : options.eyeHeight;
  // The vertical scale: how much the ray climbs or drops per hundred
  // blocks of ground, per row away from the centre. Four gives a
  // vertical field of about 45 degrees, which is roughly what a person
  // sees when they look up and down.
  const verticalScale = options.verticalScale === undefined ? 4 : options.verticalScale;

  const position = bot.entity ? bot.entity.position.floored() : new Vec3(0, 0, 0);
  const originX = position.x;
  const originY = position.y + eye;
  const originZ = position.z;

  // The bot's facing, in whole degrees. Minecraft's yaw 0 looks along
  // +z, and the yaw grows clockwise seen from above.
  const yaw = Math.round(((bot.entity ? bot.entity.yaw : 0) * 180) / Math.PI) % 360;
  const yawIndex = (yaw + 360) % 360;

  const rows = [];
  for (let row = 0; row < height; row++) {
    // Rows above the centre look up, rows below look down. The slope is
    // an integer per hundred steps, so the kernel stays in integers.
    const slope = Math.round(height / 2 - row) * verticalScale;
    let line = '';
    for (let column = 0; column < width; column++) {
      const offset = Math.round(((column - width / 2) * fov) / width);
      const angle = (yawIndex + offset + 360) % 360;
      line += raycast(bot, originX, originY, originZ, angle, slope, maxDistance);
    }
    rows.push(line.replace(/\s+$/, ''));
  }
  return rows.join('\n');
}

/** One cell: march along the ray and take the first block that is there. */
function raycast(bot, originX, originY, originZ, angle, slope, maxDistance) {
  const dx = COS[angle];
  const dz = -SIN[angle];
  for (let step = 1; step <= maxDistance; step++) {
    const x = originX + Math.trunc((dx * step) / TABLE);
    const z = originZ + Math.trunc((dz * step) / TABLE);
    const y = originY + Math.trunc((slope * step) / 100);
    const block = bot.blockAt(new Vec3(x, y, z));
    if (!block) continue;
    if (block.name === 'air' || block.name === 'cave_air' || block.name === 'void_air') continue;
    return GLYPHS[block.name] || DEFAULT_GLYPH;
  }
  return ' ';
}

module.exports = { project, GLYPHS };
