'use strict';
// viewer/src/translate.js — the bridge between the world's version and the
// viewer's version.
//
// The Thor runs Minecraft 26.1. prismarine-viewer's browser bundle was
// built against 1.21.4: its textures, its block models and the
// minecraft-data tables inside it stop there. Its version lookup
// (viewer/lib/version.js) answers null for '26.1' — '26.1' is not a
// major.minor it knows — so the page says "null is not supported" and
// draws nothing.
//
// So the translation happens here, on the server, where minecraft-data
// has both versions. Every 26.1 block state is re-encoded as the 1.21.4
// block state with the same name and the same properties:
//
//   26.1 state id  ->  (block name, properties)  ->  1.21.4 state id
//
// The world is not changed. The bots, the skills and the reflex all still
// speak 26.1; only the bytes on their way to the browser are re-encoded.
//
// A block that 1.21.4 does not have is drawn as the nearest block it does
// have (fallback-blocks.js), and the fact is counted, so the page can say
// so rather than quietly lying.

const registry = require('prismarine-registry');
const BitArray = require('prismarine-chunk/src/pc/common/BitArrayNoSpan');
const FALLBACK_BLOCKS = require('./fallback-blocks');

// One block changed its property between the two versions: the creaking
// heart used to say whether it was creaking, and now says what state it
// is in. The alias says how one is read as the other.
const PROPERTY_ALIASES = {
  creaking_heart: {
    creaking_heart_state: {
      as: 'active',
      value: (value) => (value === 'awake' ? 'true' : 'false'),
    },
  },
};

// A block can keep its name and still gain a value: 26.1's note block can
// be a copper trumpet, which 1.21.4 has no note block for. The table
// says which 1.21.4 sound stands in for it.
const VALUE_FALLBACKS = {
  note_block: {
    instrument: {
      trumpet: 'bell',
      trumpet_exposed: 'bell',
      trumpet_oxidized: 'bell',
      trumpet_weathered: 'bell',
    },
  },
};

/**
 * Read the property values a state id stands for.
 *
 * The state ids of one block run from its minStateId to its maxStateId.
 * Within that run, the first property varies slowest and the last varies
 * fastest — the same order minecraft uses and the same order
 * prismarine-block reads them in.
 */
function decodeProperties(blockEnum, stateId) {
  const properties = {};
  const states = blockEnum.states || [];
  let data = stateId - blockEnum.minStateId;
  for (let i = states.length - 1; i >= 0; i--) {
    const prop = states[i];
    properties[prop.name] = propertyValue(prop, data % prop.num_values);
    data = Math.floor(data / prop.num_values);
  }
  return properties;
}

/** The value of one property at one of its positions. */
function propertyValue(prop, index) {
  if (prop.type === 'enum' || prop.values) return prop.values[index];
  if (prop.type === 'bool') return !index;
  return index;
}

/**
 * The position of a value inside a property's list of values.
 *
 * A value the target does not have (26.1's copper trumpets on a note
 * block, say) falls back to the target's first value, and says so.
 */
function valueIndex(prop, value) {
  if (value === undefined || value === null) return 0;
  if (prop.type === 'enum' || prop.values) {
    const index = prop.values.indexOf(String(value));
    return index < 0 ? 0 : index;
  }
  if (prop.type === 'bool') {
    if (value === true || value === 'true') return 0;
    if (value === false || value === 'false') return 1;
    return 0;
  }
  const number = Number(value);
  return Number.isFinite(number) ? number : 0;
}

/** Is this value one the target property knows? */
function valueKnown(prop, value) {
  if (value === undefined || value === null) return true;
  if (prop.type === 'enum' || prop.values) {
    return prop.values.indexOf(String(value)) >= 0;
  }
  return true;
}

class Translator {
  /**
   * @param {string} sourceVersion the version the world speaks
   * @param {string} targetVersion the version the browser can draw
   */
  constructor(sourceVersion, targetVersion) {
    this.sourceVersion = sourceVersion;
    this.targetVersion = targetVersion;
    this.source = registry(sourceVersion);
    this.target = registry(targetVersion);
    this.air = this.target.blocksByName.air.minStateId;

    // source state id -> target state id
    this.map = new Map();
    // source block name -> { target, why } for the blocks drawn as a stand-in
    this.standIns = new Map();
    // source block name -> [notes] for the blocks drawn approximately
    this.approximations = new Map();
    // source block name -> how many times it was drawn
    this.usage = new Map();
    // source biome id -> target biome id
    this.biomes = new Map();
    // anything that could not be re-encoded exactly
    this.warnings = [];

    this.build();
  }

