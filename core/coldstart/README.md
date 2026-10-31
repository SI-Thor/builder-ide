# `core/coldstart` — cold start: ask-mode, the melt, and the calibration batch

Week 2 item 12 of `docs/plan.md`: *cold-start ask-mode + the calibration
batch's first members (seeded-defect reference set grows nightly, sized to
the unused lane)*, against `docs/design/core-spec.md` (v2) §3.5 and decision
13(a). Pass/fail: gaps §7 tests 1–3 as automated tests, and the reference
set's FP/FN table publishes its first row.

The one-paragraph idea. On night one the only honest currency is the sealed
guess and the measured number, and cold start is **a mechanism, not a number
of nights** (decision 13a): questions and `guess` confidence decay per
builder, per reason code, at **two observations** — auditable in the ledger,
never switched off by hand. Cold start *is* taste acquisition: asking is how
a builder earns the observations that end the asking.

```
core/coldstart/
  models.py        the spec's records + this seat's own (chips, questions, reference members, FP/FN rows)
  ports.py         the seams: LedgerPort (core-api), SealerPort (vocab), Clock
  stubs.py         in-memory stand-ins for the sibling seats, each headed by its owner
  openline.py      §3.5 the empty project's first screen (gaps §7 test 1)
  askmode.py       §3.5 ask-mode: one question at a time, ≤ 6, a skip writes nothing
  gate.py          decision 13a: ask→act and guess→claim at two observations, per builder
  sealing.py       the melt's seal policy: the confidence is computed, never chosen
  claims.py        the utterance gate: a claim below two observations does not render
  bank.py          the night-one question bank (eight two-chip questions)
  calibration.py   §1.9 the seeded-defect reference set, nightly growth, the FP/FN table
```

Run it: `.venv/bin/python -m pytest` (63 tests). The venv lives in this
worktree per the brief.

## The melt, mechanically (decision 13a)

Three things flip at the same threshold, per builder × reason code, and all
of them are folds over the audit log (`gate.ColdStartGate`):

| observations | mode | sealed confidence | may speak |
|---|---|---|---|
| 0–1 | **ask** | `guess`, basis "0 observations" / "1 observation" | no (`below_two_observations`) |
| 2 | **act** | real, basis "2/2 kept" (low — under three, honestly low) | yes, uncertainty leads |
| 3+ | act | ratio bands (low/medium/high) | yes, no lead clause |

**Per builder is load-bearing.** A taste row written by answering a question
is tagged `asked-by:<builder>`; the gate counts, for builder *b*, the
owner's active rows on the code that are attributed to *b* or unattributed
(the owner's unprompted keeps count for every builder — the ledger is shared
and readable). So the Companion's melt is not the Architect's melt, and the
whole thing is auditable: every decision re-derives from `taste.note.appended`
events alone (tested by rebuilding the gate mid-melt).

The first-week table of G §1.9 is therefore a *prediction the tests can
falsify*, not a schedule: `test_melt.py`'s five-sitting fake owner produces
question counts `[6, 6, 2, 2, 0]` — questions fall to zero per code as
denominators pass two, never by a calendar. The live seven-night melt run is
week 3 item 13's; the mechanism it will exercise is done here.

## Ask-mode (§3.5; G §1 20:12)

