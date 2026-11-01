#!/usr/bin/env python3
"""The peak memory of a decision server.

Two numbers are reported:

* the **host** peak: the high-water mark of the server process's
  resident set (``VmHWM`` in ``/proc``), which on the Thor includes the
  unified-memory allocations the GPU made;
* the **GPU** peak: what the server itself reports as its torch CUDA
  high-water mark (``/stats``), for the server that keeps one.

The peak of the whole measurement is the sum of the two servers'
processes, since the baseline and ours are both resident while the
tick is measured.
"""

from __future__ import annotations

import argparse
import json
import urllib.request
from pathlib import Path


def pid_on_port(port: int) -> int | None:
    """The pid listening on a local port."""
    want = f"{port:04X}"
    inodes: set[str] = set()
    for line in Path("/proc/net/tcp").read_text().splitlines()[1:]:
        parts = line.split()
        if parts[3] != "0A":  # LISTEN
            continue
        if parts[1].rsplit(":", 1)[1] == want:
            inodes.add(parts[9])
    if not inodes:
        return None
    # walk the processes and find the one holding the socket
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        try:
            for fd in (proc / "fd").iterdir():
                try:
                    target = fd.readlink().as_posix()
                except OSError:
                    continue
                if target.startswith("socket:[") and target[8:-1] in inodes:
                    return int(proc.name)
        except OSError:
            continue
    return None


def vm_hwm_gb(pid: int) -> float:
    """The peak resident set of a process, in GB."""
    for line in Path(f"/proc/{pid}/status").read_text().splitlines():
        if line.startswith("VmHWM:"):
            return int(line.split()[1]) / (1024.0 * 1024.0)
    return 0.0


def vm_rss_gb(pid: int) -> float:
    for line in Path(f"/proc/{pid}/status").read_text().splitlines():
        if line.startswith("VmRSS:"):
            return int(line.split()[1]) / (1024.0 * 1024.0)
    return 0.0


def gpu_stats(url: str) -> dict:
    try:
        with urllib.request.urlopen(f"{url.rstrip('/')}/stats", timeout=5) as resp:
            return json.loads(resp.read())
    except Exception:
        return {}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ours", default="http://127.0.0.1:8138")
    ap.add_argument("--baseline", default="http://127.0.0.1:8137")
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    out: dict = {}
    for name, url in (("ours", args.ours), ("baseline", args.baseline)):
        port = 8138 if name == "ours" else 8137
        pid = pid_on_port(port)
        entry: dict = {"port": port, "pid": pid}
        if pid:
            entry["host_peak_rss_gb"] = vm_hwm_gb(pid)
            entry["host_rss_gb"] = vm_rss_gb(pid)
        stats = gpu_stats(url)
        for k in ("gpu_peak_alloc_gb", "gpu_peak_reserved_gb"):
            if k in stats:
                entry[k] = stats[k]
        out[name] = entry

    total = sum(v.get("host_peak_rss_gb", 0.0) for v in out.values())
    out["both_servers_host_peak_rss_gb"] = total
    text = json.dumps(out, indent=2)
    print(text)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text + "\n")


if __name__ == "__main__":
    main()
