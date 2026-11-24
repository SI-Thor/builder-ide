'use strict';
// ops/check-translation.js — is the 26.1 → 1.21.4 drawing honest?
//
// The browser cannot draw Minecraft 26.1: prismarine-viewer's assets and
// its bundled minecraft-data stop at 1.21.4. So the server re-encodes
// every block state on its way to the page. This checks that the
// re-encoding is right, without a browser:
//
//   1. every 26.1 state id lands on a 1.21.4 state id of the same block
//      (or on the documented stand-in);
//   2. the properties survive the round trip, block for block;
//   3. the stand-ins are all blocks 1.21.4 really has;
//   4. a chunk keeps its shape: the palette keeps its length, the bit
//      array is untouched, and every entry is a real 1.21.4 state;
//   5. all three kinds of palette container survive it.
//
// Run: node ops/check-translation.js

const path = require('node:path');
const { Translator, decodeProperties } = require(path.join(__dirname, '..', 'viewer', 'src', 'translate.js'));

const SOURCE = process.env.AW_MINECRAFT_VERSION || '26.1';
const TARGET = '1.21.4';

let failures = 0;
function check(ok, message) {
  if (!ok) {
    failures += 1;
    console.log(`  FAIL  ${message}`);
  }
}

console.log(`the drawing: ${SOURCE} → ${TARGET}`);
const translator = new Translator(SOURCE, TARGET);

console.log('\n1. every state id lands on the right block');
let mismatched = 0;
for (const [stateId, targetStateId] of translator.map) {
  const sourceBlock = translator.source.blocksByStateId[stateId];
  const targetBlock = translator.target.blocksByStateId[targetStateId];
  if (!sourceBlock || !targetBlock) {
    mismatched += 1;
    continue;
  }
  const standIn = translator.standIns.get(sourceBlock.name);
  const wanted = standIn ? standIn.target : sourceBlock.name;
  if (targetBlock.name !== wanted) mismatched += 1;
}
console.log(`  ${translator.map.size} state ids, ${mismatched} on the wrong block`);
check(mismatched === 0, `${mismatched} state ids land on the wrong block`);

console.log('\n2. the properties survive the round trip');
const signature = (block) =>
  (block.states || []).map((s) => s.name + ':' + s.type).join(',');
let lost = 0;
let approximated = 0;
let compared = 0;
for (const name of Object.keys(translator.source.blocksByName)) {
  const sourceBlock = translator.source.blocksByName[name];
  const targetBlock = translator.target.blocksByName[name];
  if (!targetBlock) continue;
  // Only the blocks whose properties are the same in both versions can be
  // compared like for like; the others are the documented approximations.
  if (signature(sourceBlock) !== signature(targetBlock)) continue;
  for (let stateId = sourceBlock.minStateId; stateId <= sourceBlock.maxStateId; stateId++) {
    const targetStateId = translator.map.get(stateId);
    const before = decodeProperties(sourceBlock, stateId);
    const after = decodeProperties(targetBlock, targetStateId);
    compared += 1;
    for (const [key, value] of Object.entries(before)) {
      if (String(after[key]) === String(value)) continue;
      // A value the target cannot hold at all is an approximation, and is
      // named in the notes below; anything else is a mistake.
      const prop = (targetBlock.states || []).find((p) => p.name === key);
      if (prop && prop.values && prop.values.indexOf(String(value)) < 0) {
        approximated += 1;
        break;
      }
      lost += 1;
      if (lost <= 5) {
        console.log(`  FAIL  ${name} ${key}: ${value} → ${after[key]}`);
      }
      break;
    }
  }
}
console.log(`  ${compared} states compared, ${lost} lost a property, ${approximated} drawn approximately`);
check(lost === 0, `${lost} states lost a property on the way`);

console.log('\n3. the stand-ins are real 1.21.4 blocks');
let badStandIns = 0;
for (const [name, standIn] of translator.standIns) {
  if (!translator.target.blocksByName[standIn.target]) {
    badStandIns += 1;
    console.log(`  FAIL  ${name} → ${standIn.target}, which ${TARGET} does not have`);
  }
}
console.log(`  ${translator.standIns.size} stand-ins, ${badStandIns} imaginary`);
check(badStandIns === 0, `${badStandIns} stand-ins are not real blocks`);

