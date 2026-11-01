# `core/tiles` — the system that gets better

Casey's B2, decided on 2026-10-31: **no LLMs on the Thor.** Language comes
from the cloud; the Thor plays and learns.

> *The cloud writes the options; the Thor learns which ones work, and when.*

This package is that loop, as code. The cloud model writes a **tile** — a
script in the closed, typed vocabulary — the Thor keeps the tiles in a
**library**, a small local model **chooses** between them, every use is
recorded as a **play**, and the night **retrains** from those plays and
hands the losers back to the cloud: *"write a better one, here is why it
lost."*

The design is [`docs/design/tiles.md`](../../docs/design/tiles.md). Each
module's docstring cites it; the citations are the contract.

## The five pieces

| module | what it owns |
|---|---|
| `models.py` | the records: `Tile`, `TileStep`, `Precondition`, `TileAuthor`, `Outcome`, `PlayCost`, `PlayRecord`, `FeedbackPacket` |
| `door.py` | the door: a tile enters only if the vocabulary admits it |
| `library.py` | the options: content addressed, versioned, never deleted |
| `author.py` | the cloud seam: `ScriptedAuthor` (the fake) and `CloudAuthor` (the real one) |
| `plays.py` | the play record: written to the log, folded back out of it |
| `chooser.py` | the decision model: the contextual bandit, behind the `TileChooser` door |
| `retrieval.py` | the retrieval front: the tiles that *mean* the right thing, found by embedding, narrowed to K |
| `bands.py` | the three score bands — execute, confirm, compile — held by `core.hysteresis`'s gate |
| `nail.py` | the export: a tile library and its chooser, content addressed, in the `.nail` shape |
| `retrain.py` | the nightly loop: refit, rank, retire, and the feedback packets |
| `stats.py` | the numbers the seat's claims are made of: Wilson, Newcombe, the two-proportion z |
| `ope.py` | the off-policy estimators: what a **new** chooser would have earned on the old log ([`OPE.md`](OPE.md)) |
| `events.py` | the tile group's four audit types (§1.8) |
| `ports.py` | the two seams: the ledger and the vocabulary |

## The rules, and why they are rules

1. **A tile is content addressed.** Its id is the hash of its body, so the
   same script is the same tile whoever wrote it, and a changed body is a
   different tile. The body is frozen: a tile never changes, it is *retired*.
2. **A tile is never deleted.** `delete()` is refused, always. A tile leaves
   the eligible set by being retired, with a reason and a timestamp, and it
   keeps its body, its plays and its history.
3. **The cloud author is bound by the same door as a builder.** An unknown
   word, or a parameter outside that word's schema, is *refused* — not
   repaired, not clamped. Free text does not enter the world through the
   cloud any more than it enters through a child.
4. **The context travels with the play.** A play without its context cannot
   be learned from; that is the whole difference between a contextual bandit
   and a lookup table.
5. **A play that does not fit is refused, not truncated.** The ledger caps a
   payload at 4 KiB, and a truncated context is a lie about the context.
6. **The log is the source of truth.** The library and the chooser's
   statistics are folds over the audit log. A restart loses nothing, and a
   replay gives the same answer.
7. **One measure at a time.** The critic's verdict, the owner's keep-or-undo
   and a sealed prediction that held are three different measurements, and
   the record says which one it was. Mixing them would let the critic's
   optimism quietly become the builder's taste.
8. **A play carries the propensity it was drawn with.** The chooser
   measures the probability of its own choice at the moment it makes it,
   because the exploration rate decays and the greedy arm moves: a
   propensity computed afterwards is a different number from the one the
   choice was drawn from. Without it the play cannot be weighted for an
   off-policy estimate, and a missing propensity is **never** defaulted to
   1.0 — a default is a bias nobody can see. See [`OPE.md`](OPE.md).
9. **The front narrows; it does not decide.** The retrieval front takes the
   K tiles whose meaning matches the context and hands them to the chooser,
   which is the only thing that knows what *wins*. A front that decided
   would throw the learning away, and a chooser shown the whole library
   would drown in options it has no estimate for. Eligibility comes first:
   a tile whose preconditions do not hold is not a low-scoring option, it
   is not an option, and it is never scored.
10. **A choice made through the front carries the whole policy's
    probability.** Two mechanisms make that choice — the front proposes,
    the chooser disposes — so the propensity is the **product** of both
    draws, and the shortlist it was drawn from travels with the play
    record. Recording only the chooser's own number would make the
    importance weights too large and the estimates too confident.
11. **A similarity score is meaningless without the embedder that made
    it.** Every number the front produces travels with the embedder's
    record — kind, model, licence, dimensions — and a model whose licence
    has not been checked is reported as *unchecked* rather than free.
