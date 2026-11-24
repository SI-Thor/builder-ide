'use strict';
// viewer/src/server.js — the world's window.
//
// One port, two views:
//
//   /            the 3D view (prismarine-viewer): the world as a
//                spectator sees it, with the builders in it
//   /ascii       the Syzygy text view of one perspective: the same
//                world, projected into text by an integer kernel
//   /ascii/frame the current text frame (plain text)
//   /status      who is in the world and what the reflex is doing
//
// The viewer joins the world as "Watcher", a spectator that stands at
// the depot. It needs no account of its own: the world is LAN-only and
// the whitelist is the door.

const path = require('node:path');
const fs = require('node:fs');
const http = require('node:http');
const express = require('express');
const socketio = require('socket.io');
const mineflayer = require('mineflayer');
const { pathfinder: pathfinderPlugin, Movements, goals } = require('mineflayer-pathfinder');
const { WorldView } = require('prismarine-viewer/viewer');
const { supportedVersions, getVersion } = require('prismarine-viewer/viewer/lib/version');
const ENTITY_MODELS = require('prismarine-viewer/viewer/lib/entity/entities.json');
const { project } = require('./ascii');
const { Translator } = require('./translate');

const DEFAULTS = {
  host: process.env.AW_HOST || '192.168.0.78',
  port: Number(process.env.AW_PAPER_PORT || 25565),
  version: process.env.AW_MINECRAFT_VERSION || '26.1',
  webPort: Number(process.env.AW_VIEW_PORT || 8080),
  reflexHost: process.env.AW_REFLEX_HOST || '127.0.0.1',
  reflexPort: Number(process.env.AW_REFLEX_PORT || 8110),
  botLog:
    process.env.AW_BOT_LOG ||
    path.join(path.dirname(path.dirname(__dirname)), 'runtime', 'logs', 'bots.jsonl'),
  name: 'Watcher',
};

const PUBLIC_DIR = path.join(__dirname, '..', 'public');
const VIEWER_PUBLIC = path.join(
  path.dirname(require.resolve('prismarine-viewer/package.json')),
  'public'
);
// The voice engine and the ORT wasm files it needs, served from the
// packages themselves: the page never reaches the internet. The
// packages' exports map does not name their dist files, so the dist
// directory is found through the package's own entry point.
const KOKORO_DIST = path.dirname(require.resolve('kokoro-js'));
const TRANSFORMERS_DIST = path.dirname(require.resolve('@huggingface/transformers'));

// --- the drawing ------------------------------------------------------------
//
// The world runs Minecraft 26.1. prismarine-viewer's browser bundle was
// built against 1.21.4, and its version lookup answers null for 26.1 —
// so the page used to say "null is not supported" and draw nothing.
//
// So the server re-encodes the world's block states into the version the
// browser can draw (translate.js), and tells the page that version. If
// even that version's assets are missing, the page says so and points at
// the text view rather than going blank.

const LATEST_SUPPORTED = supportedVersions[supportedVersions.length - 1];

// The mobs the browser has a model for. Anything else is left out of the
// drawing rather than drawn as a magenta box.
const DRAWABLE_ENTITIES = new Set(Object.keys(ENTITY_MODELS));

/** Are the browser's assets for this version on the server? */
function assetsFor(version) {
  return {
    blocksStates: fs.existsSync(path.join(VIEWER_PUBLIC, 'blocksStates', `${version}.json`)),
    textures: fs.existsSync(path.join(VIEWER_PUBLIC, 'textures', `${version}.png`)),
  };
}

/**
 * Which version the page draws with, and whether it can draw at all.
 */
function planFor(sourceVersion) {
  const exact = getVersion(sourceVersion);
  const target = exact || LATEST_SUPPORTED;
  const assets = assetsFor(target);
  const plan = {
    ok: assets.blocksStates && assets.textures,
    source: sourceVersion,
    target,
    translated: exact === null,
    supported: supportedVersions,
  };
  if (!plan.ok) {
    plan.message =
      `This browser build cannot draw Minecraft ${sourceVersion}, and the assets ` +
      `for ${target} are not on the server either.`;
  }
  return plan;
}

