'use strict';
// bots/src/validator.js — the supervisor's word on what may be built.
//
// builder-ide's core/precedent (the precedent-store repo, dac910a)
// defines the interface this file mirrors:
//
//   validate(proposal, proposal_keys) ->
//     { type: 'allow' | 'deny' | 'ask_human',
//       reason: str, matched_precedents: [id], rule_matches: [key] }
//
// It is **not merged** into this repo, so the world runs a local rule
// table with the same interface, the way the Thor brief allows
// ("builder-ide core/precedent if merged; else a local rule table with
// the same interface"). The day core/precedent lands, this file can
// become a thin client of it: the call site (council.js, projects.js)
// asks for a verdict and never learns which table answered.
//
// Two doors are checked here, and both are cheap:
//
// * **Projects.** Every new project — the council's, a model's, a
//   person's — is a proposal until a verdict allows it. `ask_human`
//   holds the project on the board (a human's own proposal answers
//   itself: the proposer is the answer).
// * **Edits.** Every structural edit (a block placed under a project)
//   is checked against the project's **ratified scope**: the exact
//   block list the verdict allowed. A block outside that list is build
//   drift, and drift is denied, not scored.
//
// The rules are a table, not code branches, so a new rule is a row and
// every verdict names the rows that produced it.

// --- the rule table -----------------------------------------------------------
//
// Each rule: a key, the text (what it stands for), and a check over
// the proposal. A rule speaks only when its key is in the proposal's
// keys — the same protocol as core/precedent, where the caller names
// the proposal's facets and the validator matches rules by key.
//
// What the world can supply is the world's own list, in one place
// (materials.js), so the validator and the supply duty cannot drift
// apart again.
const { isGatherable } = require('./materials');

const RULES = {
  'kind:known': {
    text: 'the community has a builder for this kind of project',
    check: (p) =>
      ['depot-chest', 'replant', 'farm', 'path', 'shelter', 'fix', 'ramp'].includes(p.kind)
        ? null
        : 'deny',
  },
  'kind:unknown': {
    text: 'no builder in this community knows how to raise that',
    check: () => 'deny',
  },
  'scope:bounded': {
    text: 'a project ratifies at most 64 blocks',
    check: (p) => {
      const n = p.scope && p.scope.blocks ? p.scope.blocks.length : 0;
      if (n === 0) return 'ask_human'; // nothing to build: a person should say what
      return n <= 64 ? null : 'deny';
    },
  },
  'site:known': {
    text: 'the site is a place in the world, not a hope',
    check: (p) => {
      const s = p.site;
      if (!s || !Number.isFinite(s.x) || !Number.isFinite(s.y) || !Number.isFinite(s.z)) {
        return 'ask_human';
      }
      if (Math.abs(s.x) > 1000 || Math.abs(s.z) > 1000) return 'deny';
      return null;
    },
  },
  'materials:gatherable': {
    text: 'the world can supply the materials it asks for',
    check: (p) => {
      // The list is the world's, in one place (materials.js): a bill
      // names the raw the gatherer can carry, and the owner crafts the
      // rest. The old list here named crafted things (a wooden_hoe)
      // that the supply chain could never deliver, so the bill passed
      // the validator and then starved at the site.
      for (const name of Object.keys(p.materials || {})) {
        if (!isGatherable(name)) return 'ask_human';
      }
      return null;
    },
  },
};

// The precedents: what the community has already been allowed (or
// refused), seeded from the playable round's record. A precedent can
// override one rule key (core/precedent's rule_override); none of the
// seeds need to — the table above allowed them on their own keys.
const PRECEDENTS = [
  {
    id: 'prec-001-wall-east-of-depot',
    keys: ['kind:path', 'kind:shelter'],
    decision: 'allow',
    note: 'the cobble wall east of the depot, raised through the playable round',
    rule_override: null,
  },
  {
    id: 'prec-002-depot-ground-pile',
    keys: ['kind:depot-chest'],
    decision: 'allow',
    note: 'goods at the depot were a pile on the ground; a chest was the fix',
    rule_override: null,
  },
  {
    id: 'prec-003-chop-the-forest',
    keys: ['kind:replant'],
    decision: 'allow',
    note: 'the spawn forest fed the wall; replanting it was owed',
    rule_override: null,
  },
];

/** The facets a proposal carries, as keys.
 *
 * The kind facet names itself known or unknown: the rule table speaks
 * by key, so "rollercoaster" must arrive as `kind:unknown` for the
 * table to deny it — the same protocol core/precedent's callers follow
 * (the caller names the facet, the rule answers by that name).
 */
