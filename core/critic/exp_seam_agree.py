"""Experiment: the swap plant's edge score against the check's reading.

The plant scores a donor by the **worst** of its four edges' distance from
the host, and records that number in the recipe. The check measures the
**weakest** of a block's four sides. They should agree — the check reads
the same step the plant looked for — and the measurement says they do not,
so this script prints them side by side for every base.

Run:

    .venv/bin/python core/critic/exp_seam_agree.py
"""

from __future__ import annotations

import sys

sys.path.insert(0, "/home/caseydigennaro/lm-wt/critic-calib")

from core.critic import defects  # noqa: E402
from core.critic.checks import DEFAULT_THRESHOLDS, _check_patch_seam  # noqa: E402
from core.critic.harvest import harvest  # noqa: E402
from core.critic.imaging import load_rgb  # noqa: E402


def main() -> int:
    bases = harvest()
    print(f"bases: {len(bases)}\n")
    images = [load_rgb(b.image_path) for b in bases]
    for index, (base, image) in enumerate(zip(bases, images)):
        donor = images[(index + 1) % len(images)]
        plan_ = defects.plan("texture_swap", base_id=base.id, seed=902, donor_id="d")
        broken, recipe = defects.apply(image, plan_, donor_image=donor)
        outcome = _check_patch_seam(broken, DEFAULT_THRESHOLDS)
        print(
            f"  {base.id:12s} block={recipe['bbox']} "
            f"plant_edge={recipe['edge_distance']:.3f} "
            f"check_seam={outcome.measured['seam_strength']:.3f} "
            f":: {outcome.detail}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
