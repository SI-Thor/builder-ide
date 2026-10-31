"""What the resident process must be able to do — the scene half of the seam.

The recipe is ours; the scene is the engine's (the contract's rule 5: the
lower layer belongs to the engine). This module is the interface between the
two, and it is deliberately tiny:

* the resident holds the **recipe document** (ours) and applies the ops to
  it with :func:`core.engine.resident.protocol.apply_ops` — the same
  semantics the core uses, checked against it by digest on every sync;
* the backend holds the **scene** (theirs) and updates it *in place* when
  the document moves — that is the whole point of a resident: the scene is
  mutated, not rebuilt from a file.

A backend is written against this protocol, never against Blender directly,
so the same adapter drives the deterministic fake (the tests) and the real
engine (the opt-in test). Both are import-free of ``core``: the resident may
run under the engine's own interpreter.
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

__all__ = ["SceneBackend"]


@runtime_checkable
class SceneBackend(Protocol):
    """The scene operations a resident process provides."""

    def describe(self) -> dict:
        """What this backend is: ``pin``, ``capabilities`` and ``source``.

        The pin is checked by the adapter against the recipe's own pin — the
        same check every other flavour makes (contract rule 2).
        """

    def on_document(self, document: dict, touched: list[str]) -> None:
        """The recipe document moved; bring the scene along, in place.

        ``touched`` names the entries the ops reached — the dirty set. A
        backend that can regenerate only what changed should do exactly
        that; one that cannot may rebuild, but it must say so in its
        ``stats``.
        """

    def state(self) -> dict:
        """The scene's state, JSON-able.

        The digest is computed by the **core** from this document, so the
        arithmetic has one home — and the digest is only taken at
        checkpoints, because it is O(scene size) and a resident must not pay
        that on every keystroke (WS §5.4).
        """

    def stage(self, *, stage: str, dep_keys: list[str], version_hash: str) -> bytes:
        """One stage's output bytes, evaluated against the resident scene."""

    def preview(self, *, subject: str, rung: int, resolution: str, seed: int) -> bytes:
        """A preview rendered from the resident scene."""

    def export(self, *, format: str, profile: str) -> bytes:
        """A compiled output. A backend that cannot export refuses loudly."""

    def stats(self) -> dict:
        """The backend's own counters — objects, materials, what it applied."""
