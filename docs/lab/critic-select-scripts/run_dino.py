#!/usr/bin/env python3
"""Run the DINOv2 probe over the reference set, in its splits and heads.

    python docs/lab/critic-select-scripts/run_dino.py --head knn --split base
    python docs/lab/critic-select-scripts/run_dino.py --head linear --split member

The split is the point of this candidate:

* ``base`` — leave-one-**base**-out. The scored member and every member made
  from the same base render are out of the training set. This is the honest
  protocol: each base contributes one defective member *and* one clean
  control, so a member-level split leaves the clean control of the same base
  in the training set and the probe is scored on a picture it has already
  seen a near-copy of.
* ``member`` — leave-one-member-out. Kept so the leak can be **measured**
  rather than argued about.

The features are cached under ``core/critic/.cache/dino`` so a second run
pays only for the heads, not the forward pass.

Needs the torch venv (``python3 -m venv .venv-torch && .venv-torch/bin/pip
install torch transformers pillow numpy``) — the core itself never needs
torch.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness import CACHE, MANIFEST, load_set, run_candidate, write_result  # noqa: E402

from core.critic.candidates.dino import DinoFeatures, DinoProbeCritic  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--head", choices=("knn", "linear"), default="knn")
    parser.add_argument("--split", choices=("base", "member"), default="base")
    parser.add_argument("--manifest", default=str(MANIFEST))
    parser.add_argument("--night", default=None)
    args = parser.parse_args()

    members, bases = load_set(args.manifest, CACHE)
    image_members = [m for m in members if m.layer == "image"]

    extractor = DinoFeatures(cache_dir=CACHE / "dino")
    features = {}
    started = time.perf_counter()
    for member in image_members:
        features[member.member_id] = extractor.encode(member.derived_path)
    feature_seconds = time.perf_counter() - started
    print(
        f"features: {len(features)} pictures in {feature_seconds:.1f} s "
        f"({feature_seconds / max(1, len(features)) * 1000:.0f} ms each)"
    )

    critic = DinoProbeCritic(
        members=image_members,
        features=features,
        extractor=extractor,
        head=args.head,
        split=args.split,
        cache_dir=CACHE / "dino",
    )
    payload = run_candidate(critic, members, bases, night=args.night)
    payload["head"] = args.head
    payload["split"] = args.split
    payload["feature_seconds_total"] = round(feature_seconds, 3)
    write_result(payload, f"dino-{args.head}-{args.split}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
