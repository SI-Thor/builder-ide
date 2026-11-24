'use strict';
// bots/src/agent.js — one builder in the world.
//
// A builder is a mineflayer client with a role. What it does is not up to
// it: every tick it tells the reflex what it can see and what it needs,
// and the reflex answers with one skill to do. The skill is a small
// JavaScript function from the library, it runs in the sandbox, and its
// outcome is measured against the prediction the skill made.
//
// Three things are worth noticing:
//
// * **The pathing is not the agent's.** The skill says *what* to do
//   ("mine that oak log"); mineflayer's own planners work out how to get
//   there. The reflex chooses the decision, not the footsteps.
// * **The measure is the skill's own prediction.** A skill says what it
//   expects to change; the world checks it. That is what makes a win rate
//   mean something.
// * **Nothing about a human is recorded.** The log holds decisions and
//   outcomes. Chat and audio are never stored.

const crypto = require('node:crypto');
const mineflayer = require('mineflayer');
const { goals } = require('mineflayer-pathfinder');
const { buildApi, createSandbox, givePathfinding } = require('./api');
const { isAgent, parseCommand, HELP_LINE } = require('./humanity');

const ROLES = {
  gatherer: 'Gets the raw material the other builders need.',
  builder: 'Puts things together in the world.',
  scout: 'Looks around so the others know what is there.',
  farmer: 'Grows food so the world keeps going.',
};

class Agent {
  constructor({
    name,
    role,
    host,
    port,
    version,
    reflex,
    log,
    tickMs = 2000,
    offset = 0,
    onSpawn,
    guard = null,
  }) {
    this.name = name;
    this.role = role;
    this.host = host;
    this.port = port;
    this.version = version;
    this.reflex = reflex;
    this.log = log;
    this.tickMs = tickMs;
    this.offset = offset;
    this.onSpawn = onSpawn;
    this.guard = guard;

    // The other builders, set once everyone is in. A command heard by
    // four bots must be answered by one, and "who is nearest" needs the
    // whole crew's positions.
    this.community = [];

    this.bot = null;
    this.sandbox = null;
    this.api = null;
    this.counters = { mined: 0, placed: 0 };
    this.running = false;
    this.reconnecting = false;
    this.ticks = 0;
    this.plays = 0;
    this.wins = 0;
    this.losses = 0;
    this.lastConfidence = null;
    this.lastChoice = null;
    this.lastActivity = null;
    this.humanNames = new Set();
    this.duty = null;
    this.lastSaidAt = 0;
    this.lastRepliedAt = 0;
    this.pauseUntil = null;
  }

  // -- the connection ---------------------------------------------------------

  connect() {
    return new Promise((resolve, reject) => {
      this.bot = mineflayer.createBot({
        host: this.host,
        port: this.port,
        username: this.name,
        auth: 'offline',
        version: this.version,
        checkTimeoutInterval: 60000,
      });

      // A kick during login (Paper throttles same-IP reconnects after a
      // crash) closes the socket with 'end' and no 'error' — an
      // unsettled promise here hangs reconnect()'s await forever, and a
      // throttled builder never comes back (Pebble and Timber, 2026-11-02
      // 18:31Z). Only the first of spawn/error/end settles it.
      let settled = false;
      const settle = (fn, arg) => {
        if (settled) return;
        settled = true;
        fn(arg);
      };

      this.bot.once('spawn', () => {
        givePathfinding(this.bot, this.guard);
        this.api = buildApi(this.bot, this.counters, this.guard || undefined);
        this.sandbox = createSandbox(this.api);
        this.listenForPeople();
        this.watchTheBlocks();
        this.log.note({ bot: this.name, event: 'spawn', position: this.position() });
        if (this.onSpawn) this.onSpawn(this);
        settle(resolve, this);
      });

      this.bot.once('error', (err) => {
        this.log.note({ bot: this.name, event: 'error', detail: String(err.message || err) });
        settle(reject, err);
      });

      this.bot.on('kicked', (reason) => {
        this.log.note({ bot: this.name, event: 'kicked', detail: String(reason) });
      });

      this.bot.on('end', (reason) => {
        this.log.note({ bot: this.name, event: 'end', detail: String(reason) });
        settle(reject, new Error(`ended before spawn: ${String(reason)}`));
        // The world restarts, the network wobbles, the whitelist is
        // applied a second late: a builder that gives up is a builder
        // that never comes back. So it comes back.
        if (this.running) this.reconnect();
      });
    });
  }

  /** Come back after the world went away. */
  async reconnect() {
    if (this.reconnecting) return;
    this.reconnecting = true;
    while (this.running) {
      // Paper throttles reconnects from one address: wait longer than
      // the throttle window, and wait longer still for the builders
      // further down the line, so they do not all come back at once.
      await new Promise((resolve) => setTimeout(resolve, 15000 + this.offset * 7000));
      if (!this.running) break;
      try {
        this.bot = null;
        await this.connect();
        this.log.note({ bot: this.name, event: 'rejoined' });
        break;
      } catch (err) {
        this.log.note({
          bot: this.name,
          event: 'rejoin_failed',
          detail: String(err.message || err),
        });
      }
    }
    this.reconnecting = false;
  }

