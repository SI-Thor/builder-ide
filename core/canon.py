"""Canonical serialization, hashing, timestamps and ids (core-spec §1.0).

Content hashes are sha256 over canonical JSON — sorted keys, no whitespace,
UTF-8 — written ``sha256:ab12…``. Timestamps are RFC 3339 UTC. Ids are
prefixed short strings.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timezone

ID_PREFIXES = {
    "recipe": "rcp_",
    "version": "ver_",
    "branch": "br_",
    "edit": "ed_",
    "work_order": "wo_",
    "packet": "pkt_",
    "asset": "ast_",
    "prediction": "pr_",
    "taste_note": "tn_",
    "audit": "aud_",
    "night": "night_",
    "task": "task_",
    "job": "job_",
    "attempt": "att_",
    "question": "q_",
}


def canonical_json(obj: object) -> str:
    """Canonical JSON text: sorted keys, no whitespace, UTF-8 friendly."""
    return json_dumps_sorted(obj)


def json_dumps_sorted(obj: object) -> str:
    import json

    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def canonical_bytes(obj: object) -> bytes:
    return canonical_json(obj).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def content_hash(obj: object) -> str:
    """sha256 over canonical JSON, written ``sha256:…`` (spec §1.0)."""
    return f"sha256:{sha256_hex(canonical_bytes(obj))}"


def bytes_hash(data: bytes) -> str:
    return f"sha256:{sha256_hex(data)}"


def now_utc() -> str:
    """RFC 3339 UTC with millisecond precision (ordering matters mid-second)."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def new_id(kind: str) -> str:
    prefix = ID_PREFIXES[kind]
    return f"{prefix}{secrets.token_hex(6)}"


def night_id(at: str | None = None, taken: frozenset[str] = frozenset()) -> str:
    """night_YYYY-MM-DD, suffixed -2, -3… when a second night starts same day."""
    stamp = (at or now_utc())[:10]
    base = f"night_{stamp}"
    if base not in taken:
        return base
    n = 2
    while f"{base}-{n}" in taken:
        n += 1
    return f"{base}-{n}"
