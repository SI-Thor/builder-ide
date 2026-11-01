# The measurements behind round 13

Two scripts, both of which **read** the box and change nothing: they start
no process, take no lease and stop nothing.

## `watch-guard.sh` — the live guard, watched for an hour

```bash
~/lm-wt/thor-admit/tools/thor-admit/watch-guard.sh /tmp/guard-watch.log 62 60
```

Sixty-two samples, a minute apart: the box's free memory, the daemon's
status (the leases, the queue, the guard's own line), and **every new
`guard.*` event in the daemon's log**. Every fifth sample it also lists the
box's ten biggest processes, because the guard's candidates are the biggest
processes that no lease owns — and seeing them is how a near miss is
noticed.

* **What it needs:** the daemon running, and `thor-admit` in `~/lm-tools`.
* **How long it takes:** a minute per sample; an hour for the round-13 run.
* **What it produces:** a text file, one line per sample, and the daemon's
  own guard events at the end.

The round-13 run is in the lab record (section 23 of
`docs/lab/exp-thor-admit.md`), with the box state beside every number.

## `measure-guard-candidates.sh` — what the guard would consider, right now

```bash
~/lm-wt/thor-admit/tools/thor-admit/measure-guard-candidates.sh
```

The box's biggest processes, with their resident set, the device bytes the
driver says they hold, the sum the guard ranks by, and whether a lease owns
them.

* **What it needs:** the daemon running (`thor-admit status --json`) and
  `nvidia-smi` for the device bytes.
* **How long it takes:** about a second.
* **Why the group and not the pid:** a lease owns a whole **process group**.
  A model server started by `thor-admit serve` is the serve client's child,
  and it is the child's group that the lease owns — so a server that looks
  unleased by pid is not unleased.
