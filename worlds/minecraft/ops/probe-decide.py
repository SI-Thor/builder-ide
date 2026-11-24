#!/usr/bin/env python3
"""Probe the reflex decide seam: does a held bot's ask reach the service?

Prints, per bot: http status, elapsed seconds, and the raw body. A held
bot's ask must come back as a refusal ("paused: drift pause (soft)...")
and must leave a drift.yield row in the ledger.
"""
import json
import sys
import time
import urllib.request
import urllib.error

URL = "http://127.0.0.1:8110/decide"


def ask(bot, role, context, timeout=20):
    payload = json.dumps(
        {
            "bot": bot,
            "role": role,
            "context": {"task": context, "source": "probe"},
            "state": "a world with builders",
        }
    ).encode()
    req = urllib.request.Request(
        URL, data=payload, headers={"Content-Type": "application/json"}
    )
    start = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            body = res.read().decode("utf-8", "replace")
            return res.status, round(time.time() - start, 2), body
    except urllib.error.HTTPError as exc:
        return exc.code, round(time.time() - start, 2), exc.read().decode("utf-8", "replace")
    except Exception as exc:
        return "ERR", round(time.time() - start, 2), f"{type(exc).__name__}: {exc}"


for bot, role, context in [
    ("Pebble", "gatherer", "gather wood"),
    ("Timber", "builder", "build a chest"),
    ("Sprout", "farmer", "farm the field"),
    ("Kite", "scout", "survey the ground"),
]:
    status, secs, body = ask(bot, role, context)
    print(f"--- {bot} ({role}) ---")
    print(f"    status={status} elapsed={secs}s")
    print(f"    body={body[:500]!r}")
    sys.stdout.flush()
