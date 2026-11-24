# prior-art.md — what our old work already has that general-contractor can take

Scout-gc report, 2026-11-02. Read-only pass over Casey's GitHub orgs (SuperInstance, lucineer, SI-Thor,
purplepincher, si-ready, patchwork-quilt, Luciddreamer-ai — everything `gh` lists for the account), with
skims only: READMEs, docs, and a few source files. Nothing was cloned. Each find lists: the link, the idea,
whether it was **built** (code and tests exist, read at least partly) or **written** (docs/papers only), and
what the general-contractor (GC) should take. At the end: the 5 ideas most worth taking.

The GC brief itself was read first over `ssh thor-lan` (`~/lm-wt/general-contractor/BRIEF.md`), so "what we
take" is judged against its model: job with acceptance test + deadline + crew-time budget, bids from evidence,
award, checkpoint burn, close, debt and reputation, retooling, disappearing-tool design goal.

---

## A. The named leads

### 1. SuperInstance/crab-cell
<https://github.com/SuperInstance/crab-cell>
"The crab owes, the watcher checks, the ledger is where they meet." An assigned role creates an obligation (a
debt); a routine runs contained and reports honestly; a watcher decides GO / NO-GO / ESCALATE each cycle and
fulfills, renews, or escalates debts when reports are late or dishonest. Every run appends a token to the
ledger; the loop is the mechanism by which untrusted work becomes trustworthy. "Nothing runs free... fail to
manual, not to automatic."
**Built** — `watcher.py`, bwrap/Landlock sandbox shells, templates, worked examples, seven docs, a 60-second test.
**Take:** the debt vocabulary is the GC's overrun model (overrun = debt carried on the sub, fulfilled by
underruns, renewed when unpaid). GO / NO-GO / ESCALATE is exactly the 80%-of-bid checkpoint: stop, report, and
let the GC re-scope or cancel. The "does it report honestly?" question at every cycle is the discipline the GC
should apply at close time before writing actuals.