  position() {
    if (!this.bot || !this.bot.entity) return null;
    const p = this.bot.entity.position;
    return { x: Math.floor(p.x), y: Math.floor(p.y), z: Math.floor(p.z) };
  }

  // -- the tick ---------------------------------------------------------------

  /** What the builder can see and what it needs. This is the context. */
  context() {
    const t = this.bot ? this.bot.time.timeOfDay / 24000 : 0;
    const players = this.bot ? Object.values(this.bot.players) : [];
    const humans = players
      .filter((p) => p && p.username && p.username !== this.name)
      .filter((p) => !this.isAgent(p.username))
      .map((p) => p.username);
    this.humanNames = new Set(humans);
    return {
      bot: this.name,
      role: this.role,
      phase: t < 0.3 || t > 0.8 ? 'night' : 'day',
      time_of_day: Math.round(t * 1000) / 1000,
      health: this.bot ? this.bot.health : 20,
      food: this.bot ? this.bot.food : 20,
      has_material: this.bot ? this.bot.inventory.items().length > 0 : false,
      humans: humans.length,
      human_present: humans.length > 0,
      confidence: this.lastConfidence,
    };
  }

  /** The shared state the whole world's pack is asked over. */
  worldState() {
    const ctx = this.context();
    const phase = ctx.phase === 'day' ? 'daytime' : 'night';
    return (
      `${phase} in a Minecraft world. ` +
      `This builder is a ${ctx.role}. ` +
      `It has ${ctx.has_material ? 'some materials' : 'no materials'} and ` +
      `${ctx.humans === 0 ? 'no humans nearby' : `${ctx.humans} human(s) nearby`}.`
    );
  }

  isAgent(name) {
    return isAgent(name);
  }

  // -- the people -------------------------------------------------------------

  /**
   * Say one line, out loud. Rate-limited by default (a builder with a
   * narration every tick is noise, not company); a reply to a person is
   * never dropped — it is `force`, because whoever asked is waiting.
   * The line goes to the log too, as the builder's own words: that is
   * what the voices page speaks. Nothing a *person* said ever enters
   * the log (the privacy rule); this is the builder's line only.
   */
  say(text, { force = false } = {}) {
    if (!this.bot) return false;
    const now = Date.now();
    if (!force && now - this.lastSaidAt < 20000) return false;
    this.lastSaidAt = now;
    try {
      this.bot.chat(text);
    } catch (err) {
      // Not in the world yet; the line is dropped, not stored for later.
    }
    this.log.say({ bot: this.name, text });
    return true;
  }

  /** Chat and whispers: a person talking to the crew. */
  listenForPeople() {
    const heard = (username, message) => this.heard(username, message);
    this.bot.on('chat', heard);
    this.bot.on('whisper', heard);
  }

  /**
   * Watch the blocks change around us, so the no-grief ledger learns
   * what a person placed. Four builders see the same change; the ledger
   * takes it once.
   */
  watchTheBlocks() {
    if (!this.guard) return;
    this.bot.on('blockUpdate', (oldBlock, newBlock) => {
      try {
        this.guard.observe(oldBlock, newBlock);
      } catch (err) {
        // A ledger entry is protective, never load-bearing.
      }
    });
  }

  /**
   * One line of chat reached this builder. If it is a person and it is
   * one of the commands, exactly one builder acts on it — the named
   * one, the one whose role owns the job, or the nearest — except
   * "stop", which every builder obeys.
   */
  heard(username, message) {
    if (!username || username === this.name) return;
    if (isAgent(username)) return; // only people command the crew
    const parsed = parseCommand(message);
    if (!parsed) return; // free text is not on the tick

    if (parsed.addressee) {
      const named = this.community.find(
        (a) => a.name.toLowerCase() === parsed.addressee.toLowerCase()
      );
      if (!named || named !== this) return;
    } else if (parsed.route === 'role') {
      const owner = this.community.find((a) => a.role === parsed.role);
      if (!owner || owner !== this) return;
    } else if (parsed.route === 'nearest') {
      if (!this.iAmNearestTo(username)) return;
    }

    this.handleCommand(parsed.command, username, Boolean(parsed.addressee));
  }

  /** Am I the closest builder to this person? Ties go to the first name.
   *
   * A player's position lives on their *entity* (mineflayer's player
   * list carries no position of its own), and an entity is tracked
   * only while it is in view — so a person far from every builder has
   * no position anyone can rank, and nobody claims the command until
   * they are near enough to be seen. */
  iAmNearestTo(speaker) {
    const them = this.playerPosition(speaker);
    if (!them) return false;
    let best = null;
    let bestDistance = Infinity;
    for (const other of this.community) {
      if (!other.bot || !other.bot.entity) continue;
      const distance = other.bot.entity.position.distanceTo(them);
      if (distance < bestDistance - 0.5 || (distance < bestDistance + 0.5 && best && other.name < best.name)) {
        best = other;
        bestDistance = Math.min(bestDistance, distance);
      }
    }
    return best === this;
  }

