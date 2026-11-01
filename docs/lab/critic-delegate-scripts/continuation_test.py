#!/usr/bin/env python3
"""The continuation test: does applying the suggested edit clear the flag?

The critic's continuation is a typed edit (``lower_object``): the support
surface below the thing that is floating, and the distance to drop it. This
script takes every member where the hybrid flagged ``floating_object``,
applies the edit the verdict carries, and measures what happened:

* the **named thing's** open space before and after (the scripted check's own
  measurement, on that thing);
* the scripted checks' verdict on the edited frame;
* the **delegate's** answer on the edited frame — because in the hybrid the
  delegate is the judge of this class, so the flag is the delegate's to
  clear;
* whether the flag cleared.

    python docs/lab/critic-delegate-scripts/continuation_test.py --delegate d1
    python docs/lab/critic-delegate-scripts/continuation_test.py --delegate clef

The edited frames are written next to the results, so the pictures can be
looked at as well as measured.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import replace
from pathlib import Path

HERE = Path(__file__).resolve().parent
SELECT = HERE.parent / "critic-select-scripts"
for path in (str(HERE), str(SELECT)):
    if path not in sys.path:
        sys.path.insert(0, path)

from harness import CACHE, MANIFEST, load_set  # noqa: E402

from core.critic.checks import run_image_checks  # noqa: E402
from core.critic.edits import apply_edit  # noqa: E402
from core.critic.imaging import load_rgb, save_rgb  # noqa: E402
from core.critic.select import resolve_critic  # noqa: E402
from core.critic.surface import suggest_edit  # noqa: E402

RESULTS = HERE / "results"


def _floating_gap(image) -> float:
    """The scripted check's measured gap under the thing it fires on."""
    for outcome in run_image_checks(image):
        if outcome.check == "floating_blob":
            return float(outcome.measured.get("gap", 0.0))
    return 0.0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--delegate", default="d1")
    parser.add_argument("--manifest", default=str(MANIFEST))
    args = parser.parse_args()

    members, bases = load_set(args.manifest, CACHE)
    critic, reason = resolve_critic("hybrid", delegate=args.delegate)
    if reason:
        print(f"! {reason} — the scripted critic answered")
    hybrid = getattr(critic, "critic", critic)
    print(f"the hybrid's delegate: {hybrid.delegate.name}")

    RESULTS.mkdir(parents=True, exist_ok=True)
    rows = []
    for member in members:
        if member.layer not in critic.layers or not member.derived_path:
            continue
        verdict = critic.score(member, bases=bases)
        outcome = verdict.outcome("floating_blob")
        if outcome is None or not outcome.fired:
            continue

        image = load_rgb(member.derived_path)
        edit = verdict.edits[0] if verdict.edits else suggest_edit(image)
        if edit is None:
            rows.append(
                {
                    "member_id": member.member_id,
                    "base_id": member.base_id,
                    "flagged": True,
                    "edit": None,
                    "cleared": False,
                    "note": "the verdict carried no continuation",
                }
            )
            continue

        edited = apply_edit(image, edit)
        edited_path = RESULTS / f"{member.member_id}-edited.png"
        save_rgb(edited_path, edited)

        edited_member = replace(member, derived_path=str(edited_path))
        after = critic.score(edited_member, bases=bases)
        after_outcome = after.outcome("floating_blob")

        before_checks = run_image_checks(image)
        after_checks = run_image_checks(edited)
        gap_before = next(
            (c.measured.get("gap", 0.0) for c in before_checks if c.check == "floating_blob"),
            0.0,
        )
        gap_after = next(
            (c.measured.get("gap", 0.0) for c in after_checks if c.check == "floating_blob"),
            0.0,
        )

        rows.append(
            {
                "member_id": member.member_id,
                "base_id": member.base_id,
                "defect": member.defect,
                "flagged": True,
                "edit": edit.as_dict(),
                "edited_path": str(edited_path),
                "checks_gap_before": gap_before,
                "checks_gap_after": gap_after,
                "checks_fired_after": [
                    c.check for c in after_checks if c.fired
                ],
                "delegate_after": (
                    after_outcome.measured.get("d1_probability")
                    if after_outcome
                    else None
                ),
                "delegate_after_detail": after_outcome.detail if after_outcome else None,
                "cleared": bool(after_outcome and not after_outcome.fired),
            }
        )
        print(
            f"  {member.member_id} {member.defect}: "
            f"edit drop={edit.drop_px} px onto {edit.support.kind} "
            f"(row {edit.support.row}) -> "
            f"checks gap {gap_before:.4f} -> {gap_after:.4f}, "
            f"flag cleared: {rows[-1]['cleared']}"
        )

    payload = {
        "delegate": args.delegate,
        "fallback_reason": reason,
        "rows": rows,
        "cleared": sum(1 for r in rows if r["cleared"]),
        "total": len(rows),
    }
    out = RESULTS / f"continuation-{args.delegate}.json"
    out.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    print(f"\ncleared {payload['cleared']} of {payload['total']} flagged members")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
