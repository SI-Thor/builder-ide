"""The Prop-maker's generative batch: a night of props, made not modelled.

This seat takes a prop request ("a weathered crate, about a metre across"),
generates it — concept prompt to image to mesh, through the TRELLIS.2
service on the Thor — and records what it made: the asset, where it came
from, what licence it carries, and whether it is any good.

The package is deliberately in three layers, so the two-thirds of it that
never touches the GPU can be tested without one:

* **the mesh layer** (:mod:`core.genbatch.glb`, :mod:`core.genbatch.mesh`)
  reads a GLB and measures it — watertightness, triangles, bounding box,
  volume, area, centre of mass;
* **the judgement layer** (:mod:`core.genbatch.critic`,
  :mod:`core.genbatch.assets`) turns those measurements into a score and an
  :class:`core.models.Asset` with its provenance and licence row;
* **the service layer** (:mod:`core.genbatch.comfy`,
  :mod:`core.genbatch.workflow`, :mod:`core.genbatch.executor`,
  :mod:`core.genbatch.night`) drives ComfyUI and the core's night runner.
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "0.1.0"