  build() {
    const sourceBlocks = this.source.blocksByName;
    const targetBlocks = this.target.blocksByName;

    for (const biome of Object.values(this.source.biomes || {})) {
      const target = Object.values(this.target.biomes || {}).find(
        (b) => b.name === biome.name
      );
      if (target) this.biomes.set(biome.id, target.id);
    }

    for (const name of Object.keys(sourceBlocks)) {
      const sourceBlock = sourceBlocks[name];
      const targetBlock = targetBlocks[name];

      if (!targetBlock) {
        const standIn = FALLBACK_BLOCKS[name] || 'air';
        const target = targetBlocks[standIn];
        if (!target) {
          throw new Error(
            `the fallback for ${name} is ${standIn}, which ${this.targetVersion} does not have`
          );
        }
        this.standIns.set(name, {
          target: standIn,
          why:
            standIn === 'air'
              ? `${name} is new in ${this.sourceVersion} and has no ${this.targetVersion} twin`
              : `${name} is new in ${this.sourceVersion}; ${standIn} is drawn in its place`,
        });
      }

      for (let stateId = sourceBlock.minStateId; stateId <= sourceBlock.maxStateId; stateId++) {
        this.map.set(stateId, this.encode(sourceBlock, stateId, targetBlock));
      }
    }
  }

  /**
   * Re-encode one source state id as the target state id that looks the same.
   */
  encode(sourceBlock, stateId, targetBlock) {
    // The block itself is missing from the target: draw the stand-in.
    if (!targetBlock) {
      const standIn = this.target.blocksByName[FALLBACK_BLOCKS[sourceBlock.name] || 'air'];
      return this.encodeBlock(standIn, {}, sourceBlock.name);
    }

    const properties = decodeProperties(sourceBlock, stateId);
    const aliases = PROPERTY_ALIASES[sourceBlock.name] || {};

    // Read the source's properties into the target's language.
    const valueFallbacks = VALUE_FALLBACKS[sourceBlock.name] || {};
    const targetProperties = {};
    for (const [key, value] of Object.entries(properties)) {
      const alias = aliases[key];
      if (alias) {
        targetProperties[alias.as] = alias.value(value);
        continue;
      }
      const fallback = (valueFallbacks[key] || {})[String(value)];
      if (fallback) {
        targetProperties[key] = fallback;
        const seen = this.approximations.get(sourceBlock.name) || new Set();
        seen.add(`${key}=${value} is new in ${this.sourceVersion}; ${fallback} is drawn instead`);
        this.approximations.set(sourceBlock.name, seen);
        continue;
      }
      targetProperties[key] = value;
    }

    // Note where the two versions disagree.
    const notes = [];
    const targetStates = targetBlock.states || [];
    for (const prop of targetStates) {
      if (targetProperties[prop.name] === undefined) {
        notes.push(`${prop.name} has no ${this.sourceVersion} value; ${this.targetVersion}'s first is drawn`);
      } else if (!valueKnown(prop, targetProperties[prop.name])) {
        notes.push(`${prop.name}=${targetProperties[prop.name]} is new in ${this.sourceVersion}; ${this.targetVersion}'s first is drawn`);
      }
    }
    for (const key of Object.keys(properties)) {
      if (aliases[key]) continue;
      const known = targetStates.some((prop) => prop.name === key);
      if (!known) {
        notes.push(`${key} is new in ${this.sourceVersion} and is not drawn`);
      }
    }

    const targetStateId = this.encodeBlock(targetBlock, targetProperties, sourceBlock.name);
    if (notes.length) {
      const seen = this.approximations.get(sourceBlock.name) || new Set();
      for (const note of notes) seen.add(note);
      this.approximations.set(sourceBlock.name, seen);
    }
    return targetStateId;
  }

  /** The target's state id for a block and its properties. */
  encodeBlock(targetBlock, properties, sourceName) {
    let data = 0;
    let offset = 1;
    const states = targetBlock.states || [];
    for (let i = states.length - 1; i >= 0; i--) {
      const prop = states[i];
      data += offset * valueIndex(prop, properties[prop.name]);
      offset *= prop.num_values;
    }
    return targetBlock.minStateId + data;
  }

  /**
   * The target state id for a source state id.
   */
  translate(stateId) {
    if (typeof stateId !== 'number' || !Number.isFinite(stateId)) return this.air;
    const target = this.map.get(stateId);
    if (target === undefined) return this.air;

    const sourceBlock = this.source.blocksByStateId[stateId];
    if (sourceBlock) {
      this.usage.set(sourceBlock.name, (this.usage.get(sourceBlock.name) || 0) + 1);
    }
    return target;
  }

