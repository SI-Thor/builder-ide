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

function itemId (name) {
  if (!bot) throw new Error('the bot is not connected')
  const id = bot.registry.itemsByName[name]
  if (id === undefined) throw new Error('no item named ' + name)
  return id
}

function blockId (name) {
  if (!bot) throw new Error('the bot is not connected')
  const id = bot.registry.blocksByName[name]
  if (id === undefined) throw new Error('no block named ' + name)
  return id
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

function distance (a, b) {
  const dx = a.x - b.x
  const dy = a.y - b.y
  const dz = a.z - b.z
  return Math.sqrt(dx * dx + dy * dy + dz * dz)
}

async function waitFor (fn, timeoutMs, label) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    if (fn()) return true
    await sleep(120)
  }
  throw new Error('timed out waiting for ' + label)
}

async function gotoPosition (position, timeoutMs) {
  const goal = new goals.NearestBlock(position, 1)
  bot.pathfinder.setGoal(goal)
  await new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      bot.removeListener('path_complete', onDone)
      bot.removeListener('path_blocked', onBlocked)
      reject(new Error('the walk did not finish in time'))
    }, timeoutMs)
    const onDone = () => { clearTimeout(timer); resolve() }
    const onBlocked = () => { clearTimeout(timer); resolve() }
    bot.once('path_complete', onDone)
    bot.once('path_blocked', onBlocked)
  })
  bot.pathfinder.setGoal(null)
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

// The tool tiers: wood, stone, iron, gold, diamond.
const TIERS = { wooden: 1, stone: 2, iron: 3, golden: 4, gold: 4, diamond: 5, netherite: 6 }

function tier (item) {
  const name = item.name
  for (const [prefix, value] of Object.entries(TIERS)) {
    if (name.startsWith(prefix + '_')) return value
  }
  return 0
}

