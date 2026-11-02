#!/usr/bin/env python3
"""The 16:33 kill, made on purpose, and the sweep that stops it.

**What happened on 2026-11-01 at 16:33.** The admission daemon names a
lease's lock file after the lease's number, and the numbers start again at
1 when the daemon restarts. A client that is still alive from before the
restart — the ``agent-world`` seat's d1-2B server, holding
``leases/1.lock`` from a daemon that no longer existed — still holds the
old inode. The new daemon handed the night lease 1, the shim's ``flock``
waited for a lock nobody was going to give, and the daemon gave the night
up after its 30 s grant grace ("the client never took the lock"). The
night died with no traceback.

**What this script shows.**

1. *The failure.* A lock file with the number the daemon is about to hand
   out is put in place — older than the daemon, and held by a live
   client. A client that asks for the lease blocks, and the daemon stops
   it after 30 s.
2. *The fix.* The same file is put in place again, and the night runner's
   ``sweep_stale_lease_locks()`` clears it — naming the holder — and the
   night's own lease is taken in a moment, on the same number.

Run from the repo root on the Thor::

    cd ~/lm-wt/night-v4 && PYTHONPATH=. \
        ~/lm-wt/propmaker-batch/.venv/bin/python \
        docs/lab/night-v4-scripts/test_lease_lock_collision.py

It takes the box's leases (1 GB) and leaves nothing behind.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path

RUNNER = Path(__file__).with_name("run_night.py")


def load_runner():
    spec = importlib.util.spec_from_file_location("night_runner", RUNNER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sys.path.insert(0, str(module.THOR_ADMIT_PKG))
    return module


runner = load_runner()
import thor_admit  # noqa: E402


def daemon_started() -> float:
    """When the daemon that is running now started."""
    report = runner.daemon_status()
    return time.time() - float(report.get("uptime_s") or 0.0)


def take_one_lease(label: str) -> int:
    """A lease, taken and released, and the number it was given."""
    with thor_admit.lease("1G", label, tier="live") as lease:
        return int(lease.lease_id)


def put_stale_lock(number: int, started: float) -> tuple[Path, subprocess.Popen]:
    """A lock file from before the daemon started, held by a live client."""
    path = runner.THOR_ADMIT_LEASES / f"{number}.lock"
    path.write_text("")
    old = started - 3600
    os.utime(path, (old, old))
    holder = subprocess.Popen(
        [sys.executable, "-c",
         "import fcntl,sys,time\n"
         "f=open(sys.argv[1],'r+')\n"
         "fcntl.flock(f,fcntl.LOCK_EX)\n"
         "print('held',flush=True)\n"
         "time.sleep(600)\n", str(path)],
        stdout=subprocess.PIPE, text=True)
    assert holder.stdout.readline().strip() == "held"
    return path, holder


def ask_without_the_sweep(label: str) -> dict:
    """The 16:33 failure, made on purpose."""
    started = time.monotonic()
    proc = subprocess.Popen(
        [sys.executable, "-c",
         "import sys\n"
         "sys.path.insert(0, sys.argv[1])\n"
         "import thor_admit\n"
         "with thor_admit.lease('1G', sys.argv[2], tier='live') as lease:\n"
         "    print('granted', lease.lease_id, flush=True)\n",
         str(runner.THOR_ADMIT_PKG), label],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        out, _ = proc.communicate(timeout=60)
        return {"exit": proc.returncode, "output": out.strip(),
                "waited_s": round(time.monotonic() - started, 1)}
    except subprocess.TimeoutExpired:
        proc.kill()
        out, _ = proc.communicate()
        return {"exit": None, "output": out.strip(), "timeout_s": 60,
                "waited_s": round(time.monotonic() - started, 1)}


def main() -> int:
    started = daemon_started()
    print(f"the daemon started at {time.strftime('%H:%M:%S', time.localtime(started))}")

    number = take_one_lease("night-v4.collision-test")
    print(f"a lease was taken and released: number {number}; the next is {number + 1}")

    path, holder = put_stale_lock(number + 1, started)
    print(f"the stale lock file is in place: {path} (mtime "
          f"{time.strftime('%H:%M:%S', time.localtime(path.stat().st_mtime))}), "
          f"held by pid {holder.pid}")

    print("--- without the sweep ---")
    failure = ask_without_the_sweep("night-v4.collision-test")
    print(json.dumps(failure, indent=2))

    print("--- with the sweep ---")
    # The daemon removes the lock file when it releases the lease, so the
    # file has to be put in place again for the sweep to find it.
    path, holder = put_stale_lock(number + 1, started)
    print(f"the stale lock file is in place again: {path} (held by pid {holder.pid})")
    row = runner.sweep_stale_lease_locks("the collision test")
    print(json.dumps(row, indent=2))
    print(f"the stale file is still on the disk: {path.exists()}")

    began = time.monotonic()
    heavy = runner.Heavy(ledger=None)
    with heavy.hold("the collision test", label="night-v4.collision-test"):
        took = time.monotonic() - began
    print(f"the lease was taken in {took:.2f} s")

    holder.kill()
    holder.wait()
    print(json.dumps({"without_the_sweep": failure,
                      "swept": row["unlinked"],
                      "stale_file_gone": not path.exists(),
                      "lease_taken_s": round(took, 2)}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
