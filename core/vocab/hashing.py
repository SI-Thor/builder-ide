"""Canonical JSON and content hashes.

Spec §1.0: *"Content hashes: sha256 over canonical JSON (sorted keys, no
whitespace, UTF-8), written `sha256:ab12…`."*

**The definitions live in :mod:`core.canon`** — one canonical form for the
whole tree, so a hash written by the API half is the same hash the
vocabulary computes. This file stays so ``from core.vocab.hashing import
canonical_json`` keeps working.
"""

from __future__ import annotations

from core.canon import (
    canonical_bytes,
    canonical_json,
    content_hash,
    short_hash,
)

__all__ = ["canonical_json", "canonical_bytes", "content_hash", "short_hash"]
