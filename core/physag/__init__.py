"""physag-lite: props that work, accepted by running their action.

The loop this package implements, per prop:

1. **Plan.** A cloud model writes a typed
   :class:`~core.physag.spec.InteractionSpec`: the parts, the joints, the
   action, and the physical priors. No language model runs on the Thor.
2. **Generate.** A mesh arrives from the TRELLIS.2 path on the Thor.
3. **Build.** The mesh is segmented into the spec's parts, each part is
   decomposed into convex pieces, and the pieces are written into an MJCF
   with the joints and a force-capped actuator.
4. **Check.** MuJoCo executes the action and scores it: completion against
   a relative band, stability against penetration, explosion and the rest
   baseline.
5. **Repair.** Once, at most: the check's measurements and a render go back
   to the planner, which returns a revised spec with the action and the
   joint limits frozen.
6. **Record.** A delivery record per prop says what was verified and what
   was estimated, and what the prop cost.

The Hy4 guards are the reason several of the modules look the way they
do; each one is explained at the top of the module that carries it.
"""

from __future__ import annotations

__all__ = [
    "check_prop",
    "decompose_part",
    "load_spec",
    "run_prop",
    "save_spec",
    "segment",
]

from core.physag.check import check_prop
from core.physag.decompose import decompose_part
from core.physag.pipeline import run_prop
from core.physag.segment import segment
from core.physag.spec import InteractionSpec, load_spec, save_spec