  /** Where a player is, or null if they are out of sight (or gone). */
  playerPosition(name) {
    const entity = this.playerEntity(name);
    return entity ? entity.position : null;
  }

  /** The player's entity, the thing a follow can hold on to. */
  playerEntity(name) {
    const player = this.bot.players[name];
    if (player && player.entity) return player.entity;
    return (
      Object.values(this.bot.entities).find(
        (e) => e && e.type === 'player' && e.username === name && e.position
      ) || null
    );
  }

  /** The last place a player was seen — a person who runs out of view
   *  is still there, and a follower that wants to keep up walks to
   *  where they went. */
  rememberPlayer(name, position) {
    if (!this._remembered) this._remembered = new Map();
    this._remembered.set(name, { position: position.clone(), at: Date.now() });
  }

  rememberedPlayer(name, withinMs) {
    const row = this._remembered && this._remembered.get(name);
    if (!row || Date.now() - row.at > withinMs) return null;
    return row.position;
  }

  handleCommand(command, from, addressed = false) {
    // The word is logged, never the line around it: a person's words
    // are theirs (the privacy rule), and the crew's obedience is the
    // world's own record.
    this.log.note({ bot: this.name, event: 'command', command, from });
    switch (command) {
      case 'stop':
        this.clearDuty('stopped');
        this.interrupt();
        // A stop is seen, not merely done: the crew holds still for a
        // moment (releasing anything the planner still holds, every
        // tick, so no leaked goal can tail the person), and then takes
        // up its own work again.
        this.pauseUntil = Date.now() + 5000;
        if (this.iAmNearestTo(from)) this.say(`we've stopped, ${from}`, { force: true });
        return;
      case 'follow':
        this.setDuty({ kind: 'follow', player: from, expires: 15 * 60 * 1000 }, `following you, ${from}`);
        return;
      case 'come':
        this.setDuty({ kind: 'come', player: from, expires: 180 * 1000 }, `coming, ${from}`);
        return;
      case 'help-build':
        if (this.guard) this.guard.ledger.invite(this.name, from, 10);
        this.setDuty({ kind: 'assist', player: from, phase: 'approach', since: new Date().toISOString(), expires: 10 * 60 * 1000 }, `coming, ${from} — show me where to build`);
        return;
      case 'gather-wood':
        this.setDuty({ kind: 'gather', material: 'wood', player: from, phase: 'fetch', expires: 10 * 60 * 1000, tries: 0 }, `going for wood, ${from}`);
        return;
      case 'gather-stone':
        this.setDuty({ kind: 'gather', material: 'stone', player: from, phase: 'fetch', expires: 10 * 60 * 1000, tries: 0 }, `going for stone, ${from}`);
        return;
      case 'go-home':
        this.setDuty({ kind: 'home', expires: 5 * 60 * 1000 }, 'heading to the depot');
        return;
      case 'what-doing': {
        // A person who picked this builder by name is owed the answer
        // even if the crew answered a moment ago; the plain question
        // is rate-limited so four questions in a row are four
        // conversations, not one echo.
        if (!addressed && Date.now() - this.lastRepliedAt < 15000) return;
        this.lastRepliedAt = Date.now();
        const doing = this.duty
          ? {
              follow: `following ${this.duty.player}`,
              come: `coming to ${this.duty.player}`,
              home: 'walking to the depot',
              gather: `gathering ${this.duty.material} for ${this.duty.player}`,
              assist: `helping ${this.duty.player} build`,
            }[this.duty.kind]
          : this.lastActivity
            ? `working on: ${this.lastActivity}`
            : 'between jobs';
        this.say(`${this.name} is ${doing}`, { force: true });
        return;
      }
      case 'what-building': {
        if (Date.now() - this.lastRepliedAt < 15000) return;
        this.lastRepliedAt = Date.now();
        const board = this.shared && this.shared.board;
        this.say(
          board
            ? `the community is building: ${board.headline()}`
            : 'we keep no board yet',
          { force: true }
        );
        return;
      }
      case 'build-farm':
      case 'plant-trees':
      case 'build-shelter':
      case 'build-chest': {
        if (Date.now() - this.lastRepliedAt < 15000) return;
        this.lastRepliedAt = Date.now();
        const kinds = {
          'build-farm': 'farm',
          'plant-trees': 'replant',
          'build-shelter': 'shelter',
          'build-chest': 'depot-chest',
        };
        if (!this.shared || !this.shared.proposeFromHuman) return;
        const answer = this.shared.proposeFromHuman(kinds[command], from);
        this.say(`${answer}`, { force: true });
        return;
      }
      case 'help': {
        if (Date.now() - this.lastRepliedAt < 30000) return;
        this.lastRepliedAt = Date.now();
        this.say(HELP_LINE, { force: true });
        return;
      }
      default:
        return;
    }
  }

