"""Canonical JSON and content hashing — core-spec v2 §1.0.

**The definitions live in :mod:`core.canon`** — one canonical form for the
whole tree. The recipe half grew its own copy of these helpers while it was
a separate branch; it agreed byte-for-byte with the API half's, and now it
is the same module. This file stays so ``from core.recipe.canonical import
canonical_json`` keeps working.
"""

from __future__ import annotations

from core.canon import (
    bytes_hash,
    canonical_bytes,
    canonical_json,
    content_hash,
    hash_bytes,
    is_content_hash,
)

__all__ = [
    "canonical_json",
    "canonical_bytes",
    "hash_bytes",
    "bytes_hash",
    "content_hash",
    "is_content_hash",
]
