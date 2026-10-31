# exp-judge-tiles-coldstart — judge-first versus bandit-from-zero on the tiles rig

*2026-10-31, the ProArt seat's brief run, measured on the Thor
(thor-lan, aarch64). Liquid-study Part 3 item 1's smallest experiment:
`core/judge/` built, d1-2B behind it, the tiles shortlist as the first
caller, and the cold-start curve the study named as the primary
reading.*

## Headline

| # | Finding |
|---|---|
| 1 | **The judge is a real cold-start prior.** Plays 1–50: judge-prior **0.66** vs bandit-from-zero **0.54** (+12 pp) — the only stretch of the night where the bandit has no data, and exactly the stretch the prior is for. Over the whole 600: judge-prior **0.7967** vs bandit **0.7867**. |
| 2 | **The gate does its job without hurting the arm.** Judge-prior agreed with the bandit's picks on **98.8 %** of plays — one bucket's judgment fell below τ (0.442 < 0.5), was **surfaced, not acted on**, that bucket kept the bandit's flat prior, and the arm finished ahead anyway. |
| 3 | **Judge-only (argmax, gated) wins 0.69** against a uniform pick's ~0.33 on this rig — far above E1's T3 caution (one-shot d1-2B 0.450 on lab-cascade's tiles toy). On a shortlist *with described candidates*, d1-2B is much better than the toy suggested. |
| 4 | **The offline τ sweep is the sharper number**: at τ ≤ 0.4 (act on everything) judge-only scores **0.853** — at P_MATCH's own ceiling — while at τ = 0.7+ (uniform fallback everywhere) it falls to 0.387. The 0.4–0.5 confidence band's judgments were right *on this rig*; the sweep is what `ConfidencePolicy`'s per-task table is for. The default stays 0.5 (E1) until a task's own calibration. |
| 5 | **A judgment costs 42.1 ms p50 / 44.2 ms p90** (600 calls, 6 described candidates, 234 input tokens p50) and the server peaked at **774.7 MB RSS** — the residency bill of the rung-0 backend. §4.3's 32.2 ms was a shorter state with bare option keys; ~10 ms is the described-shortlist premium, not a surprise (§4.1's cost decomposition). |
| 6 | **The runs are reproducible.** Two full runs — server restarted between them — produced identical win rates, agreements and curves: the seeded game and the deterministic Q8 decision head give the same answer twice. |

## The rig

`tests/tiles/test_acceptance_learning.py`'s, verbatim in shape: six
tiles (two per style) in the M1 slice's crates word; 600 plays over the
seeded context sequence; a play wins with p = 0.85 when the tile's
style is what the context asked for and p = 0.15 otherwise; the draws
are sha256-seeded by (tile, bucket, play index), so **every arm plays
the identical game**. The bandit arm's constants are the acceptance
run's (ε = 0.25, decay 0.995, floor 0.02, seed 7); its 0.7867 sits
beside that run's published 0.798 floor.

Three arms:

* **bandit** — the contextual bandit from zero;
* **judge-prior** — `JudgePriorChooser`: one judged `choice` over the 6
  candidates per cold context bucket, the judge's distribution as the
  bandit's prior mean there, the bandit learning from every play;
* **judge-only** — every play through the judge; act on the argmax at
  or above τ, else *surfaced, not acted on* and a seeded uniform pick.

## The cold-start curve (win rate by play index, 12 × 50)

| arm | 1–50 | 51–100 | 101–150 | 151–200 | 201–250 | 251–300 | 301–350 | 351–400 | 401–450 | 451–500 | 501–550 | 551–600 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| bandit | **0.54** | 0.86 | 0.74 | 0.86 | 0.78 | 0.82 | 0.80 | 0.78 | 0.82 | 0.80 | 0.80 | 0.84 |
| judge-prior | **0.66** | 0.86 | 0.74 | 0.86 | 0.78 | 0.82 | 0.80 | 0.78 | 0.82 | 0.80 | 0.80 | 0.84 |
| judge-only | 0.70 | 0.72 | 0.60 | 0.76 | 0.68 | 0.72 | 0.76 | 0.62 | 0.72 | 0.56 | 0.70 | 0.74 |

| | first half | second half |
|---|---|---|
| bandit | 0.7667 | 0.8067 |
| judge-prior | 0.7867 | 0.8067 |
| judge-only | 0.6967 | 0.6833 |

The judge-prior arm converges to the bandit's curve by the second
bucket — that is the design working: the prior matters exactly while
the bandit has nothing, then real plays wash it out at the rate the
bandit's own prior count sets. Judge-only never learns, so its curve
is noise around 0.69.

## Agreement, gates, latency, cost

