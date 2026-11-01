"""The render, in its own process.

MuJoCo's offscreen renderer is the one part of the loop that can take the
whole run down: the EGL context on this box does not survive being torn
down and made again in the same process, and the next render *aborts* the
process rather than raising — an abort that takes the run with it, ten
props in.

So the render happens in a subprocess. The child loads the model, puts the
state back, renders, and writes the picture; the parent waits and carries
on whether the child succeeded or not. A render is a nicety for the
planner's repair round, and it is not worth a whole experiment's run.

Run it directly::

    python -m core.physag.render model.xml state.npz out.png
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# MuJoCo picks its GL backend when it is imported, so the choice has to
# be made before the import. The Thor has no display for GLFW; EGL is the
# backend that works here.
os.environ.setdefault("MUJOCO_GL", "egl")
os.environ.setdefault("MUJOCO_EGL_DEVICE_ID", "0")

import numpy as np  # noqa: E402


def render(
    model_path: str | Path,
    state_path: str | Path,
    out_path: str | Path,
    *,
    height: int = 480,
    width: int = 480,
    lookat: tuple[float, float, float] = (0.0, 0.0, 0.0),
    distance: float = 1.0,
    azimuth: float = 135.0,
    elevation: float = -18.0,
) -> Path:
    """Render one state of one model, and write it as a PNG."""
    import mujoco

    model = mujoco.MjModel.from_xml_path(str(model_path))
    data = mujoco.MjData(model)
    state = np.load(str(state_path))
    mujoco.mj_resetData(model, data)
    data.qpos[:] = state["qpos"]
    data.qvel[:] = state["qvel"]
    data.time = float(state["time"])
    mujoco.mj_forward(model, data)

    renderer = mujoco.Renderer(model, height, width)
    try:
        camera = mujoco.MjvCamera()
        mujoco.mjv_defaultCamera(camera)
        camera.lookat[:] = lookat
        camera.distance = distance
        camera.azimuth = azimuth
        camera.elevation = elevation
        renderer.update_scene(data, camera=camera)
        image = renderer.render()
    finally:
        try:
            renderer.close()
        except Exception:  # pragma: no cover - the context's teardown
            pass

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        from PIL import Image

        Image.fromarray(image).save(out_path)
    except Exception:  # pragma: no cover - a PNG is a nicety, not the result
        out_path.with_suffix(".raw").write_bytes(image.tobytes())
    return out_path


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) < 3:
        print("usage: python -m core.physag.render model.xml state.npz out.png", file=sys.stderr)
        return 2
    model_path, state_path, out_path = argv[:3]
    lookat = (0.0, 0.0, 0.0)
    distance = 1.0
    if len(argv) >= 7:
        lookat = tuple(float(v) for v in argv[3:6])  # type: ignore[assignment]
        distance = float(argv[6])
    render(model_path, state_path, out_path, lookat=lookat, distance=distance)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