  /** A job from a person outranks the reflex until it is done. The
   *  `expires` given here is how long the job may run; the clock starts
   *  now. (The first battery run had it read as a timestamp, so every
   *  duty was born already expired — nine seconds of gathering, then
   *  "the duty ran out of time".) */
  setDuty(duty, line) {
    duty.expires = Date.now() + duty.expires;
    duty.since = new Date().toISOString();
    this.duty = duty;
    this.interrupt(); // whatever walk was under way stops for the person
    this.log.note({ bot: this.name, event: 'duty_set', kind: duty.kind, from: duty.player || null });
    if (line) this.say(line, { force: true });
  }

  clearDuty(why) {
    if (!this.duty) return;
    this.log.note({ bot: this.name, event: 'duty_clear', kind: this.duty.kind, why });
    // A follow holds the planner with a dynamic goal and walks with
    // the follower's movements; let both go with the duty.
    if (this.duty.kind === 'follow') {
      this.interrupt();
      this.workMovements();
    }
    this.duty = null;
  }

  /** The movements a follower walks with: no digging, parkour allowed. */
  followMovements() {
    const { Movements } = require('mineflayer-pathfinder');
    const movements = new Movements(this.bot);
    movements.canDigBlocks = false;
    this.bot.pathfinder.setMovements(movements);
  }

  /** The movements the skills work with (digs on the job, careful steps). */
  workMovements() {
    const { Movements } = require('mineflayer-pathfinder');
    const movements = new Movements(this.bot);
    movements.canDigBlocks = true;
    movements.allow1by1towers = false;
    movements.allowParkour = false;
    this.bot.pathfinder.setMovements(movements);
    // The depth floor, on the road as well as at the workface: the
    // crew mined itself into pits twice over (Pebble at bedrock for
    // hours; Kite found at y=32 a day later), and the planner was the
    // last door still open — a walk "east" would happily dig down
    // through a cave roof. No path may dig below y=48 — unless the
    // builder is already deep, when digging is the way *up* and the
    // floor would trap the very bot it protects.
    const floorY = 48;
    const deep = () => this.bot.entity && this.bot.entity.position.y < floorY - 3;
    try {
      const plain = movements.safeToBreak.bind(movements);
      movements.safeToBreak = (block) => {
        if (!plain(block)) return false;
        if (!block || !block.position) return true;
        if (block.position.y < floorY && !deep()) return false;
        if (this.guard) return this.guard.mayDig(block.position).ok;
        return true;
      };
    } catch (err) {
      // The planner's own rule stands; the api's guard still holds.
    }
  }

  /** Stop the walk under our feet, if there is one. A dynamic goal
   *  (the follow) is cleared too, or the planner would pick it up
   *  again the moment it is asked anything else. */
  interrupt() {
    try {
      if (this.bot.pathfinder) {
        this.bot.pathfinder.stop();
        this.bot.pathfinder.setGoal(null);
      }
    } catch (err) {
      // Nothing was walking.
    }
  }

