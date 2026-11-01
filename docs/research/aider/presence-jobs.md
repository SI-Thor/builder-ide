# The first 12 presence jobs for thor-admit

thor-admit has a presence scheduler with three tiers — **preparation**, **practice**, **study** — but no queue. This is the first queue. Each job is drawn from an idea already in the corpus, has a command shape, a peak-memory estimate against the Thor's 122 GB unified pool, a resumability answer, and a morning metric that shows whether the night was worth it.

Ranked by value per GPU-hour. "Value" means: does the morning metric change a decision we are about to make? A job that produces a number we already know is worth zero, no matter how cheap.

---

## 1. Warp terrain bake at the next resolution step

- **Tier:** preparation
- **Source:** `lib-idea4.md` (Warp SDF mesher, 44–56× on terrain), `lib-syzygy.md` (resolution slope)
- **Command shape:** `thor-admit enqueue --tier prep --job warp-terrain --region <id> --grid <next-step> --seed <n>`
- **Peak memory:** ~8–14 GB (Warp terrain at 208×112, plus the mesh cache)
- **Resumable:** yes — per-region, per-grid-step; the stage cache is content-addressed
- **Morning metric:** mesh cache hit rate on the next day's camera path. If the bake covered the path, hit rate ≥ 80%; if not, the anticipatory predictor is wrong and that is the finding.

## 2. Partial scene splice for the predicted next zone

