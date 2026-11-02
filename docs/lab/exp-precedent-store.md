# exp-precedent-store — the store a human can edit, rules as data, and a verdict that is the same bytes every time

*Casey Digennaro's brief of 2026-11-01 on branch `precedent-store` (round 2,
2026-11-02). Measured on the Thor. v1 (commit `dac910a`) laid the store,
the validator and the manifest; this round makes the ledger
human-editable, moves the design note's rules into data, and wires the
board's scope into `core/drift`'s build-drift signal.*

What the brief asked for, and where each thing stands:

| # | The ask | Status |
|---|---|---|
| 1 | markdown-readable precedents a human can edit, round-trip exact | done, `core/precedent/store.py` |
| 2 | seeds: permission ladder + no-grief rules + hard rules as data | done, `core/precedent/rules.py`, `seeds.py` |
| 3 | determinism tests: byte-identical verdicts | done, `tests/precedent/test_verdict_determinism.py` |
| 4 | ask a human when nothing applies | done, `core/precedent/validator.py` |
| 5 | `BoardManifest` read by `core/drift`'s build-drift signal | done, wired and tested |
| 6 | this document, with numbers | below |

`community-loop` (agent-world) will call `core/precedent`: the v1
interface is unchanged — every v1 test still passes untouched.

---

## 1. The mechanism

### 1.1 A precedent is a markdown document

The markdown is the storage format, not an export. One case is one
document: the fields as `- **Name:** value` bullets, the decision and
the rationale as `## ` sections whose body is either a fenced block or
plain prose. The rules of the format:

- a fenced body is rendered with **one more backtick than the longest
  run in the content** (`_fenced`), so a decision that itself holds a
  fenced block still round-trips — the render can always out-fence its
  own content;
- prose before the first section is ignored: a human can leave a note
  among the bullets;
- `None` round-trips as *absent* (`author`, `rule_override` omitted),
  never as the word "None";
- a typo'd field name is an error, not a comment;
- a key may not hold a comma (keys render comma-separated on one line).

`Precedent.as_markdown()` / `from_markdown()` and `parse_precedents()`
(a file of documents), plus `PrecedentStore.save_markdown` /
`load_markdown` (one file) and `save_files` / `load_files` (one `.md`
per case — the shape a human edits in). The store stays append-only:
loading a duplicate id raises, it never rewrites.

The store's hash is **recomputed from the content**, not embedded
(`Precedent.hash()` over canonical JSON): embedding it would only turn a
human's edit of a rationale into an error instead of a decision.

### 1.2 Rules as data

`Rule(key, text, effect, hard, source)` — `effect` is `allow`, `deny`
or `ask_human`. The three sources are rows in
`core/precedent/seeds.py`, every row carrying where it came from:

| Source (what the doc says) | rows | hard deny | soft |
|---|---|---|---|
| `docs/design/vibecode-in-world.md` §1.4, the permission ladder P3/P2/P1 | 9 | 6 | 3 allow (`ladder.p3.owner`, `ladder.p2.supervised`, `ladder.p1.preflight`) |
| `agent-world/src/humanity.js`, `BRIEF-playable.md` §2 "never grief" | 6 | 5 | 1 allow (`nogrief.assume_theirs`) |
| `docs/design/vibecode-in-world.md` §3.1, the seven hard rules | 7 | 7 | — |
| **total** | **22** | **18** | **4** |

Only a deny may be hard (`Rule` raises otherwise), and a hard rule is
never waived — not even by a precedent whose `rule_override` names it
(that is how the "no breaking a person's blocks" promise survives a
misguided case). A *soft* rule's key named by a meeting precedent *is*
removed: that is what "this case decided the general question" means.

Two seeded precedent rows round the store out: `seed-human-request` (a
person's request is **allow** on arrival) and `seed-kid-apply` (a child
actor applying a branch is **ask**).

### 1.3 The validator, and ask-human

`Validator(store, rules).validate(proposal, proposal_keys)` returns a
`Verdict(type, reason, matched_precedents, rule_matches)`.

