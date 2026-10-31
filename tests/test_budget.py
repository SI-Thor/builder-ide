"""The branch-flip budget, measured on this box.

core-spec v2 §4.1: *branch flip ≤ 2 s* ``[b]`` and *apply ≤ 10 s* ``[b]``.
The budgets are marked ``[b]`` — a test can check them — so this file checks
them, and prints the measured number with the state of the box beside it.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from core.recipe.blobs import FileBlobStore
from core.recipe.ledger import InMemoryLedger, SQLiteLedger
from core.recipe.models import Actor, Op, Recipe
from core.recipe.store import RecipeStore

#: §4.1 — branch flip ≤ 2 s, apply ≤ 10 s.
BRANCH_FLIP_BUDGET_S = 2.0
APPLY_BUDGET_S = 10.0


def _box_state() -> str:
    """The state of the box beside the number (CLAUDE.md)."""
    cores = os.cpu_count()
    memory = ""
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemTotal"):
                memory = line.split(":", 1)[1].strip()
                break
    except OSError:
        pass
    model = ""
    try:
        for line in Path("/proc/device-tree/model").read_bytes().splitlines():
            model = line.decode("utf-8", "replace").strip("\x00")
            break
    except OSError:
        pass
    return f"{model or 'unknown board'}, {cores} cores, MemTotal {memory or 'unknown'}"


def _store(ledger, tmp_path: Path, schemas) -> RecipeStore:
    return RecipeStore(
        ledger=ledger,
        blobs=FileBlobStore(tmp_path / "home"),
        schemas=schemas,
    )


def _prepare(store: RecipeStore, fjellvik: Recipe, actor: Actor):
    store.create_recipe(fjellvik, actor)
    branch = store.create_branch(
        name="option-a",
        recipe="rcp_fjellvik",
        head="ver_0001",
        purpose="morning-option",
        actor=actor,
    )
    store.apply_edit(
        "ver_0001",
        [Op(op="set", path="harbor.crates.params.count", value=20)],
        author=actor,
        message="more crates",
        branch=branch.id,
    )
    return branch


def test_the_morning_branch_flip_is_cheap(
    tmp_path, schemas, fjellvik: Recipe, actor: Actor
):
    """The pointer move the morning does, timed against the 2 s budget."""
    ledger = SQLiteLedger(tmp_path / "core.db")
    store = _store(ledger, tmp_path, schemas)
    branch = _prepare(store, fjellvik, actor)

    start = time.perf_counter()
    store.apply_branch(branch.id, actor=actor)
    elapsed = time.perf_counter() - start

    print(
        f"\nbranch flip (SQLite ledger, synchronous=FULL): "
        f"{elapsed * 1000:.2f} ms · budget {BRANCH_FLIP_BUDGET_S:.0f} s · "
        f"box: {_box_state()}"
    )
    assert elapsed < BRANCH_FLIP_BUDGET_S


def test_the_flip_is_cheap_with_an_in_memory_ledger(
    tmp_path, schemas, fjellvik: Recipe, actor: Actor
):
    ledger = InMemoryLedger()
    store = _store(ledger, tmp_path, schemas)
    branch = _prepare(store, fjellvik, actor)

    start = time.perf_counter()
    store.apply_branch(branch.id, actor=actor)
    elapsed = time.perf_counter() - start

    print(
        f"\nbranch flip (in-memory ledger): {elapsed * 1000:.2f} ms · "
        f"box: {_box_state()}"
    )
    assert elapsed < BRANCH_FLIP_BUDGET_S


def test_the_whole_apply_flow_is_inside_its_ten_second_budget(
    tmp_path, schemas, fjellvik: Recipe, actor: Actor
):
    """Apply = the flip plus the scoring the owner's apply triggers."""
    ledger = SQLiteLedger(tmp_path / "core.db")
    store = _store(ledger, tmp_path, schemas)
    branch = _prepare(store, fjellvik, actor)

    start = time.perf_counter()
    store.apply_branch(branch.id, actor=actor)
    elapsed = time.perf_counter() - start

    print(
        f"\napply flow: {elapsed * 1000:.2f} ms · budget {APPLY_BUDGET_S:.0f} s · "
        f"box: {_box_state()}"
    )
    assert elapsed < APPLY_BUDGET_S


def test_the_flip_commits_one_audit_event(tmp_path, schemas, fjellvik: Recipe, actor: Actor):
    """A flip is a pointer move: one row, no re-render, no new version."""
    ledger = SQLiteLedger(tmp_path / "core.db")
    store = _store(ledger, tmp_path, schemas)
    branch = _prepare(store, fjellvik, actor)
    before = len(store.list_versions("rcp_fjellvik"))
    seq_before = ledger.last_seq()

    store.apply_branch(branch.id, actor=actor)

    events = ledger.events(since_seq=seq_before)
    assert [event.type for event in events] == ["branch.head.moved"]
    assert len(store.list_versions("rcp_fjellvik")) == before
