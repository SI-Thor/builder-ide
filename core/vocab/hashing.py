"""Canonical JSON and content hashes.

Spec §1.0: *"Content hashes: sha256 over canonical JSON (sorted keys, no
whitespace, UTF-8), written `sha256:ab12…`."*

Everything the project seals, hashes or compares goes through here, so the
canonical form is defined in exactly one place.
"""

from __future__ import annotations

import hashlib
from typing import Any

__all__ = ["canonical_json", "canonical_bytes", "content_hash", "short_hash"]


def canonical_json(value: Any) -> str:
    """Return the canonical JSON text of `value`.

    Sorted keys, no whitespace, UTF-8 (not \\u-escaped). `None` is `null`,
    floats keep their shortest round-trip repr (Python's default `repr`).
    """
    return _canonical(value, sort_keys=True)


def canonical_bytes(value: Any) -> bytes:
    """The UTF-8 bytes of `canonical_json` — what a hash is taken over."""
    return canonical_json(value).encode("utf-8")


def content_hash(value: Any) -> str:
    """`sha256:<hex>` over the canonical JSON of `value` (spec §1.0)."""
    return "sha256:" + hashlib.sha256(canonical_bytes(value)).hexdigest()


def short_hash(value: Any, length: int = 12) -> str:
    """A short, deterministic id fragment derived from `value`.

    Ids in this project are content-derived wherever the record is immutable
    (a sealed prediction, a recipe version), so a rebuild of the same night
    produces the same ids.
    """
    return hashlib.sha256(canonical_bytes(value)).hexdigest()[:length]


def _canonical(value: Any, *, sort_keys: bool) -> str:
    import json

    return json.dumps(
        value,
        sort_keys=sort_keys,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
