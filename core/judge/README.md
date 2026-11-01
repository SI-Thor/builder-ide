# `core/judge` — one judgment seam, three backends

`docs/research/jev.md` named the seat and the shape; the liquid study
(`docs/research/liquid-study.md` Part 3, item 1) sized it and picked the
model. This package is the seam they asked for: **typed judgments over
one shared state**, answered by whichever backend the caller configures,
under a confidence gate that is a measurement rather than a taste, with
**every attempt recorded in the ledger**.

The four question kinds:

| kind | the question | what comes back |
|---|---|---|
| `choice` | named options | a probability per option; the argmax answers |
| `score` | an ordered scale of 2–10 levels | a probability per level |
| `noul` | a bare claim | P(true), and its complement |
| `verify` | a claim against evidence | P(true) — carried on the wire as a noul over claim + evidence |

A **pack** is a question set over one shared state, asked in one call —
§4.1 measured the per-question saving of the shared prefix (a pack of 3
on d1-3B Q8: 116.9 ms, against 3 × 49 ms standalone). The pack's hash
(state + questions, order included) is what every recorded verdict
cites.

## The modules

| module | what it owns |
|---|---|
| `models.py` | the records: `Question`, `Judgment`, `JudgeCost`; the state hash, the question-set hash, the pack hash (state **and** questions); the sum-to-one rule |
| `backends.py` | the wire and the four backends (below); `JudgeRefusal` with a closed reason code |
| `gate.py` | the confidence gate as policy: `ConfidencePolicy` (τ, with the shipped `CALIBRATED_TAUS`), `EscalationLadder`, `StandingGate` and its `StandingConfig` |
| `judge.py` | the `Judge` service: ask a pack, pre-flight its size, walk the ladder, record every attempt; `fold_judgments`; `standing_from_rows` (the standing, rebuilt from the log); `plan_pack` |
| `shortlist.py` | the first caller: `JudgePriorChooser`, the tiles shortlist |
| `events.py` | the seat's one audit type, `judge.verdict` |
| `ports.py` | the ledger protocol (the same shape `core.night.ledger` implements) |

## The backends

Each is a parameter with a default (`Judge()` runs the fake).

| backend | what it is | what it costs |
|---|---|---|
| `FakeBackend` | deterministic; scripted answers for tests | its wall time, nothing else |
| `D1Backend` | llama-server's `/v1/systemone` — the exact call `docs/research/liquid-study-scripts/` makes, on whatever port the caller configures. The server is the caller's to start and stop (under `~/lm-wt/heavy.lock`, one at a time) | GPU minutes, no cents |
| `JevBackend` | TypeSafe's Jev over its System One HTTP provider | the key comes from the environment (`JEV_API_KEY`, or `TYPESAFE_API_KEY`) and is **never printed**; the price per call is not published, so the row records `input_tokens` and `cost_known: false` |
| `ClefBackend` | Cloudflare Clef on Workers AI, in the `{"model", "input": {state, questions}}` envelope `clef-cascade/prior-poc/worker-index.js` took. Nothing here deploys anything | priced from the published neuron rates |

All four speak one canonical wire shape — a state plus typed questions,
back a probability per option — which is why the cascade's rungs are
configuration, not code.

## The confidence gate is policy, and the default is E1's

Lab-cascade's E1 (folded into the liquid study as §1.4): on the action
gate, **every** d1-2B error sat below confidence 0.5; above 0.5 the
model was 196/196 exactly right; a gate at 0.5 caught 100 % of the
errors with 2 % of the traffic. So:

> **act at or above τ; escalate below** — τ per (backend, model,
> task): the pair's own calibration where the shipped table has one
> (`CALIBRATED_TAUS`), `DEFAULT_TAU = 0.5` otherwise.