async function mineOne (block) {
  const reference = block.position.offset(0.5, 0.5, 0.5)
  await bot.lookAt(reference, true)
  await bot.dig(block)
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

// -- the primitives ------------------------------------------------------------

const PRIMITIVES = {
  async move_to (x, y, z, timeoutMs) {
    const ms = timeoutMs || 30000
    await gotoPosition({ x: Math.round(x), y: Math.round(y), z: Math.round(z) }, ms)
    return { at: bot.entity.position }
  },

  async move_to_block (block, maxDistance, timeoutMs) {
    const ms = timeoutMs || 30000
    const found = bot.findBlock({
      matching: (b) => b && b.name === block,
      maxDistance: maxDistance || 32
    })
    if (!found) throw new Error('no ' + block + ' within ' + (maxDistance || 32))
    const goal = new goals.NearestBlock(found.position, 2)
    bot.pathfinder.setGoal(goal)
    await new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        bot.removeListener('path_complete', onDone)
        bot.removeListener('path_blocked', onBlocked)
        reject(new Error('the walk to ' + block + ' did not finish in time'))
      }, ms)
      const onDone = () => { clearTimeout(timer); resolve() }
      const onBlocked = () => { clearTimeout(timer); resolve() }
      bot.once('path_complete', onDone)
      bot.once('path_blocked', onBlocked)
    })
    bot.pathfinder.setGoal(null)
    return { at: bot.entity.position, block: found.position }
  },

  async mine_block (block, maxDistance, count) {
    const want = Math.max(1, Math.min(64, count || 1))
    const reach = Math.min(48, maxDistance || 24)
    let mined = 0
    for (let i = 0; i < want; i++) {
      const found = bot.findBlock({
        matching: (b) => b && b.name === block,
        maxDistance: reach
      })
      if (!found) break
      try {
        await gotoPosition(found.position, 12000)
      } catch (err) { /* walk as close as possible */ }
      await mineOne(found)
      mined++
      await sleep(150)
    }
    return { mined, inventory: inventoryCounts() }
  },

  async collect (item, count, maxDistance) {
    const want = Math.max(1, Math.min(64, count || 1))
    const reach = Math.min(48, maxDistance || 24)
    const before = inventoryCounts()[item] || 0
    let got = 0
    for (let i = 0; i < want; i++) {
      const blockName = Object.keys(DROPS).find((key) => DROPS[key] === item)
      if (!blockName) throw new Error('the bridge does not know what drops ' + item)
      const found = bot.findBlock({
        matching: (b) => b && b.name === blockName,
        maxDistance: reach
      })
      if (!found) break
      try {
        await gotoPosition(found.position, 12000)
      } catch (err) { /* walk as close as possible */ }
      await mineOne(found)
      const ok = await pickUp(item, 4000)
      if (!ok) break
      got++
      await sleep(120)
    }
    const after = inventoryCounts()[item] || 0
    return { collected: after - before, have: after, inventory: inventoryCounts() }
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
      if (!table) {
        throw new Error('no recipe for ' + item + ' in the 2x2 grid; place a crafting table first')
      }
      throw new Error('no recipe for ' + item)
    }
    await bot.craft(recipes[0], want, table || null)
    return { crafted: want, inventory: inventoryCounts() }
  },

  async place_block (block, x, y, z) {
    const id = blockId(block)
    const item = bot.inventory.items().find((entry) => entry.name === block)
    if (!item) throw new Error('no ' + block + ' to place')
    await bot.equip(item, 'hand')
    const reference = bot.entity.position.offset(0.5, 0.5, 0.5)
    await bot.lookAt(reference, true)
    await bot.placeBlock(new (require(path.join(MINECRAFT_DIR, 'node_modules', 'vec3')))(x, y, z), id)
    return { placed: block }
  },

  async place_adjacent (block) {
    const id = blockId(block)
    const item = bot.inventory.items().find((entry) => entry.name === block)
    if (!item) throw new Error('no ' + block + ' to place')
    await bot.equip(item, 'hand')
    const feet = bot.entity.position.floored()
    // Try the block above the bot's feet first, then the one it faces.
    const spots = [
      feet.offset(0, 1, 0),
      feet.offset(0, 0, 1),
      feet.offset(0, 0, -1),
      feet.offset(1, 0, 0),
      feet.offset(-1, 0, 0)
    ]
    for (const spot of spots) {
      const existing = bot.blockAt(spot)
      if (existing && existing.name !== 'air') continue
      try {
        await bot.lookAt(spot.offset(0.5, 0.5, 0.5), true)
        await bot.placeBlock(spot, id)
        return { placed: block, at: spot }
      } catch (err) { /* try the next spot */ }
    }
    throw new Error('no room to place ' + block)
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
    await bot.lookAt({ x, y, z }, true)
    return { looking: bot.entity.position && bot.entity.look ? [bot.entity.look.x, bot.entity.look.y, bot.entity.look.z] : null }
  },

  async sleep (ms) {
    await sleep(Math.max(0, Math.min(600000, ms || 0)))
    return { slept: ms || 0 }
  },

  async scan (radius) {
    const reach = Math.min(48, radius || 16)
    const found = {}
    for (const name of INTERESTING) {
      const block = bot.findBlock({
        matching: (b) => b && b.name === name,
        maxDistance: reach
      })
      if (!block) continue
      found[name] = {
        distance: Math.round(distance(block.position, bot.entity.position) * 10) / 10,
        x: block.position.x,
        y: block.position.y,
        z: block.position.z
      }
    }
    return { nearby: found }
  },

  async scan_ore (radius) {
    const reach = Math.min(32, radius || 16)
    const base = bot.entity.position.floored()
    const found = {}
    const half = Math.floor(reach / 16)
    for (let dx = -half; dx <= half; dx++) {
      for (let dz = -half; dz <= half; dz++) {
        const cx = base.x + dx * 8
        const cz = base.z + dz * 8
        for (let y = -60; y <= 56; y++) {
          const block = bot.blockAt({ x: cx, y, z: cz })
          if (!block || !ORES.includes(block.name)) continue
          const here = { x: cx, y, z: cz }
          const d = Math.round(distance(here, bot.entity.position) * 10) / 10
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
    for (let i = 0; i < n; i++) {
      const feet = bot.entity.position.floored()
      const under = bot.blockAt(feet.offset(0, -1, 0))
      if (under && under.name !== 'air' && under.name !== 'water' && under.name !== 'lava') {
        try {
          await bot.lookAt(feet.offset(0.5, -0.5, 0.5), true)
          await bot.dig(under)
          dug++
        } catch (err) { break }
      }
      // Step down and forward, so the shaft is a staircase and the bot
      // does not have to climb back.
      const ahead = feet.offset(0, -1, 1)
      const aheadBlock = bot.blockAt(ahead)
      if (aheadBlock && (aheadBlock.name === 'air' || aheadBlock.name === 'water')) {
        try {
          await gotoPosition(ahead, 6000)
          continue
        } catch (err) { /* fall through to the break */ }
      }
      break
    }
    return { dug, at: bot.entity.position }
  },

  async count (item) {
    return { count: inventoryCounts()[item] || 0 }
  },

  async has (item) {
    return { has: (inventoryCounts()[item] || 0) > 0 }
  }
}

// -- the sandbox ----------------------------------------------------------------

async function runInSandbox (code, timeoutMs, wantValue) {
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
    Math, JSON, Date, Object, Array, String, Number, Boolean, Error, isNaN, parseInt, parseFloat
  })
  const script = new vm.Script('(async () => {\n' + code + '\n})()')
  const value = await Promise.race([
    script.runInContext(context, { timeout: Math.max(1000, timeoutMs) }),
    sleep(Math.max(1000, timeoutMs)).then(() => { throw new Error('the program ran out of time') })
  ])
  return { value, log: captured }
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
      bot.pathfinder.setMovements(new Movements(bot))
      spawned = true
      resolve()
    })
    bot.once('error', (err) => { if (!spawned) reject(err) })
    bot.once('kicked', (reason) => { if (!spawned) reject(new Error('kicked: ' + reason)) })
    bot.on('end', () => { spawned = false })
    setTimeout(() => { if (!spawned) reject(new Error('the bot did not spawn in time')) }, 60000)
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
      const outcome = await runInSandbox(request.code, request.timeout_ms || 120000, false)
      result = { ok: true, log: outcome.log, seconds: (Date.now() - started) / 1000 }
    } else if (cmd === 'evaluate') {
      const started = Date.now()
      const outcome = await runInSandbox(request.code, request.timeout_ms || 30000, true)
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
