// Can the bot craft at all?
//
// The client holds 887 recipes, keyed by recipe id. prismarine-recipe
// looks the book up by the id of the item a recipe produces. This one
// re-keys the book in place and asks whether a recipe then appears.
//
// Usage:
//   ~/lm-wt/agent-world/runtime/node/bin/node \
//       docs/lab/voyager-port-scripts/probe_diag4.js

'use strict'

const path = require('path')
const MINECRAFT_DIR = process.env.VOYAGER_MINECRAFT_DIR ||
  '/home/caseydigennaro/lm-wt/agent-world/bots'
const mineflayer = require(path.join(MINECRAFT_DIR, 'node_modules', 'mineflayer'))

function report (label, value) {
  console.log(label + ': ' + JSON.stringify(value))
}

function idOf (entry) {
  if (entry === undefined || entry === null) return undefined
  if (typeof entry === 'object') return entry.id
  return entry
}

const bot = mineflayer.createBot({
  host: '127.0.0.1', port: 25600, username: 'voyager',
  version: '26.1.2', auth: 'offline', checkTimeoutInterval: 120000
})

bot.once('spawn', () => {
  setTimeout(() => {
    const book = bot.registry.recipes || {}
    const keys = Object.keys(book)
    const planksId = idOf(bot.registry.itemsByName.oak_planks)
    const logId = idOf(bot.registry.itemsByName.oak_log)
    const tableId = idOf(bot.registry.itemsByName.crafting_table)
    report('ids', { planksId, logId, tableId })

    let shaped = 0
    let shapeless = 0
    const producing = {}
    for (const key of keys) {
      const list = book[key]
      if (!Array.isArray(list)) continue
      for (const entry of list) {
        if (!entry) continue
        if (entry.inShape) shaped++
        else shapeless++
        const id = idOf(entry.result)
        if (id === undefined) continue
        ;(producing[id] = producing[id] || []).push({ key, entry })
      }
    }
    report('recipes_shaped', shaped)
    report('recipes_shapeless', shapeless)
    report('distinct_results', Object.keys(producing).length)
    report('producing_planks_count', (producing[planksId] || []).length)
    report('producing_planks_raw', (producing[planksId] || []).slice(0, 4))
    report('producing_table_raw', (producing[tableId] || []).slice(0, 3))

    // Re-key in place: the recipe id -> item id index that
    // prismarine-recipe expects. The object must be mutated, not
    // replaced: prismarine-recipe captured the reference at load.
    const byItem = {}
    for (const key of keys) {
      const list = book[key]
      if (!Array.isArray(list)) continue
      for (const entry of list) {
        const id = idOf(entry && entry.result)
        if (id === undefined) continue
        ;(byItem[id] = byItem[id] || []).push(entry)
      }
    }
    for (const key of keys) delete book[key]
    for (const id of Object.keys(byItem)) book[id] = byItem[id]
    report('rekeyed_keys_sample', Object.keys(book).slice(0, 6))

    const found = bot.recipesFor(planksId, null, 4, null)
    report('recipesFor_planks_after_rekey', found.length)
    report('recipesFor_planks_recipe', found[0] ? {
      requiresTable: found[0].requiresTable,
      inShape: found[0].inShape,
      ingredients: found[0].ingredients,
      result: found[0].result,
      delta: found[0].delta
    } : null)

    const all = bot.recipesAll(planksId, null, null)
    report('recipesAll_planks_after_rekey', all.length)

    const tableRecipes = bot.recipesFor(tableId, null, 1, null)
    report('recipesFor_table_after_rekey', tableRecipes.length)
    report('recipesFor_table_recipe', tableRecipes[0] ? {
      requiresTable: tableRecipes[0].requiresTable,
      inShape: tableRecipes[0].inShape,
      ingredients: tableRecipes[0].ingredients,
      delta: tableRecipes[0].delta
    } : null)

    // The names behind the ids, so the recipe reads in the player's terms.
    const nameOf = (id) => {
      const item = bot.registry.items[id]
      return item ? item.name : null
    }
    report('ingredient_names', (tableRecipes[0] && tableRecipes[0].delta || []).map((d) => ({
      name: nameOf(d.id), count: d.count
    })))

    bot.quit()
    setTimeout(() => process.exit(0), 500)
  }, 12000)
})

bot.on('error', (err) => { console.log('error: ' + err.message) })
setTimeout(() => { console.log('timeout'); process.exit(1) }, 90000)
