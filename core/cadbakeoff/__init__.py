"""cad-bakeoff: SolidCraft against build123d on the ten physag-lite props.

The package holds the experiment: the frozen prop specs, the shared prompt, the
two front-end validators, the build drivers, the analytic ground truth, the
URDF generator and the MuJoCo action checker.

See ``README.md`` in this directory and ``docs/lab/exp-cad-bakeoff.md`` in the
repository root for what was measured and what it means.
"""

from __future__ import annotations

__all__ = ["specs", "analytic"]