Deny beats ask beats allow; a hard rule beats everything; nothing at all
matched is **`ASK_HUMAN`** — a verdict, not an error. Silent acceptance
of a proposal the board has never ruled on is the one outcome that must
not exist (`BRIEF-playable.md` §2).

### 1.4 Determinism: the same question twice is the same bytes

`Verdict.canonical()` is the payload; `digest()` is its `sha256:`. All
lists are sorted, the reason cites the first of a sorted list, and
nothing depends on key order, store insertion order, dict order or the
process. `tests/precedent/test_verdict_determinism.py` proves it —
including two fresh `python -c` processes producing identical lines.

### 1.5 The BoardManifest, and the build-drift seam

`BoardManifest.from_store(store, rules=...)` projects the board's active
case ids and ratified scope keys. `fingerprint()` hashes **content, not
the creation time** (so two seats projecting the same board say the same
word), and `save`/`load` round-trip through markdown a human can widen
by hand — the widened file *is* the new truth on load.

`core/drift`'s `BuildDriftSignal` reads it. With a manifest the signal is
computable: it scores `drift.build_drift` rows (`build_drift_events()` in
`core/drift/ledger.py` reads them from the world ledger) as the fraction
of the head's keys outside the ratified scope — 1.0 for a head validated
against another board's manifest. With no manifest it is exactly the v1
seam: named, not computable, with its reason.

---

## 2. Results

| # | Finding |
|---|---|
| 1 | **The seeded board is 22 rule rows (18 hard deny, 4 soft allow) and 2 precedents.** The 13 seed scenarios in `tests/precedent/test_seeds.py` decide as the design note says: `deny` for every grief and hard-rule case, `allow` for the ladder's permission rows and a human's request, `ask_human` for nothing-applying and the child-actor apply. |
| 2 | **A verdict costs 4.2 µs at p50** (p90 4.7 µs, p99 5.0 µs; max 428.8 µs with first-call warmup) over 20,000 mixed verdicts in one process on the Thor — store and rules built before the clock. |
| 3 | **Verdicts are byte-identical across processes.** Two fresh interpreters reproduce the same `canonical()` lines and `sha256:` digests as in-process (`test_two_processes_produce_the_same_bytes`); key order, store insertion order and a markdown round-trip do not move one byte. |
| 4 | **`save` -> `load` is the identity** for 15 awkward shapes of a precedent (fenced decision, headings and titles inside a body, blank-line padding, unicode, absent author/keys/metadata); a hand-written document with unfenced prose parses and then round-trips. |
| 5 | **The drift seam is real where it can be.** Without a manifest the build signal's `computable` is `False` and it says why (v1 behaviour, tests unchanged); with one, 4 branch events score `0.0 / 0.5 / 1.0 / None` as the manifest says, and `build_drift_events()` reads `drift.build_drift` rows from the world ledger's `audit` table. |

Numbers are measured on the Thor by
`docs/lab/precedent-store-scripts/measure_verdict.py` (run under
`thor-admit`; the latency line is machine-dependent, the digests are
not). Rule counts are asserted by `tests/precedent/test_seeds.py`, so
the doc and the code cannot drift apart silently.

---

## 3. What is not verified, and what is not here

- **Nothing writes `drift.build_drift` rows yet.** The world does not
  commit build events; `build_drift_events()` is exercised against rows
  written directly into a fixture ledger. The seam is defined and
  tested, not yet fed.
- **No writer produces a `BoardManifest` yet.** `from_store` projects
  one; the boards fixture is not wired to persist it. Whoever calls
  `core/precedent` first should write the manifest where `core/drift`
  can read it.
- **Latency was measured at 2 precedents and 22 rules.** The store is a
  list plus two indexes; `match()` sorts the matches, so a large ledger
  is an open question, not a measured one.
- **`core/recipe` has no gap objects and no `stores` yet** (the design
  note's §1.7 future), so a gap-driven validator is out of scope here
  exactly as it is in the ideal: questions appear as rows with
  `rule_override`, not as objects.
- Timings: one machine, one process, no CPU pinning; the max is
  first-call warmup, not a tail the box showed twice.
