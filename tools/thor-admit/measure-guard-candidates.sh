#!/usr/bin/env bash
# The guard's candidates, right now: the biggest processes that no lease owns.
#
# The guard's candidate is the biggest process that **no lease owns**, ranked
# by resident set **plus** the device bytes the driver says it holds. The
# threshold is 4 GiB of that sum (`--guard-min-rss`), so a model server with
# a small resident set and a large device allocation is a candidate long
# before its resident set reaches 4 GiB.
#
# A lease owns a whole **process group**, so the check here is the group and
# not the pid: a model server started by `thor-admit serve` is the serve
# client's child, and it is the child's group that the lease owns.
#
# What it needs: the daemon running (`thor-admit status --json`) and
# `nvidia-smi` for the device bytes. What it does: reads /proc and /proc's
# own record of the locks. It allocates nothing and takes nothing.
# How long it takes: about a second.
set -uo pipefail

python3 - <<'PY'
import json, os, subprocess, sys

def run(command):
    return subprocess.run(command, capture_output=True, text=True, timeout=30).stdout

# The leases, and the process groups they own.
leased_pids, leased_groups = set(), set()
try:
    report = json.loads(
        run([os.path.expanduser("~/lm-tools/thor-admit"), "status", "--json"])
    )
    for lease in report.get("leases", []):
        if lease.get("pid"):
            leased_pids.add(int(lease["pid"]))
        if lease.get("pgid"):
            leased_groups.add(int(lease["pgid"]))
except Exception as error:
    print(f"could not read the status: {error}", file=sys.stderr)

# The device bytes, from the driver.
device = {}
try:
    for line in run([
        "nvidia-smi",
        "--query-compute-apps=pid,used_memory",
        "--format=csv,noheader,nounits",
    ]).splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            device[int(parts[0])] = int(parts[1]) * 1024 * 1024
except Exception as error:
    print(f"could not read the device bytes: {error}", file=sys.stderr)

rows = []
for name in os.listdir("/proc"):
    if not name.isdigit():
        continue
    pid = int(name)
    try:
        with open(f"/proc/{pid}/statm") as fh:
            rss = int(fh.read().split()[1]) * 4096
        with open(f"/proc/{pid}/cmdline", "rb") as fh:
            cmd = fh.read().replace(b"\0", b" ").decode("utf-8", "replace").strip()
        with open(f"/proc/{pid}/stat") as fh:
            stat = fh.read()
        close = stat.rfind(")")
        fields = stat[close + 1 :].split()
        pgrp = int(fields[2])
    except (OSError, ValueError, IndexError):
        continue
    if not cmd:
        continue
    total = rss + device.get(pid, 0)
    if total < 256 * 1024 * 1024:
        continue
    rows.append((total, rss, device.get(pid, 0), pid, pgrp, cmd))

rows.sort(reverse=True)
print(f"{'rss':>7} {'device':>7} {'ranked':>7}  {'pid':<8} {'pgrp':<8} {'owned':<6} command")
for total, rss, dev, pid, pgrp, cmd in rows[:12]:
    owned = "lease" if (pid in leased_pids or pgrp in leased_groups) else "NO"
    print(
        f"{rss/2**30:6.2f}G {dev/2**30:6.2f}G {total/2**30:6.2f}G  {pid:<8} {pgrp:<8} "
        f"{owned:<6} {cmd[:100]}"
    )
print()
print("the guard's threshold: 4 GiB of resident set (--guard-min-rss)")
print("leased pids:", sorted(leased_pids), " leased groups:", sorted(leased_groups))
PY
