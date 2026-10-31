"""Canonical JSON and content hashing — core-spec v2 §1.0.

The store of record hashes canonical JSON: sorted keys, no whitespace, UTF-8.
Every hash in the system is written ``sha256:<64 hex>``.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

__all__ = [
    "canonical_json",
    "canonical_bytes",
    "hash_bytes",
    "content_hash",
    "is_content_hash",
]


def canonical_json(value: Any) -> str:
    """Serialize ``value`` canonically: sorted keys, no whitespace, UTF-8."""
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def canonical_bytes(value: Any) -> bytes:
    return canonical_json(value).encode("utf-8")


def hash_bytes(data: bytes) -> str:
    """The content hash of raw bytes."""
    return "sha256:" + hashlib.sha256(data).hexdigest()


def content_hash(value: Any) -> str:
    """The content hash of a JSON-serialisable value."""
    return hash_bytes(canonical_bytes(value))


def is_content_hash(value: str) -> bool:
    return (
        isinstance(value, str)
        and value.startswith("sha256:")
        and len(value) == len("sha256:") + 64
        and all(c in "0123456789abcdef" for c in value[len("sha256:") :])
    )