Escalation walks a configured `EscalationLadder` (the brief's: local
d1-2B → cloud Clef / Jev → a cloud LLM work order). It is **per
question**: only the questions that fell short are re-asked of the next
rung, over the same shared state. A judgment still below τ at the
ladder's end is **surfaced, not acted on** — the row says `surfaced`,
`JudgeAnswer.surfaced` is true, and acting on it is the caller's
explicit decision, never the judge's.

Where a judgment drives a state that **persists across ticks**, a raw
threshold flickers — each flap a fact written, withdrawn, written
again. `StandingGate` is that case, and it is not a new mechanism: it
wraps `core/hysteresis` (built, measured, 13 tests) with the judgment's
confidence as the continuous signal, τ as the enter line, and a band
inside which the standing does not move. The clock stays the caller's.

**The standing's defaults are measurements, all the way down.**
`Judge(standing=StandingGate())` routes the ladder's escalation trigger
through the hysteresis standing: the first rung's act-or-escalate
decision is the standing's word per question id (the subject that
persists across ticks), the later rungs stay gated by the policy's τ,
and `judge(..., now=tick)` is required — a standing without the
caller's clock cannot replay. The **shape** comes from replaying the
liquid study's recorded d1 traces through the gate
([`docs/lab/exp-hysteresis-d1.md`](../../docs/lab/exp-hysteresis-d1.md)):
`StandingConfig` = band 0.15, dwell_up 2, dwell_down 0 — the one shape
that kills the flicker while keeping the raw gate's catch of the
model's misreadings and its agreement, at a drop latency of zero and an
act latency of at most two ticks. The **τ is resolved per ask**: the
shipped `CALIBRATED_TAUS` names the measured τ per (backend, model,
task) — on the traces the calibrated τ was 0.7, where the raw gate
flickers 66 times in 240 ticks; `DEFAULT_TAU` covers an uncalibrated
pair until its own calibration lands in the table; an explicitly bound
`StandingGate(tau=…)` is the caller's. Wherever the τ came from, the
row says so — `tau_source` is `calibrated`, `configured` or `default`
on every `judge.verdict` row.

**The standing is durable, and the ledger is its memory.** A
standing-governed row carries everything the gate consumed — the
confidence (in the judgment), the `tick`, the `tau`, and the
`standing_config` (band, dwells) — so a restart, a new process or a
clock jump loses nothing:

```python
from core.judge.judge import standing_from_rows, fold_judgments

standing = standing_from_rows(fold_judgments(ledger.events()))
judge = Judge(backend=backend, standing=standing, ledger=ledger)
```

The rebuild replays the rows through a fresh gate, subject by subject,
and **refuses what it cannot reproduce**: a recorded word the replay
does not return, a null-confidence tick that moved a standing, a τ or a
shape that moved under a live subject. The returned gate continues
exactly where the log ends, dwell counters included. The whole property
is exercised against the real recording —
`tests/judge/test_d1_replay.py` replays the 240-tick d1-2B trace
through the default wiring and fails unless it reproduces the sweep's
measured result (66 flickers at the raw calibrated τ, 1 after the
gate), tick for tick, with the standing rebuilt from the ledger alone
at the midpoint.

The standing's word rides on every `judge.verdict` row and on
`JudgeAnswer.standing_words`, and `surfaced` follows the standing where
it governed — the raw gate word and the standing's can differ (a sub-τ
tick the band holds is acted on; a confident tick during warm-up is
escalated), so the row carries both. A judgment with no confidence
never passes and leaves the standing untouched: a continuous gate takes
no reading from a null.

## Every judgment is recorded

One `judge.verdict` row per **attempt**: the author
(`judge@<backend>:<model>` — every row records its author), the
distribution, the confidence, τ and where the τ came from, the gate
decision, the cost (wall seconds, GPU minutes, hosted cents, input
tokens), the latency, the hashes of what the attempt actually asked
over — the state, the questions, and the pack (state **and**
questions, one hash) — and the rung the attempt was escalated from.
**Refused attempts are rows too** — the edges are the story, and a
refusal row says whether the ladder moved on after it
(`refusal_then_escalate`, and the rung it was `escalated_to`): a
backend failure — a d1 lock, a missing Jev key, a Clef network error —
is an edge the ladder walks past, not the end of the walk.

