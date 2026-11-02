#!/usr/bin/env node
// The Minecraft bridge — the node side of the Voyager loop's first adapter.
//
// The Python core speaks line-delimited JSON to this process over
// stdin/stdout. One request per line, one response per line:
//
//   -> {"id":1,"cmd":"observe"}
//   <- {"id":1,"ok":true,"result":{...}}
//
// The bot itself is mineflayer, talking to the **private** Paper server
// on 127.0.0.1:25600 (never the live agent-world on 25565, never its
// world). The skill library's programs run in a `vm` sandbox whose only
// global is the `mc` object: the closed vocabulary of primitives.
//
// The primitives are the world's action space. A skill may not reach
// past them — there is no `require`, no `bot`, no `process`, no
// network inside the sandbox. That is the second door; the static door
// (the vocabulary scan in Python) is the first.
//
// Licence: the loop's design follows MineDojo/Voyager (MIT), whose
// notice is kept in the repository's LICENSE and NOTICE files.

'use strict'

const vm = require('vm')
const path = require('path')
const readline = require('readline')

const MINECRAFT_DIR = process.env.VOYAGER_MINECRAFT_DIR ||
  '/home/caseydigennaro/lm-wt/agent-world/bots'
const mineflayer = require(path.join(MINECRAFT_DIR, 'node_modules', 'mineflayer'))
const { pathfinder, Movements, goals } = require(
  path.join(MINECRAFT_DIR, 'node_modules', 'mineflayer-pathfinder'))
const Vec3 = require(path.join(MINECRAFT_DIR, 'node_modules', 'vec3'))
const Block = require(path.join(MINECRAFT_DIR, 'node_modules', 'prismarine-block'))

const HOST = process.env.VOYAGER_MC_HOST || '127.0.0.1'
const PORT = parseInt(process.env.VOYAGER_MC_PORT || '25600', 10)
const USERNAME = process.env.VOYAGER_MC_USER || 'voyager'
const VERSION = process.env.VOYAGER_MC_VERSION || '26.1.2'

// What a block drops. The vanilla ids the bridge knows how to collect;
// anything else is mined for the block itself.
const DROPS = {
  oak_log: 'oak_log', birch_log: 'birch_log', spruce_log: 'spruce_log',
  jungle_log: 'jungle_log', acacia_log: 'acacia_log', dark_oak_log: 'dark_oak_log',
  oak_planks: 'oak_planks', cobblestone: 'cobblestone', stone: 'cobblestone',
  deepslate: 'cobblestone', cobbled_deepslate: 'cobblestone',
  coal_ore: 'coal', deepslate_coal_ore: 'coal',
  iron_ore: 'raw_iron', deepslate_iron_ore: 'raw_iron',
  copper_ore: 'raw_copper', deepslate_copper_ore: 'raw_copper',
  gold_ore: 'raw_gold', deepslate_gold_ore: 'raw_gold',
  diamond_ore: 'diamond', deepslate_diamond_ore: 'diamond',
  lapis_ore: 'lapis_lazuli', deepslate_lapis_ore: 'lapis_lazuli',
  redstone_ore: 'redstone', deepslate_redstone_ore: 'redstone',
  gravel: 'gravel', sand: 'sand', dirt: 'dirt', andesite: 'andesite',
  diorite: 'diorite', granite: 'granite', obsidian: 'obsidian',
  clay: 'clay', sandstone: 'sandstone', netherrack: 'netherrack'
}

// The blocks worth reporting when the world is scanned.
const INTERESTING = [
  'oak_log', 'birch_log', 'spruce_log', 'jungle_log', 'acacia_log', 'dark_oak_log',
  'cobblestone', 'stone', 'deepslate', 'coal_ore', 'iron_ore', 'copper_ore',
  'gold_ore', 'diamond_ore', 'lapis_ore', 'redstone_ore',
  'deepslate_iron_ore', 'deepslate_coal_ore', 'deepslate_diamond_ore',
  'crafting_table', 'furnace', 'chest', 'sand', 'gravel', 'clay', 'obsidian'
]

const ORES = [
  'coal_ore', 'iron_ore', 'copper_ore', 'gold_ore', 'diamond_ore', 'lapis_ore',
  'redstone_ore', 'deepslate_coal_ore', 'deepslate_iron_ore',
  'deepslate_copper_ore', 'deepslate_gold_ore', 'deepslate_diamond_ore',
  'deepslate_lapis_ore', 'deepslate_redstone_ore'
]

let bot = null
let spawned = false
const logLines = []

