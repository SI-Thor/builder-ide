'use strict';
// bots/src/council.js — the planner: what the world needs next.
//
// "The council" is deterministic first: every council tick it looks at
// the world (through one builder's eyes — they all see the same one)
// and turns what it finds into project proposals, in a fixed order of
// need. A model is never asked to *decide*; the only model on this
// path is a DeepInfra call that may *propose* a new project when the
// deterministic needs are all met, and its proposal faces the same
// validator as everyone else's — an unknown kind is denied, an
// out-of-bounds scope is denied, and a denied proposal is only a
// logged line, never a build.
//
// The order of need (each line is the brief's own list):
//   1. open issues on a project        — the tester's findings first
//   2. a chest at the depot            — the pile loses goods (the
//                                        playtest's own finding)
//   3. the spawn forest replanted      — a night of chopping took it
//   4. a farm by the depot             — food the world grows itself
//   5. a path to a standing site       — the walk the crew wears
//   6. a shelter                       — a roof over the depot work
//
// A proposal the validator allows is **ratified** and waits on the
// board for its owner's role; `ask_human` holds it; `deny` abandons it
// with the verdict written down. Nothing starts unratified.

const { validate } = require('./validator');
const { rawBill } = require('./materials');

const DEFAULTS = {
  intervalMs: 60 * 1000, // a council tick every minute
  proposeCooldownMs: 30 * 60 * 1000, // a model proposal at most every half hour
  stallNoteMs: 30 * 60 * 1000, // when a project's silence is worth a note
  stallAbandonMs: 90 * 60 * 1000, // and when it is worth giving up
  denyCooldownMs: 30 * 60 * 1000, // a denied kind waits before another try
  forestLogsWanted: 8, // trunks near spawn before the forest "is back"
  deepinfra: {
    baseUrl: process.env.AW_DEEPINFRA_URL || 'https://api.deepinfra.com/v1/openai',
    model: process.env.AW_DEEPINFRA_MODEL || 'meta-llama/Llama-3.1-8B-Instruct',
    keyFile:
      process.env.AW_DEEPINFRA_KEYFILE ||
      `${process.env.HOME || '/home/caseydigennaro'}/.config/last-mile/secrets.env`,
    timeoutMs: 20000,
  },
};

/** Read the DeepInfra key from the secrets file (never logged). */
function deepinfraKey(opts) {
  const fs = require('node:fs');
  try {
    const text = fs.readFileSync(opts.deepinfra.keyFile, 'utf8');
    const row = text.split('\n').find((l) => /^DEEPINFRA_API_KEY=/.test(l.trim()));
    return row ? row.trim().slice('DEEPINFRA_API_KEY='.length).trim() : null;
  } catch (err) {
    return null;
  }
}

/**
 * One proposal from the model, or null. The prompt names the board and
 * the fixed kinds — the model chooses among them, it does not invent
 * kinds (the validator would deny an invention anyway, and the deny is
 * the honest outcome of a model that tries).
 */
async function modelProposal(board, world, opts, log) {
  const key = deepinfraKey(opts);
  if (!key) return null;
  const body = {
    model: opts.deepinfra.model,
    max_tokens: 200,
    temperature: 0.7,
    messages: [
      {
        role: 'system',
        content:
          'You propose small building projects for a Minecraft community of four agents ' +
          '(gatherer, builder, scout, farmer) around their depot. Answer with ONE JSON object ' +
          'only: {"kind": one of "depot-chest"|"replant"|"farm"|"path"|"shelter", ' +
          '"title": short, "why": short, "dx": integer -40..40, "dz": integer -40..40}. ' +
          'dx/dz are offsets from the depot. No prose outside the JSON.',
      },
      {
        role: 'user',
        content:
          `The board so far: ${JSON.stringify(
            board.list().map((p) => ({ kind: p.kind, status: p.status, title: p.title }))
          )}. Depot at ${JSON.stringify(world.depot())}. Propose the next project.`,
      },
    ],
  };
  try {
    const fetch = globalThis.fetch;
    if (!fetch) return null;
    const res = await fetch(`${opts.deepinfra.baseUrl}/chat/completions`, {
      method: 'POST',
      headers: { 'content-type': 'application/json', authorization: `Bearer ${key}` },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(opts.deepinfra.timeoutMs),
    });
    if (!res.ok) {
      log({ event: 'council_model_refused', detail: `HTTP ${res.status}` });
      return null;
    }
    const data = await res.json();
    const text = data.choices && data.choices[0] && data.choices[0].message
      ? data.choices[0].message.content
      : '';
    const found = String(text).match(/\{[^{}]*\}/);
    if (!found) return null;
    const parsed = JSON.parse(found[0]);
    return parsed;
  } catch (err) {
    log({ event: 'council_model_unreachable', detail: String(err.message || err) });
    return null;
  }
}

