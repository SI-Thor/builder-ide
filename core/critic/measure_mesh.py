"""Measure the mesh half's baseline across the rebuilt scenes.

Prints, per scene, the facts the mesh checks will be built on:

* how many props there are and how many are watertight;
* the distribution of ``inward`` (the fraction of faces pointing inwards) —
  the number that separates a hollow shell from an open surface;
* the spread of prop sizes within a family — the number ``scale_bounds`` is
  measured against;
* how many props reach outside the frame — the number ``edge_cut`` is
  measured against.

Run:

    .venv/bin/python core/critic/measure_mesh.py <scene.blend> [...]
"""

from __future__ import annotations

import collections
import re
import sys

sys.path.insert(0, "/home/caseydigennaro/lm-wt/critic-calib")

from core.critic.mesh import probe_scene  # noqa: E402

#: The scene's infrastructure: the terrain, the sky, the liquid, the camera
#: rig. These are not *props* — they are the scene — and the mesh checks are
#: about props.
INFRA = ("Terrain", "atmosphere", "emitter", "liquid", "camrig")


def family(name: str) -> str:
    """The asset family a prop belongs to.

    ``BoulderFactory(490645449).spawn_placeholder(3)`` and ``Tree.281`` are
    each one family; the index at the end is not part of it.
    """
    base = name.split(".")[0]
    base = re.sub(r"\(\d+\)$", "", base)
    base = base.split("(")[0]
    return base


def is_prop(name: str) -> bool:
    return not any(key in name for key in INFRA)


def main(argv: list[str]) -> int:
    python = "/home/caseydigennaro/src/infinigen-thor/.venv/bin/python"
    for blend in argv:
        stats = probe_scene(blend, python=python)
        props = [o for o in stats.objects if o.faces > 0 and is_prop(o.name)]
        infra = [o for o in stats.objects if o.faces > 0 and not is_prop(o.name)]
        print(f"=== {blend}")
        print(f"  objects={len(stats.objects)} props={len(props)} infra={len(infra)}")

        inward = sorted(o.inward for o in props)
        print(
            "  inward: min={:.3f} p50={:.3f} p90={:.3f} max={:.3f} "
            "nonzero={}".format(
                inward[0],
                inward[len(inward) // 2],
                inward[int(len(inward) * 0.9)],
                inward[-1],
                sum(1 for v in inward if v > 0.0),
            )
        )
        wt = sum(1 for o in props if o.watertight)
        print(f"  watertight: {wt}/{len(props)}")

        fams: dict[str, list] = collections.defaultdict(list)
        for o in props:
            fams[family(o.name)].append(o)
        for fam, objs in sorted(fams.items()):
            diags = sorted(o.diagonal for o in objs)
            med = diags[len(diags) // 2] or 1.0
            ratios = [d / med for d in diags]
            ratios.sort()
            print(
                f"  {fam[:30]:32s} n={len(objs):3d} med={med:8.3f} "
                f"ratio p05={ratios[int(len(ratios) * 0.05)]:.2f} "
                f"p50={ratios[len(ratios) // 2]:.2f} "
                f"p95={ratios[int(len(ratios) * 0.95)]:.2f}"
            )

        # How many props reach outside the frame? The terrain always does;
        # the question is what the props do.
        camera = stats.camera
        if camera is not None:
            outside = 0
            for o in props:
                corners = [
                    (x, y, z)
                    for x in (o.x0, o.x1)
                    for y in (o.y0, o.y1)
                    for z in (o.z0, o.z1)
                ]
                for corner in corners:
                    right, up, forward = camera.projects(corner)
                    if forward <= 0:
                        continue
                    half_w = camera.half_width * forward / camera.depth
                    half_h = camera.half_height * forward / camera.depth
                    if abs(right) > half_w or abs(up) > half_h:
                        outside += 1
                        break
            print(f"  props outside the frame: {outside}/{len(props)}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