12. **The bundle's timestamps are part of its content, not the clock.** A
    wall-clock stamp would make every export of the same library a
    different bundle, and the content hash would stop being an address. So
    the bundle says when its oldest tile was authored and when its newest
    one was, and re-exporting an unchanged library gives back the same
    bundle, byte for byte.

## The acceptance run, and the numbers

`tests/tiles/test_acceptance_learning.py` is the seat's claim, exercised: a
scripted cloud author writes 6 tiles, a simulated game scores them over 600
plays, and the contextual bandit's win rate is compared with a uniform pick
over the same contexts.

**No real LLM call is made anywhere in this suite.** The author sits behind
the adapter and the adapter's fake is used.

Measured on the **Thor** (aarch64, `thor`, 2026-10-31 12:30 AKDT; the box
was busy — load average 22 on 14 cores, GPU 97% from other work):

| | |
|---|---|
| chooser win rate | **479/600 = 0.798** |
| uniform pick win rate | 215/600 = 0.358 |
| difference | **+0.440** |
| 95% CI on the difference (Newcombe's method 10) | **[0.388, 0.488]** |
| z, p | 15.43, p < 1e-50 |
| first half → second half | 232/300 = 0.773 → 247/300 = 0.823 |
| cost of a choice | 0.05 ms/play (600 plays in 30 ms) |

The claim is not "the chooser won a lot" — it is **the 95% interval on the
difference does not include zero**. The win rate also *rises* over the
night, which is the part that matters: the system gets better from its own
outcomes.

The simulated game is not a switch: a play wins with probability 0.85 when
the tile's style is the one the context asked for and 0.15 when it is not.

## Finding the tiles: the retrieval front

The chooser above is a bandit: it learns which tile wins in which bucket, and
it picks well *among the tiles it was handed*. With six tiles that is enough;
with six hundred it is not, because the bandit's estimate is one number per
(bucket, tile) and it can only act on what it is given.

`retrieval.py` is the missing half. It embeds the game's state, embeds each
tile once when it is added, and takes the K tiles whose meaning matches. The
chooser then does what it is good at — learning from outcomes — inside that
shortlist.

**The embedder is a parameter, and the record says which one.** The default is
a local static model (model2vec's `potion-base-8M`, **MIT**, 256 dimensions,
CPU only, no forward pass); the floor is `HashingEmbedder`, feature hashing
with no model, no download and no licence question. Both run, and the choice
between them was measured rather than assumed — see
[`docs/lab/exp-tiles-retrieval.md`](../../docs/lab/exp-tiles-retrieval.md)
§5.9: on requests that share words with the tile, the free fallback is
*sharper*; on a paraphrase it has no signal at all.

`model2vec` is an **optional extra** (`pip install -e ".[embed]"`), so the core
installs without it and the front falls back to hashing.

**The three bands** (`bands.py`) are `quilt-pincher`'s, and they are held by
`core/hysteresis`'s gate rather than by a new mechanism — the same way
`core/judge.StandingGate` holds the judge's escalation. Above the high line
the tile is executed; in the gap it is played but marked confirmed; below the
low line **nothing is played** and a request goes to the cloud author for a
new tile. A score that wobbles across the line does not move the band,
because the gate's split thresholds hold it.

**The numbers, on the acceptance rig** (the ProArt, 2026-11-01; the harness
reproduces the acceptance run's own rig — the same `ScriptedAuthor`, the same
contexts, the same seeded game — and the bandit arm comes out at the
published 479/600 = 0.798):

| arm | win rate | against the bandit |
|---|---|---|
| bandit (from zero) | 479/600 = 0.7983 | — |
| **retrieval-only** | **504/600 = 0.8400** | +0.0417, CI [−0.0019, +0.0851], p = 0.0608 |
| retrieval-bandit (K = 3) | 493/600 = 0.8217 | +0.0233, CI [−0.0211, +0.0677], p = 0.3029 |
| fastpath (τ = 0.42) | 486/600 = 0.8100 | +0.0117, CI [−0.0333, +0.0566], p = 0.6106 |
| always-matching (the reference) | 503/600 = 0.8383 | +0.0400, CI [−0.0037, +0.0836], p = 0.0724 |

The front's top-1 was the tile whose style the context asked for in **600 of
600** contexts, with no learning at all, and it landed on the
always-matching reference — the best class of policy the game allows. The
fast path costs **0.12 ms at p95**.

**The rig cannot resolve the +0.04**, and that is worth saying plainly: the
always-matching reference itself is only p = 0.0724 against the learner at
600 plays. The mechanism's claim is exact and measured; the *value* of it over
the learner is +0.04 with an interval that just includes zero.

Pincher's own thresholds do **not** transfer: at his 0.80 the fast path never
fires (0 of 600 contexts), because that number was measured in a different
embedding space — the calibrated line for ours is 0.42. The full measurement,
the calibration rules and what the experiment does not say are in the lab
note.

## The export: a `.nail` bundle

`nail.py` writes the library and the chooser into the shape `quilt-pincher`
uses — `version`, `reflexes`, `vetoRules`, `compileHistory`, `metadata` — with
the field names kept so the two are comparable, and the mapping written down
in the module's docstring. A tile is a reflex in pincher's sense: an action
compiled once by a language model and then reused for free.

Two things are added on top. The **chooser travels with the tiles**, because
a library without its chooser's estimates is a set of options with no
decisions attached, and the reader would have to relearn them. And the bundle
is **content addressed**: the hash covers the reflexes, the rules, the
history, the metadata and the chooser state, so a changed tile or a changed
estimate gives a different hash and the same bundle always gives the same one.

## Running it

```bash
cd ~/lm-wt/tiles-retrieval
.venv/bin/python -m pytest -q tests/tiles          # this seat's suite
.venv/bin/python -m pytest -q                     # the whole core
```

169 tests for this seat, no network, no GPU, no LLM: the seat's whole point
is that the loop, the library, the chooser and the learning can be
exercised before the engine lands. The retrieval seat's own are:

```bash
.venv/bin/python -m pytest -q tests/tiles/test_retrieval.py tests/tiles/test_bands.py \
    tests/tiles/test_retrieval_propensities.py tests/tiles/test_nail.py   # 55 tests
```

The off-policy estimators print their own numbers:

```bash
PYTHONPATH=. .venv/bin/python docs/lab/tiles-ope-scripts/measure_ope.py
```

and the retrieval front's experiment prints its:

```bash
PYTHONPATH=. .venv/bin/python docs/lab/tiles-retrieval-scripts/measure_tiles_retrieval.py
PYTHONPATH=. .venv/bin/python docs/lab/tiles-retrieval-scripts/measure_tiles_retrieval.py \
    --embedder hashing --out docs/lab/tiles-retrieval-scripts/results/tiles-retrieval-e1-hashing.json
```

## How it connects to the core

* **the ledger is the contract.** The tiles seat writes audit events
  (`tile.authored`, `tile.retired`, `tile.played`, `tile.retrained`) and
  nothing else. Four new types are a schema change to the closed set
  (§1.8), mirrored into `core/records.py`, `core/night/events.py` and
  `core/recipe/events.py` so every reader of the log agrees.
* **the vocabulary is the door.** The seat does not own the words; it asks
  the registry whether a word exists and whether a tile's params are in
  schema. The M1 slice's three words are enough to exercise it.
* **the recipe store is downstream.** A tile's steps become a typed edit,
  which the recipe store validates and commits like any other. This seat
  does not write the recipe.
* **the engine and the critic are the game.** What happened when a tile was
  played is the engine's and the critic's to say; this seat writes the
  record.

## Scoring a chooser that has not run yet

[`OPE.md`](OPE.md) is the note: the three estimators, the variance and the
interval, the weight diagnostics, the negative control, and the measured
numbers. In one line — the log carries the propensity the chooser measured
at the moment of each choice, and `core.tiles.ope.evaluate()` turns a log
into an estimate of what a **new** policy would have earned, with an
interval and a denominator, refusing rather than guessing when the log
cannot support the question.

The numbers and how to reproduce them are in
[`docs/lab/exp-tiles-ope.md`](../../docs/lab/exp-tiles-ope.md).

## What is not here yet

The **learned ranker** and the **RL** rung of the chooser ladder, the
**policies** of the motion section (a trained policy is a tile-chooser of
another kind — see the design), the **resident, batched serving** the
ladder is meant to run under (the chooser is an in-process object for now,
and picks in 0.05 ms), the cloud transport's real endpoint, the
**recipe-store integration** (playing a tile end to end), and the morning
report's tile column. Each is a small step after this one, and the seams
for them are already named: `TileChooser` for the next rung, `TileAuthor`
for the cloud, `TileLibrary` for the options.

## The open questions

`docs/design/tiles.md` §10 lists the eight decisions this design cannot
make on its own — the authoring budget, who reviews a tile, which measure
trains the chooser, whether a chooser may act alone at night, whether a
retired tile gets another chance, how long play records are kept, one
chooser per world or per character, and what a tile's family is. Each has a
default, so the seat keeps working while Casey is away.
