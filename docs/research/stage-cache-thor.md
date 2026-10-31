# The stage cache and partial regeneration — measured on the Thor

**Date:** 2026-10-31 (07:50–07:58 AKDT) · **Where:** this worktree
(`stage-cache`) · **Box:** NVIDIA Jetson AGX Thor (sm_110, 14× Cortex-X4A,
128 GB LPDDR5X, Ubuntu 24.04) · **Engine:** the round-2 venv at
`~/lm-wt/v2-next`, read-only — infinigen `2.0.0a3 @ 224598d4` (the patched
traceable-scenes tree), procfunc 0.37.0, bpy 4.2.0, Python 3.11.13.

**Box state, beside every number.** The box was **shared and getting
busier through the run**: load average 21.6 → 27.1 over the eight minutes
(another seat's `sweep-mountain-s2-coarse` was running on
`~/src/infinigen-thor` throughout; the GPU rail was **idle — 0 %, 2.4–2.8
W — in every sample**, because a trace realizes nothing). Every wall clock
below is therefore an **upper bound** on an idle box, and where two runs
of identical work differ (the room traces 40.5 s, 44.4 s, 57.9 s, 63.1 s,
66.2 s across the session), the load moved, not the work.

What this measures is plan §3 week-2 item 9's pass/fail: *"edit one room"
end-to-end vs full regeneration, with per-stage timings; cache hit rate
per night reported; cache keys ⊆ (recipe hash, engine pin, stage)*. The
machinery is this branch's: `core/engine/DIRTY.md` (the contract),
`stagecache.py` (the store), `graph.py` (the diff), `regen.py` (the
driver), driven end to end through the engine seam against the real venv.
Reproduce with `.venv/bin/python examples/stage_cache_thor.py`; the raw
numbers are `stage-cache-thor.json` beside this file.

### The short version

| ask | full regeneration | partial regeneration | the saving |
|---|---|---|---|
| **edit one room** (a 3-entry recipe: room + terrain + crates) | **48.7 s** — all three entries re-trace (room 44.4, terrain 1.9, crates 2.2) | **60.1 s wall under peak load, of which engine work is exactly the room's re-trace (57.9 s); the siblings are hits the engine is never asked for** (0.0 s, byte-identical from cache) | the siblings' re-trace (**4.1 s here**) plus, at this recipe's mix, immunity to load spikes on the cheap entries; the room dominates both runs, which is what the next row is for |
| **add a desk** (round 2's one-`chosen_idx` edit, re-run on fresh traces) | **36.6 s** whole CLI (trace 33.6 s; generation+render 36.6 s; 8,065 `choice_idx` calls; peak RSS 829 MB) | the graph diff says the desk's is the only new work: **+2,698 nodes added, 0 removed, 2 changed, closure 2,704 nodes = 12.6 % of the head graph** — so a splicing engine would re-execute 12.6 % and reuse 87.4 %; the measured marginal cost of the desk is **+15.9 s** whole-CLI (an upper bound: it includes the desk's render; round 2's cProfile attribution of the same edit is **+5.5 s of generation**, 1,104/1,432 functions identical) | **~87 % of the room's graph — 21 s of the 36 s room build at round 2's attribution — is reusable work a subtree-level cache skips |
| **a 10-edit session** | computed, not re-run: **702.4 s** (the session's own measured per-entry walls, summed over the 30 stage asks) | **measured: 122.6 s**, hit rate **76.67 %** (23 hits / 30 asks, 7 misses, 0 evictions, 10 entries / 10.1 MB) | **5.7×**, and the three edits that revisited an earlier seed cost **0.01–0.02 s each** — a content-addressed cache remembers |

---

## 1. "Edit one room" — stage granularity, cold cache vs warm

The recipe is three independent generator entries — `fjellvik.room`
(`room_livingroom_rand`), `fjellvik.terrain` (`terrain_scene_rand`),
`fjellvik.crates` (`storage_cabinet_with_door_rand`) — and the edit is one
op: `fjellvik.room.seed 0 → 1`. The same edit runs twice through
`Regenerator.regenerate`: once against a **cold** cache (every entry
misses → the full-regeneration cost), once against a **warm** one (the
room misses, the siblings hit).

| | cold (full) | warm (partial) |
|---|---|---|
| verdicts | miss 3 / hit 0 | miss 1 / hit 2 |
| engine work charged | room 44.4 s + terrain 1.9 s + crates 2.2 s | room 57.9 s only |
| whole regenerate wall | 48.7 s (load 21.6) | 60.1 s (load rising to 26+) |
| siblings | re-traced | **0.0 s — served byte-identical from cache, the engine never asked** |

The load honesty matters here: the warm run's *room* trace (57.9 s) ran
under heavier load than the cold run's (44.4 s), so the whole-wall
comparison (60.1 vs 48.7 s) says more about the box than the cache. What
the contract guarantees — and what this measures cleanly — is the
**engine work**: the warm regeneration charged exactly one entry, and the
other two stages came back **byte-identical** (hash-verified reads; the
hit's bytes equal a fresh generation's, which the real-engine test
asserts). At this recipe's mix the sibling saving is 4.1 s per edit
(~8 %); the expensive entry is the room itself, and the room's *inside*
is the next scenario.

Per-entry stage sizes for scale: the room's traced stage is 5.28 MB /
18,725 nodes; terrain 106 KB / 413 nodes; crates ~0.3–0.4 MB / ~1–3 k
nodes.

## 2. "Add a desk" — subtree granularity, the round-2 edit re-run

Round 2's edit (one `chosen_idx` at `room.py:661`, desk absent → present,
forced with the experiment's own `choice_tool.py` while the RNG stream
position is unchanged) re-run fresh through this branch's graph diff:

| | baseline | desk variant | |
|---|---|---|---|
| nodes | 18,725 | 21,423 | **+2,698 added, 0 removed, 2 changed** — identical to round 2 §4.1(a), reproduced |
| the 2 changed shared ids | | | the join `n16943` (the `_operator.add` where the desk's objects join the room's lists — grown by an inline embedded Proxy tree) and the tail `n18724` (a positional id re-bound) |
| dirty closure (what re-executes) | | | **2,704 nodes = 12.62 %** of the head graph — the added subtree, the join, and their consumers to the outputs |
| `choice_idx` calls (un-traced run) | 7,185 | 8,065 | **+880**, the desk's own choices (the graph records **+49 choice nodes**, round 2's number) |
| whole-CLI wall, 320×180 / 4 spp | 20.76 s | 36.64 s | **+15.88 s** — an *upper bound* on the desk's cost: it includes the desk's render time at floor settings; round 2's cProfile attribution of the same edit on the un-traced path is **+5.5 s of generation** (21.6 → 27.1 s), with 1,104 of 1,432 profiled functions at identical call counts |
| peak RSS | | 829 MB | `/usr/bin/time -v`, the round-2 convention |
| the diff itself | | | **314 ms** to diff the two 5.28 MB graphs (240 ms on the quiet first run of the same pair) |