/** Build the full proposal (site + scope + materials) for a kind.
 *
 * The scope is the ratified block list — the exact blocks the project
 * may place. It is computed here, deterministically, from the world's
 * own ground; the model never writes a block list.
 */
function buildProposal(kind, world, extras = {}) {
  const depot = world.depot();
  if (kind === 'depot-chest') {
    // The search reaches past the no-grief keep-out: the depot plateau
    // carries a departed visitor's two blocks (TestHumanH, 2026-11-02),
    // and ground near them is not ground we may plan on — but the
    // chest still belongs "at the depot", within a short walk.
    const spot = world.standableNear(depot.x + 3, depot.y, depot.z, 14);
    if (!spot) return null;
    return {
      kind,
      title: 'a chest at the depot',
      need: 'goods left on the ground are swept up by whoever walks by',
      site: { x: spot.x, y: spot.y, z: spot.z, r: 4 },
      // The chest sits *in* the standable spot (on the ground), not a
      // block above it: a floating chest has nothing to build against,
      // and the raw material is logs — the builder crafts the chest.
      scope: { blocks: [{ name: 'chest', x: spot.x, y: spot.y, z: spot.z }] },
      // A chest is a 3x3 craft: the bill counts the bench too when the
      // site has none within crafting reach (the depot's bench serves
      // every site near it; a bill that re-counted it would
      // over-charge the world's wood).
      materials: rawBill({
        chest: 1,
        ...(world.benchNear(spot.x, spot.y, spot.z) ? {} : { crafting_table: 1 }),
      }),
      owner: 'builder',
    };
  }
  if (kind === 'replant') {
    const spots = world.plantableSpots(depot.x, depot.y, depot.z, 24, 16);
    if (!spots.length) return null;
    return {
      kind,
      title: 'replant the spawn forest',
      need: 'the night of chopping that built the wall took the forest',
      site: { x: depot.x, y: depot.y, z: depot.z, r: 24 },
      scope: { blocks: spots.map((s) => ({ name: 'oak_sapling', x: s.x, y: s.y + 1, z: s.z })) },
      materials: { oak_sapling: spots.length },
      owner: 'farmer',
    };
  }
  if (kind === 'farm') {
    const plot = world.farmPlot(depot.x, depot.y, depot.z, 40);
    if (!plot) return null;
    return {
      kind,
      title: 'a farm by the depot',
      need: 'food the world grows itself, instead of none',
      site: { x: plot.x, y: plot.y, z: plot.z, r: 6 },
      scope: {
        blocks: plot.blocks.map((b) => ({ name: b.name, x: b.x, y: b.y, z: b.z })),
      },
      materials: rawBill({
        wooden_hoe: 1,
        // The hoe is a 3x3 craft: no bench within reach of the plot,
        // and the bill owes the wood for one (day one the farm billed
        // the hoe's log alone and the bench came out of nobody's
        // bill — "the farm bill under-counts the bench").
        ...(world.benchNear(plot.x, plot.y, plot.z) ? {} : { crafting_table: 1 }),
        wheat_seeds: plot.blocks.filter((b) => b.name === 'wheat').length,
      }),
      owner: 'farmer',
    };
  }
  if (kind === 'ramp') {
    const from = extras.from;
    const to = extras.to;
    if (!from || !to) return null;
    const plan = world.rampSteps(from.x, from.y, from.z, to.x, to.z);
    if (!plan || !plan.length) return null;
    // Each step is a cell carved down to its target top; the scope
    // names the dirt that finishes it. Dirt, not cobblestone: this
    // world's stone breaks to a bare nothing even under a pickaxe
    // (probe-quarry.js, 17:20 UTC — equip ok, dig resolved, block to
    // air, no drop entity, no item), while dirt drops to any hand,
    // and the carve itself is dirt — the steps pay for themselves out
    // of the ground they are cut into. The bill is empty for the same
    // reason: no raw the gatherer must carry.
    const blocks = plan.map((s) => ({ name: 'dirt', x: s.x, y: s.top, z: s.z }));
    // The site hugs the plan: a radius ten times wider than the work
    // drew the departed visitor's rim blocks into the first
    // proposal's site and the validator denied it (b058).
    const mid = blocks[Math.floor(blocks.length / 2)];
    const spread = Math.max(
      ...blocks.map((b) => Math.hypot(b.x - mid.x, b.z - mid.z))
    );
    return {
      kind,
      title: 'steps out of the depot gully',
      need: 'the floor the crew stands on is a pit; the walks that carry goods die at its rim',
      site: { x: mid.x, y: mid.y, z: mid.z, r: Math.max(4, Math.ceil(spread)) },
      scope: { blocks },
      materials: {},
      owner: 'builder',
    };
  }
  if (kind === 'path') {
    const to = extras.to;
    if (!to) return null;
    const blocks = world.pathBlocks(depot.x, depot.y, depot.z, to.x, to.z, 40);
    if (!blocks.length) return null;
    return {
      kind,
      title: `a path from the depot toward ${to.title}`,
      need: 'the walk between the depot and the work is worn bare',
      site: { x: Math.round((depot.x + to.x) / 2), y: depot.y, z: Math.round((depot.z + to.z) / 2), r: 48 },
      scope: { blocks },
      materials: { cobblestone: blocks.length },
      owner: 'builder',
    };
  }
  if (kind === 'shelter') {
    // The footprint must be CLEAR, not just standable: surfaceAt
    // skips leaves and logs when it reads the ground, so the first
    // site it picked stood inside a dense spruce grove — the plan's
    // wall and roof cells grew through trunks and canopy, the walk
    // into the pocket hung the planner, and every placement from the
    // pit below was silently out of reach (b069, 2026-11-02 19:16Z:
    // "Server did not answer the placement", four in a row). A spot
    // whose three cells above the ground are not air is a grove, and
    // a grove is not a shelter site — the next candidate ring out is.
    const replaceable = (name) => name === 'air' || name === 'cave_air'
      || name === 'void_air' || name.endsWith('_grass') || name === 'fern';
    const clearAbove = (cand) => {
      for (let dx = -1; dx <= 1; dx++) {
        for (let dz = -1; dz <= 1; dz++) {
          const ground = world.surfaceAt(cand.x + dx, cand.z + dz);
          if (ground == null) return false;
          for (let dy = 1; dy <= 3; dy++) {
            const cell = world.blockAt(cand.x + dx, ground + dy, cand.z + dz);
            if (cell && !replaceable(cell.name) && cell.boundingBox !== 'empty') return false;
          }
        }
      }
      return true;
    };
    let spot = null;
    for (const [dx, dz] of [[8, 8], [12, 4], [12, 12], [4, 12], [12, 0], [0, 12], [-8, 8], [8, -8]]) {
      const cand = world.standableNear(depot.x + dx, depot.y, depot.z + dz, 6);
      if (cand && clearAbove(cand)) {
        spot = cand;
        break;
      }
    }
    if (!spot) return null;
    const blocks = [];
    // A 3x3 hut: a cobble ring two high on a 3x3 footprint, a plank
    // roof over all nine, one gap for a door — 23 blocks, inside the
    // 64-block bound the validator holds.
    for (let dx = -1; dx <= 1; dx++) {
      for (let dz = -1; dz <= 1; dz++) {
        const x = spot.x + dx;
        const z = spot.z + dz;
        const ground = world.surfaceAt(x, z);
        if (ground == null) return null;
        const y = ground + 1;
        const wall = Math.abs(dx) === 1 || Math.abs(dz) === 1;
        if (!wall) continue;
        if (dx === 1 && dz === 0) continue; // the door
        blocks.push({ name: 'cobblestone', x, y: y, z });
        blocks.push({ name: 'cobblestone', x, y: y + 1, z });
      }
    }
    for (let dx = -1; dx <= 1; dx++) {
      for (let dz = -1; dz <= 1; dz++) {
        const x = spot.x + dx;
        const z = spot.z + dz;
        const ground = world.surfaceAt(x, z);
        if (ground == null) return null;
        blocks.push({ name: 'oak_planks', x, y: ground + 3, z });
      }
    }
    return {
      kind,
      title: 'a shelter by the depot',
      need: 'a roof over the depot work',
      site: { x: spot.x, y: spot.y, z: spot.z, r: 6 },
      scope: { blocks },
      materials: rawBill({
        cobblestone: blocks.filter((b) => b.name === 'cobblestone').length,
        oak_planks: blocks.filter((b) => b.name === 'oak_planks').length,
      }),
      owner: 'builder',
    };
  }
  return null;
}

