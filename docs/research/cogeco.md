# REPORT — fit study: cognitive-ecology as builder-ide's kernel?

*2026-10-30. Scope per `BRIEF.md`: read all of
[`SuperInstance/cognitive-ecology`](https://github.com/SuperInstance/cognitive-ecology)
(cloned to `/tmp/cognitive-ecology`, v0.1.0, commit `a0fb210`), read builder-ide's
`CLAUDE.md`, `docs/vision.md`, `docs/design/core-spec.md` (= `~/lm-wt/spec-v2/SPEC.md`,
byte-identical), `docs/research/ux-day.md`, `docs/research/ux-trust.md`, and write
this fit study.*

**Method note.** Everything claimed about cognitive-ecology below was read in its
source and, where runnable, reproduced in a venv in this directory (`.venv/`):
`pytest` → **99/99 green** (including the 15 golden-corpus pairs);
`examples/week_in_a_box.py` → reproduces the README numbers exactly (4 routines
born, 332 observations handled, 5 scripts self-retired, 8 justifications broken,
10.88 learned utility); `examples/tiny_mud.py` → daily briefings as documented;
`ecology check tests/corpus/dead_chain_depth2/…` → dead-at-depth-2 with exit 1
(the external audit's Finding 2 fix, verified live). Two findings from reading
that matter for trust: the live panel's round-002 "architect" cites files and a
commit that do not exist anywhere in the repo (`lifecycle.py:72`,
`scheduler.py:119`, `7ef21a4` — no grep hits), i.e. its proposed "changes live
in commit…" are fabricated citations; and `library/originals/` records that the
manifesto itself was received from Casey — **both projects have the same owner**,
which changes the fit question from "partnership" to "where does one codebase
end."

---

## 0. The verdict in one paragraph

The two projects are complements, not competitors, and they converge on the same
deep instinct from opposite sides. cognitive-ecology is a **substrate theory**:
an always-on world of processes under a conservation law (WHY), with a
deliberately mechanical, zero-LLM runtime — but almost no product surface, no
durability, no cost model, no human. builder-ide is a **product**: an experience
spine, a trust/taste theory, real hardware budgets and crash recovery — but its
"world" is a night shift, not an organism; nothing in it must justify its own
continued existence. Each has built exactly the half the other has not designed.
**Recommendation: option (b)** — keep builder-ide's core as specified, vendor
cognitive-ecology's WHY kernel as a library (it is pure, tested, and
golden-corpus-pinned), borrow its lifecycle and consolidation semantics, and let
the ecology remain the research home for the always-on organism (option (c)
alongside). Do not make the ecology the core (option (a)) until its own
falsification program (round 002's seed-43 design) has actually run.

---

## 1. The mapping, concept by concept

At a glance — CE = cognitive-ecology, BI = builder-ide:

| Concept pair | Structural rhyme | Who is ahead, and where |
|---|---|---|
| Runtime/ticks ↔ day-night service | unattended overnight work over a durable log | CE: always-on theory · BI: operations (crash, rails, reboot) |
| Attention economy ↔ scheduler rails | admission control, economy not hierarchy | CE: justification-weighted bidding (idea) · BI: real cost rails |
| Budgets | scarce resource, enforced before spend | BI, decisively |
| Script ecology ↔ vocabulary lifecycle | candidate→active→retired, no deletion | CE: self-retiring machinery · BI: schema/rich metadata |
| WHY kernel ↔ keep/reject + branches | liveness is attested, deletion is refused | CE: the only computable law · BI: the attestation *stream* |
| Sleep ↔ overnight loop | the night is when the system changes itself | CE: consolidation theory · BI: production + honesty mechanics |
| Identity ↔ taste ledger | identity = persistent preference, not memory | BI, by a full specification |
| Morning briefing ↔ morning report | bounded, executive, decision-first surface | BI, by a product margin |
| LLMs-as-teachers ↔ the model cast | powerful agents outside the typed loop | CE: zero-LLM discipline · BI: the economics of using them |
| Provenance ↔ audit log/assets | "provenance or it didn't happen" | BI (event-sourced, hashed, licenced) |
| Characters vs ship's computer ↔ processes vs teachers | cheap in-loop, powerful out-of-loop | BI (three-layer separation is designed) |
| Work orders ↔ (unbuilt) exocortex | capability grows through a gated lifecycle | BI: fully specified · CE: sketched, unbuilt |
| Recipe history ↔ world graph/library | keep decisions, not artifacts; replay by seed | BI (event-sourced, content-addressed) |

### 1.1 Runtime, ticks, budgets ↔ the day/night service

CE's L0 (`src/ecology/runtime.py`) is a tick loop: the clock advances, tensions
age, `JustificationWatch.recheck` runs, processes bid, a policy allocates
`budget_per_tick` (10.0 default; 12.0 in the tiny MUD, `demo.py:227`), funded
processes tick and starved ones wait — "never killed; the economy is not a
hierarchy" (`runtime.py:186-231`). Law 1 is explicit: nothing is event-driven
internally; events perturb ongoing processes; "the world exists before the
player logs in" (`library/originals/MANIFESTO-…:29-37`). Tick time is
deterministic — `Event.ts` is tick, not wall clock, "deterministic worlds
replay exactly" (`src/ecology/events.py:25-27`).

BI's core is a durable FastAPI+SQLite service (spec §4) whose "world" has a
rhythm instead of a heartbeat: interactive day (Talk ≤ 2 s / Watch ≤ 5 s /
Workshop ≤ 60 s clocks, ux-day §"The three clocks"), batch night (§3.2), with
the night's tick existing as `night.tick` heartbeat rows (§1.8) whose gaps are
how the morning's status line is *computed* (§3.4).

**Match:** both center unattended work over a durable record, and both are
deterministic-by-construction (CE seeds and tick determinism; BI content-hash
keys, seeded samplers, "deterministic rebuild" gate step §2.3.1).
**Differ:** CE is always-on simulation; BI is presence-gated production — big
batches literally wait for client detach or a deadline (§1.9 `detach_deadline`).
CE's runtime has no HTTP, no crash recovery, no concurrency; BI's spec has a
boot sequence, job leases, a kill -9 acceptance test (§5.4) and four computed
morning statuses (§3.4). **Ahead:** CE owns the *idea* of a world that runs
between human moments; BI owns the operational reality of a service that
survives one. Neither has both.

### 1.2 Attention economy ↔ scheduler rails

CE's L-attention (`src/ecology/attention.py`) implements the manifesto formula
`attention = urgency × justification × opportunity × novelty × expected_value`
as a multiplicative bid (one zero factor zeroes the bid — deliberately kept,
ADR 0005), with three swappable policies: `MarketPolicy` (proportional),
`CentralPolicy` (fixed priority), `HybridPolicy` (default: 30% governance
reserve for identity-level bidders that **rolls over to the market when
unclaimed** — a lesson a failing test taught, `docs/JOURNAL.md` M2). WHY status
becomes a multiplier: alive 1.0 / unknown 0.25 / dead 0.0
(`attention.py:27-32`), which is Open Question #5 "probed — yes"
(`library/open-questions.md` row 5).

BI's allocation is the model scheduler and the rail system: hot/warm/cold model
tiers (§1.9), CPU vs GPU lanes (§3.2.3), Magnus's reserved lane inside the night
(§3.2.3), and — closest in spirit to a governance reserve — the hot tier
"reserved for interactive" that day previews may preempt into (§7.8). There is
no bidding between characters; the Companion does not outbid the Architect for
anything.

**Match:** both treat attention as an economy with admission control rather
than a hierarchy, and both reserve a slice for concerns that must not starve.
**Differ:** CE allocates *process energy per tick* among internal citizens; BI
allocates *money, GPU-minutes and model loads* among jobs. CE has no cost
concept at all; BI has no concept of its own components competing for
existence. **Ahead:** BI on realism; CE on the one idea BI lacks — that the
system's own parts should compete for the right to keep running.

### 1.3 Budgets

CE: `budget_per_tick` energy units among processes, plus a per-event script
budget (2.0, `demo.py:138`) and simulation budgets (§ `sim.py`). Abstract
units, no currency, no enforcement beyond the tick.

BI: the three-rail system `(gpu_minutes, hosted_cents, wall_minutes)` at
per-cycle / per-attempt / per-order / per-night granularity (§1.3 `Budget`,
§5.5), **plus the fourth rail** — `loads_per_night` per model, enforced at
batch admission because weight-swap thrash, not VRAM, is the binding constraint
on a 122 GB unified box (§0 #13, §5.5). Graduated degradation (80% stop opening
batches; 95% stop; 100% commit-and-report, §5.5), enforcement *before* spend,
kill switch, graduated throttling with the AWS agentic-cost hierarchy as
grounding (ux-trust §"Safe mistakes").

**Verdict:** BI is ahead by a design generation. CE's week-in-a-box runs on a
laptop-class tick loop where budget is an abstraction; nothing in CE has ever
been throttled by a real constraint. If CE's processes ever bid for *actual*
Thor GPU-minutes, BI's rail design is the missing currency exchange.

### 1.4 Script ecology (candidate→active→retired) ↔ vocabulary lifecycle

CE's L4 (`src/ecology/scripts.py`): a `Script` carries trigger, conditions,
cost, learned utility (EMA 0.3), success rate; candidates promote after 2
successes, active scripts retire after ≥5 runs below utility 0.1
(`scripts.py:32-38`); "retirement is not deletion: the script and its metrics
remain in the ledger as institutional memory" (`scripts.py:14-15`). Agents are
script collections (the zMUD insight); the runtime stays cheap.

BI's nearest structure is the vocabulary: `VocabularyEntry.status ∈ {active,
coming-soon, retired}` (§1.5), where `coming-soon` is pinned when a WO is
filed, `active` happens only on a kept work order, and words version only
through kept WOs. Rejected branches are retained and visitable — "a rejection
is a branch you can revisit, not a hole in the ground" (§1.2, from ux-trust).

**Match:** this is the strongest structural rhyme in either codebase — a
three-state lifecycle, promotion by evidence, retirement without deletion —
stated in almost the same words on both sides.
**Differ in one load-bearing way:** CE's lifecycle is *self-administered by
measured utility* (a script retires itself by its own numbers, in
`_lifecycle()`); BI's is *owner-gated* (a word activates when the owner keeps
the WO that produced it). CE trusts the machine's measurement; BI trusts the
human's keep. Also: CE's script is a unit of *behavior*; BI's word is a unit of
*permission* (what a character may do), with a JSON-Schema-subset param
contract a character cannot smuggle free text through (§1.5).
**Ahead:** BI on metadata (param schemas, acceptance templates, taste notes,
provenance, versions); CE on the one mechanism BI lacks — nothing in BI ever
retires itself. A vocabulary word with zero `vocab.call`s across a month stays
`active` forever, even though the data to notice (call counts, §1.5's derived
capability view) already exists in the audit log.

### 1.5 WHY kernel (questionable vs dead) ↔ keep/reject, branches, and the absence of a law

CE's kernel (`src/ecology/why/`, ported from the Rust `why` v0.2 and pinned to
the same 15-pair golden corpus, ADR 0001) is a pure function
`evaluate(graph, attestation, as_of)` with four statuses — alive / dead /
unknown / absent — and the semantics the audit forced: liveness only propagates
over **explicit** edges (inferred edges are candidates that "never confer a
verdict", `why/reach.py:10-14`); deadness propagates through explicit chains at
any depth; roots are mortal (`until` hard-expires, `review-by` + 30-day grace
degrades to stale→unknown, `why/model.py:72-82`). ADR 0002 fixes the crucial
distinction: a root **attested dead** makes explicit dependents dead (weight
0.0 — removal justified), while a root whose liveness is merely **unknown**
(dangling, stale, inferred-only) makes dependents *questionable* — weight 0.25,
still running, "starving only under contention (pinned as a 4:1 energy-ratio
test)". The manifesto's "questionable, not deleted" is thus two different
strengths of the same law. `JustificationWatch` turns statuses into bid weights
and emits `justification.broken` events (`runtime.py:72-140`).

BI has **no equivalent law** — and, unexpectedly, already has the raw material
for one. What BI has: append-only audit with one narrow erase exception (§1.0),
rejected branches retained (§1.2), provenance on every asset (§1.6), "why?" one
tap from any card (ux-day moment 9). What BI lacks: any computation of "this
thing's reason to exist is gone." But look at what keep/reject *is*: the owner
is a liveness oracle. A `wo.kept` event is an attestation ("alive, by casey,
2026-11-03"); `RecipeEntry.origin: "wo_14"` (§1.1) is a justification edge from
an entry to the work order that produced it; a WO traces to a context packet
and an owner's goal. That is a justification graph already implicit in the
schema — typed, dated, authored — with nobody evaluating it. Recipe entries
whose founding WO's goal has gone stale have no status today; they just
persist.

**Match:** the shared instinct that deletion is the wrong default and history
is kept. **Differ:** CE computes necessity; BI governs it by hand.
**Ahead:** CE, uniquely — this is the one concept in the study with no BI
counterpart at all. (And BI is ahead only in having a *motivated* attestation
stream, which CE conspicuously lacks — see §3.2 below.)

### 1.6 Sleep consolidation ↔ the overnight loop

CE's L7 (`src/ecology/sleep.py`) is infrastructure evolution, not
summarization: observations → episodes (signature grouping) → patterns
(frequency ≥ 3) → candidate scripts (replay-validated, utility-seeded) →
promotion; memory graduates observation→episode→pattern→routine in the world
graph (`world.py:110-121`); the night also rechecks WHY, prunes retirement
candidates, and habituates old tensions (`demo.py:168-176`). ADR 0003 pins the
philosophy: **mechanical first, zero LLMs** — "this much accumulation happens
before any model is involved" is the point; teachers enter later as *proposers
of better handlers* for mechanically-validated patterns, run through the same
promotion pipeline ("they edit the organism; they are not the organism").

BI's night (§3.2) is production: slate → pre-flight → lanes → the sealed-bet
loop (edit → sealed prediction → preview rungs → geometry check → critic →
keep-or-revert as a *verdict* write) → graduated throttling → pre-bake for the
morning → report. Its only consolidation-like passes are the morning report
build, the calibration batch on idle nights (§3.5 — the critic's seeded-defect
reference set, "the cheapest data the project will ever buy"), and the
mechanical "melt" of ask-mode questions ("questions stop for a builder the
moment that builder holds two observations on a reason code", §3.5).

**Match:** both reserve the night for what the day doesn't do, and both make
the night's learning *mechanical where it can be*. **Differ in theory:** CE's
night compiles **experience into capability** (new machinery the system did not
have); BI's night performs **work** and accumulates **knowledge about the
owner** (taste rows, prediction verdicts). CE's world ends the week with organs
it did not have Monday (`README.md:63-70`, reproduced here); BI's world ends
the night with renders, branches and a better-calibrated crew, but the crew's
*capabilities* change only through work orders.
**Ahead:** CE conceptually — "experts compile, they don't remember" is a real
mechanism BI has not designed; BI operationally — its night survives reboots,
names its cuts, and reports honestly, which CE's in-process sleeper has never
had to do. Note CE's own panel flagged the evidence gap: replay-validation
"confuses frequency with value" (ADR 0003's own admission), and round 002's
whole critique is that week-in-a-box is a telemetry monoculture with no noise
floor.

### 1.7 Identity ↔ the taste ledger

CE (`src/ecology/identity.py`): identity is "persistent preference: what
repeatedly wins" — a normalized value distribution (default
truth/usefulness/exploration), reinforced multiplicatively and renormalized (an
EMA attractor), with stability measured as entropy concentration
(`identity.py:46-60`). The manifesto's final question is *the* identity
question: "after ten years… what is the smallest structure that must remain
true for the organism to still be itself?"

BI (`ux-trust.md` §"The taste ledger", spec §1.7): taste is "a statistical
tendency over artifacts… countable, comparable, and it survives the session
that produced it." Taste notes carry closed reason codes (a fixed dozen), an
artifact ref (never a conversation), author scoping (Magnus's rows never fold
into Casey's — decision §7.4), a single writer (the owner's verdict event,
never a builder), denominators always shown, two separate tallies (world
competence vs taste predictions) because "they fail differently," one-action
export/erase, and the anti-sycophancy regime (no praise ever; counts not
adjectives; the two-observation gate before any taste claim). Builder identity
through model swaps is handled by the continuity notice (ux-trust §"Research
transfer"): what persists is "your ledger, your taste, the commitments it made,
its branch history."

**Match:** this is the second-strongest rhyme, and it is *definitional* — both
sides independently define identity as persistent preference rather than memory
or narrative. CE's `reinforce()` on payoff and BI's reason-code counts are the
same attractor in two notations.
**Differ:** CE's identity is the **organism's** (its values); BI's is the
**owner's** (their taste), learned by the system — plus a thin per-character
identity (voice spec + continuity notice). CE's is a 69-line dataclass that the
tiny MUD never wires in (`demo.py` constructs no `Identity`); BI's is specified
to the field, with gates, erasure mechanics, and a research grounding.
**Ahead:** BI, by a full specification. But note the conceptual gift flows
back: BI's taste ledger *is* CE's identity attractor, done properly — and CE's
`stability()` concentration measure is exactly the kind of mechanical
"has taste converged yet" signal BI's cold-start melt (§3.5) currently
approximates with raw counts.

### 1.8 Morning briefing ↔ morning report

CE (`src/ecology/briefing.py`): things that changed, top-3 urgent tensions
(expectation vs reality vs age), recommendations (`retire-script`,
`review-necessity`), script census, world census, necessity census, optional
identity snapshot. Framed as "the executive's view… stewardship, not a chat
prompt" — Open Question #9's minimal probe; "the 'map' remains unbuilt"
(`library/open-questions.md` row 9).

BI (§3.2.8, RV patch 2): the report is a pre-built static page whose order is
load-bearing — computed four-value status line + reason; failures always lead;
the cut named, not just the spend; night numbers with split kept-counts;
filmstrip; three branches *plus two standing options*; parked questions
triaged top-3 + count; the per-builder tally with denominators; and the
three-number line (`5.3 h of your Thor · $0.00 hosted · 2 h of your attention
(9 decisions; budget 10)`) — the morning may ask at most 10 decisions, and if
the night would produce more, the cut happens at the queue, not at the reader.

**Match:** both are bounded, executive, decision-first surfaces with top-3
triage, both distrust the chat prompt, and both treat honesty as the design
constraint (BI: "nothing appears in the report that wasn't worked", ux-day
§3; CE: the necessity census says what died).
**Differ:** BI's report is a *product* with latency budgets (first paint ≤ 3 s),
pre-rendered comparisons, an attention budget, and kill -9 survivability; CE's
is a debug print. Direction differs too: CE's briefing recommends **system**
actions; BI's report asks **owner** decisions.
**Ahead:** BI, decisively — except for one thing BI lacks: CE's necessity
census, a one-line answer to "what still deserves to exist?" BI's report
counts what ran and what it cost; nothing in it can say "these three vocabulary
words and that whole branch have no live reason anymore."

### 1.9 LLMs as teachers ↔ the model cast

CE's Law 4: "The runtime must mostly work without them. Models edit the
organism; they do not impersonate it" (`README.md:24-26`). Delivered: the
ecology's week compiles 10.88 utility with zero LLM calls, and the teacher
layer (`src/ecology/llm/`, `src/ecology/research/`) is strictly *outside* the
tick — a 7-model research panel (DeepInfra) plus Jev decision gates, run under
a cache-first prompt protocol (stable prefix + append-only transcript,
ADR 0004), with every turn a receipt (ADR 0006). The open question the crew
asks itself: "What is the first *legitimate* runtime use of a teacher — and
does it violate Law 4 the moment it becomes load-bearing?"
(`library/open-questions.md`).

BI is the inversion: models are load-bearing everywhere — companion LLM and
critic vision model are *hot tier, always resident* (§1.9), generative models
are the production line, engineer agents write code. The rhyme that survives
the inversion is **containment by typing**: CE's "teachers edit the organism"
is BI's "characters change the recipe only through a closed, typed vocabulary…
they never write Blender code" and "data, never code, for agent changes"
(vision.md, CLAUDE.md). Both put a deterministic, inspectable channel between
a model and the state; neither will let a model freehand the system.

**Differ:** BI would fail CE's Law 4 on day one and considers that the point —
remove BI's models and there is no product. CE's runtime would keep ticking.
**Ahead:** CE on discipline (the zero-LLM lower bound is *measured*, not
asserted); BI on the practical machinery of using models well (rails, load
caps, demotion, calibration bands — §1.9's critic `calibration` record with a
measured FP/FN band is a trust idea CE's panel gates approximate with Jev
scores).

### 1.10 Provenance ↔ the audit log, assets, and licences

CE (ADR 0006): every panel turn records provider, model, latency, tokens,
cached tokens, provider-reported cost; transcripts land in `library/rounds/`
as receipts ("a receipt, not a text"); a vacant seat is recorded as vacant (the
MiniMax 401 became a transcript line); `ecology usage` aggregates the SQLite
ledger; total live panel spend ~$0.116 across 33 turns — believable precisely
because every call logged itself. The WHY graph itself is also provenance:
edges carry explicit/inferred provenance and every status carries a derivation
chain (`why/reach.py:284-316` — "no 'trust me'").

BI: provenance is structural, not documentary. One append-only audit log is
the source of truth; all other tables are projections rebuilt by folding it
(§1.0, §5) — "the audit log *is* the checkpoint" (decision #7, no LangGraph).
Every asset carries `Provenance {generator, model_id, weights repo+revision,
prompt ≤ 256 chars, seed, env, library_versions}` plus a `Licence` row with
`dependency_terms` — and "the scheduler stamps provenance, not the job…
so it cannot be forged or forgotten by an engineer process" (§1.6). No card
without an artifact (§1.8); "why?" is one tap on anything (ux-day moment 9);
re-runs through a different model are labelled "reinterpreted", never
"regenerated" (§1.6).

**Match:** both hold "provenance or it didn't happen" as constitutional, and
both record cost per action. **Differ:** BI's provenance is queryable state
with hash verification, licence gates that *block promotion*, and a
rebuild-by-fold ledger; CE's is markdown receipts plus a usage DB, its event
history is a bounded in-memory deque (10 000 events, `events.py:41`), and it
has no licence concept at all.
**Ahead:** BI. CE's round-002 fabrication finding (§ Method note) is the
cautionary tale BI's design already answers: a receipt is not the same as a
verifiable claim against state — BI's sealed-prediction hashes and
evidence-sha256s are exactly the anti-fabrication machinery a panel transcript
lacks.

### 1.11 Characters vs ship's computer ↔ processes vs teachers

CE has no characters and does not want any: the tiny MUD's citizens are
mechanical organs (observer, reflex, sleeper, reporter; the environment is
"the world, not a citizen", `demo.py:63-70`). Its only person-shaped things
are the *panel roles* (analyst, explorer, verifier, contrarian, architect,
indexer, synthesizer — `research/panel.py`), explicitly research-cell
metaphors rather than personas, used to argue about the system from outside.

BI's three-layer separation is its signature architecture (vision.md
§"The architecture: three layers"): **characters** (avatars, in-world, cheap,
local, closed vocabulary, never code), the **ship's computer** (no avatar, no
first person — "it never says 'I think'… that constraint… prevents the most
powerful agent in the stack from acquiring the authority of a person",
ux-trust §"Telling the computer apart"), and the **engineer** behind one
adapter (sandboxed, worktree'd, evidence-bearing, never writing the store).
The four separations — register, presence, authority, disclosure — are
specified, plus the whole voice apparatus (per-builder voice rules, zero
praise, the Critic authors nothing, the tone wheel, kid mode as chips-not-text).

**Match:** the *cut* is identical even though the sides are swapped: keep the
cheap thing inside the loop and the powerful thing outside it, typed and
gated. CE: mechanical processes in the tick, LLM teachers outside it. BI:
typed characters in the world, the computer and engineers behind work orders.
CE's panel roles even rhyme with BI's cast (contrarian↔Critic's job,
synthesizer↔Companion's), but CE's panel exists to *design* the organism; BI's
characters exist to *live* in the world.
**Ahead:** BI — the separation is a designed product surface with an ethics
grounding (ux-trust's companion-app literature). CE is ahead only in that its
"in-world" processes genuinely run and self-modulate today.

### 1.12 Work orders and vocabulary ↔ CE's unbuilt exocortex

BI's work order is "the bridge between the characters' closed vocabulary and
the computer that can extend it" (§1.3): compile-from-context-packet ≤ 20 s, a
≤ 25-word confirm line with a two-line price, never-guess questioning, states
from `compiling` to `kept`/`parked`/`failed`, acceptance checks that must be
machine-checkable, engineer attempts in seats, a merge gate (deterministic
rebuild → tests → geometry → render ladder → constraints → critic → licence →
budget audit → diff pack, §2.3), and promotion in one transaction (branch,
vocab word `coming-soon → active`, character notified — the "I can do rope
now" beat, ux-day 07:34).

CE has no counterpart *built* — but its roadmap names the same need twice:
"developmental biology — the sleeper should spawn specialist cells when
patterns justify them" and "exocortex evolution — teachers propose better
handlers for compiled routines" (`docs/ARCHITECTURE.md` layer map), with the
manifesto's own example ("a research cell that notices 500 monthly
road-analysis tasks spawns a RoadAnalysisCell — a new specialist, justified
through WHY", originals L96-98). Sleep compiles *deterministic* routines
mechanically; the exocortex would have *teachers* write better ones — "run
through the same promotion pipeline" (ADR 0003), i.e., proposed, validated,
promoted by realized utility.

**Match:** both grow capability through a gated lifecycle with evidence, and
both keep the proposer outside the runtime. CE's planned teacher-proposes /
pipeline-validates / utility-promotes is structurally BI's
engineer-proposes / gate-validates / owner-promotes.
**Differ:** the arbiter — CE's promotion court is measured utility; BI's is
the owner's keep. **Ahead:** BI, by the width of a full spec (states,
transitions, guards, budgets, evidence kinds) versus two roadmap lines. If CE
builds the exocortex, it should steal BI's merge-gate ordering wholesale.

### 1.13 Recipe history ↔ the world graph and the library

BI: "a project's source of truth is its recipe… renders and meshes are caches.
A night's work is a diffable recipe history" (CLAUDE.md). Recipes are immutable
versions; change is a typed op list (≤ 32 ops, ~412 bytes for the crate bet);
branches are pointer moves; the store is event-sourced SQLite with
content-addressed blobs; the audit log folds to rebuild every projection;
rejected branches are kept; idempotency keys and CAS transitions everywhere
(§1.0-§1.2, §5.3). Undo, branch, replay are free *by construction*.

CE: the world graph is typed, addressable, SQLite-backed — "not RAG — a world
model" (`src/ecology/world.py:1-11`) — with the memory maturity ladder as its
best idea (a memory node *graduates* observation→episode→pattern→routine→policy
and never backward, `world.py:110-121`). The `library/` is "cumulative: nothing
is deleted, things graduate (like memory in the world graph)"
(`library/INDEX.md`). But node state mutates in place (`touch()` overwrites
attrs; only created/updated ticks survive), and the observation stream — the
event bus history — is a bounded deque. There is no history of the organism's
own state changes, only of its observations.

**Match:** both keep the *decision structure* and regenerate the heavy
artifacts; both are seed-deterministic and replay-minded; both treat "nothing
is deleted" as law.
**Differ:** BI has versioned, content-addressed, crash-recoverable history; CE
has current-state persistence plus a human-curated library. **Ahead:** BI.

---

## 2. Three options

### Option (a) — builder-ide's core *is* cognitive-ecology

The core service on the Thor embeds the ecology runtime; characters and
engineers register as processes; the WHY graph governs vocabulary words, work
orders, branches and assets; the audit log rides the event fabric; a sleep
cycle consolidates each night; the morning report grows a necessity census.

**What it buys:** one law for "what deserves to exist" across everything
(words, branches, assets, characters); the self-retiring machinery; real
capability accumulation (sleep compiling the audit log into routines); and the
ecology gains a real workload and a real machine.

**Costs (high):**
- A rewrite of spec v2's data model to sit on the ecology's — which is the
  *weaker* foundation: the ecology has no service layer, no durability story,
  no concurrency, no crash recovery. §4/§5 of the spec would be built anyway;
  adopting (a) means building BI's entire operational spec *inside* a runtime
  whose persistence is in-place mutation plus a bounded deque.
- Law 4 collides with the product: five bidding processes and justification
  weights add machinery whose value for a two-user world is unproven, while
  the load-bearing parts of BI (companion, critic, generation) are exactly what
  the law excludes.
- The ecology's own evidence is thin and its authors know it: round 002's
  critique stands unanswered (telemetry monoculture; the day-5 cliff where 8
  scripts read dead while `active` stayed 15; no noise floor; no per-tick bid
  instrumentation; sleep-born routines have no WHY edges — their own open
  question). Making it the kernel adopts unvalidated semantics as foundation.

**Risks:** building the organism before the product; a third fork of the WHY
kernel (Rust reference, Python port, ours) with drift risk; the attestation
burden — a WHY-governed world needs someone to attest roots, and if the owner
is the only attester, the law is only as alive as the owner's attention.

### Option (b) — borrow the concepts and pieces into our own core (recommended)

Keep spec v2 as the core. Import, piecewise:

1. **Vendor the WHY kernel** (`ecology.why`, ~700 lines, pure, 39 tests, pinned
   to the 15 golden pairs). Feed it a graph BI already implicitly has:
   `RecipeEntry.origin → wo_ → goal`, vocabulary words → kept WOs, assets →
   entries. `wo.kept` / `wo.rejected` / branch applies are attestations with
   author and date. Output: the morning report's missing necessity census;
   `review-necessity` cards; `until`/`review-by` semantics for goals and WOs
   ("this branch's founding goal is 45 days stale — questionable, 0.25").
   Follow ADR 0001's rule: BI-specific cases become new corpus pairs first.
2. **Adopt the script-lifecycle semantics for the vocabulary**: words with zero
   calls over a window become *questionable* (they already have the call-count
   data, §1.5's derived view); self-retirement by measured disuse, owner-gated
   removal — CE's machine measurement, BI's human promotion.
3. **Add a sleep-style consolidation pass** to the night (a second night job,
   after the report build): compile the audit log's patterns — repeated critic
   reason codes per word, repeated context-packet shapes, repeated WO failure
   modes — into *proposals* (retire this word; propose that one; pre-warm that
   env). Mechanical, zero LLMs, proposal-only: the owner's slate is the
   promotion gate. This is CE's `SleepCycle` aimed at BI's ledger.
4. **Take the two clever small bits**: `Identity.stability()` as a taste-ledger
   convergence signal for the cold-start melt; tension semantics (expectation
   vs reality, pressure growing with age) as the internal shape of BI's parked
   questions, which today have no urgency ordering.

**Costs (low, per piece):** integration design, corpus-pair authoring, and
divergence management against upstream (the corpus contract is precisely what
makes this manageable). **Risks (low):** scope creep, and half-adopting
semantics — e.g. taking "questionable" without taking the weights, or taking
retirement without taking no-deletion.

### Option (c) — separate projects, interoperating

No code coupling. The ecology stays the research home for the always-on
organism; possibly it runs *on* the Thor as a tenant (its processes bidding
for real GPU budget — which would give its attention economy a real currency
and its rails something to enforce). Cross-use of its panel tooling (cheap
multi-model discussion with receipts) for BI design reviews. Findings shared,
code separate.

**Costs:** forgoes the structural gains; the necessity gap stays open.
**Risks:** near none — except concept drift: two lifecycles, two provenance
models, two "identity = preference" definitions evolving separately.

### Recommendation

**(b), with (c) as the frame.** Vendor the WHY kernel now — it is the single
highest-value import in the study: pure, tested, contract-pinned, and aimed at
a gap (necessity) that BI's schema is already implicitly building the graph
for. Borrow lifecycle and consolidation semantics as behaviors, not as a
runtime. Do not adopt the tick loop or the attention economy: for a two-user
product whose night is a scheduled window, justification-weighted per-tick
bidding is complexity without demonstrated value — and CE's own falsification
program hasn't run yet. Keep the ecology alive as the place where the
always-on question (Law 1) is actually tested, and revisit adoption when its
evidence improves.

**What would change the recommendation:**
- Round 002's seed-43 program actually lands — 5 seed-42 replicates for a noise
  floor, 3 domains with a regime shift, sleep-disabled control, per-tick bid
  instrumentation showing dead-justified work really starves — and passes: the
  runtime/attention layers become credible, and (a) becomes worth costing.
- The ecology grows a service/durability layer (HTTP, event-sourced history,
  crash recovery): the dominant cost of (a) collapses, and (b)'s "behaviors
  not runtime" line moves.
- BI's vocabulary grows into the hundreds of words with WOs landing nightly
  and no human able to tell what's dead: the WHY law stops being a nice-to-
  have and (a)'s law-everywhere story gets urgent.
- Casey wants the *daytime* always-on world — characters living and working
  between sessions, the "world exists before the player logs in" as an
  experience: that is Law 1 as a product requirement, and only the ecology has
  built anything for it.

---

## 3. What builder-ide would give back

1. **A second environment — the one its own experiment is asking for.** The
   ecology has run against synthetic telemetry only; its panel designed the
   next experiment (3 domains, regime shift, control) because one stationary
   stream is a monoculture. BI's audit log *is* that experiment, occurring
   naturally: recipe edits, sealed bets, critic verdicts, WO attempts, model
   loads, budget events — multi-domain, non-stationary, human-perturbed. The
   week-in-a-box lineage gains its second world without writing a simulator.
2. **The re-attestation loop the crown question says is missing.** Round 001's
   panel independently converged on the "re-attestation economics gap," and the
   crown-question reflection names digest 2's *liveness oracle* (premise
   currency, staleness-beats-liveness) as "the piece the built system still
   under-carries: `until`/`review-by` exist, but nothing yet *drives*
   re-attestation" (`library/reflections/crown-question-followup.md`). BI's
   keep/reject/apply events are a continuous, motivated attestation stream —
   necessity gets re-attested by a human with a stake, with author and date.
   That is the missing oracle, arriving as a product by-product.
3. **Provenance and licence discipline.** CE records model/cost receipts but
   has no licence model and no content-addressed artifact store. BI's
   `Asset`/`Provenance`/`Licence` design (scheduler-stamped, dependency terms,
   promotion-blocking) upgrades CE's library and usage ledger directly — and
   matters the moment the exocortex generates artifacts.
4. **The event-sourced history CE's world graph lacks.** "Store recipes, not
   meshes" — typed op lists, content hashes, fold-to-rebuild projections — is
   the durable form of CE's memory graduation ladder, which today sits on
   in-place mutation and a bounded event deque. An organism that wants to
   survive ten years needs BI's §5, verbatim.
5. **Thor-native generation as the exocortex's hands.** CE's unbuilt layer is
   "teachers propose better handlers"; its open question is the first
   legitimate runtime use of a teacher. BI's whole pattern — powerful agents
   propose typed changes through a gate, runtime stays mechanical, promotion by
   evidence — is a worked answer to Law 4's boundary question, and its model
   scheduler (tiers, per-family envs, load caps, batching) is the physical
   plant that makes teacher-proposals affordable on real hardware.
6. **The experience spine.** CE's Open Question #9 ("what's the user actually
   looking at? a map, not a dashboard" — unbuilt) is answered, in design, by
   BI: the three clocks, the sealed-bet drama, briefing-before-roaming,
   failures lead, computed status lines, restraint and line budgets, "honest
   idleness." When CE's briefing grows up, BI's ux-day/ux-trust are its spec.
7. **Scoring discipline.** Sealed-before-render, per-claim-type denominators,
   recency weighting, never-self-scored, two tallies (world vs taste) —
   directly applicable to CE's script utility learning and to judging teacher
   proposals ("does the teacher's handler beat the mechanical one" is a
   two-tally question), and the anti-fabrication answer to what round 002's
   architect did with its invented citations.

---

## 4. Questions for its authors/agents

Deciding the fit:

1. **Re-attestation economics.** Nothing today *drives* re-attestation —
   `review-by` expires silently. What mechanism do you intend (owner nudges in
   the briefing? attention-priced re-attestation?), and would an external,
   motivated attestation stream — BI's keep/reject events as att.txt rows —
   be a welcome input, or a violation of "att.txt is the constitution"?
2. **Has any of round 002 landed?** The noise floor (5 seed-42 replicates),
   seed 43 (3 domains, regime shift at tick 150, sleep-disabled control),
   per-tick bid instrumentation, the provisional 0.7-weight expiring WHY edge
   for sleep-born routines. Until then, is OQ#5's "probed — yes" better read
   as *implemented, not yet evidenced*? And: the panel's architect cited
   `lifecycle.py:72`, `scheduler.py:119`, and commit `7ef21a4` — none exist.
   Is a panel proposal pending until a build agent lands it, and should
   transcripts flag unreferenced claims?
3. **Who owns a sleep-born routine's justification?** (Your own ledger's first
   open question.) Is the panel's expiring-provisional-edge design the chosen
   answer, or is justification-by-pattern-node still open?
4. **Law 4's boundary.** What is the first *legitimate* runtime use of a
   teacher, and what test says it has become load-bearing? Would BI's pattern
   — teachers propose typed edits through a gate; the tick stays mechanical —
   satisfy the law, in your judgment?
5. **Embedding the kernel.** Does the golden-corpus contract (ADR 0001) permit
   vendoring `ecology.why` into a sibling project with the corpus tests kept
   intact? Would you accept BI's necessity cases (vocabulary words, branches,
   assets under goals) as new corpus pairs — i.e., is the corpus open to a
   second domain?
6. **Durability.** The runtime is single-threaded and in-memory; the world
   graph mutates in place; the event history is bounded at 10 000. What is the
   intended story for an organism meant to run for years — and would you adopt
   an event-sourced audit log (BI's §5) as the fabric's history?
7. **Identity — whose?** `identity.py` is unwired in the demo. Is identity the
   organism's values or the owner's taste? BI has a fully-specified owner-
   taste ledger; to you is that a complement, a replacement, or a conflation?
8. **Tension habituation.** Pressure compounds forever in v1 (your own open
   question). BI caps outstanding blocking questions at 3 and habituates by
   resolving on age (`demo.py:174-176` is yours; the cap is ours). Any planned
   convergence on bounded-outstanding-tension policies?
9. **A tenant, not a kernel.** Would you be interested in the ecology running
   *on* builder-ide's core as its second environment — its processes bidding
   for real GPU-minutes, its sleep reading BI's audit log? That tests the
   attention economy against a real currency and gives seed 43 its
   multi-domain stream for free.
10. **A local teacher seat.** The MiniMax 401 left the ideator seat vacant;
    the panel is hosted-only. Any plan for a Thor-resident seat so the teacher
    layer has a zero-hosted-cost fallback (BI's `aider-local` pattern)?

---

*Files cited:* cognitive-ecology — `README.md`, `docs/{MANIFESTO,ARCHITECTURE,
PROCESS,PROVIDERS,JOURNAL}.md`, `docs/ADRs/0001-0006`,
`library/{INDEX,open-questions}.md`, `library/originals/{MANIFESTO-…,
audit-why-2026-10-30}.md`, `library/reflections/crown-question-followup.md`,
`library/rounds/{001,002,003}-…md`, `src/ecology/{runtime,attention,scripts,
sleep,briefing,identity,tension,world,events,sim,demo,cli}.py`,
`src/ecology/why/{model,reach}.py`, `src/ecology/{llm,research}/*`,
`examples/{week_in_a_box,tiny_mud}.py`.
builder-ide — `CLAUDE.md`, `docs/vision.md`, `docs/design/core-spec.md`
(= `~/lm-wt/spec-v2/SPEC.md`), `docs/research/{ux-day,ux-trust}.md`
(spec sections cited as §; ux documents by section name).*
