#!/usr/bin/env python3
"""The bake-off harness: score the reference set with one candidate.

One candidate per run, because the candidates are very different beasts: the
scripted checks are analytic and take milliseconds, the local VLM wants a
30 B model resident, and Jev is a cloud call. The harness runs one, measures
it, and writes ``results/<candidate>.json``; ``report.py`` reads the results
and prints the tables side by side.

    python docs/lab/critic-select-scripts/score_set.py --candidate scripted
    python docs/lab/critic-select-scripts/score_set.py --candidate vlm
    python docs/lab/critic-select-scripts/score_set.py --candidate hybrid \
        --set delegate=vlm

Every candidate is measured on the **same** members, with the **same**
counting rule (:func:`core.critic.critic.calibration_table`), so the tables
are comparable by construction.

The mesh half needs an interpreter with ``bpy`` — the Infinigen checkout's
virtualenv on the Thor:

    export CRITIC_BLENDER_PYTHON=~/src/infinigen-thor/.venv/bin/python
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness import CACHE, MANIFEST, load_set, run_candidate, write_result  # noqa: E402

from core.critic.select import resolve_critic  # noqa: E402


def _parse_value(raw: str):
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", default="scripted")
    parser.add_argument("--name", default=None, help="the result file's name")
    parser.add_argument("--manifest", default=str(MANIFEST))
    parser.add_argument("--night", default=None)
    parser.add_argument(
        "--set",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="a keyword argument for the candidate (repeatable)",
    )
    args = parser.parse_args()

    kwargs = {}
    for item in args.set:
        key, _, raw = item.partition("=")
        kwargs[key] = _parse_value(raw)

    members, bases = load_set(args.manifest, CACHE)

    critic, reason = resolve_critic(args.candidate, **kwargs)
    if reason:
        print(f"! {reason} — falling back to the scripted critic")

    payload = run_candidate(critic, members, bases, night=args.night)
    payload["fallback_reason"] = reason
    payload["kwargs"] = {k: v for k, v in kwargs.items()}
    write_result(payload, args.name or args.candidate)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
