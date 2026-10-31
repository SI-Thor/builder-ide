"""Capture the box's state alongside every number (CLAUDE.md: "Measure, with the
box's state beside every number").

The Thor's GPU memory is NOT separately observable (`nvidia-smi` reports
memory.total/memory.used as [N/A] on this box -- see rev-tech.md C9), so we
read memory from /proc/meminfo and tegrastats instead of nvidia-smi.
"""

import os
import platform
import shutil
import subprocess
import time


def _run(cmd, timeout=15):
    try:
        return subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout
        ).stdout.strip()
    except Exception as exc:  # pragma: no cover - diagnostic path
        return f"<unavailable: {exc}>"


def _meminfo():
    out = {}
    with open("/proc/meminfo") as fh:
        for line in fh:
            key, _, rest = line.partition(":")
            out[key] = int(rest.strip().split()[0])  # kB
    return out


def snapshot():
    mem = _meminfo()
    return {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "kernel": platform.release(),
        "arch": platform.machine(),
        "loadavg_1_5_15": os.getloadavg(),
        "nproc": os.cpu_count(),
        "mem_total_gib": round(mem["MemTotal"] / 1048576, 2),
        "mem_available_gib": round(mem["MemAvailable"] / 1048576, 2),
        "nvpmodel": _run("nvpmodel -q 2>/dev/null | head -4"),
        "nvidia_smi": _run(
            "nvidia-smi --query-gpu=name,driver_version,utilization.gpu,power.draw,"
            "temperature.gpu,clocks.gr --format=csv,noheader"
        ),
        "tegrastats": _run("timeout 3 tegrastats --interval 1000 2>/dev/null | tail -1"),
        "nvcc": _run("/usr/local/cuda/bin/nvcc --version 2>/dev/null | tail -2"),
        "jetson_clocks": "present" if shutil.which("jetson_clocks") else "absent",
    }


def banner(title):
    snap = snapshot()
    print("=" * 78)
    print(f"{title}")
    print("=" * 78)
    for k, v in snap.items():
        print(f"  {k:22s}: {v}")
    print("-" * 78)
    return snap


if __name__ == "__main__":
    import json

    print(json.dumps(snapshot(), indent=2))
