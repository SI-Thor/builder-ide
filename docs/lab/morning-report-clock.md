# The morning's clocks: is a static page over the ledger fast enough?

**Idea.** The morning report is the one surface where being slow would break
the promise: the owner opens it before the world, and the spec budgets the
first paint at ≤ 3 s (Watch clock, core-spec v2 §4.1, spine moment 13). The
spec's answer is "a static page over the ledger" — no server round-trip, no
streaming, nothing to wait for. The open question is whether that page is
cheap to *produce* as well as cheap to *serve*: the night builds it at stop,
on the same box that was rendering all night, and the build must not eat the
morning's clock.

**Hypothesis.** Folding the log into the night and rendering the page is
pure CPU work over a few dozen rows, so it is orders of magnitude inside the
3 s budget — the page can be rebuilt at any time (after a crash, on demand,
on another machine) without costing anybody's morning.

**Setup.** The clean simulated night (`core/night/nights.py::clean_night`):
50 audit events, 2 tasks kept, 1 parked, 2 sealed bets with their verdicts.
The measured operation is the whole build: `build_report` (the fold) plus
`render_html` and `render_text`. The second measurement is the status line
alone, folded 100 times, because the status line is what the report's first
line is made of and it has to be a ledger read (§3.4). The third is the
durable append — one `night.tick` committed to SQLite in WAL mode with
`synchronous=FULL`, because that is the cost every other number sits on
(§5.1: the change is fsynced before the append returns).

**Numbers.** NVIDIA Jetson AGX Thor Developer Kit, 14 Neoverse cores,
MemTotal 128 766 528 kB (≈122.8 GiB), Python 3.12.3, Linux 6.8.12-1021-tegra,
aarch64. Measured 2026-10-30:

| Operation | Measured | Budget | Margin |
|---|---|---|---|
| morning report: fold + HTML + text (50 events) | **0.2 ms** | 3 s | ~15 000× |
| status line: one fold of 50 events | **0.052 ms** | instant (a ledger read) | — |
| append: one fsynced `night.tick` (WAL, synchronous=FULL) | **0.70 ms** | — | — |

The page is 3 385 bytes of HTML and 853 bytes of text — it is a page, not an
application.

**How to reproduce.**

```bash
cd ~/lm-wt/night-runner
.venv/bin/python -m pytest tests/test_budget.py -q -s
```

The test prints each number beside the state of the box, and fails if the
morning page takes longer than the Watch clock's 3 s or a durable append
takes longer than 0.5 s.

**Verdict: useful.** The morning's clock is not close, and the interesting
part is *why*: the page costs what a fold costs, because the report has no
state of its own. That is the same property that makes the feed survive a
kill -9 (§5.4) and the status line survive the failure it describes
(§3.4) — one design decision, three guarantees. The corollary is a rule for
the rest of the build: anything that would need to be *computed* to show the
morning (a live model load, a render, a tally the log cannot answer) belongs
in the night, not in the page. The night pre-bakes; the morning reads.

Nothing here needs re-deciding. The numbers are measurements, not estimates,
and the box they came off is named above.