  /**
   * Re-encode a chunk column: every block state and every biome in it.
   *
   * A section's blocks live in a palette container (prismarine-chunk
   * calls it that too), and there are three kinds:
   *
   *   'indirect' the usual one: a list of states and a bit array of
   *             indexes into that list. The list is re-encoded and keeps
   *             its length, so the bit array still means the same thing.
   *   'single'  one state for the whole section. The state is re-encoded.
   *   'direct'  the global palette: the bit array holds the states
   *             themselves. Each one is read, re-encoded and written back.
   */
  translateChunk(chunkJson) {
    const column = JSON.parse(chunkJson);

    if (Array.isArray(column.sections)) {
      for (let i = 0; i < column.sections.length; i++) {
        const raw = column.sections[i];
        if (typeof raw !== 'string') continue;
        const section = JSON.parse(raw);
        section.data = this.translateContainer(section.data, false);
        column.sections[i] = JSON.stringify(section);
      }
    }

    if (Array.isArray(column.biomes)) {
      for (let i = 0; i < column.biomes.length; i++) {
        const raw = column.biomes[i];
        if (typeof raw !== 'string') continue;
        column.biomes[i] = this.translateContainer(raw, true);
      }
    }

    return JSON.stringify(column);
  }

  /**
   * Re-encode one palette container.
   */
  translateContainer(containerJson, isBiome) {
    if (typeof containerJson !== 'string') return containerJson;
    let container;
    try {
      container = JSON.parse(containerJson);
    } catch (err) {
      return containerJson;
    }
    if (!container || typeof container !== 'object') return containerJson;

    if (container.type === 'indirect' && Array.isArray(container.palette)) {
      container.palette = container.palette.map((id) =>
        isBiome ? this.translateBiome(id) : this.translate(id)
      );
    } else if (container.type === 'single') {
      container.value = isBiome
        ? this.translateBiome(container.value)
        : this.translate(container.value);
    } else if (container.type === 'direct') {
      container.data = this.translateDirect(container.data, isBiome);
    }

    return JSON.stringify(container);
  }

  /**
   * Re-encode a direct container: the bit array holds the states itself.
   */
  translateDirect(bitArrayJson, isBiome) {
    if (typeof bitArrayJson !== 'string') return bitArrayJson;
    let array;
    try {
      array = BitArray.fromJson(bitArrayJson);
    } catch (err) {
      return bitArrayJson;
    }
    for (let i = 0; i < array.capacity; i++) {
      const value = array.get(i);
      const translated = isBiome ? this.translateBiome(value) : this.translate(value);
      if (translated > array.valueMask) {
        // The target's states do not fit in the bits the source used.
        // This has never happened: both versions need fifteen bits.
        this.warnings.push(
          `a direct palette of ${array.bitsPerValue} bits cannot hold ${translated}`
        );
        return bitArrayJson;
      }
      array.set(i, translated);
    }
    return array.toJson();
  }

  /**
   * The target's id for a biome.
   */
  translateBiome(biomeId) {
    if (typeof biomeId !== 'number' || !Number.isFinite(biomeId)) return 0;
    const target = this.biomes.get(biomeId);
    if (target !== undefined) return target;
    // A biome 1.21.4 does not have is drawn as the plains.
    const plains = Object.values(this.target.biomes || {}).find(
      (b) => b.name === 'plains'
    );
    return plains ? plains.id : 0;
  }

  /**
   * Every block that is drawn approximately, whether or not it is in view.
   */
  allApproximations() {
    const all = [];
    for (const [name, notes] of this.approximations) {
      all.push({ from: name, notes: [...notes] });
    }
    all.sort((a, b) => a.from.localeCompare(b.from));
    return all;
  }

  /**
   * What the page needs to say about the drawing.
   */
  stats() {
    const standIns = [];
    const approximations = [];
    for (const [name, count] of this.usage) {
      const standIn = this.standIns.get(name);
      if (standIn) {
        standIns.push({ from: name, to: standIn.target, why: standIn.why, count });
      }
      const notes = this.approximations.get(name);
      if (notes) {
        approximations.push({ from: name, notes: [...notes], count });
      }
    }
    standIns.sort((a, b) => b.count - a.count);
    approximations.sort((a, b) => b.count - a.count);

    return {
      source: this.sourceVersion,
      target: this.targetVersion,
      blocksDrawn: this.usage.size,
      drawn: [...this.usage.keys()].sort(),
      standIns,
      approximations,
      warnings: this.warnings,
      exact: standIns.length === 0 && approximations.length === 0 && this.warnings.length === 0,
    };
  }
}

module.exports = { Translator, decodeProperties, PROPERTY_ALIASES, FALLBACK_BLOCKS };
