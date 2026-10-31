# EXP — the store race: one connection, two threads, a 500 (world-mcp round)

**Date:** 2026-10-31 · **Seat:** `~/lm-wt/core-doors` (the core-doors brief,
item 1) · **Author:** the core-doors seat.

**Status: DONE — the lock won on the measurement, and per-thread
connections lost on semantics as well as on the number.** The failing
state, the two candidate fixes and the numbers that decided between them
are all below; the fix lives in `core/store.py` (`_serialized`) with its
reproduction in `tests/test_store_race.py`.

---

## 1. What broke

world-mcp (the MCP server over the core's HTTP doors,
`~/lm-wt/thor-world-repo`, docs/design.md §8.5) drew a 500 from the core
about one run in three under concurrent load: `sqlite3.InterfaceError` in
`core.store.count_events`, when two store-reading GETs landed in the
threadpool in the same tick.

The mechanism: every read door is served from ONE `sqlite3.Connection`
opened with `check_same_thread=False` (`core/store.py`), and FastAPI runs
the sync endpoints on anyio's threadpool — so two GETs in one tick use the
same connection from two threads. libsqlite is compiled serialized
(`sqlite3.threadsafety == 3`), but **pysqlite is not** in consequence: its
statement cache hands the *same cached statement object* to both threads
(the doors re-issue identical SQL by construction — `count_events` runs
once per word on `/v1/vocab`), and cursor state races. The errors seen, in
order of frequency, all from one 8-thread in-process probe (2400 calls,
`/tmp/probe_race.py` in the session log):

| count | error |
|---|---|
| 705 | `sqlite3.InterfaceError: bad parameter or other API misuse` |
| 566 | `TypeError: 'NoneType' object is not subscriptable` (the `fetchone()["c"]` in `count_events`) |
| 140 | `TypeError: int() argument must be ... not 'NoneType'` |
|  20 | `IndexError: tuple index out of range` |
|   2 | `sqlite3.InterfaceError: not an error` |

## 2. Reproduction through the real ASGI app

`tests/test_store_race.py::test_concurrent_reads_and_writes_keep_the_log_gapless`
— 8 threads writing vocabulary calls through the service while 30 GETs hit
five read doors through the `client` fixture. **Failed 10/10 runs before
the fix** (both the InterfaceError and the NoneType variants), passes
10/10 after. The pure-read hammer (`..._never_collide_...`, 12×12 GETs)
passed even pre-fix — reads alone collide too rarely at that size; the
write storm is what widens the window. The test file keeps both.

## 3. The two candidates, measured

Benchmark (`/tmp/bench_doors.py`, session log): the five read doors
through the real ASGI app at C concurrent clients, a vocabulary-call
writer looping every 2 ms beside them, best of 3 rounds, ProArt laptop
(WSL2, CPython 3.14.4, SQLite 3.46.1). Errors = requests that answered
non-200 or raised.

| variant | C=1 | C=4 | C=8 | C=16 |
|---|---|---|---|---|
| **unfixed** — errors | 0 | **80/400 (20%)** | **154/480 (32%)** | **176/480 (37%)** |
| unfixed — rps (p95) | 199 (6.1 ms) | 77 (80 ms) | 65 (171 ms) | 59 (279 ms) |
| **A: one lock** — errors | 0 | 0 | 0 | 0 |
| A — rps (p95) | 189 (6.4 ms) | **128 (65 ms)** | **124 (145 ms)** | **133 (266 ms)** |
| **B: per-thread read connections** — errors | 0 | 0 | 0 | 0 |
| B — rps (p95) | 172 (6.6 ms) | 86 (81 ms) | 83 (176 ms) | 85 (350 ms) |

The 20–37% error band of the unfixed store is exactly the world-mcp
"about one run in three".

**B lost, twice over.**

1. **Semantics (the tests found it first):** the store's callers read
   their own uncommitted writes inside a batch — `NightsService.start`
   opens `store.batch()`, appends the night row, and
   `attach_slate_to_night` reads that row back inside the open
   transaction. A reader on its own connection sees only committed state,
   so the night row is not there: **5 tests in `tests/test_api.py`
   failed under B** (404s from inside a batch). Closing that needs
   read-your-own-writes split personality on every read path — a second,
   invisible lock-shaped complexity, which is the thing B was supposed to
   avoid.
2. **The number:** B was slower at every concurrency (85 vs 133 rps at
   C=16; p95 350 vs 266 ms) — per-thread connection setup, schema parse
   and a second page cache, against reads that take microseconds anyway.

**A won:** reads serialized behind a lock they hold for microseconds cost
nothing at any concurrency the doors see, and they keep the one
connection's story intact — one page cache, one statement cache, one
`in_transaction` truth, and boot/batch internals untouched. The single
writer is unchanged: the lock it already held now covers reads too.

## 4. Reproduce

```
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/python -m pytest -q tests/test_store_race.py        # the fix holds
git stash -- core/store.py && \
.venv/bin/python -m pytest -q tests/test_store_race.py        # 10/10 fails again
```

## 5. Verdict

**Useful — a real bug fixed with the smallest change that the measurement
allows.** Nothing here makes the doors fast; it makes them not lie. The
throughput ceiling this box showed (~130–200 rps of read doors through the
test transport) is the test client's, not the product's.
