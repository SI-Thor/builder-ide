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
| `retrain.py` | the nightly loop: refit, rank, retire, and the feedback packets |
| `stats.py` | the numbers the seat's claims are made of: Wilson, Newcombe, the two-proportion z |
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

## Running it

```bash
cd ~/lm-wt/tiles
.venv/bin/python -m pytest -q tests/tiles          # this seat's suite
.venv/bin/python -m pytest -q                     # the whole core
```

93 tests for this seat, no network, no GPU, no LLM: the seat's whole point
is that the loop, the library, the chooser and the learning can be
exercised before the engine lands.

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
