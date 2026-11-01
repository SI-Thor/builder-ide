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

## What a seat gets for following this

The queue is fair (FIFO, priorities in front, and a request behind a head
that cannot fit is let past rather than left to rot), the box never falls
below the floor for unadmitted work, the peaks the seats declare become the
cost model's memory column, and the daemon's ledger says where the box's
hours went. `thor-admit status` shows the leases, the free memory and the
queue; `thor-admit ledger` shows the hours by tier.