function say (line) {
  logLines.push(String(line))
  if (logLines.length > 400) logLines.shift()
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

// -- the helpers ---------------------------------------------------------------

// The numeric id of an item.
//
// In this build the registry hands out the item *object*, not the number:
// bot.registry.itemsByName.oak_planks is {id: 36, name: 'oak_planks', ...}.
// Every recipe lookup is made by id, so passing the object where the
// number belongs is what made the recipe book look empty: the recipe
// book is keyed by the id of the item a recipe produces, and
// recipesFor(object) finds nothing.
function itemId (name) {
  if (!bot) throw new Error('the bot is not connected')
  const entry = bot.registry.itemsByName[name]
  if (entry === undefined || entry === null) {
    throw new Error('no item named ' + name)
  }
  const id = typeof entry === 'object' ? entry.id : entry
  if (id === undefined || id === null) {
    throw new Error('no item named ' + name)
  }
  return id
}

function blockId (name) {
  if (!bot) throw new Error('the bot is not connected')
  const entry = bot.registry.blocksByName[name]
  if (entry === undefined || entry === null) {
    throw new Error('no block named ' + name)
  }
  const id = typeof entry === 'object' ? entry.id : entry
  if (id === undefined || id === null) {
    throw new Error('no block named ' + name)
  }
  return id
}

// The distance to hand to findBlock for a given reach.
//
// findBlock does not search a sphere of the radius it is given. It walks
// an octahedron of chunk *sections* whose radius is
// ceil((maxDistance + 8) / 16), and a target D blocks away can be up to
// three sections out in each axis, so it needs an apothem of about
// 3 * ceil(D / 16). Asking for less than that is why the only tree in
// the world went missing: the bot was twelve blocks below it after
// digging, the sections no longer lined up, and findBlock answered
// "no oak_log within 96" about a tree it could see with its eyes.
function searchMaxDistance (reach) {
  const apothem = 3 * Math.ceil(Math.max(1, reach) / 16) + 2
  return Math.min(600, apothem * 16 - 8)
}

function inventoryCounts () {
  const counts = {}
  if (!bot) return counts
  for (const item of bot.inventory.items()) {
    counts[item.name] = (counts[item.name] || 0) + item.count
  }
  return counts
}

function heldName () {
  if (!bot) return ''
  const held = bot.heldItem
  return held ? held.name : ''
}

// The bot's position, floored to whole blocks.
function flooredPosition () {
  const here = bot.entity.position
  return new Vec3(Math.floor(here.x), Math.floor(here.y), Math.floor(here.z))
}

function distance (a, b) {
  const dx = a.x - b.x
  const dy = a.y - b.y
  const dz = a.z - b.z
  return Math.sqrt(dx * dx + dy * dy + dz * dz)
}

function isSolidName (name) {
  return name !== 'air' && name !== 'water' && name !== 'lava' &&
    name !== 'cave_air' && name !== 'void_air'
}

// -- the path ------------------------------------------------------------------
//
// The pathfinder this bridge runs against is mineflayer-pathfinder 2.4.5,
// and it ends a walk with one of three events:
//
//   'goal_reached' — the goal was met;
//   'path_update'  — the path changed, and carries a status: 'success',
//                    'partial', 'noPath' or 'timeout';
//   'path_stop'    — the walk was stopped before it finished.
//
// It does NOT emit 'path_complete', 'path_blocked' or 'path_timeout'.
// A listener for those names never fires, so a walk that waits for one
// waits for its own timer and nothing else — which is exactly what the
// first version of this bridge did: every walk ran to its timeout and
// then reported that it had not finished.

function walkTo (goal, timeoutMs) {
  return new Promise((resolve, reject) => {
    let settled = false
    const cleanup = () => {
      clearTimeout(timer)
      bot.removeListener('goal_reached', onReached)
      bot.removeListener('path_update', onUpdate)
      bot.removeListener('path_stop', onStopped)
    }
    const settle = (why, err) => {
      if (settled) return
      settled = true
      cleanup()
      if (err) reject(err)
      else resolve(why)
    }
    const onReached = () => settle('complete')
    const onUpdate = (results) => {
      if (!results) return
      if (results.status === 'noPath') {
        settle('no-path', new Error('the pathfinder found no path to the goal'))
      } else if (results.status === 'timeout') {
        settle('no-path', new Error('the pathfinder gave up deciding a path'))
      }
    }
    const onStopped = () => settle('stopped', new Error('the walk was stopped before it finished'))
    const timer = setTimeout(
      () => settle('timeout', new Error('the walk did not finish in time')), timeoutMs)
    bot.on('goal_reached', onReached)
    bot.on('path_update', onUpdate)
    bot.on('path_stop', onStopped)
    bot.pathfinder.setGoal(goal)
  })
}

// How long a walk may take. A bot walks at about four blocks a second, so
// a second and a bit a block is a fair clock; the floor covers the short
// walk, where the pathfinder's own thinking time dominates.
function walkBudget (distanceBlocks) {
  return Math.min(300000, Math.max(30000, Math.round(distanceBlocks * 1200)))
}

async function gotoPosition (position, timeoutMs) {
  const here = bot.entity.position
  const ms = timeoutMs || walkBudget(distance(here, position))
  const goal = new goals.GoalNear(position.x, position.y, position.z, 1)
  try {
    return await walkTo(goal, ms)
  } finally {
    bot.pathfinder.setGoal(null)
  }
}

// Stand close enough to a block to break it: two blocks, which is inside a
// player's reach and outside the block itself.
async function gotoBlock (block, timeoutMs) {
  const here = bot.entity.position
  const ms = timeoutMs || walkBudget(distance(here, block.position))
  const goal = new goals.GoalNear(
    block.position.x, block.position.y, block.position.z, 2)
  try {
    return await walkTo(goal, ms)
  } finally {
    bot.pathfinder.setGoal(null)
  }
}

// The tool tiers: wood, stone, iron, gold, diamond.
const TIERS = { wooden: 1, stone: 2, iron: 3, golden: 4, gold: 4, diamond: 5, netherite: 6 }

function tier (item) {
  const name = item.name
  for (const [prefix, value] of Object.entries(TIERS)) {
    if (name.startsWith(prefix + '_')) return value
  }
  return 0
}

async function equipTool (kind) {
  const suffix = '_' + kind
  const best = bot.inventory.items()
    .filter((item) => item.name.endsWith(suffix))
    .sort((a, b) => tier(b) - tier(a))[0]
  if (!best) return false
  await bot.equip(best, 'hand')
  return true
}

// Hold the tool that breaks this block fastest.
//
// Without this the bot breaks stone with its bare hands, which takes
// about four minutes a block: the tech tree would not finish inside the
// run's budget, and the measurement would be about patience rather than
// about planning.
async function holdBestToolFor (block) {
  let tool = null
  try {
    tool = bot.pathfinder.bestHarvestTool(block)
  } catch (err) {
    tool = null
  }
  if (!tool) return false
  if (bot.heldItem && bot.heldItem.type === tool.type) return true
  await bot.equip(tool, 'hand')
  return true
}

// Break one block.
//
// The block object is read again at the moment of the dig: a block found
// before a walk may no longer be the block at that place, and digging a
// stale block either digs nothing or digs the wrong thing.
async function mineOne (block) {
  const fresh = bot.blockAt(block.position)
  if (!fresh || !isSolidName(fresh.name)) {
    throw new Error('the block at ' + block.position + ' is no longer there')
  }
  await holdBestToolFor(fresh)
  try {
    // 'raycast' picks the face the bot can actually see, which matters
    // when the bot is standing next to the block rather than above it.
    await bot.dig(fresh, true, 'raycast')
  } catch (err) {
    // The raycast refuses a block that is not in view; the plain dig
    // still works when the face is reachable.
    await bot.dig(fresh, true)
  }
  return fresh
}

async function pickUp (itemName, timeoutMs) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    const counts = inventoryCounts()
    if ((counts[itemName] || 0) > 0) return true
    await sleep(150)
  }
  // Not picked up: walk onto the drop and touch it.
  const drops = Object.values(bot.entities)
    .filter((entity) => entity && entity.name === 'item' && entity.position)
    .sort((a, b) => distance(a.position, bot.entity.position) - distance(b.position, bot.entity.position))
  if (drops.length) {
    try {
      await gotoPosition(drops[0].position, 8000)
      await bot.touch(drops[0])
      await sleep(400)
    } catch (err) { /* the drop may already be gone */ }
  }
  const counts = inventoryCounts()
  return (counts[itemName] || 0) > 0
}

