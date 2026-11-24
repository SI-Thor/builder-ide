'use strict';
// viewer/src/fallback-blocks.js — the stand-ins for blocks 1.21.4 does not have.
//
// The world runs Minecraft 26.1; the browser's 3D view is drawn with
// 1.21.4's assets (see translate.js for why). Seventy-four blocks exist
// in 26.1 and not in 1.21.4, so each one is drawn as the nearest block
// 1.21.4 does have. The table is explicit and checked at load time: a
// target that 1.21.4 does not have is a mistake, not a silent hole.
//
// Every entry here is a visual stand-in only. The world itself is 26.1 —
// the bots, the skills and the reflex all speak 26.1. Nothing is changed
// in the world; this only changes what the browser draws.

module.exports = {
  // The copper furniture (bars, chains, chests, lanterns, torches and the
  // golem statues) is new in 26.1. The plain copper blocks themselves
  // (copper_block, exposed_copper, waxed_*) already exist in 1.21.4.
  copper_bars: 'iron_bars',
  copper_chain: 'chain',
  copper_chest: 'chest',
  copper_golem_statue: 'stone',
  copper_lantern: 'lantern',
  copper_torch: 'torch',
  copper_wall_torch: 'wall_torch',
  exposed_copper_bars: 'iron_bars',
  exposed_copper_chain: 'chain',
  exposed_copper_chest: 'chest',
  exposed_copper_golem_statue: 'stone',
  exposed_copper_lantern: 'lantern',
  oxidized_copper_bars: 'iron_bars',
  oxidized_copper_chain: 'chain',
  oxidized_copper_chest: 'chest',
  oxidized_copper_golem_statue: 'stone',
  oxidized_copper_lantern: 'lantern',
  weathered_copper_bars: 'iron_bars',
  weathered_copper_chain: 'chain',
  weathered_copper_chest: 'chest',
  weathered_copper_golem_statue: 'stone',
  weathered_copper_lantern: 'lantern',
  waxed_copper_bars: 'iron_bars',
  waxed_copper_chain: 'chain',
  waxed_copper_chest: 'chest',
  waxed_copper_golem_statue: 'stone',
  waxed_copper_lantern: 'lantern',
  waxed_exposed_copper_bars: 'iron_bars',
  waxed_exposed_copper_chain: 'chain',
  waxed_exposed_copper_chest: 'chest',
  waxed_exposed_copper_golem_statue: 'stone',
  waxed_exposed_copper_lantern: 'lantern',
  waxed_oxidized_copper_bars: 'iron_bars',
  waxed_oxidized_copper_chain: 'chain',
  waxed_oxidized_copper_chest: 'chest',
  waxed_oxidized_copper_golem_statue: 'stone',
  waxed_oxidized_copper_lantern: 'lantern',
  waxed_weathered_copper_bars: 'iron_bars',
  waxed_weathered_copper_chain: 'chain',
  waxed_weathered_copper_chest: 'chest',
  waxed_weathered_copper_golem_statue: 'stone',
  waxed_weathered_copper_lantern: 'lantern',

  // The lightning rod gained its oxidation stages in 26.1.
  exposed_lightning_rod: 'lightning_rod',
  oxidized_lightning_rod: 'lightning_rod',
  weathered_lightning_rod: 'lightning_rod',
  waxed_lightning_rod: 'lightning_rod',
  waxed_exposed_lightning_rod: 'lightning_rod',
  waxed_oxidized_lightning_rod: 'lightning_rod',
  waxed_weathered_lightning_rod: 'lightning_rod',

  // The chain itself was renamed: 1.21.4's `chain` is 26.1's `iron_chain`.
  iron_chain: 'chain',

  // The shelves are new; each is drawn as the planks it is made of.
  acacia_shelf: 'acacia_planks',
  bamboo_shelf: 'bamboo_planks',
  birch_shelf: 'birch_planks',
  cherry_shelf: 'cherry_planks',
  crimson_shelf: 'crimson_planks',
  dark_oak_shelf: 'dark_oak_planks',
  jungle_shelf: 'jungle_planks',
  mangrove_shelf: 'mangrove_planks',
  oak_shelf: 'oak_planks',
  pale_oak_shelf: 'pale_oak_planks',
  spruce_shelf: 'spruce_planks',
  warped_shelf: 'warped_planks',

  // The ground cover and flowers of 26.1.
  bush: 'short_grass',
  firefly_bush: 'short_grass',
  leaf_litter: 'short_grass',
  wildflowers: 'short_grass',
  short_dry_grass: 'short_grass',
  tall_dry_grass: 'tall_grass',
  cactus_flower: 'poppy',
  golden_dandelion: 'dandelion',
  potted_golden_dandelion: 'potted_dandelion',

  // The dried ghast is a dry, tall block; the hay bale stands in for it.
  dried_ghast: 'hay_block',

  // The test blocks are debug blocks; they are drawn as air.
  test_block: 'air',
  test_instance_block: 'air',
};
