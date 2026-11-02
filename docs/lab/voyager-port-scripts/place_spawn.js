// Put the sandbox's spawn where the tech tree is.
//
// The private world's spawn is on a beach: the nearest tree was 86
// blocks away, and a bot that has to cross that before it can cut a
// log is a measurement of the pathfinder, not of the loop. The spawn
// is moved to the foot of the tree instead.
//
// The spawn lives in the world's level.dat, which is gzipped NBT, and
// the bot's own saved position lives in world/players/data/<uuid>.dat,
// also gzipped NBT. Both are rewritten: the spawn so a fresh world
// starts at the tree, and the saved position so the bot that has
// already been here does not come back to the beach.
//
// Usage:
//   ~/lm-wt/agent-world/runtime/node/bin/node \
//       docs/lab/voyager-port-scripts/place_spawn.js <x> <y> <z>
//
// It prints what it found and what it changed, and leaves the old
// files beside the new ones.

'use strict'

const fs = require('fs')
const path = require('path')
const zlib = require('zlib')

const MINECRAFT_DIR = process.env.VOYAGER_MINECRAFT_DIR ||
  '/home/caseydigennaro/lm-wt/agent-world/bots'
const nbt = require(path.join(MINECRAFT_DIR, 'node_modules', 'prismarine-nbt'))

const SANDBOX = process.env.VOYAGER_SANDBOX ||
  (process.env.HOME + '/lm-wt/voyager-port/mc-sandbox')
const WORLD = path.join(SANDBOX, 'world')
const LEVEL = path.join(WORLD, 'level.dat')
const PLAYERS = path.join(WORLD, 'players', 'data')

const target = process.argv.slice(2).map(Number)
if (target.length !== 3 || target.some(Number.isNaN)) {
  console.log('usage: place_spawn.js <x> <y> <z>')
  process.exit(2)
}

// Every tag whose name mentions a spawn, with where it sits.
function findSpawns (value, trail) {
  const out = []
  if (!value || typeof value !== 'object') return out
  if (Array.isArray(value.value)) {
    value.value.forEach((entry, index) => {
      out.push(...findSpawns(entry, trail + '[' + index + ']'))
    })
    return out
  }
  if (typeof value.value === 'object' && value.value !== null) {
    for (const key of Object.keys(value.value)) {
      const child = value.value[key]
      const here = trail + '.' + key
      if (/spawn/i.test(key)) out.push({ path: here, tag: child })
      out.push(...findSpawns(child, here))
    }
  }
  return out
}

async function readNbt (file) {
  const plain = zlib.gunzipSync(fs.readFileSync(file))
  return await nbt.parseUncompressed(plain)
}

async function writeNbt (file, root) {
  const backup = file + '.before-spawn'
  if (!fs.existsSync(backup)) fs.copyFileSync(file, backup)
  const out = zlib.gzipSync(await nbt.writeUncompressed(root))
  fs.writeFileSync(file, out)
}

async function patchLevel (x, y, z) {
  const root = await readNbt(LEVEL)
  const spawns = findSpawns(root, '')
  console.log('spawn tags in ' + LEVEL + ':')
  for (const entry of spawns) {
    console.log('  ' + entry.path + ' = ' + JSON.stringify(entry.tag.value))
  }
  let changed = 0
  for (const entry of spawns) {
    const tag = entry.tag
    // The shape in this world: Data.spawn.pos is an int array of three.
    if (tag.type === 'compound' && tag.value && tag.value.pos) {
      const pos = tag.value.pos
      if (pos.type === 'intArray' || pos.type === 'list') {
        pos.type = 'intArray'
        pos.value = [Math.floor(x), Math.floor(y), Math.floor(z)]
        console.log('  set ' + entry.path + '.pos = ' + JSON.stringify([x, y, z]))
        changed++
        continue
      }
    }
    if (tag.type === 'list' && Array.isArray(tag.value) && tag.value.length === 3) {
      tag.value = [
        { type: 'int', value: Math.floor(x) },
        { type: 'int', value: Math.floor(y) },
        { type: 'int', value: Math.floor(z) }
      ]
      console.log('  set ' + entry.path + ' = ' + JSON.stringify([x, y, z]))
      changed++
      continue
    }
    // The older shape: SpawnX, SpawnY and SpawnZ beside each other.
    const key = entry.path.split('.').pop().toLowerCase()
    let value = null
    if (key === 'spawnx') value = Math.floor(x)
    else if (key === 'spawny') value = Math.floor(y)
    else if (key === 'spawnz') value = Math.floor(z)
    if (value === null) continue
    tag.value = value
    console.log('  set ' + entry.path + ' = ' + value)
    changed++
  }
  if (!changed) {
    console.log('no spawn tag was changed')
    return false
  }
  await writeNbt(LEVEL, root)
  console.log('wrote ' + LEVEL)
  return true
}

async function patchPlayers (x, y, z) {
  // The bot has a saved position from the last time it was here, and
  // that position wins over the world spawn. Moving the saved file
  // aside is the honest way to start over: the bot comes back as a
  // first-time player and appears at the spawn the world now names.
  let names = []
  try {
    // The .dat_old file is the crash-recovery copy, and the server
    // falls back to it when the .dat file is missing: both go.
    names = fs.readdirSync(PLAYERS).filter((n) => n.endsWith('.dat') || n.endsWith('.dat_old'))
  } catch (err) {
    names = []
  }
  if (!names.length) {
    console.log('no player data to move')
    return true
  }
  for (const name of names) {
    const file = path.join(PLAYERS, name)
    const moved = file + '.before-spawn'
    fs.renameSync(file, moved)
    console.log('  moved ' + name + ' aside; the bot starts fresh at the spawn')
  }
  return true
}

async function main () {
  const [x, y, z] = target
  const ok = await patchLevel(x, y, z)
  if (!ok) process.exit(1)
  await patchPlayers(x, y, z)
  console.log('the sandbox now starts at (' + x + ', ' + y + ', ' + z + ')')
}

main().catch((err) => {
  console.log('failed: ' + err.message)
  process.exit(1)
})
