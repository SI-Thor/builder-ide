"""builder-ide's USD backbone — recipe → layered USD, deterministically.

The spike this package is (plan Week 2 item 8, rev-tech spike 3): the
compiled scene format of the whole project. res-cad §10 puts it first for a
reason — *nothing else lands without provenance and licence fields*.

What is here:

* :mod:`builder_usd.recipe_source` — the seam onto the recipe store
  (``core.recipe``, merged: the adapter reads committed versions).
* :mod:`builder_usd.vocabulary` — the closed, typed vocabulary the compiler
  reads; unknown parameters are refused at the door.
* :mod:`builder_usd.cad` — build123d parts as code: STEP (master), GLB
  (interchange) and a USD asset layer, all pure CPU.
* :mod:`builder_usd.compile` — the compiler: one layer per concern, provenance
  in ``customData``, sorted prims, no timestamps.
* :mod:`builder_usd.verify` — reading it back, and comparing two emissions.
* :mod:`builder_usd.probe` — the evidence that none of it touches the GPU.
"""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = ["__version__"]
