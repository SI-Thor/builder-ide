# The morning branch flip on the Thor

**Idea.** The morning's choice — "which of last night's three options do we
keep?" — is a pointer move, not a re-render: the comparisons were rendered
overnight, so applying one is `main.head = branch.head` (core-spec v2 §1.2,
D §07:11). If that pointer move costs anything close to a render, the morning
breaks: the owner is waiting at the same clock as the night was.

**Hypothesis.** A branch flip is a pointer move over the audit log, so it is
bounded by one durable append — it should land in milliseconds, orders of
magnitude inside the spec's budgets of *branch flip ≤ 2 s* and *apply ≤ 10 s*
(§4.1, both marked `[b]`, meaning a test can check them).

**Setup.** The recipe store (half B) over a SQLite ledger in WAL mode with
`synchronous=FULL` — the same durability the sealed-bet ordering depends on
(§5.1) — writing to the Thor's local NVMe. The measured operation is the
whole apply path: the head move, its audit append, and the projection update.
The in-memory ledger is measured too, as the floor.

**Numbers.** NVIDIA Jetson AGX Thor Developer Kit, 14 Neoverse cores,
MemTotal 128 766 528 kB (≈122.8 GiB), Python 3.12.3, Linux 6.8.12-1021-tegra,
aarch64. Measured 2026-10-30:

| Operation | Ledger | Measured | Budget | Margin |
|---|---|---|---|---|
| branch flip | SQLite, `synchronous=FULL` | **0.69 ms** | 2 s | ~2900× |
| apply flow (flip + scoring hook) | SQLite, `synchronous=FULL` | **0.94 ms** | 10 s | ~10 600× |
| branch flip | in-memory | 0.02 ms | 2 s | — |

The SQLite row includes the fsync'd commit of the `branch.head.moved` row, so
the number is the honest one for production; the in-memory row is the floor.

**How to reproduce.**

```bash
cd ~/src/builder-ide            # or the worktree
.venv/bin/python -m pytest tests/test_budget.py -q -s
```

The test prints the measured number beside the state of the box (board, core
count, MemTotal) — CLAUDE.md's rule that every number carries the box's state
beside it. It fails if a flip ever exceeds 2 s, or an apply exceeds 10 s.

**Verdict: useful.** The budget is not close: a flip is three orders of
magnitude inside it, and the cost is dominated by the fsync, not by the
recipe store's logic. The consequence for the rest of the design is the one
the spec already assumes — the morning's A/B/C choice is instant, so the
expensive work must happen overnight, before the owner wakes up. Nothing
here needs re-deciding; the number is now a measurement rather than an
estimate.