### 2. SuperInstance/nursery-v2
<https://github.com/SuperInstance/nursery-v2>
"Tokens, debts, recomputable lineage." A child's public TOKEN.md states name, inputs, outputs, counterparty and
declared debts ("I owe you" is part of the token); the private ROOM.md holds reasoning. Debts carry counterparty,
service mechanism, inherited debt. Scores count only if they can be replayed from the ledger ("audit by
recomputation — don't trust the record, recompute it"). Obligation trials test debt-service under pressure and
token-sufficiency (can a peer predict behavior from the token alone). Breeding selects on obligations, not
capabilities.
**Built** — Python platform, trials/, CORRECTIONS.md accounting of what v2 fixed.
**Take:** the `gc brief` block is a TOKEN: scope, acceptance test, deadline, budget, counterparty, penalties —
self-contained so a seat can predict its own behavior from it. Evidence must be recomputable from
`ledger.jsonl` alone (rail for `gc report`: never trust a stored ratio, re-derive it). Debt-service-under-pressure
is a test the GC can run on a sub (does it actually stop at 80%?). Debts keyed to a counterparty is the
ADDENDUM's (sub, developer/GC, toolset) key.

### 3. lucineer/cuda-contract
<https://github.com/lucineer/cuda-contract>
Rust contract layer for agents: `SlaClause { metric, target, minimum, penalty_per_violation, window_ms }`,
`Contract { provider, consumer, capabilities, qos_tier, clauses, expires_ms }`, `ComplianceRecord` (metric value,
compliant flag, penalty), negotiation `Proposal` with `max_penalty`, and a `ContractManager` with compliance
tracking and penalty/reward calculation. QoS tiers: BestEffort → Guaranteed.
**Built** — real crate, serde types, 8 unit tests (skimmed `src/lib.rs`).
**Take:** the record shapes for job / contract terms: a clause is (metric, target, minimum, window) — that is
already an acceptance metric with a threshold and a deadline window. Penalty-per-violation is the late-day
penalty arithmetic. `max_penalty` in the proposal is the sub's downside cap and belongs in a bid. Compliance
records map 1:1 to checkpoint rows.

### 4. lucineer/flux-market
<https://github.com/lucineer/flux-market>
The repo description promises "agent marketplace, reputation scoring, service discovery"; the actual content is
a different thing: "Structural Waste Market Simulator" — a CUDA order-book thesis claiming 60% structural waste,
flash crashes as information-cascade failure, and Law 75: learned trading strategies catastrophically fail
against fixed greedy ones.
**Written only** — README + one motivating file, no simulator code.
**Take:** one caution worth keeping: learned bidding strategies underperform fixed rules in their own model,
so compute bids from a fixed rule over history (a quantile of past actual/estimate), not from a trainable bidder.
Everything else is noise for the GC. Also a hygiene lesson: the description is stale — record ideas in the
ledger, not in metadata that can drift.

### 5. lucineer/cuda-budget
<https://github.com/lucineer/cuda-budget>
Rust budgeting: `ResourceType { ComputeMs, Tokens, MemoryBytes, NetworkBytes, MoneyCents }`,
`Allocation { allocated, spent, limit, alert_threshold }` with `utilization()`, `should_alert()`,
`is_exhausted()`; `AgentBudget` per agent with priority and alerts; budget transfer and spend-rate forecasting.
**Built** — real crate, 9 unit tests (skimmed `src/lib.rs`).
**Take:** this is crew-time accounting done already. `allocated` = bid, `spent` = burn, `alert_threshold` = the
80% rule (any fraction works — make it a parameter recorded on the job). Multiple resource types support the
honesty requirement: `Tokens` is measured, `ComputeMs`-as-wall-time is estimated — label which is which per row.
Forecasting (spend rate projection) is what a checkpoint should print so the GC can see overrun coming.

### 6. SuperInstance/trust-ledger
<https://github.com/SuperInstance/trust-ledger>
Trust as a re-derived scalar: every decision is one line in an append-only ledger
(`ts | decision_type | stake | outcome | autonomy_delta`) and the score is always recomputed from the record —
it decays unless the agent keeps acting well. Fixed delta table, capped positives, per-stake ceilings on what the
agent may do alone. "Trust compounds on observed correct action, never on wakeups."
**Built** — `trust.py`, tests, RESULTS.md with a line-by-line explanation output.
**Take:** GC reputation (on-time rate) must likewise be derived from the ledger at read time, never stored in a
config that drifts. Only closed jobs move reputation — bids and talk earn nothing. Per-stake ceilings are a
direct model for per-class budget ceilings per sub (a deep-debt sub gets smaller jobs). Deltas stay capped and
small so one win can't launder a record.

### 7. SuperInstance/decision-ledger
<https://github.com/SuperInstance/decision-ledger>
One row per (source, question, state, answer) with a question-hash of the framing. Two rules: a near-0.5 answer
is a PASS meaning the question is badly framed (clustered passes → rewrite queue), and high-confidence teacher
rows calibrate students (Platt scaling; recorded fix ECE 0.22 → 0.027). A disagreement table separates
"question_invalid" (rewrite the framing) from "student_miscalibrated" (fit the student).
**Built** — `ledger.py` with `pass_detector`, `platt_fit`, tests, CALIBRATION.md, worked scripts.
**Take:** this is the specialization machinery of ADDENDUM 1, already built once. Export a sub's high-confidence
close rows as labels; fit a weak/new sub's estimates against them. Hash the job-class spec the way they hash the
question framing, so an overhauled brief is attributed to the spec that caused the misses. When sub and GC
disagree on a class, the table tells you which fix applies: rewrite the brief or retool the sub. Nothing in the
old work does quantile bidding — that part is genuinely new here.

### 8. SuperInstance/ledger-continuity
<https://github.com/SuperInstance/ledger-continuity>
"The ledger outlives the agent." Recovery from a dead agent from the ledger file alone: self-contained task
claims, per-subresult claims with mandatory evidence, heartbeats ("without heartbeats, a successor cannot
distinguish dead from slow"), and re-check-before-claiming so recording is exactly-once under at-least-once
execution. Proven with three crash variants (clean, mid-subtask, chained A→B→C).
**Built** — small library + `test_recovery.py`, actually run and passing.
**Take:** job rows must be self-contained (scope + acceptance test inside the claim), so a relaunched seat
continues from the ledger with no shared memory — this matches the seed data's relaunches. Heartbeats belong to
the long-run-babysit job class, and the "dead vs slow" distinction is what tells the GC when to open a change
order versus cancel. Partial work (milestone results with evidence) survives a stop, which is what a checkpoint
should capture.

### 9. SuperInstance/doubt-ledger
<https://github.com/SuperInstance/doubt-ledger>
An append-only record of what you stopped checking, why, what covers it, and the event that brings it back for a
look ("trust relocates blindness; it does not delete it"). Five mandatory fields; incomplete entries are
refused; discharge demands a written reason; per-line checksums, signable tip root; exports in the qmr1 receipt
dialect so any qmr1 reader can consume it without knowing this repo exists.
**Built** — grammar-enforced ledger with pin tests P1–P7, export and signing waves.
**Take:** on long jobs somebody stops checking something mid-run; a GC that wants honesty should record that as
an entry rather than a silent gap (good fit for the checkpoint "unknown" state). `revisit_trigger` is the right
shape for change-order conditions. The qmr1 export pattern is the interop model for the disappearing-tool goal:
the GC ledger should be readable by other fleet tools without them adopting the GC.

### 10. SuperInstance/AI-Writings — THE-TWO-ECONOMIES-OF-CORRECTNESS
<https://github.com/SuperInstance/AI-Writings/blob/main/archive/versions/THE-TWO-ECONOMIES-OF-CORRECTNESS--HERMES-SYNTHESIS.md>
(also `--SEED-ARCH` and ~10 other re-tellings in `archive/versions/`; the canonical essay is referenced as their
source). The idea: there are two ways to be right — computation (infinite coverage, finite depth; you fall off a
"depth cliff") and recognition (infinite depth, finite coverage). Every model has a critical angle; work should
be decomposed into recognizable pieces and routed to where it sits relative to that angle.
**Written** — an essay with many model-generated versions; no code.
**Take:** the theory behind the ADDENDUM's specialization rule: job classes are the decomposition, and a sub
specializes exactly where its recognition is reliable (its estimates land) instead of falling off the depth cliff
(where it underbids or overruns). Route classes to subs by measured estimation reliability, not by declared
skill.

### 11. lucineer/papermill — vessel-economy and fleet-at-scale
<https://github.com/lucineer/papermill/blob/main/technical/vessel-economy.md>
(<https://github.com/lucineer/papermill/blob/main/visions/fleet-at-scale.md>) Market design for agent "vessels":
a reputation-backed unit of account (VRT), and a capability auction — RFP with requirements + max budget, bids
carrying price, capability evidence and reputation, then multi-factor selection (price × reputation × fit),
typically a reverse auction. Reputation updates use a client satisfaction score; also barter, subscription
(recurring services), gift economy inside one trust cluster. fleet-at-scale speculates about self-organizing
specialist clusters.
**Written** — LLM-authored papers, no code of its own.
**Take:** the award rule is already drafted here (price, reputation/on-time probability, fit — the GC brief's
three factors). A bid should carry an attestation backed by the sub's evidence record, and a subscription is a
standing contract for a recurring job class (the director's lanes are recurring). Skip the currency and the
macroeconomics: the GC's scarce resource is crew-time, and an internal token would be lock-in.

---

## B. Other finds worth taking

### 12. patchwork-quilt/stitch
<https://github.com/patchwork-quilt/stitch>
"The smallest thing that, if missing, makes every layer above it weaker." Eleven append-only operations on agent
state over hash-chained JSONL; every `effect` records predicted vs observed, charges the surprise against a
per-tenant per-tick budget ("γ + η ≤ log₂3", treated as a quota, not physics); writes never wait on a clock,
peer, or sequencer — verification and agreement are a fold over two files at read time.
**Built** — Python stdlib library with that principle spelled out.
**Take:** predicted-vs-observed per record is bid-vs-actual at the smallest grain; the GC's ledger rows should
carry both sides so `gc report` is just a fold. A per-tick budget is the crew-time window (the 5-hour plans)
enforced in data. Their "smallness is the scaling strategy" note is the ADDENDUM 2 disappearing-tool goal taken
seriously — a precedent for the GC's plain-formats, no-coordinator choice.

### 13. SuperInstance/receiptd
<https://github.com/SuperInstance/receiptd>
One append-only JSONL hash chain as the fleet's trust layer: tamper one byte and `verify` names the line; delete
a line and `verify` names the gap. Verdicts are three-valued (-1 / 0 / +1) with INCONCLUSIVE as a first-class
state ("a gate that can't say UNKNOWN will lie to you"). A credential split so full rewrites with recomputed
hashes are also caught.
**Built** — daemon + CLI twin, 12/12 pin tests.
**Take:** the concrete prior art for the GC's hash-chained `ledger.jsonl` — copy the verify contract (name the
line, name the gap) into the tests. Three-valued checkpoint verdicts (on-track / violated / can't tell) beat a
boolean for the "80% without a pass" report.

### 14. SuperInstance/casting-call
<https://github.com/SuperInstance/casting-call>
A capability atlas mapping pipeline roles to models: what each voice does, where it breaks, tempo ranges;
`cast(role)` before each stage, with the counterpoint constraint (don't run two of the same voice in parallel)
and what-if analysis for model swaps.
**Built** — atlas + casting director code.
**Take:** the seat is data. Model-per-class track records live in one atlas the GC can read before awarding.
Retooling is a re-cast: change the model for that job class. What-if analysis fits bids (swap the seat, re-price
the bid before awarding).

### 15. SuperInstance/agent-inbox
<https://github.com/SuperInstance/agent-inbox>
A git-native task queue with no daemon: drop a self-contained task file in `inbox/`, a worker claims it with a
commit (git settles races), work happens, results land in `done/`. Rules: the file is the message ("say what to
do, what done looks like, where to put results"), "claim before you work", "results are commits, not chat
messages".
**Built** — CLI + worker loop, usable as-is.
**Take:** the transport fallback for seats that can't call the `gc` binary: the contract block rendered by
`gc brief` is the task file; claim semantics handle two subs competing for one job; `done/` = the close event.
"Say what done looks like" is the acceptance test in one sentence.

### 16. SuperInstance/AI-Writings — `situations/`
<https://github.com/SuperInstance/AI-Writings/tree/main/situations>
Development by authored future scenes: write the world where the capability is lived in; the friction compiles
to gaps; gaps compile to machine-checkable acceptance predicates ("the future writes the acceptance test"); a
wide run returns a failure map; building = closing a rung. The README honestly marks which cross-references
are still pending merge.
**Written framework, partially built** (gap ledger and certain rungs shipped in `jev-quilt`; some paths marked
pending).
**Take:** an acceptance test is a compiled predicate with a named goal line — keep a tiny grammar (command exits
0, or metric crosses threshold) instead of prose. A checkpoint report is a failure map. Their discipline of
marking ungrounded references applies directly: everything in the GC's seed track record reconstructed from the
2026-11-01..02 lanes must be labeled reconstructed.

### 17. SuperInstance/AI-Writings — essays/the-pool-as-market.md
<https://github.com/SuperInstance/AI-Writings/blob/main/essays/the-pool-as-market.md>
The question pool read as a market for scarce attention: price = attention consumed / progress produced;
farmed prices are the known failure ("a question's price must be set by whoever answers, never by whoever asks");
long questions get systematically underpriced because their ask never clears; zero-progress spend is invisible
because the invoices live in separate transcripts.
**Written** — one essay.
**Take:** prices (bids) must come from the sub's recorded actuals, never from its self-reported ask — same
reason, same failure mode. `gc report` should show burn vs progress made so zero-progress burn is visible in one
place. The affordability of short jobs vs long jobs is a real bias to watch in awarding.

### 18. lucineer/flux-emergence-research
<https://github.com/lucineer/flux-emergence-research>
55+ GPU experiments on emergent specialization among 1024 agents: specialist advantage has a critical density
threshold (peaks around 8:1 agent:resource); accumulation beats adaptation (fixed roles outperform evolved
ones); information only matters under scarcity; and a long "killed hypotheses" list (communication, trading,
reciprocity, pheromones, lifecycle, evolution — all null or negative).
**Built** — CUDA experiment variants with a results matrix and recorded kills.
**Take:** measured specialization is cheaper than evolved allocation (supports the fixed bid rule and the
ADDENDUM's "specialization is measured, not declared"); enforce bid discipline only when crew-time is scarce;
and keep a "what we tried that did not help" section in the GC docs — every repo here that has one is more
trustworthy for it.

### 19. Name-level leads seen in the pass (descriptions and small skims only)
- `lucineer/flux-trust`, `lucineer/cuda-trust`, `lucineer/flux-confidence` — Bayesian trust with "grows slowly, decays fast", revocation; usable decay math for reputation in `gc report`.
- `SuperInstance/gitpp-intent-ledger` — append-only ledger of proposed action + gate decision + outcome, with a whole-history check for actions that landed unlicensed; the GC analog: closes with no award, awards with no bids, checkpoints without claims.
- `SuperInstance/tminus-dispatcher` — T-minus cue timing ("job-time is the t-minus"); `lucineer/flux-scheduler` deadline-aware dispatch; `lucineer/cuda-adaptive-rate` token-aware backpressure for plan-window limits; `lucineer/flux-ephemeral` TTL + CPU/memory budgets per task.
- `SuperInstance/build-guardian` — budget enforcement plus bloat-trend alerts; the trend alert is better than a raw threshold for spotting slow overruns.
- `SuperInstance/qprobe` — calibrated, receipted question grids (eval calibration vocabulary).
- `SuperInstance/synoptic-sheet`, `SuperInstance/whole-house-quilt`, `SuperInstance/quilt-stone` — living renderings of append-only ledgers and one zero-dep chain verifier ("42/42 sibling chains verified"); `quilt-stone` is worth reusing if the GC ledger ever needs cross-machine verification.

---

## Negative results (so nobody re-searches)

- No prior work implements **bid calibration at a quantile of past actual/estimate** ("bid high, overbidding
  beats underbidding"). The pieces exist (evidence records, Platt scaling, predicted/observed rows) but the rule
  itself is new in general-contractor.
- Code search for `contract|bid|subcontract|debt|owe|escrow|reputation|calibrat|estimate|SLA|budget|ledger`
  across the orgs turned up no second contractor/bidding system. The metaphor hits ("a contractor and a debt")
  are in the AI-Writings prose corpus (e.g. `seed-canon/papers/paper-590.md` on constraints as timed
  "dogs" holding a hatch, `the-pool-as-market.md`, `THE_TOKEN_FIRST_CONTRACT.md` on silent contract drift between
  chained models). They are metaphors and warnings, not mechanisms.
- `lucineer/flux-market` is not what its description says (see #4). Don't send anyone back for reputation code
  there.

---

## The 5 ideas most worth taking

1. **Overrun is debt, keyed to (sub, job class) — carried, repaid by underruns, and it triggers a retool.**
   From crab-cell (a role that owes, debts fulfilled or renewed, failures escalate) and nursery-v2 (debts are
   what a worker must do, with a counterparty and a service mechanism). One ledger event for every debt
   movement; a sub in deep debt for a class is retooled — re-cast, smaller jobs, better brief — before it bids
   that class again. This is the piece that makes underbidding expensive instead of merely unlucky.

2. **Every close writes the sub its own evidence record, and the next bid is computed from it — recomputable,
   keyed by (sub, GC, toolset).** From nursery-v2 ("audit by recomputation: if you can't recompute it, it
   doesn't count") plus decision-ledger (teacher rows calibrate students; a miss is either a bad spec or a
   miscalibrated sub, and the two get different fixes). Track |actual/estimate − 1| and on-time rate per class;
   specialization is where those are small. The GC routes each class to the sub that estimates it best.

3. **The budget is watched, not just recorded: alert at the threshold, stop at 80%, report.** From
   cuda-budget (`alert_threshold`, `utilization()`, spend-rate forecasting) and receiptd (three-valued verdicts,
   INCONCLUSIVE first-class) and crab-cell (GO / NO-GO / ESCALATE, nothing runs free). At 80% of bid crew-time
   without the acceptance test passing, the sub stops and files a report the GC must answer with re-scope,
   change order, or cancel — no open-ended runs.

4. **One append-only hash-chained JSONL, every row carrying predicted vs actual, verified at read time.**
   From stitch (predicted/observed per write, charged against a per-tick budget, writes never block) and
   receiptd (tamper a byte → verify names the line; delete → names the gap) and doubt-ledger (record what you
   stopped checking instead of trusting silently). `gc report` then becomes a fold over the ledger, and any
   other tool can read the file without adopting the GC — the disappearing-tool requirement lives here.

5. **Clause-shaped contracts: an award is a multi-factor selection, and every penalty is arithmetic on recorded
   numbers.** From cuda-contract (clause = metric + target + minimum + window + penalty-per-violation;
   proposal carries max_penalty = the sub's cap) and papermill's capability auction (bid = price + evidence
   attestation + reputation; award weighs price, on-time probability, fit). Job, bid, award, change order and
   close become one record family in one small grammar — which is how the thing ends up feeling like a pencil
   instead of a platform.