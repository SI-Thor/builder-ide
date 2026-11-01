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
| `models.py` | the records: `Question`, `Judgment`, `JudgeCost`; the pack hash; the sum-to-one rule |
| `backends.py` | the wire and the four backends (below); `JudgeRefusal` with a closed reason code |
| `gate.py` | the confidence gate as policy: `ConfidencePolicy` (τ), `EscalationLadder`, `StandingGate` and its `StandingConfig` |
| `judge.py` | the `Judge` service: ask a pack, walk the ladder, record every attempt; `fold_judgments` |
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

> **act at or above τ; escalate below** — τ per (backend, model, task),
> defaulting to `DEFAULT_TAU = 0.5`.

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

**The standing has its first real wiring, and its defaults are a
measurement.** `Judge(standing=StandingGate())` routes the ladder's
escalation trigger through the hysteresis standing: the first rung's
act-or-escalate decision is the standing's word per question id (the
subject that persists across ticks), the later rungs stay gated by the
policy's τ, and `judge(..., now=tick)` is required — a standing without
the caller's clock cannot replay. The defaults come from replaying the
liquid study's recorded d1 traces through the gate
([`docs/lab/exp-hysteresis-d1.md`](../../docs/lab/exp-hysteresis-d1.md)):
`StandingConfig` = τ `DEFAULT_TAU` (per-task calibration names τ; on
these traces the calibrated τ was 0.7, where the raw gate flickers 66
times in 240 ticks), **band 0.15, dwell_up 2, dwell_down 0** — the one
shape that kills the flicker (→ 1) while keeping the raw gate's catch of
the model's misreadings and its agreement, at a drop latency of zero and
an act latency of at most two ticks. The dwells are in ticks of the
caller's clock; a caller on a seconds clock passes its own numbers. The
standing's word rides on every `judge.verdict` row and on
`JudgeAnswer.standing_words`, and `surfaced` follows the standing where
it governed — the raw gate word and the standing's can differ (a sub-τ
tick the band holds is acted on; a confident tick during warm-up is
escalated), so the row carries both. A judgment with no confidence never
passes and leaves the standing untouched: a continuous gate takes no
reading from a null.

## Every judgment is recorded

One `judge.verdict` row per **attempt**: the author
(`judge@<backend>:<model>` — every row records its author), the
distribution, the confidence, τ and the gate decision, the cost (wall
seconds, GPU minutes, hosted cents, input tokens), the latency, the
question set's hash and the pack's hash, and the rung the attempt was
escalated from. **Refused attempts are rows too** — the edges are the
story. A pack whose verdict cannot fit the ledger's 4 KiB payload cap
is refused, not truncated (§1.8; split the pack).

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
.venv/bin/python -m pytest -q tests/judge    # 77 tests, no network, no GPU, no LLM
.venv/bin/python -m pytest -q                # the whole core
```

The Thor measurement (cold-start curve, agreement, latency, peak
memory): [`docs/lab/exp-judge-tiles-coldstart.md`](../../docs/lab/exp-judge-tiles-coldstart.md).
The standing gate's configuration, measured on the recorded d1 traces
(the sweep, the guarded choice rule, and the wiring's two behaviours):
[`docs/lab/exp-hysteresis-d1.md`](../../docs/lab/exp-hysteresis-d1.md).

## What is not here yet

The `verify` rung against a real critic report (the seam accepts the
questions; the critic's evidence packets are the caller's), the Jev
MCP stdio transport (the HTTP provider is the shape this package
speaks), the night executor as a second caller, and the work-order rung
*as a work order* — the ladder's end is surfaced rows now; filing the
order belongs to the work-order seat. Each is a small step on a seam
that already records everything.
