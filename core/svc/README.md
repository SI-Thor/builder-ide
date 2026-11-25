# The service layer

Each service here owns one lifecycle and speaks to the store through audit
events only — there is no other write path. `Core` (in `__init__.py`) is the
object they all share: the settings, the store, the ports (the recipe store,
the merge-gate engine, the telemetry), and the gc bridge.

## The gc wiring

`gc` (`tools/gc`) is a Rust binary that holds a subcontractor to its bid: a
job is written, bids come in, one is awarded, the burn is checkpointed against
the bid, and the job is closed with a three-valued verdict. builder-ide holds
a builder to its estimate the same way.

Two modules carry that conversation, and **neither of them is required**:

| module | what it is |
|---|---|
| [`gc_bridge.py`](gc_bridge.py) | the fail-open window onto the binary: it drives `gc` over `subprocess`, owns gc's ledger (`$BUILDER_HOME/gc-ledger.jsonl`, next to `core.db`), and returns gc's own numbers. It never raises. |
| [`gc_night.py`](gc_night.py) | the spine's half: the seam the night runner calls (`GcNightSeam`), and the reputation rows the morning report and the read API show (`reputation_rows`). |

The mapping, in one line each:

- a **confirmed work order** is a gc **job** (`WorkOrdersService.confirm` opens
  it; `start_attempt` hires the seat);
- a **night attempt's burn** is a gc **checkpoint** — and gc's 80%-of-bid stop
  line comes back as a **cut**, the way the night cuts any work: a queue mark
  with a reason, never a crash;
- the **morning report** closes the night's contracts with a three-valued
  verdict and the actuals, and reads the reputation back;
- `GET /v1/gc/reputation?seat=…` returns a builder's record: on time, inside the
  bid, retools, debt.

**Fail open.** The bridge is found through `$BUILDER_GC_BIN` and then
`tools/gc/target/release/gc`. With the binary absent, with a failing gc, with
an unreadable ledger, every method returns `None` and logs once: a
builder-ide without gc behaves exactly as a builder-ide without gc did before
these two modules existed.

**It is not wired into the night driver yet.** The night runner takes the seam
as an optional argument (`NightRunner(..., gc=...)`); nothing in production
passes it, because the spine's night service and the night runner are still
two halves that are not joined — the spine writes the night's rows, the runner
seat drives the attempts, and no code moves work from the first to the second.
The seam and the cut are exercised by the end-to-end test.

**How to run the tests**

    /home/proart/projects/builder-ide/.venv-local/bin/python -m pytest -q \
        -p no:cacheprovider tests/test_gc_bridge.py tests/test_gc_integration.py

Both are green with or without the gc binary built; the tests that need the
real binary skip with a stated reason when it is not there.
