#!/usr/bin/env python3
"""How far does a plant move the picture, in embedding space?

The leave-one-**base**-out split exists because a member is its base render
with a defect planted in it: a probe that had seen the base render would be
scored on a picture it already knows. This measures how close those two
pictures are, in DINOv2's embedding space — the number that says how much a
leaky split would give away, and how much of the picture a plant really
changes.

It also answers a question the tables cannot: when the probe misses a class
entirely, is the defect simply **not there** in embedding space, or is it
there and the probe cannot see it?

    python docs/lab/critic-select-scripts/plant_leak.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness import CACHE, MANIFEST, load_set  # noqa: E402

from core.critic.candidates.dino import DinoFeatures  # noqa: E402
from core.critic.set import read_bases  # noqa: E402


def main() -> int:
    members, _ = load_set(MANIFEST, CACHE)
    bases = {b.id: b for b in read_bases(MANIFEST)}
    image_members = [m for m in members if m.layer == "image"]

    extractor = DinoFeatures(cache_dir=CACHE / "dino")
    rows = []
    for member in image_members:
        base = bases.get(member.base_id)
        if base is None:
            continue
        member_vector = extractor.encode(member.derived_path)
        base_vector = extractor.encode(base.image_path)
        similarity = float(
            np.dot(member_vector, base_vector)
            / (np.linalg.norm(member_vector) * np.linalg.norm(base_vector))
        )
        rows.append(
            {
                "member_id": member.member_id,
                "base_id": member.base_id,
                "defect": member.defect,
                "cosine_to_its_base_render": round(similarity, 5),
            }
        )
        print(
            f"  {member.member_id} {str(member.defect):18s} "
            f"cosine to its base render: {similarity:.4f}"
        )

    values = [r["cosine_to_its_base_render"] for r in rows]
    by_defect: dict[str, list[float]] = {}
    for row in rows:
        by_defect.setdefault(str(row["defect"]), []).append(
            row["cosine_to_its_base_render"]
        )
    print("\nby class (cosine to the base render the plant was made on):")
    for defect, group in sorted(by_defect.items()):
        print(
            f"  {defect:18s} n={len(group)} "
            f"min {min(group):.4f} median {float(np.median(group)):.4f} "
            f"max {max(group):.4f}"
        )

    out = Path(__file__).resolve().parent / "results" / "plant-leak.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps({"rows": rows, "by_defect": by_defect}, indent=1), encoding="utf-8"
    )
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