// The three kinds of palette container a section can hold.
const bitArray = (bitsPerValue, capacity, values) => ({
  data: values,
  capacity,
  bitsPerValue,
  valuesPerLong: Math.floor(64 / bitsPerValue),
  valueMask: (1 << bitsPerValue) - 1,
});
const container = (kind, extra) =>
  JSON.stringify({ type: kind, maxBits: 15, maxBitsPerBlock: 15, ...extra });

console.log('\n4. a chunk keeps its shape');
const palette = [0, 1, 2, 45, 46, 137, 20000];
const chunk = JSON.stringify({
  worldHeight: 384,
  minY: -64,
  sections: [
    JSON.stringify({
      noSizePrefix: true,
      hasFluidCount: true,
      data: container('indirect', {
        palette,
        data: JSON.stringify(bitArray(4, 4096, [1, 2, 3, 4])),
      }),
      solidBlockCount: 100,
      fluidCount: 4,
    }),
  ],
  biomes: [container('single', { value: 7, bitsPerValue: 1, capacity: 64 })],
  blockEntities: {},
});
const translated = JSON.parse(translator.translateChunk(chunk));
const section = JSON.parse(translated.sections[0]);
const containerOut = JSON.parse(section.data);
const containerIn = JSON.parse(JSON.parse(chunk).sections[0]).data;
console.log(`  palette ${palette.length} → ${containerOut.palette.length}`);
check(containerOut.palette.length === palette.length, 'the palette changed length');
check(
  containerOut.data === JSON.parse(containerIn).data,
  'the bit array changed'
);
let outOfRange = 0;
for (const stateId of containerOut.palette) {
  if (!translator.target.blocksByStateId[stateId]) outOfRange += 1;
}
check(outOfRange === 0, `${outOfRange} palette entries are not real ${TARGET} states`);
console.log(`  every palette entry is a real ${TARGET} state: ${outOfRange === 0}`);

console.log('\n5. all three kinds of palette container survive it');
// 'single': one state for the whole section.
const single = JSON.parse(
  JSON.parse(
    translator.translateChunk(
      JSON.stringify({
        sections: [
          JSON.stringify({
            data: container('single', { value: 137, bitsPerValue: 4, capacity: 4096 }),
          }),
        ],
      })
    )
  ).sections[0]
);
const singleValue = JSON.parse(single.data).value;
console.log(`  single: 137 → ${singleValue}`);
check(
  translator.target.blocksByStateId[singleValue] !== undefined,
  'the single-value container did not survive'
);
check(
  translator.target.blocksByStateId[singleValue].name === 'oak_log',
  'the single-value container changed its block'
);

// 'direct': the bit array holds the states themselves.
const BitArray = require(path.join(
  __dirname,
  '..',
  'viewer',
  'node_modules',
  'prismarine-chunk',
  'src',
  'pc',
  'common',
  'BitArrayNoSpan'
));
const directArray = BitArray.fromArray([137, 46, 1, 0], 15);
directArray.capacity = 4096;
const directChunk = JSON.stringify({
  sections: [
    JSON.stringify({
      data: container('direct', { data: directArray.toJson() }),
    }),
  ],
});
const direct = JSON.parse(
  JSON.parse(translator.translateChunk(directChunk)).sections[0]
);
const directOut = BitArray.fromJson(JSON.parse(direct.data).data);
const directNames = [0, 1, 2, 3].map((i) =>
  translator.target.blocksByStateId[directOut.get(i)].name
);
const wantedNames = [137, 46, 1, 0].map(
  (sourceId) => translator.target.blocksByStateId[translator.map.get(sourceId)].name
);
console.log(`  direct: ${wantedNames.join(', ')} → ${directNames.join(', ')}`);
check(
  directNames.join(',') === wantedNames.join(','),
  'the direct container changed its blocks'
);

// The biomes go too.
const biomeOut = JSON.parse(JSON.parse(translator.translateChunk(chunk)).biomes[0]).value;
console.log(`  biome 7 → ${biomeOut}`);
check(
  Object.values(translator.target.biomes).some((b) => b.id === biomeOut),
  'the biome was not re-encoded'
);

console.log('\n6. the approximations that are left, named');
const all = translator.allApproximations();
for (const approximation of all) {
  console.log(`  ${approximation.from}: ${approximation.notes.join('; ')}`);
}
if (all.length === 0) console.log('  none');
console.log(
  `\n  ${translator.standIns.size} blocks are drawn as a stand-in, ${all.length} are drawn approximately`
);

console.log('');
if (failures) {
  console.log(`the drawing is not honest: ${failures} checks failed`);
  process.exit(1);
}
console.log('the drawing is honest: every state id lands where it should');