**The pack is pre-flighted against the ledger's 4 KiB payload cap
(§1.8).** `plan_pack` measures each would-be row through the same
payload builder the recorder uses, at the widest legal float width plus
a margin, and partitions an oversized pack into sub-packs that fit —
the shared state kept whole, the questions split, every sub-pack its
own recorded attempt, the answers merged in pack order. A refusal for
size never reaches the caller as "no answer". The one honest exception:
a single question whose own row cannot fit any partition still refuses,
loudly — one question cannot be split further, and a truncated or
missing answer is the failure this replaces.

**Escalation asks over the current state.** The caller may wire a
`state_reader` — its own read of the shared state — and every rung
after the first re-reads through it before asking, so an escalated
question is answered over the world as it is now, and its row cites its
own state and pack hashes rather than the first rung's. Without a
reader, every rung sees the state the caller passed, as before.

**Never-wait is a deadline** (`docs/lab/exp-never-wait.md`):
`judge(..., deadline_seconds=…)` bounds the walk. The first ask is
never refused the chance — the local rung is the fallback the first
mile commits. Past the deadline the ladder stops, the best answer so
far commits (below τ, so `surfaced` — the caller decides), and a rung
asked within the deadline that returned past it is recorded as a
**supersede** beside the committed answer, which it does not change;
`late_by_seconds` says by how much it was late, and the commit's own
row (`judge@deadline:never-wait`) lists what it committed. Committed
history is never rewritten; the late answer lives in the log for
whoever reads it next. With nothing at all to commit, the refusal is
loud, not a stall.

```python
from core.judge.judge import fold_judgments

rows = fold_judgments(ledger.events())   # one entry per judgment,
                                         # plus judgment-less refusal rows
```

## The first caller: the tiles shortlist

`JudgePriorChooser` is the tiles shortlist wired the way the brief
asked: **the judge answers `choice` over the chooser's K candidates;
the bandit is kept; the judge is the cold-start prior**. It is a
`ContextualBandit` subclass — the door, the exploration, the
propensity arithmetic and the nightly refit are the bandit's own. What
changes is the prior mean of a cold bucket: the judge's probability
per tile stands where the flat 0.5 stood, so a cold bandit's argmax is
the judge's answer, and real plays wash the prior out at the rate the
bandit's own prior count sets. A surfaced judgment sets no prior.

The play keeps the propensity the chooser measured at the choice
(tiles rule 8), so the log stays off-policy evaluable
(`core.tiles.ope`); the judgment row carries the why.

## Running it

```bash
.venv/bin/python -m pytest -q tests/judge    # 110 tests, no network, no GPU, no LLM
.venv/bin/python -m pytest -q                # the whole core
```

The Thor measurement (cold-start curve, agreement, latency, peak
memory): [`docs/lab/exp-judge-tiles-coldstart.md`](../../docs/lab/exp-judge-tiles-coldstart.md).
The standing gate's configuration, measured on the recorded d1 traces
(the sweep, the guarded choice rule, and the wiring's two behaviours):
[`docs/lab/exp-hysteresis-d1.md`](../../docs/lab/exp-hysteresis-d1.md).
The replay test that holds the defaults to that measurement — the
240-tick d1-2B trace through the wired judge, restart included — is
`tests/judge/test_d1_replay.py`, on the distilled recording beside the
sweep (`docs/lab/hysteresis-scripts/results/d1-2B-ticks.json`).

## What is not here yet

The `verify` rung against a real critic report (the seam accepts the
questions; the critic's evidence packets are the caller's), the Jev
MCP stdio transport (the HTTP provider is the shape this package
speaks), the night executor as a second caller, and the work-order rung
*as a work order* — the ladder's end is surfaced rows now; filing the
order belongs to the work-order seat. Each is a small step on a seam
that already records everything.
