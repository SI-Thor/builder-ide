"""The stage cache on disk — a hit skips the stage; eviction is by size.

The keys are §1.9's, computed by the one home for that arithmetic
(`core.recipe.stagecache`); this module is the store. What is tested here
is what ``DIRTY.md`` §§2, 4, 5 promise: byte-verified hits, LRU eviction
under a byte budget that never takes the just-written entry, refused
re-puts of different bytes under a live key, healed corrupt entries, and
the counters the nightly hit rate is reported from.
"""

from __future__ import annotations

import pytest

from core.engine.stagecache import StageCache


def key(char: str) -> str:
    return "sha256:" + char * 64


def test_a_put_then_get_roundtrips_and_counts(tmp_path):
    cache = StageCache(tmp_path)
    cache.put(key("a"), b"stage-a", mechanism="fake", request_key=key("r"))
    hit = cache.get(key("a"))
    assert hit is not None and hit.data == b"stage-a"
    assert hit.mechanism == "fake" and hit.request_key == key("r")
    assert cache.stats()["hits"] == 1


def test_a_miss_is_counted_and_returns_none(tmp_path):
    cache = StageCache(tmp_path)
    assert cache.get(key("a")) is None
    assert cache.stats() == {
        "hits": 0, "misses": 1, "hit_rate": 0.0, "evictions": 0,
        "entries": 0, "bytes": 0, "max_bytes": cache.max_bytes,
    }


def test_the_cache_survives_reopen(tmp_path):
    cache = StageCache(tmp_path)
    cache.put(key("a"), b"stage-a")
    reopened = StageCache(tmp_path)
    assert key("a") in reopened
    assert reopened.total_bytes() == 7
    assert reopened.get(key("a")).data == b"stage-a"


def test_a_corrupted_entry_is_an_integrity_error_never_a_serve(tmp_path):
    cache = StageCache(tmp_path)
    cache.put(key("a"), b"stage-a")
    path = tmp_path / "stages" / key("a").split(":")[1][:2] / key("a").split(":")[1] / "stage.bin"
    path.write_bytes(b"stage-X")
    with pytest.raises(Exception, match="byte-identical"):
        StageCache(tmp_path).get(key("a"))


def test_re_putting_different_bytes_under_a_live_key_is_refused(tmp_path):
    """The same key must mean the same bytes forever (contract rule 3):
    an engine that offers different bytes for one key is a determinism
    break, and the cache says so instead of quietly overwriting."""
    from core.recipe.errors import IntegrityError

    cache = StageCache(tmp_path)
    cache.put(key("a"), b"stage-a")
    with pytest.raises(IntegrityError, match="same key"):
        cache.put(key("a"), b"stage-b")


def test_re_putting_over_a_corrupt_entry_heals_it(tmp_path):
    cache = StageCache(tmp_path)
    cache.put(key("a"), b"stage-a")
    path = tmp_path / "stages" / key("a").split(":")[1][:2] / key("a").split(":")[1]
    (path / "stage.bin").write_bytes(b"torn")
    cache.put(key("a"), b"stage-a")  # same bytes, healing a corrupt store
    assert StageCache(tmp_path).get(key("a")).data == b"stage-a"


def test_eviction_enforces_the_budget_lru_first_and_keeps_the_new_entry(tmp_path):
    cache = StageCache(tmp_path, max_bytes=30)
    cache.put(key("a"), b"a" * 10)   # 10
    cache.put(key("b"), b"b" * 10)   # 20
    cache.get(key("a"))              # a is now more recently used than b
    cache.put(key("c"), b"c" * 10)   # 30 — at the budget
    assert len(cache) == 3
    cache.put(key("d"), b"d" * 10)   # 40 — over: evict b (LRU), not d
    assert key("b") not in cache
    assert key("d") in cache and key("a") in cache
    assert cache.total_bytes() == 30
    assert cache.stats()["evictions"] == 1


def test_eviction_never_empties_a_single_oversized_entry(tmp_path):
    cache = StageCache(tmp_path, max_bytes=5)
    cache.put(key("a"), b"a" * 100)
    assert key("a") in cache  # the one entry stays; the budget is a policy,
    assert cache.stats()["evictions"] == 0  # not a way to lose the work


def test_the_hit_rate_is_a_denominator_not_a_percentage_feeling(tmp_path):
    cache = StageCache(tmp_path)
    cache.put(key("a"), b"stage-a")
    cache.get(key("a"))
    cache.get(key("b"))
    assert cache.stats()["hits"] == 1 and cache.stats()["misses"] == 1
    cache.reset_stats()
    assert cache.stats()["hit_rate"] is None  # 0 of 0, said honestly


def test_peek_reads_without_counting(tmp_path):
    cache = StageCache(tmp_path)
    cache.put(key("a"), b"stage-a")
    assert cache.peek(key("a")).data == b"stage-a"
    assert cache.peek(key("b")) is None
    assert cache.stats()["hits"] == 0 and cache.stats()["misses"] == 0