/** The needs, in order, as proposals (or null when the need is met). */
function needs(board, world) {
  const out = [];
  const depot = world.depot();
  const done = (kind) => board.list().some((p) => p.kind === kind && (p.status === 'done' || p.status === 'active' || p.status === 'testing'));

  // 2 — the depot chest. The need stands until a chest (not a person's)
  // stands at the depot.
  if (!world.chestAt(depot.x, depot.y, depot.z, 12)) {
    const p = buildProposal('depot-chest', world);
    if (p) out.push(p);
  }
  // 2.5 — steps out of the depot gully. The spawn pocket the crew
  // stands in is rimmed by the old wall, four to six below the
  // standing ground by the chest; the walks that carry the world's
  // goods die at the rim (day one: every restart landed the crew at
  // the floor, six placement timeouts from it, deliveries tossed
  // wherever the walk died). The steps are computed from the ground
  // itself where the crew actually stands, and the board carries the
  // memory: a ramp once done is not proposed again.
  const chestSite = board
    .list()
    .find((p) => p.kind === 'depot-chest' && p.status === 'done');
  if (chestSite && chestSite.site) {
    const floor = world.lowestStand();
    if (floor) {
      const p = buildProposal('ramp', world, { from: floor, to: chestSite.site });
      if (p) out.push(p);
    }
  }
  // 3 — the forest. Trunks within 64 of the depot; fewer than eight
  // and the forest the chopping took is still owed.
  if (world.countBlocks(['oak_log', 'spruce_log', 'birch_log'], depot.x, depot.y, depot.z, 64) < DEFAULTS.forestLogsWanted) {
    const p = buildProposal('replant', world);
    if (p) out.push(p);
  }
  // 4 — the farm.
  if (!world.farmlandNear(depot.x, depot.y, depot.z, 32)) {
    const p = buildProposal('farm', world);
    if (p) out.push(p);
  }
  // 5 — a path to the furthest standing site.
  const sites = board
    .list()
    .filter((p) => (p.status === 'done' || p.status === 'active') && p.site)
    .map((p) => ({ x: p.site.x, z: p.site.z, title: p.title, id: p.id }));
  const far = sites.find(
    (s) => Math.hypot(s.x - depot.x, s.z - depot.z) > 24
  );
  if (far && !board.list().some((p) => p.kind === 'path' && p.status !== 'abandoned')) {
    const p = buildProposal('path', world, { to: far });
    if (p) out.push(p);
  }
  // 6 — the shelter, once the chest and the forest stand. The forest
  // is the WORLD's own trunk count, not a replant project's status: a
  // replant proposal only exists when the forest is GONE, so gating on
  // done('replant') meant the shelter waited on a project that could
  // never run while the forest stood — the board ran dry the moment
  // the farm finished (day three's CONTINUE: the council proposes the
  // NEXT projects so it never does).
  if (
    !done('shelter') &&
    done('depot-chest') &&
    world.countBlocks(
      ['oak_log', 'spruce_log', 'birch_log'],
      depot.x, depot.y, depot.z, 64
    ) >= DEFAULTS.forestLogsWanted
  ) {
    const p = buildProposal('shelter', world);
    if (p) out.push(p);
  }
  return out;
}

