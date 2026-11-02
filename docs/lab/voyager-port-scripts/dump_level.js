'use strict'
const fs = require('fs')
const path = require('path')
const zlib = require('zlib')
const MINECRAFT_DIR = '/home/caseydigennaro/lm-wt/agent-world/bots'
const nbt = require(path.join(MINECRAFT_DIR, 'node_modules', 'prismarine-nbt'))
const LEVEL = (process.env.VOYAGER_SANDBOX || process.env.HOME + '/lm-wt/voyager-port/mc-sandbox') + '/world/level.dat'

async function main () {
  const plain = zlib.gunzipSync(fs.readFileSync(LEVEL))
  const parsed = await nbt.parseUncompressed(plain)
  const simple = nbt.simplify(parsed)
  console.log('root keys: ' + JSON.stringify(Object.keys(simple)))
  console.log('spawn compound: ' + JSON.stringify(simple.Data.spawn))
  console.log('paperSpawnDimension: ' + JSON.stringify(simple.Data.paperSpawnDimension))
  for (const key of Object.keys(simple)) {
    const value = simple[key]
    if (value && typeof value === 'object' && !Array.isArray(value)) {
      console.log(key + ' -> ' + JSON.stringify(Object.keys(value)).slice(0, 900))
    } else {
      console.log(key + ' = ' + JSON.stringify(value).slice(0, 200))
    }
  }
}
main().catch((e) => { console.log('failed: ' + e.message) })
