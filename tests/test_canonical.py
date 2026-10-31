"""Canonical JSON and content hashing (core-spec v2 §1.0)."""

from __future__ import annotations

import re

from builder_recipe.canonical import canonical_json, content_hash, hash_bytes


def test_canonical_json_sorts_keys_and_strips_whitespace():
    assert canonical_json({"b": 1, "a": {"d": 2, "c": 3}}) == '{"a":{"c":3,"d":2},"b":1}'


def test_canonical_json_is_stable_across_dict_ordering():
    left = {"name": "Fjellvik", "seeds": {"weather": 3, "terrain": 1}}
    right = {"seeds": {"terrain": 1, "weather": 3}, "name": "Fjellvik"}
    assert canonical_json(left) == canonical_json(right)


def test_canonical_json_keeps_unicode_as_utf8():
    assert canonical_json({"n": "fjellvik-hytta"}) == '{"n":"fjellvik-hytta"}'


def test_content_hash_is_a_sha256_digest_with_prefix():
    digest = content_hash({"a": 1})
    assert digest.startswith("sha256:")
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", digest)


def test_content_hash_changes_with_content():
    assert content_hash({"a": 1}) != content_hash({"a": 2})


def test_content_hash_matches_the_sha256_of_the_canonical_bytes():
    import hashlib

    payload = {"a": 1, "b": [1, 2, 3]}
    expected = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
    assert content_hash(payload) == f"sha256:{expected}"


def test_hash_bytes_verifies_raw_bytes():
    digest = hash_bytes(b"fjellvik")
    assert digest.startswith("sha256:")
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", digest)
