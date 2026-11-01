#!/usr/bin/env python3
"""A smoke test of the CLI: the tiers, the presence queue and the ledger.

Everything it does is light: the presence job is a `sleep`, the lease is a
`sleep`, and nothing allocates memory.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path

BIN = Path(__file__).resolve().parent / "target/release/thor-admit"
STATE = Path("/tmp/thor-admit-smoke")


def run(*args: str) -> str:
    out = subprocess.run([str(BIN), *args], capture_output=True, text=True)
    return (out.stdout + out.stderr).strip()


def main() -> int:
    shutil.rmtree(STATE, ignore_errors=True)
    STATE.mkdir(parents=True)
    socket = STATE / "sock"
    daemon = subprocess.Popen(
        [str(BIN), "daemon", "--socket", str(socket), "--state-dir", str(STATE),
         "--idle-exit", "0", "--floor", "1G"],
        stdout=subprocess.DEVNULL,
        stderr=(STATE / "daemon.err").open("w"),
    )
    try:
        deadline = time.time() + 10
        while time.time() < deadline and not socket.exists():
            time.sleep(0.1)

        print("$ thor-admit presence add --tier study --peak 1G --label sweep "
              "--resumable -- sleep 30")
        print(run("presence", "add", "--socket", str(socket), "--tier", "study",
                  "--peak", "1G", "--label", "sweep", "--resumable", "--", "sleep", "30"))
        time.sleep(1.5)

        print("\n$ thor-admit presence list")
        print(run("presence", "list", "--socket", str(socket)))

        print("\n$ thor-admit status")
        print(run("status", "--socket", str(socket)))

        print("\n$ thor-admit run --tier live --peak 1G --label live -- sleep 2")
        print(run("run", "--socket", str(socket), "--tier", "live", "--peak", "1G",
                  "--label", "live", "--", "sleep", "2"))

        print("\n$ thor-admit ledger")
        print(run("ledger", "--socket", str(socket)))

        print("\n$ thor-admit presence remove 1")
        print(run("presence", "remove", "--socket", str(socket), "1"))
        print("\n$ thor-admit presence list")
        print(run("presence", "list", "--socket", str(socket)))

        print("\n$ thor-admit ledger --json (the hour being kept)")
        print(json.dumps(json.loads(run("ledger", "--socket", str(socket), "--json")),
                         indent=2)[:1200])
        return 0
    finally:
        daemon.terminate()
        try:
            daemon.wait(timeout=10)
        except subprocess.TimeoutExpired:
            daemon.kill()
        shutil.rmtree(STATE, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
