'use strict';
// bots/src/board.js — the community's project board.
//
// The world's work, written down. A project is what the community is
// building (a chest at the depot, a replanted forest, a farm); the
// board is the one file every builder reads and one process writes,
// because the crew is one process and they all see the same world.
//
// The shape follows builder-ide's BoardManifest (core/precedent/
// manifest.py): projects with scope, site, materials, owner, status,
// and the validator's word on each. The board is an **append-only
// event log** (runtime/logs/board.jsonl, beside the no-grief ledger)
// replayed into state at load, and a **snapshot** (runtime/board.json)
// so a watcher — or a returning human's page — can read the state
// without replaying history. The fingerprint is the manifest's rule:
// version over the sorted ids, sha256, twelve hex chars.
//
// One fact per place: the *events* live here; the world's own log
// (bots.jsonl) gets a one-line note per board event too, so the drift
// detector's evidence and the playtest numbers can count projects
// without reading a second format.

const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');

// What a project may be. Each kind has an executor in projects.js and
// a needs-check in council.js; a kind with neither is a proposal the
// council cannot build (the validator says so).
const KINDS = [
  'depot-chest', // a chest at the depot, so goods stop landing in a pile
  'replant', // saplings where the spawn forest stood
  'farm', // tilled ground and seeds near the depot
  'path', // a walkable line from the depot to a site
  'shelter', // a small hut with walls and a roof
  'fix', // repair what the tester found broken
];

const STATUSES = ['proposed', 'ratified', 'active', 'testing', 'done', 'held', 'abandoned'];

/** The board's fingerprint: the manifest's rule, over the live ids. */
function fingerprint(projects) {
  const ids = projects.map((p) => p.id).sort();
  const payload = `${ids.length}\x00${ids.join('\x00')}`;
  return `board/${ids.length}:${crypto.createHash('sha256').update(payload).digest('hex').slice(0, 12)}`;
}

class Board {
  /**
   * @param {string} logFile  the append-only event log (board.jsonl)
   * @param {string|null} snapshot  where the state snapshot is written
   * @param {(row: object) => void} note  the world's own log (bots.jsonl)
   */
  constructor(logFile, snapshot = null, note = null) {
    this.logFile = logFile;
    this.snapshot = snapshot;
    this.note = note || (() => {});
    this.seq = 0; // events are numbered as they are appended
    this.projects = new Map(); // id -> project
    this._replay();
  }

  _replay() {
    if (!this.logFile || !fs.existsSync(this.logFile)) return;
    for (const line of fs.readFileSync(this.logFile, 'utf8').split('\n')) {
      if (!line.trim()) continue;
      let row;
      try {
        row = JSON.parse(line);
      } catch (err) {
        continue; // a torn tail line is a crash mid-write; skip it
      }
      this._apply(row);
    }
  }

  /** Fold one event into state. The only writer of state. */
  _apply(row) {
    if (!row || !row.event || !row.id) return;
    this.seq = Math.max(this.seq, row.seq || 0);
    const known = this.projects.get(row.id);
    switch (row.event) {
      case 'proposed': {
        if (known) break;
        this.projects.set(row.id, {
          id: row.id,
          kind: row.kind,
          title: row.title,
          need: row.need || '',
          site: row.site || null,
          scope: row.scope || { blocks: [] },
          materials: row.materials || {},
          owner: row.owner || null,
          status: 'proposed',
          verdict: null,
          proposer: row.proposer || 'council',
          created_at: row.at,
          events: 1,
          placed: 0,
          issues: [],
        });
        break;
      }
      case 'validated': {
        if (!known) break;
        known.verdict = row.verdict || null;
        known.status = row.verdict && row.verdict.type === 'allow' ? 'ratified' : 'held';
        if (row.verdict && row.verdict.type === 'deny') known.status = 'abandoned';
        break;
      }
      case 'started': {
        if (!known) break;
        known.status = 'active';
        break;
      }
      case 'progress': {
        if (!known) break;
        if (typeof row.placed === 'number') known.placed = row.placed;
        if (row.note) known.last_note = row.note;
        break;
      }
      case 'materials' : {
        if (!known) break;
        known.staged = row.staged || {};
        break;
      }
      case 'testing': {
        if (!known) break;
        known.status = 'testing';
        break;
      }
      case 'done': {
        if (!known) break;
        known.status = 'done';
        known.finished_at = row.at;
        break;
      }
      case 'issue': {
        if (!known) break;
        known.issues.push({
          n: known.issues.length + 1,
          what: row.what,
          at: row.at,
          fixed_at: null,
        });
        if (known.status === 'testing' || known.status === 'done') known.status = 'active';
        break;
      }
      case 'issue_fixed': {
        if (!known) break;
        const issue = known.issues.find((i) => i.n === row.n && !i.fixed_at);
        if (issue) issue.fixed_at = row.at;
        if (known.issues.every((i) => i.fixed_at)) known.clean = true;
        break;
      }
      case 'abandoned': {
        if (!known) break;
        known.status = 'abandoned';
        known.why = row.why || '';
        break;
      }
      default:
        break;
    }
    if (known) known.events = (known.events || 1) + (row.event === 'proposed' ? 0 : 1);
  }

