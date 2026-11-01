#!/usr/bin/env python3
"""Check that Jev's description arm works end to end — one member, one call.

The description arms are the ones the brief asks for, and they are the arms
that were never run (the previous run stopped at the provider quota). This
checks the path with a single call before the whole arm is run: the
description reaches Jev, the answer comes back, and the verdict is built.

    python docs/lab/critic-select-scripts/check_jev_description.py

Prints what Jev said and the verdict's per-class answers. Never prints the
key.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness import CACHE, MANIFEST, load_set  # noqa: E402

from core.critic.candidates.jev import JevCritic, read_api_key  # noqa: E402

DESCRIPTION = (
    "A wide outdoor scene of a snowy forest clearing at dusk, with dark "
    "evergreen trees along the horizon and a pale blue-grey sky."
)


def main() -> int:
    key = read_api_key()
    if not key:
        print("! no TYPESAFE_API_KEY")
        return 2
    members, bases = load_set(MANIFEST, CACHE)
    image_members = [m for m in members if m.layer == "image"]
    if not image_members:
        print("! no image members")
        return 2
    member = image_members[0]
    print(f"member {member.member_id} (defect {member.defect})")

    for arm in ("verify", "classify"):
        critic = JevCritic(
            arm=arm,
            measurements=True,
            descriptions={member.member_id: DESCRIPTION},
            api_key=key,
        )
        verdict = critic.score(member, bases=bases, cache_dir=CACHE)
        print(f"\n{arm}: label={verdict.label} degraded={verdict.degraded}")
        for outcome in verdict.checks:
            print(f"  {outcome.check:14s} fired={outcome.fired}  {outcome.detail[:96]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
