// What is the bridge actually seeing? A diagnostic, not a measurement.
//
// Four questions, each answered from the bot's own state:
//   1. where is the bot, and how many chunks does its client hold;
//   2. why is no oak_log found, when the scan says the tree is 73 blocks
//      away — is the block there, and is its column in the cache;
//   3. what do the crafting recipes of this server's version actually
//      require (the 2x2 inventory grid, or a table);
//   4. what is loaded around the tree's column.
//
// Usage:
//   ~/lm-wt/agent-world/runtime/node/bin/node \
//       docs/lab/voyager-port-scripts/probe_diag.js
//
// It uses no model and writes nothing but the report.

'use strict'

const path = require('path')
const MINECRAFT_DIR = process.env.VOYAGER_MINECRAFT_DIR ||
  '/home/caseydigennaro/lm-wt/agent-world/bots'
const mineflayer = require(path.join(MINECRAFT_DIR, 'node_modules', 'mineflayer'))
const Vec3 = require(path.join(MINECRAFT_DIR, 'node_modules', 'vec3'))

const HOST = '127.0.0.1'
const PORT = 25600

function report (label, value) {
  console.log(label + ': ' + JSON.stringify(value))
}

const bot = mineflayer.createBot({
  host: HOST, port: PORT, username: 'voyager',
  version: '26.1.2', auth: 'offline', checkTimeoutInterval: 120000
})

bot.once('spawn', () => {
  setTimeout(() => {
    const pos = bot.entity.position
    report('position', {
      x: Math.round(pos.x * 100) / 100,
      y: Math.round(pos.y * 100) / 100,
      z: Math.round(pos.z * 100) / 100
    })

    // 1. The client's chunk cache.
    let columns = 0
    try {
      for (const key of Object.keys(bot.world.columns || {})) columns++
    } catch (err) { columns = -1 }
    report('cached_columns', columns)
    report('world_columns_keys_sample', Object.keys(bot.world.columns || {}).slice(0, 8))

    // 2. The tree: is the block there, and is its column cached?
    const tree = new Vec3(-3, 66, 103)
    const at = bot.blockAt(tree)
    report('block_at_tree', at ? at.name : null)
    const treeChunk = { x: Math.floor(tree.x / 16), z: Math.floor(tree.z / 16) }
    report('tree_chunk', treeChunk)
    let treeColumn = null
    try {
      treeColumn = bot.world.getColumn(treeChunk.x, treeChunk.z)
    } catch (err) { treeColumn = null }
    report('tree_column_cached', treeColumn ? true : false)
    report('bot_chunk', {
      x: Math.floor(pos.x / 16),
      z: Math.floor(pos.z / 16)
    })

    // The distances at which the tree is found, if it is found at all.
    for (const radius of [32, 64, 96, 128, 160]) {
      const found = bot.findBlock({
        matching: (b) => b && b.name === 'oak_log',
        maxDistance: radius
      })
      report('find_oak_log_' + radius, found
        ? { x: found.position.x, y: found.position.y, z: found.position.z,
            distance: Math.round(Math.hypot(
              found.position.x - pos.x, found.position.y - pos.y,
              found.position.z - pos.z) * 10) / 10 }
        : null)
    }

    // Every log within 160, found by scanning columns directly: the
    // difference between "the block is not there" and "findBlock does
    // not look there".
    const logs = []
    for (let cx = -8; cx <= 16; cx++) {
      for (let cz = -8; cz <= 16; cz++) {
        const column = bot.world.getColumn(cx, cz)
        if (!column) continue
        for (let y = -64; y < 128; y++) {
          const b = bot.blockAt(new Vec3(cx * 16 + 8, y, cz * 16 + 8))
          if (b && b.name && b.name.endsWith('_log')) {
            logs.push({ chunk: [cx, cz], x: b.position.x, y: b.position.y, z: b.position.z })
          }
        }
      }
    }
    report('logs_by_column_scan', logs.slice(0, 20))
    report('logs_found_count', logs.length)

    // 3. The recipes of this server's version.
    const names = ['oak_log', 'oak_planks', 'crafting_table', 'stick',
      'wooden_pickaxe', 'cobblestone', 'raw_iron', 'iron_ingot',
      'stone_pickaxe', 'furnace']
    for (const name of names) {
      const id = bot.registry.itemsByName[name]
      if (id === undefined) {
        report('recipe_' + name, 'no such item')
        continue
      }
      let all = []
      try {
        all = bot.recipesAll(id, null, null) || []
      } catch (err) {
        report('recipe_' + name, 'error ' + err.message)
        continue
      }
      report('recipe_' + name, all.map((r) => ({
        requiresTable: r.requiresTable,
        inShape: r.inShape,
        ingredients: (r.ingredients || []).map((i) => {
          const item = bot.registry.items[i.id]
          return { item: item ? item.name : i.id, count: i.count }
        }),
        result: r.result ? r.result.count : null
      })))
      let withTable = []
      try {
        withTable = bot.recipesAll(id, null, { name: 'crafting_table' }) || []
      } catch (err) { withTable = [] }
      report('recipe_' + name + '_with_table', withTable.length)
    }

    // 4. The crafting table's own recipe: is it a 2x2 one?
    const tableId = bot.registry.itemsByName.crafting_table
    const tableRecipes = bot.recipesAll(tableId, null, null) || []
    report('crafting_table_recipes', tableRecipes.map((r) => ({
      requiresTable: r.requiresTable, inShape: r.inShape
    })))

    bot.quit()
    setTimeout(() => process.exit(0), 500)
  }, 12000)
})

bot.on('error', (err) => { console.log('error: ' + err.message) })
bot.on('kicked', (reason) => { console.log('kicked: ' + reason) })
setTimeout(() => { console.log('timeout'); process.exit(1) }, 90000)