function proposalKeys(proposal) {
  const keys = [];
  if (proposal.kind) {
    keys.push(
      ['depot-chest', 'replant', 'farm', 'path', 'shelter', 'fix', 'ramp'].includes(proposal.kind)
        ? 'kind:known'
        : 'kind:unknown'
    );
    // The value key too: precedents are matched by it (a precedent
    // about depot chests should not fire for shelters), while the
    // rules answer by the status key. No rule is keyed by a value.
    keys.push(`kind:${proposal.kind}`);
  }
  if (proposal.scope) keys.push('scope:bounded');
  if (proposal.site) keys.push('site:known');
  if (proposal.materials && Object.keys(proposal.materials).length) {
    keys.push('materials:gatherable');
  }
  return keys;
}

/**
 * The verdict on a project proposal. `playerBuilds` is the no-grief
 * ledger's map ("x,y,z" -> row): a site that would build over or
 * beside a person's build is denied here as well as at the workface,
 * so a bad project never starts.
 */
function validate(proposal, proposalKeys_, { playerBuilds = new Map(), buildKeepOut = 8 } = {}) {
  const keys = proposalKeys_ || proposalKeys(proposal);
  const matched = [];
  const decisions = [];

  // The no-grief rule is not a row in the table: it is the world's
  // standing promise (PLAY.md), and it is checked whatever the keys.
  // At the project door it is coarse — a person's block inside the
  // site itself denies the project — because the granular door (the
  // api's mayPlace, and the site searches that already skip ground
  // near a person's build) holds every block. A blanket keep-out here
  // would hand one departed visitor's two blocks a veto over the whole
  // depot, which is protection nobody asked for (the TestHumanH
  // finding, 2026-11-02: every council proposal denied, site after
  // site, until the look learned to search elsewhere).
  const site = proposal.site;
  if (site && Number.isFinite(site.x) && playerBuilds.size) {
    const r2 = (site.r || 4) * (site.r || 4);
    for (const [key, row] of playerBuilds) {
      const [px, py, pz] = key.split(',').map(Number);
      const dx = px - site.x, dy = py - site.y, dz = pz - site.z;
      if (dx * dx + dy * dy + dz * dz <= r2) {
        return {
          type: 'deny',
          reason: `${row.by}'s ${row.name || 'block'} stands inside that site`,
          matched_precedents: [],
          rule_matches: ['nogrief:player-build'],
        };
      }
    }
  }

  for (const key of keys) {
    const rule = RULES[key];
    if (!rule) continue;
    const decision = rule.check(proposal);
    if (decision) decisions.push({ key, decision, text: rule.text });
    if (decision === null || decision) matched.push(key);
  }
  for (const precedent of PRECEDENTS) {
    if (precedent.keys.some((k) => keys.includes(k))) matched.push(precedent.id);
  }

  const deny = decisions.find((d) => d.decision === 'deny');
  if (deny) {
    return {
      type: 'deny',
      reason: `${deny.key}: ${deny.text}`,
      matched_precedents: PRECEDENTS.filter((p) => p.keys.some((k) => keys.includes(k))).map((p) => p.id),
      rule_matches: matched,
    };
  }
  const ask = decisions.find((d) => d.decision === 'ask_human');
  if (ask) {
    return {
      type: 'ask_human',
      reason: `${ask.key}: ${ask.text}`,
      matched_precedents: PRECEDENTS.filter((p) => p.keys.some((k) => keys.includes(k))).map((p) => p.id),
      rule_matches: matched,
    };
  }
  return {
    type: 'allow',
    reason: keys.length
      ? `allowed on ${matched.filter((m) => !m.startsWith('prec-')).join(', ')}`
      : 'allowed: nothing contested',
    matched_precedents: PRECEDENTS.filter((p) => p.keys.some((k) => keys.includes(k))).map((p) => p.id),
    rule_matches: matched,
  };
}

// --- the per-edit door ---------------------------------------------------------

/**
 * May this block be placed, as part of this project?
 *
 * The ratified scope is the exact block list the verdict allowed, so
 * an edit inside it is ratification working; an edit outside it is
 * **build drift**, and drift is denied by name. The no-grief guard
 * (the person's radius) is asked second — a project never overrides a
 * person, not even a ratified one.
 */
function checkEdit(project, name, x, y, z, guard) {
  if (!project) {
    return { ok: false, why: 'no project is ratified for this edit' };
  }
  const key = `${Math.floor(x)},${Math.floor(y)},${Math.floor(z)}`;
  const blocks = (project.scope && project.scope.blocks) || [];
  const planned = blocks.find((b) => `${b.x},${b.y},${b.z}` === key);
  if (!planned) {
    return { ok: false, why: `build drift: (${key}) is not in ${project.id}'s ratified scope` };
  }
  if (planned.name !== name) {
    return {
      ok: false,
      why: `build drift: (${key}) is ratified as ${planned.name}, not ${name}`,
    };
  }
  if (guard) {
    const verdict = guard.mayPlace({ x: Math.floor(x), y: Math.floor(y), z: Math.floor(z) });
    if (!verdict.ok) return { ok: false, why: verdict.why };
  }
  return { ok: true };
}

module.exports = { validate, checkEdit, proposalKeys, RULES, PRECEDENTS };