  /** Append one event, fold it, note it, snapshot. The only public write. */
  _emit(row) {
    row.seq = ++this.seq;
    row.at = new Date().toISOString();
    if (this.logFile) {
      try {
        fs.mkdirSync(path.dirname(this.logFile), { recursive: true });
        fs.appendFileSync(this.logFile, JSON.stringify(row) + '\n');
      } catch (err) {
        // The log on disk is the durable copy; the state in memory is
        // the working one. A failed append is a blind spot, named here
        // so it is never silent.
        this.note({ event: 'board_write_failed', detail: String(err.message || err) });
      }
    }
    this._apply(row);
    this.note({ event: 'board', board_event: row.event, project: row.id, kind: row.kind || null });
    this._snapshot();
    return this.projects.get(row.id) || null;
  }

  _snapshot() {
    if (!this.snapshot) return;
    const projects = this.list();
    const document = {
      fingerprint: fingerprint(projects),
      updated_at: new Date().toISOString(),
      counts: {
        total: projects.length,
        active: projects.filter((p) => p.status === 'active').length,
        done: projects.filter((p) => p.status === 'done').length,
        held: projects.filter((p) => p.status === 'held').length,
        open_issues: projects.reduce((s, p) => s + p.issues.filter((i) => !i.fixed_at).length, 0),
        fixed_issues: projects.reduce((s, p) => s + p.issues.filter((i) => i.fixed_at).length, 0),
        blocks_placed: projects.reduce((s, p) => s + (p.placed || 0), 0),
      },
      projects: projects.map((p) => ({
        id: p.id,
        kind: p.kind,
        title: p.title,
        status: p.status,
        owner: p.owner,
        site: p.site,
        placed: p.placed || 0,
        of: (p.scope && p.scope.blocks ? p.scope.blocks.length : 0),
        proposer: p.proposer,
        verdict: p.verdict ? p.verdict.type : null,
        issues: p.issues.length,
        open_issues: p.issues.filter((i) => !i.fixed_at).length,
      })),
    };
    try {
      fs.mkdirSync(path.dirname(this.snapshot), { recursive: true });
      const tmp = `${this.snapshot}.tmp`;
      fs.writeFileSync(tmp, JSON.stringify(document, null, 1) + '\n');
      fs.renameSync(tmp, this.snapshot);
    } catch (err) {
      this.note({ event: 'board_write_failed', detail: String(err.message || err) });
    }
  }

  // -- the reads ----------------------------------------------------------------

  list() {
    return Array.from(this.projects.values()).sort((a, b) => (a.created_at < b.created_at ? -1 : 1));
  }

  get(id) {
    return this.projects.get(id) || null;
  }

  /** The project a role should be working: active or to-start, oldest first. */
  forOwner(owner) {
    return (
      this.list().find(
        (p) => p.owner === owner && (p.status === 'active' || p.status === 'ratified')
      ) || null
    );
  }

  /** Any project waiting on the tester. */
  awaitingTest() {
    return this.list().find((p) => p.status === 'testing') || null;
  }

  // -- the writes ---------------------------------------------------------------

  propose({ kind, title, need, site, scope, materials, owner, proposer }) {
    const id = 'b' + String(this.seq + 1).padStart(3, '0');
    return this._emit({
      event: 'proposed',
      id,
      kind,
      title,
      need,
      site,
      scope,
      materials,
      owner,
      proposer: proposer || 'council',
    });
  }

  validated(id, verdict) {
    return this._emit({ event: 'validated', id, verdict });
  }

  started(id) {
    const project = this.get(id);
    if (!project || project.status === 'done' || project.status === 'abandoned') return project;
    return this._emit({ event: 'started', id });
  }

  progress(id, placed, note) {
    return this._emit({ event: 'progress', id, placed, note: note || null });
  }

  stagedMaterials(id, staged) {
    return this._emit({ event: 'materials', id, staged });
  }

  sendToTest(id) {
    return this._emit({ event: 'testing', id });
  }

  finish(id) {
    return this._emit({ event: 'done', id });
  }

  fileIssue(id, what) {
    return this._emit({ event: 'issue', id, what });
  }

  fixIssue(id, n) {
    return this._emit({ event: 'issue_fixed', id, n });
  }

  abandon(id, why) {
    return this._emit({ event: 'abandoned', id, why });
  }

  /** The one line a person is told: what the community is building now. */
  headline() {
    const active = this.list().filter((p) => p.status === 'active' || p.status === 'testing');
    if (!active.length) {
      const done = this.list().filter((p) => p.status === 'done').length;
      return done
        ? `nothing in hand just now — ${done} project(s) finished`
        : 'nothing in hand just now';
    }
    return active
      .map((p) => {
        const of = p.scope && p.scope.blocks ? p.scope.blocks.length : 0;
        const share = of ? ` (${p.placed || 0}/${of})` : '';
        return `${p.title}${share}`;
      })
      .join(' · ');
  }
}

module.exports = { Board, KINDS, STATUSES, fingerprint };
