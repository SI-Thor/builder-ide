'use strict';
// bots/src/materials.js — what the world can supply, in one place.
//
// Two lists used to disagree. The validator's "gatherable" set named
// things the gatherer could not carry (a `wooden_hoe`), and the supply
// duty carried only what its fetch knew how to find (logs, stone,
// saplings, seeds). A bill naming a crafted thing therefore passed the
// validator and then starved at the site: the farm's hoe, 2026-11-02
// ("waiting at the site for wood (the hoe)", forever).
//
// The rule the world works by now: **a bill names the raw the gatherer
// can carry; the owner crafts the rest at the site.** The chest has
// always worked that way — two logs in the bill, eight planks and a
// chest out of them — and the farm and the shelter now follow it.
//
// A 3x3 craft also needs a bench to craft it on, and a bench is a log
// (four planks) the bill must count **when the site has none within
// crafting reach** — the craft-time check (api.craft) will not find a
// table that was never brought. The council adds it per proposal; the
// bench already standing at the depot serves every site near it, so a
// bill that re-counted it would over-charge the world's wood.
//
// The raw cost of a crafted thing is here too, so the council's bills
// are computed from one table rather than guessed twice.

/** The raws the gatherer can carry, and what one of them is worth. */
const GATHERABLE = Object.freeze({
  oak_log: 1, // a log: four planks
  cobblestone: 1, // stone from the surface
  oak_sapling: 1, // from the leaves of a standing tree
  wheat_seeds: 1, // from tall grass
});

/** What a crafted thing costs in raws, for the council's bills. */
const CRAFTED_FROM = Object.freeze({
  wooden_hoe: { oak_log: 1 }, // 2 planks + 2 sticks = a share of a log
  chest: { oak_log: 2 }, // 8 planks = 2 logs
  oak_planks: { oak_log: 1 }, // 4 planks = 1 log
  crafting_table: { oak_log: 1 }, // 4 planks = 1 log
});

const GATHERABLE_NAMES = Object.freeze(Object.keys(GATHERABLE));

/** Can the gatherer carry this by name? */
function isGatherable(name) {
  return Object.prototype.hasOwnProperty.call(GATHERABLE, name);
}

/** The raws a thing costs: itself, if it is raw; its recipe, if it is crafted. */
function rawCost(name) {
  if (isGatherable(name)) return { [name]: 1 };
  return CRAFTED_FROM[name] || null;
}

/** The raw bill for a thing, in raws. */
function rawBill(costs) {
  const bill = {};
  for (const [name, count] of Object.entries(costs || {})) {
    const cost = rawCost(name);
    if (!cost) return null; // a thing the world cannot make at all
    for (const [raw, per] of Object.entries(cost)) {
      bill[raw] = (bill[raw] || 0) + per * count;
    }
  }
  return bill;
}

module.exports = {
  GATHERABLE,
  CRAFTED_FROM,
  GATHERABLE_NAMES,
  isGatherable,
  rawCost,
  rawBill,
};