/**
 * The socket, with the world's version translated on the way out.
 *
 * The WorldView emits the world's own block states: 26.1's. The browser
 * draws 1.21.4's. So the chunk palettes and the block updates are
 * re-encoded here, on their way to the page.
 */
class TranslatingSocket {
  constructor(socket, translator) {
    this.socket = socket;
    this.translator = translator;
  }

  on(event, handler) {
    this.socket.on(event, handler);
  }

  emit(event, payload) {
    if (event === 'entity') {
      const entity = this.drawable(payload);
      if (entity) this.socket.emit(event, entity);
      return;
    }
    if (!this.translator) {
      this.socket.emit(event, payload);
      return;
    }
    if (event === 'loadChunk') {
      this.socket.emit(event, {
        ...payload,
        chunk: this.translator.translateChunk(payload.chunk),
      });
      return;
    }
    if (event === 'blockUpdate') {
      this.socket.emit(event, {
        ...payload,
        stateId: this.translator.translate(payload.stateId),
      });
      return;
    }
    this.socket.emit(event, payload);
  }

  /**
   * What the browser can draw of an entity.
   *
   * prismarine-viewer has a model for a fixed list of mobs. A mob with no
   * model is left out: the browser would otherwise draw it as a magenta
   * box and say so in the console. A player is drawn as a player, with
   * their name above them.
   *
   * An entity with **no name at all** is left out too. The browser's
   * fallback for a name-less entity is a box sized from `width` and
   * `height`, and a name-less entity has neither — 26.1 knows entities
   * the viewer's 1.21.4 tables do not — so the box is built from
   * `undefined` and its geometry is pure NaN. Every load printed a
   * dozen "Computed radius is NaN" warnings for the dozen such
   * entities in view (the playtest of 2026-11-01). A departure still
   * goes through: the page must forget what it once drew.
   */
  drawable(entity) {
    if (entity.delete) return entity;
    if (!entity.name) return null;
    if (entity.username) return { ...entity, name: 'player' };
    if (DRAWABLE_ENTITIES.has(entity.name)) return entity;
    return null;
  }
}

/**
 * Move the watcher somewhere it can see.
 *
 * A spectator that spawns under a tree canopy sees only leaves, in both
 * views. So the watcher looks for a patch of open ground near the spawn
 * and walks to it: a place with four blocks of air above it, which in a
 * forest means a clearing.
 */
async function standClear(bot) {
  bot.loadPlugin(pathfinderPlugin);
  const movements = new Movements(bot);
  movements.canDigBlocks = false;
  bot.pathfinder.setMovements(movements);

  const origin = bot.entity.position.floored();
  const candidates = [];
  for (let radius = 3; radius <= 12; radius += 3) {
    for (let dx = -radius; dx <= radius; dx += 3) {
      for (let dz = -radius; dz <= radius; dz += 3) {
        if (dx === 0 && dz === 0) continue;
        candidates.push({ x: origin.x + dx, z: origin.z + dz });
      }
    }
  }

  for (const spot of candidates) {
    if (!isOpen(bot, spot)) continue;
    try {
      await bot.pathfinder.goto(new goals.GoalNear(spot.x, origin.y, spot.z, 1));
      console.log(`the watcher stood at ${bot.entity.position.floored()}`);
      return;
    } catch (err) {
      // Try the next patch.
    }
  }
}

/** Is there open sky above this column? */
function isOpen(bot, spot) {
  for (let dy = 1; dy <= 4; dy++) {
    const block = bot.blockAt(
      new (require('vec3').Vec3)(spot.x, spot.y + dy, spot.z)
    );
    if (!block) continue;
    if (block.name !== 'air' && block.name !== 'cave_air' && block.name !== 'void_air') {
      return false;
    }
  }
  return true;
}