  /**
   * One step of the duty. The tick loop calls this instead of the
   * reflex while a duty holds: a person's request is the one thing that
   * outranks the world's own work. No model is asked — the duty is a
   * goal, walked by the same planners the skills use, except "gather",
   * which asks the reflex for its family's skill like any other play
   * (the chooser still chooses; the play is still recorded).
   */
  async serviceDuty() {
    const duty = this.duty;
    if (!duty) return;
    let them = duty.player ? this.playerPosition(duty.player) : null;
    if (them) this.rememberPlayer(duty.player, them);
    if (duty.player && !them) {
      // Out of view is not gone: if they are still on the world's list
      // and were seen just now, walk to where they went.
      const remembered = this.rememberedPlayer(duty.player, 30000);
      const stillListed = Boolean(this.bot.players[duty.player]);
      if (remembered && stillListed) {
        them = remembered;
      } else {
        this.clearDuty(`${duty.player} left the world`);
        return;
      }
    }

    if (duty.kind === 'follow') {
      // A follow is not a series of walks to where the person *was*:
      // the planner's own GoalFollow holds the person's entity and
      // re-targets as they move. And a follower walks like a person —
      // no digging, parkour allowed — because the work movements (dig
      // on, parkour off) make the planner stall a few blocks from a
      // moving target and never close (probe-follow, FollowerM2:
      // 13.9 → 8.0 and then 8.0 forever; the same goal with walking
      // movements closed to 1.3 and held it).
      const entity = this.playerEntity(duty.player);
      if (entity && entity !== duty.goalEntity) {
        duty.goalEntity = entity;
        this.followMovements();
        try {
          this.bot.pathfinder.setGoal(new goals.GoalFollow(entity, 3), true);
        } catch (err) {
          // The planner could not take the goal; the next tick tries again.
        }
      }
      // The wedge, met where the follow lives: a builder pressed
      // against a face has paths computed for it (probe-follow saw
      // "success" every four seconds) and makes no first move, and the
      // walk's own un-wedge lives in gotoNear, which a follow never
      // calls. So the follow watches its own progress and nudges
      // itself loose the same way.
      const distance = entity
        ? this.bot.entity.position.distanceTo(entity.position)
        : null;
      const now = Date.now();
      if (
        distance !== null &&
        distance > 4 &&
        duty.lastDistance !== undefined &&
        Math.abs(distance - duty.lastDistance) < 0.5
      ) {
        duty.stalledSince = duty.stalledSince || now;
        if (now - duty.stalledSince > 8000) {
          duty.stalledSince = now;
          duty.lastDistance = undefined;
          duty.goalEntity = null; // force a fresh goal once loose
          const { nudge } = require('./api');
          await nudge(this.bot);
          return;
        }
      } else {
        duty.stalledSince = null;
      }
      duty.lastDistance = distance;
      // The follow's own heartbeat, sparse: what it is holding, and
      // how far behind. A follow that loses its person is a bug you
      // can only see in these numbers.
      if (!duty.lastProgressNote || Date.now() - duty.lastProgressNote > 5000) {
        duty.lastProgressNote = Date.now();
        this.log.note({
          bot: this.name,
          event: 'duty_progress',
          kind: 'follow',
          from: duty.player,
          distance: entity
            ? Math.round(this.bot.entity.position.distanceTo(entity.position) * 10) / 10
            : null,
          holding: Boolean(entity),
        });
      }
      return;
    }

    if (duty.kind === 'come' || duty.kind === 'home') {
      const target =
        duty.kind === 'home'
          ? this.api.depot()
          : { x: Math.floor(them.x), y: Math.floor(them.y), z: Math.floor(them.z) };
      const distance = this.bot.entity.position.distanceTo(
        new (require('vec3').Vec3)(target.x, target.y, target.z)
      );
      if (distance <= 3) {
        if (duty.kind === 'come') this.say(`here, ${duty.player}`, { force: true });
        this.clearDuty(duty.kind === 'home' ? 'home' : 'arrived');
        return;
      }
      await this.api.move_to(target.x, target.y, target.z);
      return;
    }

    if (duty.kind === 'gather') {
      await this.serviceGather(duty);
      return;
    }

    if (duty.kind === 'assist') {
      await this.serviceAssist(duty, them);
      return;
    }
  }

  /** "gather wood/stone": the family's skill through the reflex, then
   *  the goods carried to the person who asked. */
  async serviceGather(duty) {
    if (duty.phase === 'fetch') {
      const family = duty.material === 'wood' ? 'gatherer.wood' : 'gatherer.stone';
      let decision = null;
      try {
        decision = await this.reflex.decide({
          bot: this.name,
          role: this.role,
          context: this.context(),
          state: this.worldState(),
          family,
        });
      } catch (err) {
        this.log.note({
          bot: this.name,
          event: 'reflex_unreachable',
          detail: String(err.message || err),
        });
        return; // try again next tick, until the duty expires
      }
      if (!decision || !decision.skill_id) {
        this.say(`I can't get ${duty.material} right now, ${duty.player}`, { force: true });
        this.clearDuty('the reflex refused');
        return;
      }
      this.log.decision({
        bot: this.name,
        role: this.role,
        skill: decision.skill_id,
        title: decision.title,
        reason: 'command:' + family,
        confidence: decision.confidence,
      });
      const record = await this.play(decision, this.context());
      duty.phase = 'deliver';
      duty.how = record && record.outcome ? `${record.outcome.result}: ${record.outcome.detail}` : 'ran';
      return;
    }
    if (duty.phase === 'deliver') {
      const names =
        duty.material === 'wood'
          ? ['oak_log', 'spruce_log', 'birch_log', 'cherry_log', 'dark_oak_log', 'jungle_log', 'acacia_log', 'mangrove_log', 'pale_oak_log']
          : ['cobblestone', 'stone', 'cobbled_deepslate'];
      const taken = await this.api.take_from_depot(names);
      const target =
        this.playerPosition(duty.player) ||
        this.rememberedPlayer(duty.player, 60000);
      if (!target) {
        this.clearDuty(`${duty.player} left the world`);
        return;
      }
      if (!taken || !taken.ok) {
        // Nothing at the depot: the forest (or the stone) was not where
        // the skill looked. A person asked, so the gatherer walks to
        // new ground and looks again — up to three looks, then the
        // honest "nothing came of it".
        duty.tries = (duty.tries || 0) + 1;
        if (duty.tries < 3) {
          const home = this.api.depot();
          const angle = Math.random() * Math.PI * 2;
          const reach = 40 + Math.random() * 30;
          const x = Math.round(home.x + Math.cos(angle) * reach);
          const z = Math.round(home.z + Math.sin(angle) * reach);
          duty.phase = 'fetch';
          duty.how = taken && taken.detail ? taken.detail : 'nothing at the depot';
          this.say(`nothing there, ${duty.player} — trying farther out`, { force: true });
          await this.api.move_to(x, home.y, z);
          return;
        }
        this.say(`nothing came of it, ${duty.player} (${duty.how || 'the ground gave nothing'})`, { force: true });
        this.clearDuty('nothing to deliver');
        return;
      }
      await this.api.move_to(Math.floor(target.x), Math.floor(target.y), Math.floor(target.z));
      const item = this.bot.inventory.items().find((i) => i.name === taken.name);
      if (item) {
        try {
          await this.bot.toss(item.type, null, item.count);
        } catch (err) {
          // The goods stay in the bag; the next depot run returns them.
        }
      }
      this.say(
        `${taken.count} ${taken.name.replace(/_/g, ' ')} for you, ${duty.player}`,
        { force: true }
      );
      this.clearDuty('delivered');
    }
  }

