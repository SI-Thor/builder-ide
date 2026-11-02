# `tools/return_screen` — the RETURN SCREEN

Build #6 of `docs/design/vibecode-in-world.md` §4: the screen a returning
human opens to see what the world did while they were away, and to rewind
any of it. One page, five beats in the order `docs/research/dsmc.md` gives
(**what changed, what matters, what is waiting on you, what was undone,
what next**), with the Biographer's letter on top.

It is served from the Thor on the LAN, port **8131**, by a stdlib Python
server. It reads the world's ledger **read-only** and never writes to the
world; its only writes are visit markers and the precedent stub's events,
in `state/` beside it.

## What is on the page

| section | what it shows | where the data comes from |
|---|---|---|
| the letter | ≤ 150 words, one open question, rule-chosen | the fold below, lineage: night-v4's `write_letter.py` |
| 1 what changed | counters + plays/hour since your last visit | `tile.played` / `judge.verdict` / `tile.authored` / `tile.retired` |
| 2 what matters | the timeline scrubber (drift alarms, admitted/retired skills, judge refusals, human presence, your visits) + per-actor lanes + the "what happened to X?" box | `core.drift` over the ledger; `core.rewind` selections |
| 3 what is waiting | pending precedent questions, answered inline; the judge's health; the pause state | the precedent seam (below) |
| 4 what was undone | retirements, and **rewind to here, keep these**: pick a point on the timeline, keep actors/kinds, preview the fork | `core.rewind.select` — a preview, never a deletion |
| 5 what next | the quiet moment when nothing needs you | — |

The **"what happened to X?"** box is the active-perception idea borrowed
from OmniAgent (`docs/research/omniagent.md` on main): a deterministic
planner turns the question into one `core.rewind` selection expression
(actors, kinds, ids, a time window), pulls only the rows that answer it,
and shows both the slice it pulled and how small a fraction of the ledger
that was — a catch-up by lookup, not by replay.

## The seams, honestly

* **`core/rewind`** has landed on main, so the rewind panel calls it for
  real (`parse` + `select`). The cherry-pick onto a canon fork needs a
  recipe store to replay onto; this world does not commit to the canon
  yet, so the panel stops at the selection and says so.
* **`core/precedent`** is still on its lane branch (`precedent-store`),
  so the pending-question seam is `precedent_stub.py` — the **same
  interface** (`Precedent`, `PrecedentStatus`, `PrecedentStore.append/
  get/match/all`, the same event fields). When the lane lands,
  `serve.py`'s import flips to `core.precedent` and the stub retires.
  The stub asks only what the ledger justifies (one rule today: a judge
  refusing ≥ half its verdicts asks what the bots should do meanwhile).
* **last seen** comes from two logs: the world's own
  `runtime/logs/player-builds.jsonl` (named humans placing blocks) and
  this screen's `state/visits.jsonl` ("I'm back — mark seen"). A human
  with neither gets the whole ledger as their window.
* **drift alarms** are computed live by `core.drift` (the build-#2/#3
  detector, rate gates over 5-minute windows). The world itself has not
  written `drift.yield` events yet (the running reflex predates build #3),
  and no pause file is live — the page says both rather than implying a
  pause happened.

## Running it

    # once: the tool venv (uv hard-links from the shared cache)
    cd tools/return_screen && uv venv .venv && uv pip install --python .venv/bin/python pydantic
    # start (detached, LAN, port 8131):
    tools/return_screen/run.sh
    # stop:
    tools/return_screen/run.sh stop

Needs: the world's ledger at
`~/lm-wt/agent-world/runtime/world-ledger.sqlite3` (override with
`--db`), `--player-log` beside it. First page load folds ~93k rows
(1–3 s); the fold is cached `--ttl` seconds (default 60).

## The files

| file | what it owns |
|---|---|
| `serve.py` | the HTTP server, the routes, the page's JSON |
| `worldview.py` | the read-only fold: lanes, marks, presence, refusals, threshold |
| `letter.py` | the Biographer letter: rules, 150-word limit, the one question |
| `ask.py` | the "what happened to X?" planner and its selection |
| `rewind_api.py` | "rewind to here, keep these" as a fork preview |
| `precedent_stub.py` | the pending-question seam (`core.precedent`'s shape) |
| `public/` | the page (vanilla HTML/CSS/JS, no dependencies) |
| `verify.mjs` | the Playwright check the lab note's screenshots come from |
| `state/` | runtime state (visits, the stub's precedents) — gitignored |

## Tests

    PYTHONPATH=$REPO tools/return_screen/.venv/bin/python -m pytest tests/return_screen -q
