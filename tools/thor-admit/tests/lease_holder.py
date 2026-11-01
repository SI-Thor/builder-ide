#!/usr/bin/env python3
"""A lease holder the integration tests can silence.

The Rust client (`thor-admit run`) heartbeats while it holds a lease, and
so does the Python shim. To test what the daemon does about a client that
does *not*, the tests need a holder whose behaviour is up to them:

    silent     holds the lease, then never says another word (a stuck client)
    heartbeat  holds the lease and heartbeats on a schedule (a healthy one)
    orphan     holds the lease, then exits while a forked child keeps the
               lock's file descriptor open (a lock with nobody left to
               release it)
    abandon    takes the grant and never takes the lock at all (a lease
               that never runs)

Usage: lease_holder.py <mode> <socket> <label> [seconds]

Prints "held" once the lease is real. Speaks the daemon's protocol by hand,
which is also the proof that the protocol is speakable outside the crate.
"""
from __future__ import annotations

import fcntl
import json
import os
import socket
import sys
import time


def send(stream, request):
    stream.write((json.dumps(request) + "\n").encode("utf-8"))
    stream.flush()
    line = stream.readline()
    if not line:
        raise SystemExit("the daemon closed the connection")
    return json.loads(line)


def main() -> None:
    mode, path, label = sys.argv[1], sys.argv[2], sys.argv[3]
    seconds = float(sys.argv[4]) if len(sys.argv) > 4 else 600.0

    connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    connection.connect(path)
    stream = connection.makefile("rwb")
    send(
        stream,
        {
            "op": "acquire",
            "label": label,
            "peak": 10485760,
            "tier": "live",
            "target": {"process": {"pid": os.getpid()}},
        },
    )
    while True:
        line = stream.readline()
        if not line:
            raise SystemExit("the daemon closed the connection")
        event = json.loads(line)
        if event.get("event") == "granted":
            break
    lease_id = int(event["lease"])
    if mode == "abandon":
        # Granted, and that is the last the daemon hears of it: no lock, no
        # held, no heartbeat. The daemon must give the lease back on its
        # own, and the ledger must not book the window as running work.
        print("granted", flush=True)
        time.sleep(seconds)
        return
    lock_fd = os.open(event["lock_path"], os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(lock_fd, fcntl.LOCK_EX)
    send(stream, {"op": "held", "lease": lease_id})
    print("held", flush=True)

    if mode == "silent":
        time.sleep(seconds)
    elif mode == "heartbeat":
        end = time.time() + seconds
        while time.time() < end:
            time.sleep(0.5)
            try:
                send(stream, {"op": "heartbeat", "lease": lease_id})
            except (OSError, SystemExit):
                pass
    elif mode == "orphan":
        if os.fork() == 0:
            # The child inherits lock_fd, so the lock outlives the client
            # that took it. The parent — the daemon's client — is gone.
            time.sleep(seconds)
            os._exit(0)
        os._exit(0)

    send(stream, {"op": "release", "lease": lease_id, "peak_rss_bytes": None})


if __name__ == "__main__":
    main()