  /** "help me build": stand with the person, and when they place a
   *  block, extend their line or hand them more of the same. */
  async serviceAssist(duty, them) {
    // The invite holds while we work together, and lapses when we don't.
    if (this.guard) this.guard.ledger.invite(this.name, duty.player, 10);

    if (duty.phase === 'approach') {
      if (this.bot.entity.position.distanceTo(them) <= 4) {
        duty.phase = 'by';
        this.say(`ready, ${duty.player} — place blocks and I'll carry on the line`, { force: true });
        return;
      }
      await this.api.move_to(Math.floor(them.x), Math.floor(them.y), Math.floor(them.z));
      return;
    }

    if (this.bot.entity.position.distanceTo(them) > 8) {
      await this.api.move_to(Math.floor(them.x), Math.floor(them.y), Math.floor(them.z));
      return;
    }

    const fresh = this.freshPlacements(duty.player, duty.since);
    const latest = fresh.length ? fresh[fresh.length - 1] : null;
    if (!latest) return;

    if (duty.lastKey !== latest.key) {
      duty.prev = duty.lastKey ? this.placementAt(duty.lastKey) : null;
      duty.lastKey = latest.key;
    }
    if (
      duty.prev &&
      manhattan(duty.prev, latest) === 1 &&
      Date.now() - (duty.assistedAt || 0) > 10000
    ) {
      const dx = latest.x - duty.prev.x;
      const dy = latest.y - duty.prev.y;
      const dz = latest.z - duty.prev.z;
      const target = { x: latest.x + dx, y: latest.y + dy, z: latest.z + dz };
      const have = this.api.inventory_count(latest.name);
      if (have > 0) {
        const placed = await this.api.place(latest.name, target.x, target.y, target.z);
        if (placed.ok) {
          duty.assistedAt = Date.now();
          this.say(`carried your ${latest.name.replace(/_/g, ' ')} on, ${duty.player}`, { force: true });
        }
        return;
      }
      // Nothing of the same kind: hand over what we build with, so the
      // person can carry the line themselves.
      if (Date.now() - (duty.tossedAt || 0) > 30000) {
        const stone = this.bot.inventory.items().find(
          (i) => i.name === 'cobblestone' || i.name === 'oak_planks'
        );
        if (stone) {
          try {
            await this.bot.toss(stone.type, null, Math.min(stone.count, 8));
            duty.tossedAt = Date.now();
            this.say(`no ${latest.name.replace(/_/g, ' ')} on me — here's ${stone.name.replace(/_/g, ' ')}`, { force: true });
          } catch (err) {
            // The toss is a courtesy; the duty holds.
          }
        }
      }
    }
  }

  /** The blocks a player has placed since an instant, newest last. */
  freshPlacements(player, sinceIso) {
    if (!this.guard) return [];
    const out = [];
    for (const row of this.guard.ledger.placed.values()) {
      if (row.by !== player) continue;
      if (String(row.at) <= String(sinceIso)) continue;
      const [x, y, z] = row.pos.split(',').map(Number);
      out.push({ key: row.pos, x, y, z, name: row.name, at: row.at });
    }
    out.sort((a, b) => (a.at < b.at ? -1 : 1));
    return out;
  }

  placementAt(key) {
    const [x, y, z] = key.split(',').map(Number);
    return { x, y, z };
  }

