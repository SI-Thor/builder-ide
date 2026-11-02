// The recipe book has 887 entries, keyed by recipe id, and Recipe.find
// looks them up by item id. This one dumps what the entries actually
// look like, so the mismatch can be bridged exactly.
//
// Usage:
//   ~/lm-wt/agent-world/runtime/node/bin/node \
//       docs/lab/voyager-port-scripts/probe_diag3.js

'use strict'

const path = require('path')
const MINECRAFT_DIR = process.env.VOYAGER_MINECRAFT_DIR ||
  '/home/caseydigennaro/lm-wt/agent-world/bots'
const mineflayer = require(path.join(MINECRAFT_DIR, 'node_modules', 'mineflayer'))
const { Recipe } = require(path.join(MINECRAFT_DIR, 'node_modules', 'prismarine-recipe'))

function report (label, value) {
  console.log(label + ': ' + JSON.stringify(value))
}

report('prismarine_recipe_version',
  require(path.join(MINECRAFT_DIR, 'node_modules', 'prismarine-recipe', 'package.json')).version)
report('prismarine_registry_version',
  require(path.join(MINECRAFT_DIR, 'node_modules', 'prismarine-registry', 'package.json')).version)

const bot = mineflayer.createBot({
  host: '127.0.0.1', port: 25600, username: 'voyager',
  version: '26.1.2', auth: 'offline', checkTimeoutInterval: 120000
})

bot.once('spawn', () => {
  setTimeout(() => {
    const recipes = bot.registry.recipes || {}
    const keys = Object.keys(recipes)
    report('recipe_count', keys.length)
    report('recipe_key_types', keys.slice(0, 6))
    const first = recipes[keys[0]]
    report('one_recipe_raw', first)

    const planksId = bot.registry.itemsByName.oak_planks
    const logId = bot.registry.itemsByName.oak_log
    const tableId = bot.registry.itemsByName.crafting_table
    const stickId = bot.registry.itemsByName.stick
    report('ids', { planksId, logId, tableId, stickId })

    const producing = []
    for (const key of keys) {
      const r = recipes[key]
      const result = r && r.result
      if (!result) continue
      const id = typeof result === 'object' ? result.id : result
      if (id === planksId || id === tableId || id === stickId) {
        producing.push({ key, raw: r })
      }
    }
    report('recipes_producing_planks_table_stick', producing.slice(0, 8))
    report('producing_count', producing.length)

    const byItem = {}
    for (const key of keys) {
      const r = recipes[key]
      const result = r && r.result
      if (!result) continue
      const id = typeof result === 'object' ? result.id : result
      ;(byItem[id] = byItem[id] || []).push(r)
    }
    report('by_item_planks_count', (byItem[planksId] || []).length)
    report('by_item_planks_sample', (byItem[planksId] || []).slice(0, 4))

    try {
      const built = Recipe.find(planksId, null)
      report('recipe_find_planks', built.length)
    } catch (err) {
      report('recipe_find_planks_error', err.message)
    }
    try {
      const one = new Recipe(byItem[planksId][0])
      report('built_recipe', {
        requiresTable: one.requiresTable,
        inShape: one.inShape,
        ingredients: one.ingredients,
        result: one.result,
        delta: one.delta
      })
    } catch (err) {
      report('built_recipe_error', err.message)
    }

    bot.quit()
    setTimeout(() => process.exit(0), 500)
  }, 12000)
})

bot.on('error', (err) => { console.log('error: ' + err.message) })
setTimeout(() => { console.log('timeout'); process.exit(1) }, 90000)