// The name of a block state, cached.
//
// prismarine-block makes a whole Block object for a state id, which is
// far too slow to do a hundred thousand times in a row, so the names are
// worked out once and kept.
const stateNames = new Map()

function stateName (stateId) {
  if (stateId === undefined || stateId === null) return null
  let name = stateNames.get(stateId)
  if (name === undefined) {
    try {
      name = Block.fromStateId(stateId, 0).name
    } catch (err) {
      name = null
    }
    stateNames.set(stateId, name)
  }
  return name
}

// The nearest block of each name, in one pass over the loaded world.
//
// findBlock does not search a sphere. It walks an octahedron of chunk
// sections, and for every section whose palette holds the name it reads
// all 4096 blocks of that section. Twenty-six names therefore read the
// world twenty-six times over: a scan of the loaded area took 60 s, and
// a node process that is busy for 60 s cannot answer the server's
// keep-alive packets, so the server kicks the bot in the middle of the
// scan. This walks the world once, reads each section once, and stops
// looking for a name as soon as it has been found.
//
// It returns null if the world does not answer in the shape expected,
// and the caller falls back to findBlock.
function nearestBlocks (names, maxDistance) {
  const wanted = new Set(names)
  const here = bot.entity.position
  const chunkRadius = Math.ceil(maxDistance / 16) + 1
  const cx0 = Math.floor(here.x / 16)
  const cz0 = Math.floor(here.z / 16)

  // The columns nearest first, so the first hit for a name is usually
  // the nearest one.
  const columns = []
  for (let dx = -chunkRadius; dx <= chunkRadius; dx++) {
    for (let dz = -chunkRadius; dz <= chunkRadius; dz++) {
      columns.push([dx, dz, dx * dx + dz * dz])
    }
  }
  columns.sort((a, b) => a[2] - b[2])

  const best = new Map()
  const pending = new Set(names)
  for (const [dx, dz] of columns) {
    if (pending.size === 0) break
    const column = bot.world.getColumn(cx0 + dx, cz0 + dz)
    if (!column || !column.sections) continue
    const baseX = (cx0 + dx) * 16
    const baseZ = (cz0 + dz) * 16
    const minY = (typeof column.minY === 'number') ? column.minY : 0
    for (let si = 0; si < column.sections.length; si++) {
      const section = column.sections[si]
      if (!section || !section.palette) continue
      // The palette says which names are in this section without
      // reading a single block.
      const here1 = []
      for (const stateId of section.palette) {
        const name = stateName(stateId)
        if (name && wanted.has(name) && pending.has(name)) here1.push(name)
      }
      if (!here1.length) continue
      const sectionY = minY + si * 16
      for (let ly = 0; ly < 16; ly++) {
        for (let lz = 0; lz < 16; lz++) {
          for (let lx = 0; lx < 16; lx++) {
            const stateId = section.get({ x: lx, y: ly, z: lz })
            const name = stateName(stateId)
            if (!name || !wanted.has(name)) continue
            const x = baseX + lx
            const y = sectionY + ly
            const z = baseZ + lz
            const away = distance({ x, y, z }, here)
            if (away > maxDistance) continue
            const current = best.get(name)
            if (!current || away < current.distance) {
              best.set(name, { distance: away, x, y, z })
            }
          }
        }
      }
      for (const name of here1) pending.delete(name)
    }
  }
  const out = {}
  for (const [name, value] of best.entries()) {
    out[name] = {
      distance: Math.round(value.distance * 10) / 10,
      x: value.x,
      y: value.y,
      z: value.z
    }
  }
  return out
}