/**
 * The council. One instance in the crew's process; `world` is the
 * shared look (one builder's api — they all see the same world),
 * `playerBuilds` is the no-grief ledger's map, so the validator can
 * hold a site away from a person's build.
 */
class Council {
  constructor(board, world, { playerBuilds, log = () => {}, ...opts }) {
    this.board = board;
    this.world = world;
    this.playerBuilds = playerBuilds;
    this.log = log;
    this.opts = Object.assign({}, DEFAULTS, opts);
    this.lastModelAsk = 0;
    this.timer = null;
    this.lastProgressSeen = new Map(); // project id -> placed
    this.lastProgressAt = new Map();
    this.deniedAt = new Map(); // kind -> ts (a deny cools the kind)
  }

  /** Propose one project through the validator, whatever proposed it. */
  propose(proposal, proposer) {
    if (!proposal) return null;
    const verdict = validate(proposal, null, {
      playerBuilds: this.playerBuilds(),
    });
    const project = this.board.propose(Object.assign({}, proposal, { proposer }));
    this.board.validated(project.id, verdict);
    if (verdict.type === 'deny') {
      this.deniedAt.set(proposal.kind, Date.now());
      this.log({ event: 'council_denied', kind: proposal.kind, why: verdict.reason });
    }
    return project;
  }

