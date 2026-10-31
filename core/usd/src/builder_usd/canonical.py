"""Canonical values and hashing — the determinism floor of the USD backbone.

Everything the compiler writes into USD goes through here first, so that the
same recipe always produces the same bytes:

* **floats are quantised** to :data:`FLOAT_DECIMALS` decimals and ``-0.0`` is
  folded to ``0.0``. USD prints doubles with the shortest round-trip
  representation, so an unquantised ``0.1 + 0.2`` lands in the file as
  ``0.30000000000000004``. Quantising at authoring time is what makes the
  emitted text stable *and* reviewable.
* **dictionaries are written with sorted keys**, matching the way USD's own
  ``customData`` writer sorts them.
* **the canonical JSON** is the one the whole tree shares — it delegates
  to ``core.canon`` (sorted keys, no whitespace, UTF-8, no NaN), so a hash
  computed here equals the hash the recipe store committed for the same
  document (asserted in tests/usd/test_seam.py).
"""

from __future__ import annotations

import json
from typing import Any

__all__ = [
    "FLOAT_DECIMALS",
    "canonical_value",
    "canonical_json",
    "canonical_bytes",
    "content_hash",
    "hash_bytes",
    "quantize_float",
]

#: How many decimals a float is quantised to before it is authored.
#:
#: Six decimals of a metre is a micrometre — finer than any geometry the
#: world engine will care about, and coarse enough that the same value always
#: prints the same way.
FLOAT_DECIMALS = 6


def quantize_float(value: float) -> float:
    """Round ``value`` to :data:`FLOAT_DECIMALS` decimals, ``-0.0`` folded."""
    quantized = round(float(value), FLOAT_DECIMALS)
    return 0.0 if quantized == 0 else quantized


def canonical_value(value: Any) -> Any:
    """Return ``value`` with floats quantised and dictionaries key-sorted."""
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return quantize_float(value)
    if isinstance(value, (list, tuple)):
        return [canonical_value(item) for item in value]
    if isinstance(value, dict):
        return {
            str(key): canonical_value(value[key]) for key in sorted(value, key=str)
        }
    raise TypeError(f"cannot canonicalise {type(value).__name__}")


def canonical_json(value: Any) -> str:
    """Serialize ``value`` canonically: sorted keys, no whitespace, UTF-8.

    The serializer is the tree's one canonical form (``core.canon``) — this
    package only quantises the floats first; the bytes that leave here are
    the bytes every other seat would produce for the same value.
    """
    from core.canon import canonical_json as _the_canonical_json

    return _the_canonical_json(canonical_value(value))


def canonical_bytes(value: Any) -> bytes:
    """The canonical UTF-8 bytes of ``value``."""
    return canonical_json(value).encode("utf-8")


def hash_bytes(data: bytes) -> str:
    """The content hash of raw bytes."""
    from core.canon import bytes_hash

    return bytes_hash(data)


def content_hash(value: Any) -> str:
    """The content hash of a JSON-serialisable value."""
    return hash_bytes(canonical_bytes(value))