- **Tier:** preparation
- **Source:** `lib-idea4.md` (partial splice, 2.3–2.5× faster than rebuild)
- **Command shape:** `thor-admit enqueue --tier prep --job splice --zone <id> --delta <recipe-hash>`
- **Peak memory:** ~4–6 GB (one zone's geometry plus the delta)
- **Resumable:** yes — the splice is a cache operation; a partial splice is a valid intermediate
- **Morning metric:** splice-vs-rebuild time ratio on the zones the player actually visited. If the ratio is < 1.5×, the splice is not paying for itself and the rebuild path should be the default.

## 3. d1-2B calibration sweep on the day's logged decisions

- **Tier:** study
- **Source:** `lib-fromgoogle4.md` (Brier score, hysteresis), `lib-dsswarm4.md` (annotation tetrad)
- **Command shape:** `thor-admit enqueue --tier study --job d1-calibrate --log <day> --bins 20`
- **Peak memory:** ~6–8 GB (d1-2B resident, plus the log)
- **Resumable:** yes — per-day, per-bin
- **Morning metric:** Brier score for the day vs. the 7-day rolling baseline. If Brier > 0.18, the confidence gate is drifting and the hysteresis bounds need retuning. This is the single most valuable job on the list because it is the only one that tells you whether the bot's confidence is honest.

## 4. Hysteresis retune on real d1 traces

- **Tier:** study
- **Source:** `lib-fromgoogle4.md` (hysteresis barrier, 66 flickers → ~0)
- **Command shape:** `thor-admit enqueue --tier study --job hysteresis-retune --traces <day> --bounds 0.78,0.92 --window 120ms`
- **Peak memory:** ~2–4 GB (traces only, no model)
- **Resumable:** yes — per-trace
- **Morning metric:** flicker count on the day's traces with the new bounds vs. the old. If the new bounds do not reduce flickers by ≥ 50%, the bounds are not the problem and the model's confidence is.

## 5. Invariant gate shadow run against the ProArt's verdicts

- **Tier:** practice
- **Source:** `lib-dsswarm2.md` (shadow conductor), `lib-dsswarm4.md` (deterministic kernel before selector)
- **Command shape:** `thor-admit enqueue --tier practice --job gate-shadow --log <day> --invariants <set>`
- **Peak memory:** ~1–2 GB (the gate is CPU-shaped; the log is the cost)
- **Resumable:** yes — per-day
- **Morning metric:** shadow disagreement rate vs. the ProArt's verdicts. If > 5%, the gate's invariants are wrong and the gate cannot be trusted as the first filter.

## 6. WRM selector training on the accept/reject history

- **Tier:** study
- **Source:** `lib-dsswarm2.md` (WRM selector, 79.4% bar)
- **Command shape:** `thor-admit enqueue --tier study --job wrm-train --pairs <day> --epochs 3`
- **Peak memory:** ~10–14 GB (the selector plus the pair set)
- **Resumable:** yes — per-epoch
- **Morning metric:** selector accuracy on a held-out day vs. the majority-class baseline. If it does not beat the baseline, the selector is not learning and the cold-start problem is real.

## 7. Perceptual grammar classification on supersede events

- **Tier:** study
- **Source:** `lib-dsswarm4.md` (perceptual grammar, ≥80% agreement bar)
- **Command shape:** `thor-admit enqueue --tier study --job grammar-label --supersedes <day> --sample 100`
- **Peak memory:** ~2–3 GB (the events plus a small classifier)
- **Resumable:** yes — per-event
- **Morning metric:** agreement between the classifier's grammar label and a hand-labelled sample. If < 60%, the grammar is not derivable from the statepoint and must be declared by the generator.

## 8. Dirty-sector checkpoint exactness test

- **Tier:** practice
- **Source:** `lib-dsswarm4.md` (dirty-sector bitmap, ≤5% size bar)
- **Command shape:** `thor-admit enqueue --tier practice --job checkpoint-test --commits 10000 --rollback 1000`
- **Peak memory:** ~4–6 GB (the CRDT state plus the checkpoint)
- **Resumable:** no — the test is atomic; a partial run is not a result
- **Morning metric:** restore exactness (bit-identical or not) and checkpoint size as a fraction of total state. If either fails, the rollback path is not safe and optimistic commit must be disabled.

## 9. Stigmergic trace store warm-up on the day's tile requests

- **Tier:** preparation
- **Source:** `lib-dsswarm2.md` (stigmergic trace store, bounded retrieval)
- **Command shape:** `thor-admit enqueue --tier prep --job trace-warm --requests <day> --radius 10`
- **Peak memory:** ~1–2 GB (the trace store is small)
- **Resumable:** yes — per-request
- **Morning metric:** trace hit rate on the next day's requests. If < 30%, the trace store is not capturing what the workers actually need and the deposit schema is wrong.

## 10. Indeterminacy score I on one region

- **Tier:** study
- **Source:** `lib-dsswarm2.md` (indeterminacy score, ≥0.4 rank correlation bar)
- **Command shape:** `thor-admit enqueue --tier study --job indeterminacy --region <id> --window 24h`
- **Peak memory:** ~1 GB (the score is a scalar per tick)
- **Resumable:** yes — per-window
- **Morning metric:** rank correlation between I and next-tick rejection. If < 0.2, the score is noise and the mode switch has no signal.

## 11. Frozen statepoint fork test

- **Tier:** practice
- **Source:** `lib-dsswarm4.md` (frozen statepoint + fork)
- **Command shape:** `thor-admit enqueue --tier practice --job fork-test --moments 10 --trials 5`
- **Peak memory:** ~6–10 GB (ten frozen statepoints plus the forks)
- **Resumable:** yes — per-moment
- **Morning metric:** forked-bot time-to-goal vs. fresh-bot time-to-goal. If the fork is not faster, the frozen statepoint is not carrying useful momentum and the freeze is wasted work.

## 12. Trust ladder T0 review queue

- **Tier:** study
- **Source:** `lib-dsswarm4.md` (trust ladder, ≥80% approval bar)
- **Command shape:** `thor-admit enqueue --tier study --job trust-review --decisions 100 --tier T0`
- **Peak memory:** ~1 GB (the decisions plus the review queue)
- **Resumable:** yes — per-decision
- **Morning metric:** human approval rate on the T0 decisions. If ≥ 80%, the bot is ready for T1; if < 60%, the bot is not ready and the tier should not move.

---

## Notes on ranking

The top three are ranked by *decision value*, not by cost. Job 3 (d1 calibration) is the highest-value job on the list because it is the only one that tells you whether the bot's confidence is honest — and the confidence gate is the load-bearing mechanism in every other job. Job 1 (Warp terrain) is second because it is the only job that produces content the player will actually see. Job 2 (splice) is third because it is the cheapest way to test whether the anticipatory predictor is right.

Jobs 4–8 are the "does the mechanism work" tier. They are cheap, they are resumable, and each one produces a number that either confirms or refutes a design claim.

Jobs 9–12 are the "does the system cohere" tier. They need a second bot or a trace store, and they are the most expensive per GPU-hour. They should run only after jobs 1–8 have produced their morning metrics, because a coherence test on a system whose parts are not yet trusted is a test of the wrong thing.

## What is not on this list

- **Multiverse timeline simulation** (`lib-new2.md`) — real, but it is a world-generation mechanism, not a presence job. It belongs in the generator's queue, not thor-admit's.
- **NVFP4 kernel tuning** (`lib-googleidea1.md`, `lib-googleidea2.md`) — real, but it is a `thor-fp4` job, not a presence job. The presence scheduler should not be running kernel benchmarks.
- **MIG partition experiments** — MIG reports Disabled on our box. A presence job that assumes MIG is a job that will fail at 2am.
- **"The mob becomes an ensemble"** (`lib-dsswarm1.md`) — metaphor. The concrete form is jobs 9–11.