// -- the primitives ------------------------------------------------------------

const PRIMITIVES = {
  async move_to (x, y, z, timeoutMs) {
    const ms = timeoutMs || null
    const why = await gotoPosition({ x: Math.round(x), y: Math.round(y), z: Math.round(z) }, ms)
    return { at: bot.entity.position, why }
  },

  async move_to_block (block, maxDistance, timeoutMs) {
    const reach = Math.min(128, maxDistance || 32)
    const found = bot.findBlock({
      matching: (b) => b && b.name === block,
      maxDistance: searchMaxDistance(reach)
    })
    if (!found || distance(found.position, bot.entity.position) > reach) {
      throw new Error('no ' + block + ' within ' + reach)
    }
    const why = await gotoBlock(found, timeoutMs || null)
    return { at: bot.entity.position, block: found.position, why }
  },

  async mine_block (block, maxDistance, count) {
    const want = Math.max(1, Math.min(64, count || 1))
    const reach = Math.min(64, maxDistance || 24)
    let mined = 0
    let problem = ''
    for (let i = 0; i < want; i++) {
      const found = bot.findBlock({
        matching: (b) => b && b.name === block,
        maxDistance: searchMaxDistance(reach)
      })
      if (!found || distance(found.position, bot.entity.position) > reach) break
      try {
        await gotoBlock(found, null)
      } catch (err) {
        problem = 'walk: ' + err.message
      }
      try {
        await mineOne(found)
        mined++
      } catch (err) {
        problem = 'dig: ' + err.message
        break
      }
      await sleep(150)
    }
    return { mined, problem, inventory: inventoryCounts() }
  },

  async collect (item, count, maxDistance) {
    const want = Math.max(1, Math.min(64, count || 1))
    const reach = Math.min(64, maxDistance || 24)
    const before = inventoryCounts()[item] || 0
    // Every block that drops this item, in the order worth trying: the
    // block that is the item itself first, then the blocks that break
    // into it. Stone breaks into cobblestone, so a bot under the ground
    // finds cobblestone by mining stone.
    const sources = Object.keys(DROPS).filter((key) => DROPS[key] === item)
    if (!sources.length) throw new Error('the bridge does not know what drops ' + item)
    let got = 0
    let problem = ''
    outer:
    for (const blockName of sources) {
      for (let i = 0; i < want; i++) {
        const found = bot.findBlock({
          matching: (b) => b && b.name === blockName,
          maxDistance: searchMaxDistance(reach)
        })
        if (!found || distance(found.position, bot.entity.position) > reach) break
        try {
          await gotoBlock(found, null)
        } catch (err) {
          problem = 'walk: ' + err.message
        }
        try {
          await mineOne(found)
        } catch (err) {
          problem = 'dig: ' + err.message
          break outer
        }
        const ok = await pickUp(item, 5000)
        if (!ok) {
          problem = 'the ' + item + ' did not reach the inventory'
          break outer
        }
        got++
        await sleep(120)
      }
      if ((inventoryCounts()[item] || 0) - before >= want) break
    }
    const after = inventoryCounts()[item] || 0
    return { collected: after - before, have: after, problem, inventory: inventoryCounts() }
  },

  async craft (item, count) {
    const want = Math.max(1, Math.min(64, count || 1))
    const id = itemId(item)
    const table = bot.findBlock({
      matching: (b) => b && b.name === 'crafting_table',
      maxDistance: 4
    })
    const recipes = bot.recipesFor(id, null, want, table || null)
    if (!recipes || recipes.length === 0) {
      // The recipe may exist and the ingredients may be missing, or the
      // recipe may need a table the bot has not placed. The two need
      // different answers, and the coder's next program depends on
      // which one it is.
      const any = bot.recipesAll(id, null, table || null)
      if (!any || any.length === 0) {
        throw new Error('there is no recipe for ' + item + ' at all')
      }
      const missing = missingIngredients(any[0])
      if (missing.length) {
        throw new Error('no ' + item + ': the inventory is short of ' + missing.join(', '))
      }
      throw new Error('no ' + item + ': the recipe needs a crafting table and none is within reach')
    }
    await bot.craft(recipes[0], want, table || null)
    return { crafted: want, inventory: inventoryCounts() }
  },

  async smelt (item, count, fuel) {
    const want = Math.max(1, Math.min(64, count || 1))
    const id = itemId(item)
    const furnaceBlock = bot.findBlock({
      matching: (b) => b && b.name === 'furnace',
      maxDistance: 4
    })
    if (!furnaceBlock) throw new Error('no furnace within reach')
    const furnace = await bot.openFurnace(furnaceBlock)
    try {
      const fuelItem = fuel || 'coal'
      const fuelId = itemId(fuelItem)
      if (!bot.inventory.count(fuelId)) {
        throw new Error('no ' + fuelItem + ' to burn')
      }
      await furnace.putInput(id, null, want)
      await furnace.putFuel(fuelId, null, 1)
      // One item smelts in ten seconds; give the furnace room to finish.
      await sleep(11000 * want)
      const output = furnace.outputItem()
      if (!output) throw new Error('the furnace produced nothing')
      const name = output.name
      const produced = output.count
      await furnace.takeOutput()
      await bot.closeWindow(furnace)
      return { smelted: produced, item: name, inventory: inventoryCounts() }
    } finally {
      try { await bot.closeWindow(furnace) } catch (err) { /* already closed */ }
    }
  },

  async place_block (block, x, y, z) {
    const id = blockId(block)
    const item = bot.inventory.items().find((entry) => entry.name === block)
    if (!item) throw new Error('no ' + block + ' to place')
    await bot.equip(item, 'hand')
    const target = new Vec3(Math.round(x), Math.round(y), Math.round(z))
    const existing = bot.blockAt(target)
    if (existing && isSolidName(existing.name)) {
      throw new Error('there is already a ' + existing.name + ' at ' + target)
    }
    // The placement is made against a neighbouring solid block, with the
    // face pointing at the spot the block should go.
    const around = [
      { d: new Vec3(0, 1, 0), f: new Vec3(0, -1, 0) },
      { d: new Vec3(0, -1, 0), f: new Vec3(0, 1, 0) },
      { d: new Vec3(1, 0, 0), f: new Vec3(-1, 0, 0) },
      { d: new Vec3(-1, 0, 0), f: new Vec3(1, 0, 0) },
      { d: new Vec3(0, 0, 1), f: new Vec3(0, 0, -1) },
      { d: new Vec3(0, 0, -1), f: new Vec3(0, 0, 1) }
    ]
    let lastError = ''
    for (const spot of around) {
      const reference = bot.blockAt(target.plus(spot.d))
      if (!reference || !isSolidName(reference.name)) continue
      try {
        await bot.placeBlock(reference, spot.f)
        return { placed: block, at: target }
      } catch (err) {
        lastError = err.message
      }
    }
    throw new Error('could not place ' + block + ' at ' + target +
      (lastError ? ': ' + lastError : ': no solid block next to it'))
  },

  async place_adjacent (block) {
    const id = blockId(block)
    const item = bot.inventory.items().find((entry) => entry.name === block)
    if (!item) throw new Error('no ' + block + ' to place')
    await bot.equip(item, 'hand')
    const feet = flooredPosition()
    const ground = bot.blockAt(new Vec3(feet.x, feet.y - 1, feet.z))
    if (!ground || !isSolidName(ground.name)) {
      throw new Error('the bot is not standing on anything solid')
    }
    const sides = [
      { d: new Vec3(1, 0, 0), f: new Vec3(1, 0, 0) },
      { d: new Vec3(-1, 0, 0), f: new Vec3(-1, 0, 0) },
      { d: new Vec3(0, 0, 1), f: new Vec3(0, 0, 1) },
      { d: new Vec3(0, 0, -1), f: new Vec3(0, 0, -1) }
    ]
    let lastError = ''
    // First on the ground beside the bot's feet, then on top of a block
    // that stands beside it.
    for (const side of sides) {
      const dest = new Vec3(feet.x + side.d.x, feet.y - 1, feet.z + side.d.z)
      const existing = bot.blockAt(dest)
      if (existing && isSolidName(existing.name)) continue
      try {
        await bot.placeBlock(ground, side.f)
        return { placed: block, at: dest }
      } catch (err) {
        lastError = err.message
      }
    }
    for (const side of sides) {
      const neighbour = bot.blockAt(new Vec3(feet.x + side.d.x, feet.y - 1, feet.z + side.d.z))
      if (!neighbour || !isSolidName(neighbour.name)) continue
      const dest = new Vec3(feet.x + side.d.x, feet.y, feet.z + side.d.z)
      const existing = bot.blockAt(dest)
      if (existing && isSolidName(existing.name)) continue
      try {
        await bot.placeBlock(neighbour, new Vec3(0, 1, 0))
        return { placed: block, at: dest }
      } catch (err) {
        lastError = err.message
      }
    }
    throw new Error('no room to place ' + block +
      (lastError ? ': ' + lastError : ''))
  },

  async equip (item) {
    const found = bot.inventory.items().find((entry) => entry.name === item)
    if (!found) throw new Error('no ' + item + ' to equip')
    await bot.equip(found, 'hand')
    return { held: heldName() }
  },

  async equip_tool (kind) {
    const ok = await equipTool(kind)
    if (!ok) throw new Error('no ' + kind + ' to hold')
    return { held: heldName() }
  },

  async look_at (x, y, z) {
    await bot.lookAt(new Vec3(x, y, z), true)
    return { looking: bot.entity.look
      ? [bot.entity.look.x, bot.entity.look.y, bot.entity.look.z]
      : null }
  },

  async sleep (ms) {
    await sleep(Math.max(0, Math.min(600000, ms || 0)))
    return { slept: ms || 0 }
  },

  async scan (radius) {
    const reach = Math.min(160, radius || 16)
    let found = null
    try {
      found = nearestBlocks(INTERESTING, reach)
    } catch (err) {
      found = null
    }
    if (found !== null) return { nearby: found }
    // The world did not answer in the shape the fast search expects;
    // fall back to the slow way, which always works.
    const slow = {}
    for (const name of INTERESTING) {
      const block = bot.findBlock({
        matching: (b) => b && b.name === name,
        maxDistance: searchMaxDistance(reach)
      })
      if (!block) continue
      const away = distance(block.position, bot.entity.position)
      // The search is wider than the radius on purpose; the radius is
      // the world the caller asked about.
      if (away > reach) continue
      slow[name] = {
        distance: Math.round(away * 10) / 10,
        x: block.position.x,
        y: block.position.y,
        z: block.position.z
      }
    }
    return { nearby: slow }
  },

  async scan_ore (radius) {
    const reach = Math.min(32, radius || 16)
    const here = bot.entity.position
    const base = {
      x: Math.floor(here.x),
      y: Math.floor(here.y),
      z: Math.floor(here.z)
    }
    const found = {}
    const half = Math.max(1, Math.floor(reach / 16))
    for (let dx = -half; dx <= half; dx++) {
      for (let dz = -half; dz <= half; dz++) {
        const cx = base.x + dx * 8
        const cz = base.z + dz * 8
        for (let y = -60; y <= 56; y++) {
          const block = bot.blockAt(new Vec3(cx, y, cz))
          if (!block || !ORES.includes(block.name)) continue
          const from = { x: cx, y, z: cz }
          const d = Math.round(distance(from, bot.entity.position) * 10) / 10
          const known = found[block.name]
          if (!known || d < known.distance) {
            found[block.name] = { distance: d, x: cx, y, z: cz }
          }
        }
      }
    }
    return { ores: found }
  },

  async dig_down (steps) {
    const n = Math.max(1, Math.min(48, steps || 1))
    let dug = 0
    let problem = ''
    for (let i = 0; i < n; i++) {
      const feet = flooredPosition()
      const under = bot.blockAt(new Vec3(feet.x, feet.y - 1, feet.z))
      if (under && isSolidName(under.name)) {
        try {
          await mineOne(under)
          dug++
        } catch (err) {
          problem = err.message
          break
        }
      }
      // Step down and forward, so the shaft is a staircase and the bot
      // does not have to climb back.
      const ahead = new Vec3(feet.x, feet.y - 1, feet.z + 1)
      const aheadBlock = bot.blockAt(ahead)
      if (aheadBlock && (aheadBlock.name === 'air' || aheadBlock.name === 'water')) {
        try {
          await gotoPosition(ahead, 6000)
          continue
        } catch (err) { /* fall through to the break */ }
      }
      break
    }
    return { dug, problem, at: bot.entity.position }
  },

  async count (item) {
    return { count: inventoryCounts()[item] || 0 }
  },

  async has (item) {
    return { has: (inventoryCounts()[item] || 0) > 0 }
  }
}