async function main() {
  const app = express();
  const server = http.createServer(app);
  const io = socketio(server, { path: '/socket.io' });

  // Our own 3D page: prismarine-viewer's own client, with the banner that
  // says how the world is being drawn and the message that appears when
  // the version cannot be drawn at all. It is served before the static
  // files, so it is the page "/" gives.
  app.get('/', (req, res) => {
    const file = path.join(PUBLIC_DIR, 'index.html');
    if (!fs.existsSync(file)) {
      res.status(404).type('text/plain').send('the 3D page is missing');
      return;
    }
    res.type('html').send(fs.readFileSync(file, 'utf8'));
  });

  // The 3D view is prismarine-viewer's own client, served as it is.
  app.use(express.static(VIEWER_PUBLIC));
  // Our own pages (the ASCII view, the voices) come second, so they can add to it.
  app.use(express.static(PUBLIC_DIR));
  // The voice engine's own files: the Kokoro web build and the ONNX
  // Runtime wasm binaries it loads. Served from node_modules so the
  // page runs with no build step and no internet.
  app.use('/vendor/kokoro', express.static(KOKORO_DIST));
  app.use('/vendor/transformers', express.static(TRANSFORMERS_DIST));
  app.use(express.text({ type: 'text/plain' }));

  // --- the watcher -----------------------------------------------------------
  const bot = mineflayer.createBot({
    host: DEFAULTS.host,
    port: DEFAULTS.port,
    username: DEFAULTS.name,
    auth: 'offline',
    version: DEFAULTS.version,
  });

  bot.on('error', (err) => console.log('watcher error:', err.message));
  bot.on('end', (reason) => console.log('watcher ended:', reason));
  bot.on('kicked', (reason) => console.log('watcher kicked:', reason));

  const sockets = [];
  let plan = null;
  let translator = null;

  bot.once('spawn', () => {
    console.log(`the watcher is in the world at ${bot.entity.position}`);
    plan = planFor(bot.version || DEFAULTS.version);
    if (plan.ok) {
      if (plan.translated) {
        translator = new Translator(plan.source, plan.target);
        console.log(
          `the 3D view draws ${plan.source} as ${plan.target}: the browser has no ${plan.source} assets`
        );
      } else {
        console.log(`the 3D view draws ${plan.source} as it is`);
      }
    } else {
      console.log(plan.message);
    }
    standClear(bot).catch((err) => {
      console.log('the watcher stayed where it landed:', err.message);
    });
    io.on('connection', (socket) => {
      socket.emit('version', plan ? plan.target : DEFAULTS.version);
      sockets.push(socket);

      const worldView = new WorldView(
        bot.world,
        6,
        bot.entity.position,
        new TranslatingSocket(socket, translator)
      );
      worldView.init(bot.entity.position);

      function botPosition() {
        socket.emit('position', {
          pos: bot.entity.position,
          yaw: bot.entity.yaw,
          addMesh: true,
        });
        worldView.updatePosition(bot.entity.position);
      }

      bot.on('move', botPosition);
      worldView.listenToBot(bot);
      socket.on('disconnect', () => {
        bot.removeListener('move', botPosition);
        worldView.removeListenersFromBot(bot);
        sockets.splice(sockets.indexOf(socket), 1);
      });
    });
  });

  // --- the text view ---------------------------------------------------------
  // The frame is computed on demand, from the watcher's own state. The
  // kernel is integer and deterministic, so two readers of the same
  // state get the same characters.
  let lastFrame = '';
  let lastFrameAt = 0;

  app.get('/voices', (req, res) => {
    const file = path.join(PUBLIC_DIR, 'voices.html');
    if (!fs.existsSync(file)) {
      res.status(404).type('text/plain').send('the voices page is missing');
      return;
    }
    res.type('html').send(fs.readFileSync(file, 'utf8'));
  });

  // --- the events -------------------------------------------------------------
  // The narrated feed for the voices: the agents' plays, as they were
  // recorded in the world's own log. It holds decisions and outcomes and
  // nothing about a human (no chat, no audio — the kids' privacy rule),
  // so there is nothing here a voice must never say.
  const skillsByReflex = { cached: null, at: 0 };

  async function skillsIndex() {
    if (skillsByReflex.cached && Date.now() - skillsByReflex.at < 60000) {
      return skillsByReflex.cached;
    }
    try {
      const response = await fetch(
        `http://${DEFAULTS.reflexHost}:${DEFAULTS.reflexPort}/skills`
      );
      const body = await response.json();
      const index = new Map(
        (body.skills || []).map((s) => [
          s.id,
          { family: s.family, role: s.role, title: s.title },
        ])
      );
      skillsByReflex.cached = index;
      skillsByReflex.at = Date.now();
    } catch (err) {
      // The reflex is down or restarting; the last index still names
      // most of the skills, and a play with no name is still a play.
    }
    return skillsByReflex.cached || new Map();
  }

  app.get('/events', async (req, res) => {
    const after = String(req.query.after || '');
    const limit = Math.min(Number(req.query.limit) || 60, 200);
    const index = await skillsIndex();
    let lines = [];
    try {
      const tail = await fs.promises.readFile(DEFAULTS.botLog, 'utf8');
      lines = tail.trim().split('\n').slice(-800);
    } catch (err) {
      res.json({ events: [] });
      return;
    }
    const events = [];
    for (const line of lines) {
      let record = null;
      try {
        record = JSON.parse(line);
      } catch (err) {
        continue;
      }
      if (!record.bot) continue;
      if (record.kind !== 'outcome' && record.kind !== 'say') continue;
      if (after && String(record.at) <= after) continue;
      if (record.kind === 'say') {
        // The builder's own spoken line — its greeting, its answer to a
        // person, its word about its work. This is what the voices page
        // speaks. A person's words are never in this log, so there is
        // nothing here that must not be said aloud (the privacy rule).
        events.push({
          kind: 'say',
          at: record.at,
          bot: record.bot,
          text: String(record.text || ''),
        });
        if (events.length >= limit) break;
        continue;
      }
      const skill = index.get(record.skill) || {};
      events.push({
        kind: 'outcome',
        at: record.at,
        bot: record.bot,
        role: skill.role || null,
        family: skill.family || null,
        title: skill.title || null,
        result: record.result,
        detail: record.detail || '',
      });
      if (events.length >= limit) break;
    }
    res.json({ events });
  });

  app.get('/view-plan', (req, res) => {
    if (!plan) {
      res.json({
        ok: false,
        message: 'the watcher is not in the world yet',
        textView: '/ascii',
      });
      return;
    }
    res.json({ ...plan, textView: '/ascii' });
  });

  app.get('/ascii', (req, res) => {
    const file = path.join(PUBLIC_DIR, 'ascii.html');
    if (!fs.existsSync(file)) {
      res.status(404).type('text/plain').send('the ASCII page is missing');
      return;
    }
    res.type('html').send(fs.readFileSync(file, 'utf8'));
  });

  app.get('/ascii/frame', (req, res) => {
    if (!bot.entity) {
      res.type('text/plain').send('(the watcher is not in the world yet)');
      return;
    }
    const width = Math.min(Number(req.query.width) || 96, 200);
    const height = Math.min(Number(req.query.height) || 30, 60);
    const frame = project(bot, { width, height });
    lastFrame = frame;
    lastFrameAt = Date.now();
    res.type('text/plain').send(frame);
  });

  app.get('/status', async (req, res) => {
    const people = bot.players
      ? Object.values(bot.players)
          .filter((p) => p && p.username)
          .map((p) => ({ name: p.username, position: p.position }))
      : [];
    let reflex = null;
    try {
      const response = await fetch(`http://${DEFAULTS.reflexHost}:${DEFAULTS.reflexPort}/stats`);
      reflex = await response.json();
    } catch (err) {
      reflex = { error: 'the reflex did not answer' };
    }
    res.json({
      world: {
        host: DEFAULTS.host,
        port: DEFAULTS.port,
        version: DEFAULTS.version,
        watcher: bot.entity ? bot.entity.position : null,
      },
      people,
      reflex,
      // How the world is being drawn: which version the page gets, and
      // what had to be approximated to get there.
      view: plan,
      drawing: translator ? translator.stats() : null,
    });
  });

  server.listen(DEFAULTS.webPort, '0.0.0.0', () => {
    console.log(`the world's window is on http://${DEFAULTS.host}:${DEFAULTS.webPort}/`);
    console.log(`  3D view  : http://${DEFAULTS.host}:${DEFAULTS.webPort}/`);
    console.log(`  text view: http://${DEFAULTS.host}:${DEFAULTS.webPort}/ascii`);
  });
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