Read as a cache statement: a whole-scene regeneration of the desk variant
pays 36.6 s; the dirty-set contract says only 12.6 % of the graph — the
desk's subtree and its join points — is new work, so a splicing engine
(graph-edit `reexecute`, the seam's mechanism) would re-execute 2,704
nodes and reuse 18,721. At this box's measured rate that is **~87 % of
the room's build skipped**, which is the number that makes a 534 s coarse
stage affordable in a night. Two honest limits, both in DIRTY.md §3: the
venv boundary refuses in-place splicing today (its `replace`/`execute`
refusal names the missing piece; the marginal work was measured by
re-running, not by splicing), and this diff is **not splice-safe as-is**
(the one re-bound tail id) — the contract's verdict is "re-trace the
stage, execute the dirty subtree", which is exactly what the re-run
measured.

## 3. A scripted 10-edit session — the hit rate

Ten edits over the 3-entry recipe, each one a full `regenerate()` of
every entry (30 stage asks), through one cache (8 GiB budget; 10 entries
/ 10.1 MB / **0 evictions**) — the first seven edit distinct seeds, the
last three **go back to seeds the cache has already seen**:

| # | edit | verdicts | wall |
|---|---|---|---|
| 1 | room.seed → 1 | 2 hit / 1 miss | 66.2 s (load 27) |
| 2 | crates.seed → 43 | 2 hit / 1 miss | 4.2 s |
| 3 | terrain.seed → 1 | 2 hit / 1 miss | 3.3 s |
| 4 | crates.seed → 44 | 2 hit / 1 miss | 2.4 s |
| 5 | room.seed → 2 | 2 hit / 1 miss | 40.7 s |
| 6 | crates.seed → 45 | 2 hit / 1 miss | 3.5 s |
| 7 | terrain.seed → 2 | 2 hit / 1 miss | 2.3 s |
| 8 | crates.seed → 42 (back) | **3 hit** | **0.02 s** |
| 9 | room.seed → 0 (back) | **3 hit** | **0.01 s** |
| 10 | terrain.seed → 0 (back) | **3 hit** | **0.02 s** |

**Hit rate 76.67 %** (23/30), the cache's own counters with a clean
per-session denominator (`reset_stats` — the nightly measure P §6-2 asks
for). The session's cached wall is **122.6 s**; the same session with no
cache is **702.4 s computed** from the session's own measured per-entry
walls (one re-trace per ask — room 63.1 s at worst, crates 3.9 s,
terrain 3.3 s; computed, never measured twice by pretending). The load
sensitivity is visible in the honest direction too: edits 1 and 5 do
identical work (one room re-trace) at 66.2 s and 40.7 s — the box moved,
the cache did not.

The structural reading: with 3 entries, a single-entry edit can hit at
most 2/3; the hit rate rises with entry count and with revisits (a
content-addressed cache remembers every seed it has seen — the "edit
back" pattern that a night's iteration loop does constantly). The three
free edits at the end are that property, measured.

## 4. Artifacts and how to reproduce

```bash
.venv/bin/python examples/stage_cache_thor.py            # ~8 min on the box
.venv/bin/python -m pytest tests/engine -m engine -q      # the live assertions
```

| what | where |
|---|---|
| the raw numbers | `docs/research/stage-cache-thor.json` |
| the driver | `examples/stage_cache_thor.py` (scenarios A/B/C) |
| the contract | `core/engine/DIRTY.md` |
| the doubles' tests | `tests/engine/test_{graph,stagecache,regen}.py` |
| the real-engine assertions | `tests/engine/test_stagecache_real.py` (`-m engine`) |
| round 2's original desk measurement | `docs/research/engine-round2.md` §4 |
| scratch (wiped per run) | `$BUILDER_STAGE_SCRATCH` or `/tmp/stage-cache-thor` |

> **Verdict — does the stage cache make the night affordable?** At stage
> granularity it does exactly what the contract says, measured on real
> engine bytes: a hit skips the engine and serves byte-identical work,
> an edit charges one entry, and a 10-edit session runs at **5.7×** its
> no-cache cost with **76.67 %** hits. At subtree granularity the graph
> diff — reproduced fresh, identical to round 2 — bounds the desk edit's
> new work at **12.6 % of an 18,725-node scene**, and the splice that
> would collect that saving is the venv boundary's named missing piece,
> with the fork's `choice_tool.py` instrumentation as its starting point.