  async tick() {
    if (!this.bot || !this.bot.entity) return;
    // The pause after "stop": visibly still, and the planner is
    // re-released every tick so nothing can tail the person.
    if (this.pauseUntil && Date.now() < this.pauseUntil) {
      this.interrupt();
      return;
    }
    this.pauseUntil = null;
    // A person's request outranks the world's own work, and it never
    // waits on a model: the duty is walked, not asked.
    if (this.duty) {
      if (Date.now() > this.duty.expires) {
        this.clearDuty('the duty ran out of time');
      } else {
        try {
          await this.serviceDuty();
        } catch (err) {
          this.log.note({
            bot: this.name,
            event: 'duty_failed',
            kind: this.duty ? this.duty.kind : 'gone',
            detail: String(err.message || err),
          });
        }
        return;
      }
    }
    this.ticks += 1;

    // The drift detector's hold (§3.5 soft): this builder waits on its
    // own safe branch and stops committing — the reflex refuses its
    // asks already; the project path must not route around the hold.
    // A person's duty (above) still ranks: a held builder still answers
    // a person, because the promises in PLAY.md outrank the detector.
    if (this.shared && this.shared.pauseFor) {
      const hold = this.shared.pauseFor(this.name);
      if (hold) {
        this.interrupt();
        // Ask the reflex anyway: its refusal is recorded there as a
        // drift.yield, and a yield is what excuses the wait in the
        // detector's stall signal. A silent hold looks exactly like a
        // stall — the first live hold renewed itself on its own
        // silence (07:58 UTC, "drift signal stall+success") until the
        // ask came back.
        //
        // Once every 30 s, not every tick: the detector's windows are
        // minutes wide, so a yield every half-minute keeps the window
        // covered without writing a row per tick to the log of record.
        const now = Date.now();
        if (!this._holdAskedAt || now - this._holdAskedAt > 30000) {
          this._holdAskedAt = now;
          try {
            await this.reflex.decide({
              bot: this.name,
              role: this.role,
              context: this.context(),
              state: this.worldState(),
            });
          } catch (err) {
            // The refusal is the point, not the answer.
          }
        }
        if (!this._holdNotedAt || Date.now() - this._holdNotedAt > 60000) {
          this._holdNotedAt = Date.now();
          this.log.note({
            bot: this.name,
            event: 'drift_hold',
            level: hold.level || 'soft',
            reason: hold.reason || '',
          });
        }
        return;
      }
    }

    // The community's own work: a ratified project for this role is
    // served before the reflex is asked, because the plan — the
    // council's, ratified by the validator — *is* the decision. The
    // step runs and is recorded as a play (skill `project.<kind>`,
    // prediction none: counted on the board, not scored here), so the
    // ledger sees the world working whether a model was asked or not.
    if (this.shared && this.shared.projects) {
      const work = this.shared.projects.service(this);
      if (work) {
        this.lastActivity = work.title;
        await this.play(work, this.context());
        return;
      }
    }

    // The crew is still assembling — this builder just spawned and the
    // shared board is not wired yet. A reflex tick NOW runs a library
    // skill that knows nothing of any project: the farmer's "break up
    // the ground and leave the bag at the depot" dumped a craftable
    // hoe's planks and sticks (and a given seed) onto the pile one
    // second after spawn, on every restart (21:10:42Z spawn,
    // 21:10:43Z decision, 21:11:21Z "left the bag at the depot"). Idle
    // this tick instead; the community arrives within seconds.
    if (!this.shared || !this.shared.projects) return;

    const ctx = this.context();
    let decision;
    try {
      decision = await this.reflex.decide({
        bot: this.name,
        role: this.role,
        context: ctx,
        state: this.worldState(),
      });
    } catch (err) {
      this.log.note({
        bot: this.name,
        event: 'reflex_unreachable',
        detail: String(err.message || err),
      });
      return;
    }

    if (!decision || !decision.skill_id) {
      this.lastChoice = decision && decision.reason ? decision.reason : 'no_decision';
      this.log.decision({
        bot: this.name,
        role: this.role,
        skill: null,
        reason: this.lastChoice,
        detail: (decision && decision.detail) || '',
      });
      return;
    }

    this.lastConfidence =
      typeof decision.confidence === 'number' ? decision.confidence : this.lastConfidence;
    this.lastChoice = decision.reason;
    this.lastActivity = decision.title || this.lastActivity;
    this.log.decision({
      bot: this.name,
      role: this.role,
      skill: decision.skill_id,
      title: decision.title,
      reason: decision.reason,
      confidence: decision.confidence,
      propensity: decision.propensity,
      candidates: decision.candidates,
    });

    await this.play(decision, ctx);
  }

  // -- the play ---------------------------------------------------------------

