# exp-return-ux — the RETURN SCREEN, on the world's real ledger

**What was asked.** The Thor brief (2026-11-01 21:12): a web page served from
the Thor (port 8131, LAN only) that reads the world ledger and shows (1) the
Biographer letter (≤ 150 words, one question, night-v4 lineage), (2) a
timeline scrubber since the human's last visit with the decision points
marked (drift alarms, pauses, skills admitted/rejected, precedents), (3)
per-actor lanes (who did what, rate, spend), (4) "rewind to here, keep
these" calling `core/rewind` (landed on main), and (5) pending precedent
questions answered inline (`core/precedent` if landed, else a stub) — laid
out in dsmc's five-beat order, verified in a real browser, reported here.
The director's addendum: borrow omniagent's active perception — a
"what happened to X?" box that pulls only the slices that answer it.

**What was built.** `tools/return_screen/` — a stdlib-Python HTTP server
(`serve.py`, port 8131, LAN) over a read-only fold of the world's SQLite
ledger (`worldview.py`), the letter (`letter.py`), the ask box
(`ask.py`), the rewind preview (`rewind_api.py`), the precedent stub
(`precedent_stub.py`), and a dependency-free page (`public/`). Eleven
tests under `tests/return_screen/`; the browser check is
`tools/return_screen/verify.mjs` (Playwright, the Thor's
`~/lm-tools/playwright`). Screenshots beside this note:
[`return-ux-screenshots/`](return-ux-screenshots/).

## 1. The mechanism

### 1.1 The fact the screen stands on