// What the recipe needs and the inventory does not have.
function missingIngredients (recipe) {
  const missing = []
  for (const delta of (recipe.delta || [])) {
    if (delta.count >= 0) continue
    const item = bot.registry.items[delta.id]
    if (!item) continue
    const have = bot.inventory.count(delta.id, delta.metadata)
    const need = -delta.count
    if (have < need) missing.push(item.name + ' x' + (need - have))
  }
  return missing
}

// -- the sandbox ----------------------------------------------------------------

async function runInSandbox (code, timeoutMs) {
  if (!bot) throw new Error('the bot is not connected')
  const captured = []
  const consoleShim = {
    log: (...args) => { captured.push(args.map(String).join(' ')) },
    error: (...args) => { captured.push(args.map(String).join(' ')) }
  }
  const context = vm.createContext({
    mc: PRIMITIVES,
    console: consoleShim,
    sleep,
    Math, JSON, Date, Object, Array, String, Number, Boolean, Error,
    isNaN, parseInt, parseFloat
  })
  const script = new vm.Script('(async () => {\n' + code + '\n})()')
  const limit = Math.max(1000, timeoutMs)
  try {
    const value = await Promise.race([
      script.runInContext(context, { timeout: limit }),
      sleep(limit).then(() => { throw new Error('the program ran out of time') })
    ])
    return { value, log: captured }
  } catch (err) {
    // The program may still be walking or digging: stop it, so the next
    // program starts from a bot that is standing still.
    try { bot.pathfinder.stop() } catch (e) { /* no path */ }
    try { bot.stopDigging() } catch (e) { /* not digging */ }
    throw err
  }
}