| | |
|---|---|
| judge-prior picks agreeing with the bandit's | **0.9883** (593/600) |
| judge-only picks agreeing with the bandit's | 0.3483 |
| judge-only calls acted on at τ = 0.5 | 400/600 (surfaced: 200) |
| judge-prior's 3 bucket judgments | act 0.572, **surfaced 0.442**, act 0.539 |
| judge latency, 600 calls | **42.12 ms p50 / 44.15 ms p90** (mean 42.4) |
| input tokens per call | 234 p50 (234–236); the prior arm's shorter candidate text: 133–134 |
| cost of the judge-only arm | 0.424 GPU-minutes total; hosted_cents 0 (local) |

## The τ sweep, read offline from the recorded distributions

The trace is in the results JSON, so the gate's policy is re-readable
without touching the GPU again (the §4.3 pattern). Each row: what
judge-only would have scored had that τ been the policy (act on
argmax; seeded uniform below).

| τ | act rate | judge-only win rate |
|---|---|---|
| 0.1–0.4 | 1.000 | **0.853** |
| 0.5 (the default) | 0.667 | 0.690 |
| 0.6 | 0.333 | 0.550 |
| 0.7–0.9 | 0.000 | 0.387 |

Two readings, both honest: **on this rig the 0.4–0.5 confidence band
was right** (0.853 at full act-rate, at the simulated game's own
P_MATCH ceiling), and the **surfaced-uniform fallback is what costs
the gated arm** (0.690 vs 0.853), not the judgments themselves. The
task-calibration question — is `tiles.shortlist` a τ = 0.4 task? — is
now a table lookup away, which is the point of τ per (backend, model,
task).

## The box, beside the numbers

Second run (the two runs agree). Served under `flock
~/lm-wt/heavy.lock` on the Thor, one server, stopped after; `free -g`
**112 GB available after the load** (bar: 25 GB).

| | at start | at end |
|---|---|---|
| load1 | 4.51 | 4.64 |
| MemAvailable | 111.9 GB | 111.8 GB |
| RAM used (tegrastats) | 25.9 GB | 25.99 GB |
| GPU | 40.8 °C, 5.5 W | 45.5 °C, 9.8 W |

llama-server peak RSS over the whole run: **774.7 MB** (VmHWM). GPU
warm-up: 154 requests in 3.0 s before any timed call (IDEAS.md rule 3).

## What this settles

* **The seam works end to end on real hardware**: one judged choice per
  cold bucket, the prior flowing into the bandit's estimates, the
  propensity on every play, the surfaced judgment recorded and *not*
  acted on — all of it in ledger rows (`judge.verdict`) with their
  authors (`judge@d1:d1-2B`), distributions, latencies and costs.
* **Judge-first is the right cold-start shape** — +12 pp in the only
  stretch the bandit is blind, at the price of three 42 ms calls and
  775 MB of resident weights, converging to the bandit's curve as soon
  as the bandit has data.
* **The gate is not decoration**: the weathered bucket's 0.442 was
  surfaced and the arm did not act on it; the offline sweep turns the
  τ policy into a per-task measurement instead of an argument.
* **E1's T3 caution was about the toy, not the shape**: with described
  candidates over a shortlist, one-shot d1-2B is far better than 0.450.
  R7's question ("does a decision model beat the bandit?") now has a
  third answer: as a cold-start prior it already does, and at τ ≤ 0.4
  on this rig it beats the trained bandit too.

## Reproduce

```bash
# on the Thor (the scratch copy lives at ~/lm-wt/core-judge):
cd ~/lm-wt/core-judge/docs/lab/judge-scripts
./run_coldstart.sh 8295 600        # takes ~/lm-wt/heavy.lock, serves d1-2B Q8,
                                   # runs the three arms, stops the server
# results: results/judge-tiles-coldstart.json (committed beside this note)
```

The script is `measure_tiles_coldstart.py` (arms, rig, analysis); the
serving, the lock, the `free -g` bar and the stop are
`run_coldstart.sh`. The two committed runs used ports 8295, 600 plays,
τ = 0.5, seeds 17 (contexts) / 7 (choosers) / 99 (uniform fallback).

## What this does not settle

* The **game is simulated** (p = 0.85/0.15): the absolute win rates are
  properties of the rig; the *differences between arms* are the
  result. Real plays come from the engine and the critic.
* One rig, one seed family, n = 600: the τ ≤ 0.4 reading wants its own
  calibration pass (E1's T1/T3 pattern: McNemar on discordant pairs)
  before `tiles.shortlist` gets a per-task τ.
* No escalation rung was exercised on hardware (the ladder was
  rung-0-only); Clef/Jev behind the seam are HTTP-tested, not
  Thor-tested — that is their backends' next measurement, not this
  seam's.