The world's ledger is append-only SQLite (`agent-world/runtime/
world-ledger.sqlite3`) with a gapless `seq`, and at verification time it
held **95,693 rows over 25.6 h** — `tile.played` ~47.9 k, `judge.verdict`
~45.4 k, `tile.authored` 329, `tile.retired` 41 — written by seven actors
(Kite, Sprout, Pebble, Timber, `judge@d1:d1-2B`, `seed`, `mediator`). A
returning human's question is therefore a *query over a fold*, not a
replay; and a rewind is a branch, never a deletion
(`docs/design/vibecode-in-world.md` §2.4). The screen opens the ledger
read-only (`mode=ro`, short-lived connections; WAL readers never block the
world writing beside them) and caches the fold for 60 s.

### 1.2 Why the old way could not do it

The morning report wrote Casey's letters **by hand** from receipts, and
dsmc's point stands: that is evidence the idea is right, not that it
scales. Nothing answered "what happened while I was gone" in one place:
the drift alarms lived in `core/drift`'s output, the skill history in the
ledger, the human's last visit in no file at all, and the rewind selection
(`core/rewind`, build #5) existed as a library with no human-facing way to
point at a moment and say *keep these*.

### 1.3 What changed

| the page (in the five-beat order) | what it is | where it comes from |
|---|---|---|
| the letter | ≤ 150 words, one open question, rule-chosen | `letter.py`, the lineage of night-v4's `write_letter.py` (the surprise = the largest unexpected measured thing; the question = the decision it leaves open) |
| 1 · what changed | counters + plays/hour since last seen | the fold |
| 2 · what matters | the scrubber: **445 marks** in a whole-ledger window, actor lanes, and the **"what happened to X?"** box | `core.drift` live (0 hard / 23 tier / 18 soft alarms) + `core.rewind` selections |
| 3 · what is waiting | one pending precedent question, answered inline; the judge's health; the pause state (reported as: no pause file is live — the running reflex predates build #3's seam) | the precedent stub |
| 4 · what was undone | retirements, and **rewind to here, keep these** as a preview | `core.rewind.parse` + `select` |
| 5 · what next | the quiet moment when nothing needs you | — |

**Last seen** is real: per human, the later of their last block placed in
the world (`runtime/logs/player-builds.jsonl`) and their last "I'm back —
mark seen" on this screen (state/visits.jsonl). A human with neither gets
the whole ledger as the window. **The ask box** is active perception made
deterministic: a rule-based planner (actors, kinds, skill ids, "last N
hours", "since I left") builds one selection expression, `core.rewind`
runs it, and the page shows both the slice it pulled and how small a
fraction of the ledger that was.

## 2. The numbers (the box beside them)

The box while the screen ran: three other lanes' leases — the qwen3-vl
server (890 M), refit-drift exp2 (1.2 G), voyager-port's Minecraft server
(1.5 G) — with **101.3 G free of 122.8 G** and the return screen itself a
stdlib server (no GPU, no lease; the fold is CPU-only).

- **The letter**: 93 words (limit 150), one question, over the
  whole-ledger window; the surprise the rules picked was the tier alarm
  *"the decision model's refusal rate moved to 1.000"*. Over a 44-minute
  window that sat inside the outage, the same rules wrote a 92-word letter
  whose surprise was the refusal itself. Every number in both is a ledger
  number; the receipts line is under the letter.
- **The judge's day, as the screen tells it**: five refusal episodes; the
  latest ran **02:44:06Z → 06:19:38Z (6,327 refusals)** and *ended on its
  own* — the ledger shows clean verdicts after 06:19:38Z. A window that
  includes the recovery (1,428 verdicts, 559 refused) rates the episode
  correctly because each episode is rated by its **overlap with the
  absence** (559/1,077 = 52 % inside the overlap), not by the whole
  window's diluted 39 %.
- **The ask box**: *"what did Kite play in the last 3 hours?"* built
  `(at >= 1793591640 and at < 1793602440) and (actor in (Kite)) and
  (kind in (tile.played))` and pulled **4,522 of 95,621 rows — 4.73 % of
  the ledger** — to answer it.
- **The rewind preview**: point at seq 62,554 (2026-11-01T18:27:02Z, a
  judge verdict), keep `Kite` × `tile.played`: the fork
  `rewind/20261101T182702Z/keep-Kite-tile.played` would replay **12,849
  events** of the 33,139 after the point and leave 20,290 behind, each
  with the reason (16,347 judge rows, 2,133 Sprout, 1,476 Pebble, …). The
  ledger keeps every row; nothing was written.
- **The precedent seam**: the stub asked exactly one question (the latest
  ≥ 50 % episode the absence overlapped — the earlier four episodes ask
  nothing; a stack of questions is a nag), it was answered inline
  (`keep_bandit`, "what they did"), and the store holds two append-only
  events: proposed, adjudicated.
- **Cost of the screen**: `core.drift` over the whole ledger is
  **1.04 s to fold + 0.02 s to gate**; the full fold is cached 60 s, so a
  returning page load is instant against the cache and a few seconds
  after the world has moved it. The 11 tests pass in **0.10–0.16 s** on a
  fixture ledger (a uv venv, hard-linked from the shared cache).

## 3. The browser check (how these screenshots were made)

`tools/return_screen/verify.mjs`, headless Chromium via Playwright on the
Thor: every section screenshotted, the four interactions a returning human
makes (ask, pick a timeline point and preview the fork, answer the
question, mark seen) driven, and the phone width (390 × 844) loaded
separately. The verdict beside this note (`return-ux-screenshots/
verdict.json`): **`ok: true`, zero console errors, zero page errors, zero
horizontal overflow at phone width.** Two real bugs the browser check
caught that the unit tests could not: timeline coordinates went `NaN`
because the page appended `Z` to timestamps that already carried it (the
click handler died before the rewind point could be set), and a click on
the dense timeline always landed on a mark, so "click empty space" could
never set the point — now any click sets the point and reads the nearest
mark.

## 4. What it makes possible

Casey can leave, come back, and in one page see what changed, answer the
one question that needs him, and — if something went wrong — point at the
moment and say *keep Kite's work, drop the rest*, with the fork described
before anything branches. The ask box is the first ledger-sized use of
the rewind selection language as an instrument for reading, not just
rewinding. And the screen is the substrate dsmc wanted for the Biographer:
letters written from the same fold the human can audit.

## 5. What was not verified

- **The letter has not been read by Casey.** dsmc is explicit that his
  reaction calibrates the rest; the rules here were tuned against one
  live day (a refusal outage) and one quiet fixture.
- **The rewind preview stops at the selection.** The cherry-pick onto a
  canon fork (`core.rewind.cherry_pick`) was not run against this world —
  it does not commit to a canon yet; the byte-identical replay proof is
  the rewind-select lane's, on the Bevy world.
- **The precedent seam is a stub.** It writes only to its own JSONL;
  `core/precedent` (the `precedent-store` lane) was not exercised here.
  The interface matches (`Precedent`, `PrecedentStatus`, `append/get/
  match/all`), so the swap is one import line.
- **The drift and pause seams are one-sided**: `core.drift` computes the
  alarms live, but the world has never written a `drift.yield` event and
  no pause file exists (the running reflex predates build #3) — the page
  reports both as such rather than implying a pause happened.
- **One viewer, one load.** No concurrent-viewer or load test; the
  verification browser is headless Chromium on the Thor, not WebKit,
  Firefox, or a physical phone. First load after a cache expiry takes
  seconds; the bound was the script's 20 s wait, not a stopwatch.
- Timeline at phone width scrolls horizontally inside its card (a 25-hour
  window does not fit 390 px); the counters, lanes and question all
  stack cleanly.

## 6. Reproducing

    # on the Thor, in this worktree:
    tools/return_screen/run.sh                       # serve on :8131 (LAN)
    PYTHONPATH=$PWD tools/return_screen/.venv/bin/python \
        -m pytest tests/return_screen -q             # 11 tests, < 1 s
    PATH=$HOME/.nvm/versions/node/v24.22.2/bin:$PATH \
        node tools/return_screen/verify.mjs http://127.0.0.1:8131/ \
        docs/lab/return-ux-screenshots               # ~40 s, rewrites the shots

Needs the world ledger where the brief says it is, and (once) the tool
venv: `uv venv tools/return_screen/.venv && uv pip install --python
tools/return_screen/.venv/bin/python pydantic pytest fastapi httpx`
(fastapi/httpx only because the repo's shared test conftest imports them).
The live world kept writing throughout; every number above is from the
run named in the screenshots' `verdict.json`.