// -- the world ------------------------------------------------------------------

function facts () {
  const position = bot.entity.position
  return {
    position: {
      x: Math.round(position.x * 10) / 10,
      y: Math.round(position.y * 10) / 10,
      z: Math.round(position.z * 10) / 10
    },
    health: bot.health,
    food: bot.food,
    held: heldName(),
    inventory: inventoryCounts(),
    time_of_day: bot.time.timeOfDay,
    on_ground: bot.entity.onGround,
    looking: bot.entity.look
      ? [Math.round(bot.entity.look.x), Math.round(bot.entity.look.y), Math.round(bot.entity.look.z)]
      : null
  }
}

function connect () {
  return new Promise((resolve, reject) => {
    bot = mineflayer.createBot({
      host: HOST,
      port: PORT,
      username: USERNAME,
      version: VERSION,
      auth: 'offline',
      checkTimeoutInterval: 120000
    })
    bot.loadPlugin(pathfinder)
    bot.once('spawn', () => {
      const movements = new Movements(bot)
      // The bot may dig through what is in its way, which is how it gets
      // into a cave and out of a hill.
      movements.canDig = true
      movements.allow1by1towers = false
      movements.allowParkour = false
      bot.pathfinder.setMovements(movements)
      spawned = true
      // The client is given the chunks around the spawn a moment after
      // the spawn, not at it: a scan over a client that holds no chunks
      // finds nothing, and "nothing" reads like "the world is empty".
      // Wait for the ground under the bot and its neighbours to be
      // there before the world is handed over.
      waitForChunks(90000).then(resolve, reject)
    })
    bot.once('error', (err) => { if (!spawned) reject(err) })
    bot.once('kicked', (reason) => { if (!spawned) reject(new Error('kicked: ' + reason)) })
    bot.on('end', () => { spawned = false })
    setTimeout(() => { if (!spawned) reject(new Error('the bot did not spawn in time')) }, 60000)
  })
}

