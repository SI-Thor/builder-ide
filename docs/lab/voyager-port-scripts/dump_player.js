'use strict'
const fs = require('fs')
const path = require('path')
const zlib = require('zlib')
const MINECRAFT_DIR = '/home/caseydigennaro/lm-wt/agent-world/bots'
const nbt = require(path.join(MINECRAFT_DIR, 'node_modules', 'prismarine-nbt'))
const dir = process.env.VOYAGER_SANDBOX ||
  (process.env.HOME + '/lm-wt/voyager-port/mc-sandbox')

async function main () {
  const files = fs.readdirSync(dir + '/world/players/data')
  for (const name of files) {
    if (!name.endsWith('.dat')) continue
    const plain = zlib.gunzipSync(
      fs.readFileSync(dir + '/world/players/data/' + name))
    const parsed = await nbt.parseUncompressed(plain)
    const simple = nbt.simplify(parsed)
    console.log(name + ' keys: ' + JSON.stringify(Object.keys(simple)))
    for (const key of Object.keys(simple)) {
      const value = simple[key]
      if (value && typeof value === 'object' && !Array.isArray(value)) {
        console.log('  ' + key + ' -> ' + JSON.stringify(Object.keys(value)).slice(0, 300))
      } else {
        console.log('  ' + key + ' = ' + JSON.stringify(value).slice(0, 120))
      }
    }
  }
}
main().catch((e) => { console.log('failed: ' + e.message) })
