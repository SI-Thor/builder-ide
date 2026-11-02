#!/usr/bin/env python3
"""Drive the bridge by hand, with its stderr kept in a file.

The tech-tree probe showed the bridge writing a Node stack trace into
the response stream ("Error: write EPIPE" and the frames under it), so
the two sides lost step with each other. This driver starts the bridge
the same way the adapter does, sends the same requests the probe sends,
and keeps the bridge's stderr in a file so the exception that ends it
can be read instead of guessed at.

Usage:

    ~/lm-wt/voyager-port/.venv/bin/python \
        docs/lab/voyager-port-scripts/drive_bridge.py

What it needs: the sandbox up on 127.0.0.1:25600. How long it takes:
about two minutes (the scan is the slow part).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
BRIDGE = REPO / "core" / "voyager" / "adapters" / "minecraft_bridge.js"
NODE = "/home/caseydigennaro/lm-wt/agent-world/runtime/node/bin/node"
MINECRAFT_DIR = "/home/caseydigennaro/lm-wt/agent-world/bots"
OUT = REPO / "docs" / "lab" / "voyager-port-scripts" / "results"
STDERR = OUT / "bridge-stderr.log"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["VOYAGER_MC_HOST"] = "127.0.0.1"
    env["VOYAGER_MC_PORT"] = "25600"
    env["VOYAGER_MC_USER"] = "voyager"
    env["VOYAGER_MC_VERSION"] = "26.1.2"
    env["VOYAGER_MINECRAFT_DIR"] = MINECRAFT_DIR

    handle = STDERR.open("w")
    process = subprocess.Popen(
        [NODE, str(BRIDGE)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=handle,
        text=True, bufsize=1, env=env,
    )
    next_id = 0

    def call(cmd: str, **payload):
        nonlocal next_id
        next_id += 1
        request = {"id": next_id, "cmd": cmd}
        request.update(payload)
        started = time.time()
        process.stdin.write(json.dumps(request) + "\n")
        process.stdin.flush()
        line = process.stdout.readline()
        took = time.time() - started
        print(f"--- {cmd} took {took:.1f}s", flush=True)
        if not line:
            print("    (the bridge closed the pipe)", flush=True)
            return None
        try:
            answer = json.loads(line)
        except ValueError:
            print(f"    NOT JSON: {line[:400]!r}", flush=True)
            return None
        if not answer.get("ok"):
            print(f"    error: {answer.get('error')}", flush=True)
        else:
            result = answer.get("result")
            text = json.dumps(result, sort_keys=True, default=str)
            print(f"    ok: {text[:600]}", flush=True)
        return answer

    call("connect")
    call("run", code="const r = await mc.scan(96); console.log(JSON.stringify(r.nearby));",
         timeout_ms=180000)
    call("run",
         code=("const r = await mc.move_to_block('oak_log', 96, 60000);"
               "console.log('at ' + JSON.stringify(r.at));"),
         timeout_ms=180000)
    call("observe")

    print("\n=== the bridge's stderr ===", flush=True)
    handle.flush()
    try:
        print(STDERR.read_text()[-4000:], flush=True)
    except Exception as exc:
        print("could not read the stderr file: " + str(exc), flush=True)

    try:
        process.stdin.close()
    except Exception:
        pass
    try:
        process.terminate()
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