  /** A kind the validator denied lately is not re-proposed every
   *  minute: the deny is a verdict about the world (a site that will
   *  not pass), and the world does not change that fast. */
  kindCooling(kind) {
    const at = this.deniedAt.get(kind) || 0;
    return Date.now() - at < this.opts.denyCooldownMs;
  }

  /** One council tick. Returns what it did, for the tests. */
  async tick({ allowModel = true } = {}) {
    const did = { proposed: [], held: 0, abandoned: [] };

    // 0 — the stalls: a project silent too long is a stuck project.
    for (const p of this.board.list()) {
      if (p.status !== 'active') continue;
      const placed = p.placed || 0;
      if (placed !== (this.lastProgressSeen.get(p.id) ?? placed)) {
        this.lastProgressSeen.set(p.id, placed);
        this.lastProgressAt.set(p.id, Date.now());
        continue;
      }
      // The first sighting of a project that has placed nothing counts
      // as its first silence. Before this, `lastProgressAt` was never
      // set for a project whose first block never came, so `since` was
      // "now" on every tick and the age never grew: a project that
      // placed nothing was never abandoned (2026-11-02, the farm with
      // a hoe no one could deliver).
      if (!this.lastProgressAt.has(p.id)) {
        this.lastProgressSeen.set(p.id, placed);
        this.lastProgressAt.set(p.id, Date.now());
        continue;
      }
      const since = this.lastProgressAt.get(p.id) || Date.now();
      const age = Date.now() - since;
      if (age > this.opts.stallAbandonMs) {
        this.board.abandon(p.id, `no progress for ${Math.round(age / 60000)} min`);
        this.lastProgressAt.delete(p.id);
        this.lastProgressSeen.delete(p.id);
        did.abandoned.push(p.id);
      }
    }

    // The owner of a proposal must be free: one project per role.
    const busy = new Set(
      this.board
        .list()
        .filter((p) => p.status === 'active' || p.status === 'testing' || p.status === 'ratified')
        .map((p) => p.owner)
    );

    const wanted = needs(this.board, this.world);
    // The council says what it is thinking. A board that does not move
    // looks exactly like a board with nothing to do, and the two are
    // very different: on 2026-11-02 the council proposed nothing for
    // forty minutes and the log did not say why. One line a minute.
    this.log({
      event: 'council_tick',
      needs: wanted.map((p) => p.kind),
      busy: Array.from(busy).sort(),
      proposed: did.proposed.length,
      abandoned: did.abandoned.length,
    });

    for (const proposal of wanted) {
      if (busy.has(proposal.owner)) continue;
      // One project of a kind at a time: a need already on the board
      // (in any living status) is being handled, not forgotten.
      const onBoard = this.board
        .list()
        .some((p) => p.kind === proposal.kind && p.status !== 'abandoned');
      if (onBoard) continue;
      if (this.kindCooling(proposal.kind)) continue;
      const project = this.propose(proposal, 'council');
      if (project) {
        did.proposed.push(project.id);
        busy.add(proposal.owner);
        if (project.status === 'held') did.held += 1;
      }
    }

    // The model's one proposal, when every need is met and the board
    // is quiet — and no more than once per cooldown.
    const quiet =
      !did.proposed.length &&
      !this.board.list().some((p) => p.status === 'active' || p.status === 'testing' || p.status === 'ratified');
    if (allowModel && quiet && Date.now() - this.lastModelAsk > this.opts.proposeCooldownMs) {
      this.lastModelAsk = Date.now();
      const idea = await modelProposal(this.board, this.world, this.opts, this.log);
      if (idea && idea.kind) {
        const proposal = buildProposal(idea.kind, this.world, {});
        if (proposal) {
          proposal.title = String(idea.title || proposal.title).slice(0, 60);
          proposal.need = String(idea.why || proposal.need).slice(0, 120);
          const project = this.propose(proposal, 'deepinfra');
          if (project) did.proposed.push(project.id);
        } else {
          this.log({ event: 'council_model_unbuildable', kind: String(idea.kind) });
        }
      }
    }
    return did;
  }

  start() {
    if (this.timer) return;
    const loop = async () => {
      try {
        await this.tick();
      } catch (err) {
        this.log({ event: 'council_failed', detail: String(err.message || err) });
      }
    };
    loop();
    this.timer = setInterval(loop, this.opts.intervalMs);
  }

  stop() {
    if (this.timer) clearInterval(this.timer);
    this.timer = null;
  }
}

module.exports = { Council, needs, buildProposal, DEFAULTS };
