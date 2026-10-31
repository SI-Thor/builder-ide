"""The store race: concurrent store-reading GETs over ONE SQLite connection.

The store serves every read door from a single shared ``sqlite3.Connection``
(``check_same_thread=False``), and FastAPI runs the sync endpoints on
anyio's threadpool — so two GETs landing in the same tick use the same
connection from two threads. pysqlite's statement cache and cursor state
are not safe under that: the calls collide and the door answers 500 with
``sqlite3.InterfaceError: bad parameter or other API misuse`` in
``core.store.count_events`` — about one run in three under the world-mcp
server's load (thor-world-repo, docs/design.md §8.5).

These tests reproduce it through the real ASGI app — the ``client``
fixture, the way every door is actually called — and hold after the fix:
reads either take the connection under the store's lock or ride their own
per-thread connection; either way two GETs in one tick cannot collide.

Reproduction aid: the words on the vocabulary make ``/v1/vocab`` call
``count_events`` once per word, so each GET issues many copies of the same
SQL — exactly the statement-cache collision that produced the 500s.
"""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

from core.events import core_actor
from core.svc.vocab import VocabService

from tests.conftest import PANEL

WORDS = [f"props.stress.{i:02d}" for i in range(8)]

READ_DOORS = ["/v1/vocab", "/v1/slate", "/v1/branches", "/v1/budget", "/healthz"]


def _seed_words(core) -> None:
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {"count": {"type": "integer", "minimum": 1, "maximum": 48}},
    }
    for word in WORDS:
        VocabService(core).add_word(
            {"word": word, "kind": "prop", "owner_character": "",
             "params": schema}, core_actor())


def _hammer(client, workers: int, per_worker: int) -> list[int]:
    """Concurrent GETs through the real ASGI app, as two requests land in
    one tick. Returns every status the doors answered with."""
    statuses: list[int] = []
    guard = threading.Lock()
    start = threading.Barrier(workers)

    def worker(n: int) -> None:
        local: list[int] = []
        start.wait()  # release the workers together: the same-tick collision
        for i in range(per_worker):
            door = READ_DOORS[(n + i) % len(READ_DOORS)]
            local.append(client.get(door, headers=PANEL).status_code)
        with guard:
            statuses.extend(local)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for n in range(workers):
            pool.submit(worker, n)
    return statuses


def test_concurrent_gets_never_collide_on_the_store_connection(core, client):
    """Two GETs in one tick must both answer 200 — never a 500 from a
    shared sqlite3 connection (§1.0's store serves the doors; it does not
    make them race)."""
    _seed_words(core)
    statuses = _hammer(client, workers=12, per_worker=12)
    bad = [s for s in statuses if s != 200]
    assert bad == [], (
        f"{len(bad)} of {len(statuses)} concurrent GETs failed: {sorted(set(bad))}"
    )


def test_concurrent_reads_and_writes_keep_the_log_gapless(core, client):
    """While reads race, the one writer still commits: every append inside
    the storm lands, the seq stays gapless (§1.8), and every read the
    storm produced answered 200."""
    _seed_words(core)

    def write(n: int) -> None:
        VocabService(core).call("prop-maker", WORDS[n % len(WORDS)], {"count": n + 1})

    with ThreadPoolExecutor(max_workers=8) as pool:
        writes = [pool.submit(write, n) for n in range(24)]
        reads = [pool.submit(client.get, door, headers=PANEL) for door in READ_DOORS * 6]
        for f in writes:
            f.result()  # a failed append raises here
    statuses = [f.result().status_code for f in reads]
    assert all(s == 200 for s in statuses), f"reads failed during writes: {statuses}"
    seqs = [e.seq for e in core.store.events_since(0)]
    assert seqs == list(range(1, len(seqs) + 1))