  async play(decision, ctx) {
    const started = Date.now();
    const before = {
      mined: this.counters.mined,
      placed: this.counters.placed,
      position: this.position(),
      inventory: this.inventoryMap(),
    };

    let result = { done: false, detail: 'the skill did not run' };
    let failure = null;
    try {
      // A skill's body is source text the sandbox runs; a project
      // step's body is a function the projects service built (a plan
      // walked in the world, recorded as a play like any other).
      result =
        typeof decision.body === 'function'
          ? await decision.body()
          : (await this.sandbox.run(decision.body)) || result;
    } catch (err) {
      failure = String((err && err.message) || err);
    }

    const outcome = this.measure(decision.predict || { kind: 'none' }, before, failure);
    // The skill's own reason is part of the record: "there is nothing at
    // the depot" is the difference between a skill that failed and a
    // skill that had no reason to run.
    const said = result && result.detail ? String(result.detail) : '';
    if (said && outcome.detail && !outcome.detail.includes(said)) {
      outcome.detail = `${outcome.detail} — ${said}`;
    }
    // A duty may carry its own result too: a project step that mined,
    // staged, or delivered material is a won play, whatever the sealed
    // prediction's default says. The drift detector's success signal
    // reads exactly these rows, and a crew whose every play scores
    // 'partial' can never show its baseline a healthy rate (2026-11-02:
    // the gatherer worked all morning while 20 projects sat at zero).
    if (!failure && result && (result.result === 'win' || result.result === 'lose')) {
      outcome.result = result.result;
      outcome.score = result.result === 'win' ? 1 : 0;
    }
    const wall = (Date.now() - started) / 1000;

    const record = {
      id: 'play_' + crypto.randomBytes(6).toString('hex'),
      at: new Date().toISOString(),
      skill_id: decision.skill_id,
      skill_version: decision.skill_version || 1,
      context: Object.assign({}, ctx, {
        confidence: this.lastConfidence,
        chooser_reason: decision.reason,
      }),
      outcome,
      cost: { wall_seconds: wall, gpu_minutes: 0, hosted_cents: 0 },
      chooser: 'bandit/ctx-v1+judge',
      chooser_version: '1',
      propensity: typeof decision.propensity === 'number' ? decision.propensity : null,
      candidates: decision.candidates || [],
    };

    this.plays += 1;
    if (outcome.result === 'win') this.wins += 1;
    if (outcome.result === 'lose') this.losses += 1;

    this.log.outcome({
      bot: this.name,
      skill: decision.skill_id,
      result: outcome.result,
      measure: outcome.measure,
      detail: outcome.detail,
      wall_seconds: Number(wall.toFixed(3)),
    });

    try {
      await this.reflex.play(record);
    } catch (err) {
      this.log.note({
        bot: this.name,
        event: 'play_not_recorded',
        detail: String(err.message || err),
      });
    }
    return record;
  }

  inventoryMap() {
    const map = {};
    if (!this.bot) return map;
    for (const item of this.bot.inventory.items()) map[item.name] = item.count;
    return map;
  }

  /** Did the prediction hold? This is the measure the record carries. */
  measure(predict, before, failure) {
    const detail = (result) =>
      failure ? `the skill failed: ${failure}` : (result && result.detail) || '';

    if (failure) {
      return { result: 'lose', measure: 'sealed_prediction', score: 0, detail: failure };
    }

    const kind = predict && predict.kind ? predict.kind : 'none';
    const min = predict && predict.min ? predict.min : 1;

    if (kind === 'inventory_delta') {
      const after = this.inventoryMap();
      const item = predict.item;
      const gained = (after[item] || 0) - (before.inventory[item] || 0);
      return {
        result: gained >= min ? 'win' : 'lose',
        measure: 'sealed_prediction',
        score: gained >= min ? 1 : 0,
        detail: `${item} ${gained >= 0 ? '+' : ''}${gained} (wanted ${min})`,
      };
    }
    if (kind === 'block_placed') {
      const placed = this.counters.placed - before.placed;
      return {
        result: placed >= min ? 'win' : 'lose',
        measure: 'sealed_prediction',
        score: placed >= min ? 1 : 0,
        detail: `${placed} block(s) placed (wanted ${min})`,
      };
    }
    if (kind === 'block_broken') {
      const mined = this.counters.mined - before.mined;
      return {
        result: mined >= min ? 'win' : 'lose',
        measure: 'sealed_prediction',
        score: mined >= min ? 1 : 0,
        detail: `${mined} block(s) mined (wanted ${min})`,
      };
    }
    if (kind === 'moved_to') {
      const now = this.position();
      let moved = 0;
      if (now && before.position) {
        moved = Math.sqrt(
          Math.pow(now.x - before.position.x, 2) +
            Math.pow(now.y - before.position.y, 2) +
            Math.pow(now.z - before.position.z, 2)
        );
      }
      return {
        result: moved >= min ? 'win' : 'lose',
        measure: 'sealed_prediction',
        score: moved >= min ? 1 : 0,
        detail: `moved ${moved.toFixed(1)} blocks (wanted ${min})`,
      };
    }
    // No measurable effect: the play happened, but it cannot be called a
    // win or a loss. It is partial, and it says so.
    return {
      result: 'partial',
      measure: 'sealed_prediction',
      score: null,
      detail: detail(null) || 'the skill ran; it made no measurable change',
    };
  }

  // -- the loop ---------------------------------------------------------------

  start() {
    this.running = true;
    const loop = async () => {
      while (this.running) {
        try {
          await this.tick();
        } catch (err) {
          this.log.note({
            bot: this.name,
            event: 'tick_failed',
            detail: String(err.message || err),
          });
        }
        await new Promise((resolve) => setTimeout(resolve, this.tickMs));
      }
    };
    loop();
  }

  stop() {
    this.running = false;
    if (this.bot) this.bot.quit('the world is resting');
  }
}

// The names the world owns live in humanity.js now, with the rest of
// how a builder behaves when a person is in the world.
function manhattan(a, b) {
  return Math.abs(a.x - b.x) + Math.abs(a.y - b.y) + Math.abs(a.z - b.z);
}

module.exports = { Agent, ROLES };
