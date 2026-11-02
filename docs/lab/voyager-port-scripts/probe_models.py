#!/usr/bin/env python3
"""Are the three cloud roles reachable, and what do they cost?

The brief names the three roles and says the key comes from the house
secrets file and is never printed. This probe asks each role one tiny
question, prints the model's own answer, the token counts the provider
reported, and how long it took. The key itself is never printed.

Usage:

    ~/lm-wt/voyager-port/.venv/bin/python \
        docs/lab/voyager-port-scripts/probe_models.py

What it needs: a key in the house secrets file and network access to
api.deepinfra.com. How long it takes: about a minute.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from core.voyager.llm import DEFAULT_MODELS, ModelRouter  # noqa: E402

ROLES = ("planner", "coder", "verifier")


def main() -> int:
    router = ModelRouter.from_models(dict(DEFAULT_MODELS))
    print("roles:", json.dumps(DEFAULT_MODELS, sort_keys=True), flush=True)

    question = (
        "You are the planner of a Minecraft agent. Name the next one "
        "meaningful step toward getting wood, as a single short sentence. "
        "Do not write code."
    )
    for role in ROLES:
        started = time.time()
        try:
            reply = router.complete(
                role, "You are terse and concrete.", question,
                max_tokens=200, temperature=0.3)
        except Exception as exc:
            print(f"{role}: FAILED after {time.time() - started:.1f}s "
                  f"{type(exc).__name__}: {exc}", flush=True)
            continue
        elapsed = time.time() - started
        print(f"--- {role} ({router.client(role).model}) {elapsed:.1f}s", flush=True)
        print((reply.text or "")[:400].strip(), flush=True)
        print("tokens:", json.dumps(reply.usage.as_dict(), sort_keys=True), flush=True)

    print("cost book:", json.dumps(router.cost.snapshot(), sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
