// Why is the recipe book empty? A second diagnostic.
//
// The first diagnostic showed that every recipe query comes back empty,
// for every item, with and without a table: the client has no recipes at
// all. This one asks the client what it thinks the protocol version is,
// whether the server ever sent recipe data, and what the registry holds.
//
// Usage:
//   ~/lm-wt/agent-world/runtime/node/bin/node \
//       docs/lab/voyager-port-scripts/probe_diag2.js

'use strict'

const path = require('path')
const MINECRAFT_DIR = process.env.VOYAGER_MINECRAFT_DIR ||
  '/home/caseydigennaro/lm-wt/agent-world/bots'
const mineflayer = require(path.join(MINECRAFT_DIR, 'node_modules', 'mineflayer'))

function report (label, value) {
  console.log(label + ': ' + JSON.stringify(value))
}

report('mineflayer_exports', Object.keys(mineflayer))
report('mineflayer_supported_versions', (mineflayer.supportedVersions || (require(path.join(MINECRAFT_DIR, 'node_modules', 'minecraft-data')).versions.pc) || []).slice ? (mineflayer.supportedVersions || Object.keys(require(path.join(MINECRAFT_DIR, 'node_modules', 'minecraft-data')).versions.pc)).slice(-15) : [])
report('mineflayer_version', require(path.join(MINECRAFT_DIR, 'node_modules', 'mineflayer', 'package.json')).version)

const bot = mineflayer.createBot({
  host: '127.0.0.1', port: 25600, username: 'voyager',
  version: '26.1.2', auth: 'offline', checkTimeoutInterval: 120000
})

let recipePackets = 0
let recipePacketBytes = 0
let registryPackets = 0

bot._client.on('update_recipes', (data) => {
  recipePackets++
  recipePacketBytes += JSON.stringify(data).length
})
bot._client.on('registry_data', (data) => {
  registryPackets++
})

bot.once('spawn', () => {
  setTimeout(() => {
    report('registry_version', bot.registry.version)
    report('registry_minecraftVersion', bot.registry.version.minecraftVersion)
    report('registry_protocol', bot.registry.version.version)
    report('registry_recipes_keys', Object.keys(bot.registry.recipes || {}).length)
    report('registry_recipes_sample', Object.keys(bot.registry.recipes || {}).slice(0, 6))
    report('registry_items', Object.keys(bot.registry.items || {}).length)
    report('registry_blocks', Object.keys(bot.registry.blocks || {}).length)
    report('registry_entities', Object.keys(bot.registry.entities || {}).length)
    report('update_recipes_packets', recipePackets)
    report('update_recipes_bytes', recipePacketBytes)
    report('registry_data_packets', registryPackets)
    report('game_version', bot.game && bot.game.version)
    report('protocol_version', bot._client.version)
    report('features', bot.registry.version.features || null)

    // Does a crafting table window even open?
    const table = bot.findBlock({
      matching: (b) => b && b.name === 'crafting_table',
      maxDistance: 8
    })
    report('crafting_table_nearby', table ? table.position : null)
    report('furnace_nearby', (() => {
      const f = bot.findBlock({ matching: (b) => b && b.name === 'furnace', maxDistance: 16 })
      return f ? f.position : null
    })())

    bot.quit()
    setTimeout(() => process.exit(0), 500)
  }, 12000)
})

bot.on('error', (err) => { console.log('error: ' + err.message) })
setTimeout(() => { console.log('timeout'); process.exit(1) }, 90000)
