#!/usr/bin/env python3
"""Measure the presence scheduler and the ledger on the real box.

Everything here is light: the presence job is a sleep and a small CPU
spinner, the leases are `sleep`s, and nothing allocates memory. The box's
own state is printed beside every number.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

BIN = Path(__file__).resolve().parent / "target/release/thor-admit"
GIB = 1024**3


def meminfo() -> dict[str, int]:
    out = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        key, _, rest = line.partition(":")
        value = rest.split()
        if value:
            out[key] = int(value[0]) * 1024
    return out


def loadavg() -> str:
    return " ".join(f"{x:.2f}" for x in os.getloadavg())


def proc_stat(pid: int) -> tuple[float, float]:
    """(utime+stime in seconds, rss in bytes)."""
    text = Path(f"/proc/{pid}/stat").read_text()
    fields = text[text.rfind(")") + 1 :].split()
    ticks = os.sysconf("SC_CLK_TCK")
    cpu = (int(fields[11]) + int(fields[12])) / ticks
    rss = int(fields[21]) * os.sysconf("SC_PAGE_SIZE")
    return cpu, rss


def box_state() -> str:
    mem = meminfo()
    return (
        f"MemAvailable {mem['MemAvailable'] / GIB:.1f} GiB of {mem['MemTotal'] / GIB:.1f} GiB, "
        f"load {loadavg()}, {time.strftime('%H:%M:%S %Z')}"
    )


def wait_for(predicate, seconds: float, what: str, log: Path | None = None) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.1)
    if log is not None and log.exists():
        print(log.read_text()[-3000:])
    raise SystemExit(f"timed out waiting for {what}")


def cli(socket: Path, *args: str) -> str:
    # The socket goes right after the subcommand: the options are the
    # subcommand's own, and a "--" further along would swallow them.
    out = subprocess.run(
        [str(BIN), args[0], "--socket", str(socket), *args[1:]],
        capture_output=True,
        text=True,
    )
    return out.stdout + out.stderr


def status(socket: Path) -> dict:
    out = subprocess.run(
        [str(BIN), "status", "--socket", str(socket), "--json"],
        capture_output=True,
        text=True,
    )
    return json.loads(out.stdout)


def main() -> int:
    state_dir = Path(tempfile.mkdtemp(prefix="thor-admit-measure-"))
    socket = state_dir / "sock"
    daemon = subprocess.Popen(
        [
            str(BIN),
            "daemon",
            "--socket",
            str(socket),
            "--state-dir",
            str(state_dir),
            "--idle-exit",
            "0",
        ],
        stdout=subprocess.DEVNULL,
        stderr=(state_dir / "daemon.err").open("w"),
    )
    try:
        wait_for(socket.exists, 10, "the daemon's socket")
        time.sleep(1.0)
        print(f"box: {box_state()}")

        # --- A: the daemon's own cost, idle -----------------------------
        time.sleep(30)
        cpu0, rss0 = proc_stat(daemon.pid)
        time.sleep(30)
        cpu1, rss1 = proc_stat(daemon.pid)
        idle_cpu = (cpu1 - cpu0) / 30.0 * 100.0
        print(
            f"A idle daemon: RSS {rss1 / 1024:.0f} KiB, CPU {idle_cpu:.2f}% of one core "
            f"(30 s window)"
        )

        # --- B: a presence job and a live lease --------------------------
        floor = 1 * GIB
        # A second daemon would fight for the floor; restart with the one
        # the measurements use.
        daemon.terminate()
        daemon.wait(timeout=10)
        daemon = subprocess.Popen(
            [
                str(BIN),
                "daemon",
                "--socket",
                str(socket),
                "--state-dir",
                str(state_dir),
                "--idle-exit",
                "0",
                "--floor",
                str(floor),
            ],
            stdout=subprocess.DEVNULL,
            stderr=(state_dir / "daemon.err").open("w"),
        )
        wait_for(socket.exists, 10, "the daemon's socket")
        time.sleep(1.0)

        spinner = (
            "import time\n"
            "end = time.time() + 45\n"
            "n = 0\n"
            "while time.time() < end:\n"
            "    n += 1\n"
        )
        add = cli(
            socket,
            "presence",
            "add",
            "--tier",
            "study",
            "--peak",
            "1G",
            "--label",
            "measure.study",
            "--resumable",
            "--",
            "python3",
            "-c",
            spinner,
        )
        print("B presence add:", add.strip())
        wait_for(
            lambda: any(
                job["state"] == "running" for job in status(socket)["presence"]
            ),
            20,
            "the presence job to run",
            state_dir / "daemon.log",
        )
        print(f"B the presence job is running: {box_state()}")

        live = subprocess.Popen(
            [
                str(BIN),
                "run",
                "--socket",
                str(socket),
                "--peak",
                "1G",
                "--label",
                "measure.live",
                "--tier",
                "live",
                "--",
                "sleep",
                "45",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        # --- C: the daemon's cost with work running ---------------------
        time.sleep(20)
        cpu0, rss0 = proc_stat(daemon.pid)
        time.sleep(30)
        cpu1, rss1 = proc_stat(daemon.pid)
        busy_cpu = (cpu1 - cpu0) / 30.0 * 100.0
        print(
            f"C busy daemon: RSS {rss1 / 1024:.0f} KiB, CPU {busy_cpu:.2f}% of one core "
            f"(30 s window, one lease and one presence job running)"
        )

        out, err = live.communicate(timeout=90)
        print("C the live lease said:", err.strip().replace("\n", " | "))

        # --- D: the ledger ----------------------------------------------
        ledger = cli(socket, "ledger", "--json")
        buckets = json.loads(ledger)["ledger"]
        current = buckets[-1]
        print("D ledger, the hour being kept:")
        print(json.dumps(current, indent=2)[:4000])

        # --- E: the pre-emption, on the real box -------------------------
        available = meminfo()["MemAvailable"]
        presence_peak = 4 * GIB
        live_peak = 2 * GIB
        preemption_floor = (
            available - presence_peak - live_peak + GIB
        )
        daemon.terminate()
        daemon.wait(timeout=10)
        daemon = subprocess.Popen(
            [
                str(BIN),
                "daemon",
                "--socket",
                str(socket),
                "--state-dir",
                str(state_dir),
                "--idle-exit",
                "0",
                "--floor",
                str(preemption_floor),
            ],
            stdout=subprocess.DEVNULL,
            stderr=(state_dir / "daemon.err").open("w"),
        )
        wait_for(socket.exists, 10, "the daemon's socket")
        time.sleep(1.0)
        cli(
            socket,
            "presence",
            "add",
            "--tier",
            "study",
            "--peak",
            "4G",
            "--label",
            "measure.preempt",
            "--resumable",
            "--",
            "sleep",
            "120",
        )
        wait_for(
            lambda: any(
                job["state"] == "running" for job in status(socket)["presence"]
            ),
            20,
            "the presence job to run",
            state_dir / "daemon.log",
        )
        print(f"E the presence job holds 4 GiB it has not used: {box_state()}")
        started = time.time()
        live = subprocess.run(
            [
                str(BIN),
                "run",
                "--socket",
                str(socket),
                "--peak",
                "2G",
                "--label",
                "measure.live2",
                "--tier",
                "live",
                "--",
                "sleep",
                "5",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        waited = time.time() - started
        print(f"E the live lease waited {waited:.2f}s: {live.stderr.strip()}")
        log = (state_dir / "daemon.log").read_text()
        for line in log.splitlines():
            if any(
                key in line
                for key in (
                    "presence.preempted",
                    "presence.started",
                    "lease.granted",
                    "presence.finished",
                )
            ):
                print("E ", line)
        return 0
    finally:
        daemon.terminate()
        try:
            daemon.wait(timeout=10)
        except subprocess.TimeoutExpired:
            daemon.kill()
        shutil.rmtree(state_dir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