// The chunks around the bot have arrived.
//
// The client is given the chunks a moment after the spawn. Until they
// are there, a search over the world finds nothing at all.
function waitForChunks (timeoutMs) {
  const deadline = Date.now() + (timeoutMs || 60000)
  return new Promise((resolve, reject) => {
    const check = () => {
      if (!bot || !bot.entity) {
        resolve(false)
        return
      }
      const pos = bot.entity.position
      const cx = Math.floor(pos.x / 16)
      const cz = Math.floor(pos.z / 16)
      let columns = 0
      for (let dx = -1; dx <= 1; dx++) {
        for (let dz = -1; dz <= 1; dz++) {
          if (bot.world.getColumn(cx + dx, cz + dz)) columns++
        }
      }
      const ground = bot.blockAt(new Vec3(Math.floor(pos.x), Math.floor(pos.y) - 1, Math.floor(pos.z)))
      const standing = ground && isSolidName(ground.name)
      if ((columns >= 9 && standing) || Date.now() > deadline) {
        resolve(columns >= 9 && standing)
        return
      }
      setTimeout(check, 500)
    }
    check()
  })
}

// -- the wire --------------------------------------------------------------------

const rl = readline.createInterface({ input: process.stdin })
rl.on('line', async (line) => {
  let request = null
  try {
    request = JSON.parse(line)
  } catch (err) {
    process.stdout.write(JSON.stringify({ id: 0, ok: false, error: 'bad request' }) + '\n')
    return
  }
  const id = request.id
  const cmd = request.cmd
  try {
    let result = null
    if (cmd === 'connect') {
      await connect()
      result = { connected: true, version: VERSION, host: HOST, port: PORT }
    } else if (cmd === 'observe') {
      result = facts()
    } else if (cmd === 'run') {
      const started = Date.now()
      const outcome = await runInSandbox(request.code, request.timeout_ms || 120000)
      result = { ok: true, log: outcome.log, seconds: (Date.now() - started) / 1000 }
    } else if (cmd === 'evaluate') {
      const started = Date.now()
      const outcome = await runInSandbox(request.code, request.timeout_ms || 30000)
      result = {
        passed: outcome.value === true || outcome.value === 'true',
        value: outcome.value === undefined ? null : String(outcome.value),
        log: outcome.log,
        seconds: (Date.now() - started) / 1000
      }
    } else if (cmd === 'progress') {
      result = { inventory: inventoryCounts() }
    } else if (cmd === 'ping') {
      result = { pong: true, alive: spawned }
    } else if (cmd === 'quit') {
      process.stdout.write(JSON.stringify({ id, ok: true, result: { bye: true } }) + '\n')
      if (bot) bot.quit()
      setTimeout(() => process.exit(0), 300)
      return
    } else {
      throw new Error('unknown command ' + cmd)
    }
    process.stdout.write(JSON.stringify({ id, ok: true, result }) + '\n')
  } catch (err) {
    process.stdout.write(JSON.stringify({
      id,
      ok: false,
      error: String((err && err.message) || err),
      log: logLines.slice(-20)
    }) + '\n')
  }
})

rl.on('close', () => {
  if (bot) bot.quit()
  process.exit(0)
})
