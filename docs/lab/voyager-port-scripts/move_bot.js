// Move the sandbox's bot to where the tech tree is.
//
// The bot's saved position lives in world/players/data/<uuid>.dat,
// gzipped NBT, and it wins over the world spawn every time the bot
// joins. The bot was 87 blocks from the only tree and could not walk
// there: the pathfinder got it about twenty-four blocks in four
// minutes and stopped. So the saved position is moved to the foot of
// the tree.
//
// Usage:
//   ~/lm-wt/agent-world/runtime/node/bin/node \
//       docs/lab/voyager-port-scripts/move_bot.js <x> <y> <z>

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

const target = process.argv.slice(2).map(Number)
if (target.length !== 3 || target.some(Number.isNaN)) {
  console.log('usage: move_bot.js <x> <y> <z>')
  process.exit(2)
}

// The root of a player file, as a tag.
async function readRoot (file) {
  const plain = zlib.gunzipSync(fs.readFileSync(file))
  return await nbt.parseUncompressed(plain)
}

function setThree (node, want) {
  if (!node) return false
  if (Array.isArray(node.value)) {
    if (node.value.length === 3 && typeof node.value[0] === 'number') {
      node.value = want
      return true
    }
    for (const entry of node.value) {
      if (entry && Array.isArray(entry.value)) {
        entry.value = want
        return true
      }
    }
    return false
  }
  if (node.value && typeof node.value === 'object') {
    if (Array.isArray(node.value.value)) {
      node.value.value = want
      return true
    }
    if (node.value.value && typeof node.value.value === 'object') {
      return setThree(node.value.value, want)
    }
  }
  return false
}

function setPos (root, x, y, z) {
  const map = root.value
  if (!map || typeof map !== 'object') return false
  let pos = map.Pos
  if (!pos) {
    const key = Object.keys(map).find((k) => k.toLowerCase() === 'pos')
    if (key) pos = map[key]
  }
  if (!pos) return false
  console.log('  the Pos tag is a ' + pos.type + ' with ' +
    JSON.stringify(pos.value).slice(0, 120))
  return setThree(pos, [x + 0.5, y, z + 0.5])
}

async function main () {
  const [x, y, z] = target
  const names = fs.readdirSync(PLAYERS).filter((n) => n.endsWith('.dat'))
  if (!names.length) {
    console.log('no player file in ' + PLAYERS)
    process.exit(1)
  }
  for (const name of names) {
    const file = path.join(PLAYERS, name)
    const root = await readRoot(file)
    const simple = nbt.simplify(root)
    console.log(name + ' Pos was ' + JSON.stringify(simple.Pos))
    if (!setPos(root, x, y, z)) {
      console.log('  could not set Pos; the root has ' +
        JSON.stringify(Object.keys(simple)).slice(0, 200))
      continue
    }
    const backup = file + '.before-move'
    if (!fs.existsSync(backup)) fs.copyFileSync(file, backup)
    const out = zlib.gzipSync(await nbt.writeUncompressed(root))
    fs.writeFileSync(file, out)
    console.log('  Pos is now ' + JSON.stringify([x + 0.5, y, z + 0.5]) +
      ' (' + out.length + ' bytes written)')
  }
}

main().catch((err) => {
  console.log('failed: ' + err.message)
  process.exit(1)
})
