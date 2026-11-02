#!/usr/bin/env python3
"""Does the lease own the work the night starts? The 16:28:28 kill, proved.

**What happened on 2026-11-01 at 16:28:28.** The daemon's guard stopped
ComfyUI in the middle of SDXL sampling: ``guard.terminated``,
``trigger: runaway``, 10.5 GB (2.87 GB resident, 7.6 GB on the GPU). The
guard stops the biggest process that **no lease owns**, and a lease owns
the processes of its target and that target's *direct* children
(``procscan::usage_for``, ``Target::Process``). ``serve.sh`` starts
ComfyUI with ``nohup ... &`` and exits, so the server is re-parented to
init: it belongs to nobody, the night's lease cannot explain where the
memory went (``lease_growth_bytes: 0``), and the guard took it.

**What this script shows.** A lease's own accounting, measured on the box:

* a child the lease's client starts **directly** is the lease's memory —
  the lease's ``current_rss_bytes`` grows by what the child holds;
* a child started through a shell that exits (the ``serve.sh`` shape) is
  **not** — the lease's number does not move, and the guard sees an
  unexplained loss.

Run from the repo root on the Thor::

    cd ~/lm-wt/night-v4 && PYTHONPATH=. \
        ~/lm-wt/propmaker-batch/.venv/bin/python \
        docs/lab/night-v4-scripts/test_lease_ownership.py
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import time
from pathlib import Path

RUNNER = Path(__file__).with_name("run_night.py")

spec = importlib.util.spec_from_file_location("night_runner", RUNNER)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
sys.path.insert(0, str(runner.THOR_ADMIT_PKG))
import thor_admit  # noqa: E402

#: What the child holds. Big enough to see in the lease's number, small
#: enough that the guard's own rules (4 GB resident) do not fire.
CHILD_BYTES = 1024 ** 3

ALLOCATE = (
    "import time\n"
    "x = bytearray({bytes})\n"
    "print('held', flush=True)\n"
    "time.sleep(120)\n"
)


def lease_rss(lease_id: int) -> int:
    """The lease's own accounting, from the daemon."""
    report = runner.daemon_status()
    for lease in report.get("leases") or []:
        if int(lease.get("lease", -1)) == lease_id:
            return int(lease.get("current_rss_bytes", 0))
    return 0


def main() -> int:
    child_source = ALLOCATE.format(bytes=CHILD_BYTES)
    with thor_admit.lease("8G", "night-v4.ownership-test", tier="live") as lease:
        lease_id = int(lease.lease_id)
        before = lease_rss(lease_id)
        print(f"lease {lease_id}: {before / 1024 ** 2:.0f} MB before")

        direct = subprocess.Popen(
            [sys.executable, "-c", child_source],
            stdout=subprocess.PIPE, text=True)
        assert direct.stdout.readline().strip() == "held"
        time.sleep(3)
        after_direct = lease_rss(lease_id)
        print(f"with a direct child: {after_direct / 1024 ** 2:.0f} MB "
              f"(+{(after_direct - before) / 1024 ** 2:.0f} MB)")

        # The serve.sh shape: a shell that starts the work in the
        # background and exits, so the work is re-parented to init.
        shell = subprocess.run(
            ["bash", "-c", f"nohup {sys.executable} -c '{child_source}' "
                          f">/dev/null 2>&1 &"],
            check=False)
        time.sleep(4)
        after_grandchild = lease_rss(lease_id)
        print(f"with a re-parented grandchild: "
              f"{after_grandchild / 1024 ** 2:.0f} MB "
              f"(+{(after_grandchild - before) / 1024 ** 2:.0f} MB)")

        direct.kill()
        direct.wait()
    print(json.dumps({
        "lease": lease_id,
        "before_mb": round(before / 1024 ** 2),
        "with_direct_child_mb": round(after_direct / 1024 ** 2),
        "with_reparented_grandchild_mb": round(after_grandchild / 1024 ** 2),
        "child_mb": CHILD_BYTES // 1024 ** 2,
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
