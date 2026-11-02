// Empty the sandbox bot's inventory.
//
// A measurement of a tech tree has to start from nothing: if the bot
// walks in already holding the first milestone, the tree is already
// climbed and the numbers say nothing about what the loop did. The
// crashed first run left one oak_log in the bot's hand, so the saved
// player file is emptied before the measured run starts.
//
// The file is the same one move_bot.js writes: world/players/data/
// <uuid>.dat, gzipped NBT. The server must be stopped while it is
// written, or Paper keeps its own copy and wins.
//
// Usage:
//   ~/lm-wt/agent-world/runtime/node/bin/node \
//       docs/lab/voyager-port-scripts/reset_hands.js

'use strict'

const fs = require('fs')
const path = require('path')
const zlib = require('zlib')

const MINECRAFT_DIR = process.env.VOYAGER_MINECRAFT_DIR ||
  '/home/caseydigennaro/lm-wt/agent-world/bots'
const nbt = require(path.join(MINECRAFT_DIR, 'node_modules', 'prismarine-nbt'))

const SANDBOX = process.env.VOYAGER_SANDBOX ||
  (process.env.HOME + '/lm-wt/voyager-port/mc-sandbox')
const PLAYERS = path.join(SANDBOX, 'world', 'players', 'data')

// The tags that hold what the player is carrying.
const CARRIED = ['Inventory', 'EnderItems']

// The shape of one tag in this file: a list tag is
// {type: 'list', value: {type: <the element type>, value: [the tags]}},
// so emptying a list means emptying the array inside it and leaving
// the element type alone.
function emptyTag (tag) {
  if (!tag || typeof tag !== 'object') return false
  if (tag.type !== 'list') return false
  const inner = tag.value
  if (!inner || typeof inner !== 'object') return false
  if (!Array.isArray(inner.value)) return false
  inner.value = []
  return true
}

async function main () {
  const names = fs.readdirSync(PLAYERS).filter((n) => n.endsWith('.dat'))
  if (!names.length) {
    console.log('no player file in ' + PLAYERS)
    process.exit(1)
  }
  for (const name of names) {
    const file = path.join(PLAYERS, name)
    const plain = zlib.gunzipSync(fs.readFileSync(file))
    const root = await nbt.parseUncompressed(plain)
    const map = root.value
    for (const key of CARRIED) {
      const tag = map[key]
      if (!tag) {
        console.log('  no ' + key + ' tag')
        continue
      }
      console.log('  ' + key + ' is a ' + tag.type + ': ' +
        JSON.stringify(tag.value).slice(0, 200))
      const inner = tag.value
      const before = inner && Array.isArray(inner.value) ? inner.value.length : -1
      if (!emptyTag(tag)) {
        console.log('    could not empty it')
        continue
      }
      console.log('    ' + before + ' entries -> 0')
    }
    const backup = file + '.before-clear'
    if (!fs.existsSync(backup)) fs.copyFileSync(file, backup)
    const out = zlib.gzipSync(await nbt.writeUncompressed(root))
    fs.writeFileSync(file, out)
    console.log('  written (' + out.length + ' bytes)')
  }
}

main().catch((err) => {
  console.log('failed: ' + err.message)
  process.exit(1)
})
