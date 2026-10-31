"""Measure the image checks' baselines over the real sweep renders.

Every threshold in :mod:`core.critic.checks` must be set on a *measurement*,
not a guess, so this prints what the real renders actually measure: how many
isolated fireflies a clean frame has, how large the largest single-colour
region is, how far the frame's row and column profiles step, and so on.

Run:

    .venv/bin/python core/critic/measure_image.py <sweep-root>
"""

from __future__ import annotations

import statistics
import sys
from pathlib import Path

sys.path.insert(0, "/home/caseydigennaro/lm-wt/critic-calib")

from core.critic.checks import run_image_checks  # noqa: E402
from core.critic.harvest import harvest  # noqa: E402
from core.critic.imaging import load_rgb  # noqa: E402


def main(argv: list[str]) -> int:
    root = argv[0] if argv else None
    bases = harvest(root)
    print(f"bases: {len(bases)}\n")

    metrics: dict[str, list[float]] = {}

    def note(name: str, value: float) -> None:
        metrics.setdefault(name, []).append(value)

    for base in bases:
        image = load_rgb(base.image_path)
        for outcome in run_image_checks(image):
            for key, value in outcome.measured.items():
                note(f"{outcome.check}.{key}", value)
        print(f"  {base.id:16s} " + " ".join(
            f"{o.check}={'FIRE' if o.fired else '.'}" for o in run_image_checks(image)
        ))

    print("\n=== the clean frames' measurements ===")
    for name in sorted(metrics):
        values = sorted(metrics[name])
        print(
            f"  {name:28s} n={len(values):3d} min={values[0]:10.4f} "
            f"p50={values[len(values)//2]:10.4f} "
            f"p95={values[int(len(values)*0.95)]:10.4f} max={values[-1]:10.4f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