`AskMode` is policy, not content: the caller supplies a bank (`bank.py`
ships night one's eight questions), and the service decides whether a
question may be asked. The rules, all structural:

* one question at a time — a second while one is open **collapses into the
  slate** as a card, never queues in the owner's face (nothing spoken, so
  nothing audited; the slate itself is the night-runner seat's);
* ≤ 6 questions per session, counted by a fold over the spoken lines;
* each question is **two chips over two artifacts** — there is no slot for
  an adjective floating free, and never a question about the owner;
* any question is skippable and **a skip writes nothing** — not one row;
* the answer is the owner's tap: `taste.note.appended` by an `owner` actor,
  a builder's hand on the taste pen refused in code (the three-writer rule);
* only codes below the asking builder's two-observation gate are asked.

## The calibration batch (§1.9; RV patch 15; §3.5)

The reference set's first members are **recipe fragments with known,
planted defects** — hollow meshes, wrong scale, broken constraints — plus
clean members (without clean ones there is nothing to false-positive on).
Members are deterministic in `(index, seed)`; growth is **sized to the
night's unused lane**: `min(night cap 8, distance to the ~30 target, what
the leftover rail affords at [e] cost per member)`, never duplicating an id,
to the queue's third item (placement is the night runner's; the position is
a constant here so it does not drift per seat).

The run is audited per member — `job.enqueued` (CPU lane, no model, no
prediction) → `critic.verdict` → `job.done` — and the **FP/FN table is a
pure fold** over the verdicts: TP/FP/FN/TN per scripted check, `fn_rate` /
`fp_rate` as counts with denominators, and the band (catch the seeded
defects; reject no more than a set fraction of the clean ones, default one
in ten). Publishing writes one content-addressed artifact — plan item 12's
pass condition. Until a critic model is chosen and measured, every verdict
wears **`verdict@scripted`** on its face, and the table's first row is the
baseline critic selection (week 3 item 18) has to beat. If the scripted
checks cannot catch the seeded defects, the table says so (`in_band: false`)
and verdicts stay `@scripted` — the plan's M2 named risk, as a measurement.

## The seams, and exactly what was stubbed

Nothing is on `main` yet, so every sibling seat's piece is stubbed behind
the spec's interfaces. `ports.py` holds the protocols; `stubs.py` holds the
implementations, each headed by the branch that owns the real one. The stubs
keep the rules the real seats owe — gapless `seq`, append-only, §5.1's
sealed-before-render ordering, the three-writer rule — so deleting them
changes nothing the tests mean.

| stub | real owner | the contract that must hold at merge |
|---|---|---|
| `InMemoryLedger` | `core-api` (branch `core-api`) | gapless `seq`, single writer, §5.1 ordering, §1.0 append-only |
| `PredictionSealer` | `vocab` (`core/vocab/predictions.py`) | same refusal codes, same `prediction.sealed` payload (incl. `sealed_payload` and `reason_code` riding outside the record) |
| `canonical_json` / `content_hash` / `short_hash` | `vocab` (`core/vocab/hashing.py`) | byte-identical canonical form — every seal hash depends on it |
| `SystemClock` / `SteppingClock` / `FixedClock` | `vocab` (`core/vocab/clock.py`) | RFC 3339 UTC, injectable |
| `taste_rows_from_events` | `vocab` (`core/vocab/taste.py`) | rows live in `payload["row"]`, same field names |
| `Rail` | `night-runner` (`core/night/models.py`) | three axes; GPU-minutes from the cost table, not the wall clock |
| `Actor` / `AuditEvent` / `Prediction` / `TasteRow` / closed code sets | `vocab` (`core/vocab/models.py`) | field-for-field identical (both seats' folds must read the same payloads) |
| the gate thresholds (2/3, ratio bands) | `vocab` (`core/vocab/gate.py`) | `MELT_AT` == `MIN_OBSERVATIONS_TO_ACT_ALONE` == `MIN_OBSERVATIONS_TO_SPEAK_TASTE` == 2 |

## Stub-only deltas (each needs a spec decision on merge)

1. **`guess` below two observations, on the taste axis.** Spec §1.7 glosses
   `confidence: "guess"` as *the zero-prior* bet; decision 13a and G §1.9's
   melt table treat the whole sub-two regime as guess (night 2 "guesses on
   most codes", night 3 "first real claim… 2 obs"). This seat follows the
   decision: below two, a real confidence is refused (`no_basis_yet`); at
   two, a guess is refused (`guess_expired`). The basis carries the true
   count ("1 observation"), so the ledger is never lied to about how thin
   the sample is. Proposal: amend §1.7's gloss, or make the `vocab` gate's
   `taste_confidence` return `guess` below two.
2. **Per-builder attribution rides in taste-row tags** (`asked-by:<builder>`).
   The spec's `TasteRow` has no attribution field, but decision 13a's "per
   builder" is vacuous without one (a shared count decays per reason code
   only). Proposal: tags are the mechanism, or `TasteRow` gains
   `elicited_by: str | None`.
3. **`line.spoken` carries evening utterances.** §1.8 groups it under
   "night" (line-budget enforced, §5.6), but the closed set has no other
   builder-utterance type, and the cold-open line and ask-mode questions are
   evening moments. This seat uses it for every spoken line, payload
   `kind: "coldstart.ask"` for questions. Proposal: state that `line.spoken`
   is *the* utterance type (the budget applying to it), or add an evening
   group.
4. **A skip is session-local state.** "A skip writes nothing" (G §1) forces
   this: the open/skipped question cannot live in the log. After a rebuild
   the last spoken unanswered question is re-offered (and can be skipped
   again); the counts that matter — spoken, answered — are all audited.
5. **Reference members are recipe fragments, not renders.** §1.9's registry
   entry says "~30 renders"; the engine is not on this branch (M1's
   stub-generator risk), so members carry typed params and the scripted
   checks read them analytically (§2.3: scripted analytic computations, no
   physics engine). Renders compile from these when the engine lands.
6. **FP/FN counting semantics.** A planted defect of class K missed by
   `DEFECT_TARGETS[K]` is an FN — including a defect planted deliberately
   below the threshold (`detectable=False`); a check firing on a member
   carrying a *different* class of planted defect is excluded from all four
   counts (the member is defective, so the report is neither true of its own
   class nor false); band = fn 0 and fp_rate ≤ `FP_BOUND` (default 0.10).
7. **`Rail.subtract` clamps at zero** (night-runner's raises on overdraw);
   sizing only ever asks "what fits", so the clamp never hides an overdraw.
8. **`q_` ids are shared** with parked questions (§1.0). Ask-mode questions
   are a different mechanism (carried by `line.spoken`, not
   `question.parked`); the prefix is the spec's only question namespace.
   Flagged in case the merge prefers a distinct prefix.

## What is deliberately not here

Renders and the engine (M1/M2), the HTTP API and SSE (core-api), the slate
and queue placement (night-runner — `CALIBRATION_QUEUE_POSITION` is stated,
not enforced), critic *models* and their selection (week 3 item 18 — this
seat publishes the table they will be measured against), and the live
seven-night melt run (week 3 item 13 — the fake-owner simulation in
`test_melt.py` is its dry run).
