# MEMORY RULE — take a lease; the flock is only for when the daemon is gone

Every seat's heavy work on the Thor runs under the box's admission daemon,
`thor-admit` (builder-ide `tools/thor-admit`). This replaces
`flock ~/lm-wt/heavy.lock` as the default (2026-10-31, after the 13:22 OOM
and the 22:09 fall to 8 GB free). The rule is admission before spend: the
work waits its turn before it allocates, not after.

## The one line

```bash
thor-admit run --tier live --peak 20G --label <what-the-work-is> -- <command...>
```

* `--peak` is the memory the work will take at its worst. `auto` uses the
  label's own measured history (the larger of p95 and last run) once the
  label has three runs; before that the daemon refuses `auto`, so give an
  explicit peak.
* `--tier` says what kind of work it is: `live` (nights, previews,
  first-mile requests — the default), `preparation`, `practice`, or `study`
  (the box's own background work, pre-empted by live work).
* The daemon admits only when `MemAvailable − peak ≥ 25G` (and the GPU's
  own allocation pool has room above its floor), queues FIFO with
  priorities, watches the box, and its watchdog terminates — never merely
  stops — the largest lease if the box runs short.
* If the work is already a Python process:

  ```python
  from thor_admit import lease
  with lease("20G", "trellis", tier="live"):
      ...the heavy work...
  ```

* A model server a seat wants is started **once per box**, not once per
  seat:

  ```bash
  thor-admit serve d1-2B --port 8100 -- llama-server -m d1-2B --port 8100 ...
  ```

  The first caller starts it under a live lease and stays in front of it;
  every later caller gets `port 8100` back immediately and runs nothing.
  Two seats must not each start the same model — that was half of the
  22:09 incident.

## The box's lock: the lease first, the lock second

The box's own stopgap lock, `~/lm-wt/heavy.lock`, is still in use — seats
that have not migrated to leases still take it, and it is what keeps two of
them apart. It has to be taken **after** the lease, never around it.

```bash
# right: the lease first, the lock only once the lease is granted
thor-admit run --tier live --peak 20G --label <what> --lock ~/lm-wt/heavy.lock -- <command>

# wrong: the lock is taken before the lease, and held for the whole wait
flock ~/lm-wt/heavy.lock thor-admit run --tier live --peak 20G --label <what> -- <command>
```

**Why it matters.** A seat that is waiting for room holds the lock for the
whole of its wait, and the wait can be long: on 2026-11-01 a seat waited
3 003 s for an 8 GiB lease on a box with 77 GiB free, holding the lock for
all of it. The lock is also what the box's *own* work waits for, so a seat
that is not working yet still stops the box.

**You do not have to change your command line to be correct.** The client
repairs the order in place: it gives the lock back before it asks for its
lease, and takes it again the moment the lease is granted, so the command
runs with the lock held and the queue runs without it. It says so on stderr
when it finds one. Writing `--lock` is still the right thing to do — it is
the same thing without the repair, and it says in the command what the seat
meant.

`thor-admit status` names who holds the lock, and with what, so you can see
whether a seat is holding it while it waits.

## When the work changes phase: give the memory back

A lease reserves the peak it was given, and it is charged that promise
until it ends — even after the heavy part is over. On 2026-11-01 a seat
held 40 GiB with a measured peak of 0.2 GiB for two hours, and the queue
behind it went nowhere.

If your work has phases, say so with the lease:

```bash
thor-admit run --tier live --peak 40G --label trellis -- bash -c '
  load_weights                      # the heavy part
  thor-admit phase "$THOR_ADMIT_LEASE" --peak 8G    # give the rest back
  render_scene'
```

`THOR_ADMIT_LEASE` is the lease's own id, put in the command's
environment by `thor-admit run`. From Python, the shim has it too:

```python
from thor_admit import lease, phase

with lease("40G", "trellis") as held:
    load_weights()
    phase(held, "8G")
```

A shrink is always allowed (never below what the run has already touched);
a grow the box has no room for is refused, and the lease keeps the promise
it has. The daemon also **names** a lease that holds far more than it
uses — `thor-admit status` marks it `over-reserved` and prints the peak it
would fit in. That is the daemon asking; you decide, because only you
know whether the work will spike again.

## The queue is fair, but it is not a railcar

Requests are admitted first in, first out, with priorities in front. **A
request behind a head that cannot fit may be admitted first**, because a
queue that waits for a head that will not fit is a queue that does nothing.
Two asks for the same model waiting side by side become **one** promise,
so a model server is loaded once per box even when several seats ask at
once.

## If the work is not under a lease: `thor-admit exec`

Heavy work belongs under a lease — that is the rule above. But a seat
sometimes runs something small, or something it did not plan, and it runs
**outside** any lease. Then the daemon cannot account for it. On 2026-11-01
a JAX run that did exactly that took **94.5 GB of the box's unified memory
in 20 seconds**: the desktop died, the Wi-Fi driver died, and the box
needed a power cycle.

Start such work through `exec`, which refuses to start a framework that
takes the box's memory by surprise:

```bash
thor-admit exec -- python3 train_spike.py --backend mjx --nworld 256
```

`exec` refuses a JAX/XLA process unless `XLA_PYTHON_CLIENT_PREALLOCATE=false`
(or `XLA_PYTHON_CLIENT_ALLOCATOR=platform`, or
`XLA_PYTHON_CLIENT_MEM_FRACTION` of at most 0.15), and a TensorFlow process
unless `TF_FORCE_GPU_ALLOW_GROWTH=true`. It finds the framework by the
module it runs, by the code given to `-c`, or by what the script on disk
imports — the incident's script was called `train_spike.py` and said
nothing; its `import jax` said everything.

And if a process takes the box by surprise anyway, the daemon's **guard**
can stop it: the biggest process that no lease owns, when the box falls
below the emergency floor, or when the box loses memory faster than the
leases can explain it. The guard never touches the desktop, the login, the
system's own services or the seat agents. If your own job is big and
legitimately outside a lease, put its command line on the daemon's
protected list — one pattern per line, in
`~/.local/state/thor-admit/protected.txt` — and the guard will leave it
alone.

## The fallback: the daemon is gone

`thor-admit run` starts the daemon itself if it cannot reach one, so the
flock is only for when the binary itself is missing or unusable. Keep the
stopgap for exactly that case, and say in the log that you fell back:

```bash
if command -v thor-admit >/dev/null 2>&1; then
    exec thor-admit run --tier live --peak 20G --label "$LABEL" -- "$@"
else
    echo "thor-admit unavailable ($LABEL): falling back to the heavy lock" >&2
    exec flock "$HOME/lm-wt/heavy.lock" "$@"
fi
```
From Python, the same shape:

```python
try:
    from thor_admit import lease
    cm = lease("20G", "trellis", tier="live")
except Exception:
    import fcntl, contextlib

    @contextlib.contextmanager
    def lease(*args, **kwargs):  # the stopgap, while the daemon is gone
        import os
        f = open(os.path.expanduser("~/lm-wt/heavy.lock"), "w")
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)
            f.close()

with lease("20G", "trellis"):
    ...the heavy work...
```

Two things not to do with the fallback: do not wrap `thor-admit run` in the
lock (`flock heavy.lock thor-admit run ...`), because the seat then holds the
lock while it waits for room — use `--lock` instead; and do not take the lock
*and* a lease at the same time in the Python fallback, because the lock is
meant to stand in for the lease when the daemon is gone, not to be added to
it.

## What a seat gets for following this

The queue is fair (FIFO, priorities in front, and a request behind a head
that cannot fit is let past rather than left to rot), the box never falls
below the floor for unadmitted work, the peaks the seats declare become the
cost model's memory column, and the daemon's ledger says where the box's
hours went. `thor-admit status` shows the leases, the free memory and the
queue; `thor-admit ledger` shows the hours by tier.
