#!/usr/bin/env python3
"""Run Jev (the cloud judge) over the reference set, in its arms.

Four arms, because two questions have to be answered separately:

* **which question type decides** — ``jev_verify`` (a Noul per class: "is
  this evidence consistent with a hole in it?") or ``jev_classify`` (one
  Choice: "which class is this frame, or is it clean?");
* **what Jev is given** — the scripted **measurements** as well as the
  description, or the description alone.

The arms that carry the measurements are the honest "everything the critic
knows" arm; the ones without are the "perception only" arm. The difference
between them is what the scripted signals are worth.

    python docs/lab/critic-select-scripts/run_jev.py --arm verify --measurements
    python docs/lab/critic-select-scripts/run_jev.py --arm verify --captions results/captions.json

The API key comes from ``TYPESAFE_API_KEY`` (the environment, or the
last-mile secrets file). It is never printed and never written to a result.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness import CACHE, MANIFEST, load_set, run_candidate, write_result  # noqa: E402

from core.critic.candidates.jev import JevCritic, read_api_key  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arm", choices=("verify", "classify"), default="verify")
    parser.add_argument(
        "--measurements",
        action="store_true",
        help="also send the scripted checks' measurements",
    )
    parser.add_argument(
        "--captions",
        default=None,
        help="the VLM's descriptions of the frames (results/captions.json)",
    )
    parser.add_argument("--manifest", default=str(MANIFEST))
    parser.add_argument("--night", default=None)
    args = parser.parse_args()

    descriptions = {}
    if args.captions:
        path = Path(args.captions)
        if path.is_file():
            descriptions = json.loads(path.read_text(encoding="utf-8"))
        else:
            print(f"! no captions at {path} — the description arm will be empty")

    key = read_api_key()
    if not key:
        print("! no TYPESAFE_API_KEY — Jev cannot run")
        return 2

    critic = JevCritic(
        arm=args.arm,
        measurements=args.measurements,
        descriptions=descriptions,
        api_key=key,
    )

    members, bases = load_set(args.manifest, CACHE)
    payload = run_candidate(critic, members, bases, night=args.night)
    payload["arm"] = args.arm
    payload["measurements"] = args.measurements
    payload["has_descriptions"] = bool(descriptions)
    name = f"jev-{args.arm}-{'measurements' if args.measurements else 'description'}"
    write_result(payload, name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
