"""The warm scene server — its defined job, tested (plan item 15).

The brief defines the job narrowly, because the measurements do: the
server exists to **hold the scene** (so builder wait drops — the launch
tax is paid once, not per request) and to **survive a kill** (recovery is
a replay of the durable recipe, checked by digest, with no `.blend`
anywhere in the path). These tests hold it to exactly that job, on the
fake backend, through a real subprocess — the RPC, the journal, the
restarts and the guard are all the real machinery; only the scene is
fake.

The opt-in real-engine test is `test_resident_real.py` (it needs `bpy`
under its own interpreter).
"""

from __future__ import annotations

import json
import os
import signal
import sys
import time

import pytest

from core.canon import content_hash as core_content_hash
from core.engine import ResidentEngine, ResidentPolicy
from core.engine.contract import (
    Engine,
    ExportRequest,
    PreviewRequest,
    ReexecuteRequest,
    StageRequest,
    StageResult,
    expected_stage_key,
)
from core.engine.errors import EngineFailed, EnginePinMismatch
from core.engine.resident import protocol
from core.engine.resident.transport import (
    ResidentProcess,
    ResidentRefused,
    ResidentTimeout,
)
from core.recipe.edits import apply_ops as core_apply_ops
from core.recipe.errors import EditRejected as CoreEditRejected
from core.recipe.stagecache import stage_cache_key

from .conftest import PIN_V1, PIN_V2, fjellvik, param_ops

# ---------------------------------------------------------------- fixtures


def warm_policy(**overrides) -> ResidentPolicy:
    """A policy whose dials do not fire by accident: the cadence and the
    guard are turned up high, the backoff is fast, and each test that
    wants a dial to fire sets it itself."""
    base = dict(
        restart_backoff_s=0.01,
        restart_backoff_cap_s=0.05,
        health_check_interval_s=3600.0,
        checkpoint_every_ops=50,
        checkpoint_every_s=3600.0,
        growth_check_every_ops=50,
    )
    base.update(overrides)
    return ResidentPolicy(**base)


@pytest.fixture
def resident(tmp_path):
    engine = ResidentEngine(
        pin=PIN_V1, root=tmp_path / "resident", policy=warm_policy()
    )
    yield engine
    engine.stop()


def stage_for(recipe, version_hash: str, stage: str = "coarse") -> StageRequest:
    return StageRequest(
        recipe=recipe, version_hash=version_hash, stage=stage, dep_keys=[]
    )


def with_params(recipe, entry: str, **params):
    """The scripted builder edit: same recipe, one entry's params moved."""
    out = recipe.model_copy(deep=True)
    out.entries[entry].params.update(params)
    return out


def script_of_edits(base, count: int):
    """A scripted sequence of builder edits — the benchmark's list, too."""
    recipes = [base]
    for i in range(count):
        entry = "harbor.crates" if i % 2 == 0 else "harbor.racks"
        recipes.append(with_params(recipes[-1], entry, count=3 + i))
    return recipes[1:]


# ------------------------------------------------------------- the seam


def test_the_resident_satisfies_the_engine_protocol(resident):
    assert isinstance(resident, Engine)


def test_the_reported_pin_drops_straight_into_a_recipe(resident):
    described = resident.describe()
    assert described.flavour == "resident"
    assert described.pin == PIN_V1
    assert described.capabilities.stages and described.capabilities.previews
    assert "fake" in described.source and "journal.jsonl" in described.source


def test_a_recipe_pinned_elsewhere_is_refused_before_any_work(resident, tmp_path):
    """Rule 2 — and the refusal is free: no resident is started for it."""
    with pytest.raises(EnginePinMismatch):
        resident.generate_stage(stage_for(fjellvik(PIN_V2), "vh1"))
    assert resident.stats()["pid"] is None
    assert not resident.stats()["resident_alive"]


def test_the_resident_must_report_the_pin_it_was_given(tmp_path):
    """The check on the resident's own reported pin — a resident built for
    another engine is refused, not quietly trusted (rule 2's other half)."""
    engine = ResidentEngine(
        pin=PIN_V1, root=tmp_path / "r", policy=warm_policy()
    )
    lying = {"pin": PIN_V2.model_dump(mode="json")}
    with pytest.raises(EnginePinMismatch):
        engine._check_reported_pin(lying)
    engine._check_reported_pin({"pin": PIN_V1.model_dump(mode="json")})
    engine.stop()


def test_same_request_same_bytes(resident):
    recipe = fjellvik(PIN_V1)
    first = resident.generate_stage(stage_for(recipe, "vh1"))
    second = resident.generate_stage(stage_for(recipe, "vh1"))
    assert first.data == second.data
    assert first.stage_key == second.stage_key
    assert first.wall_ms is not None and first.wall_ms > 0


def test_stage_keys_are_canonical(resident):
    """Rule 4 — the key is the one canonical function's, not the engine's
    own arithmetic."""
    request = stage_for(fjellvik(PIN_V1), "vh1", stage="fine")
    result = resident.generate_stage(request)
    assert result.stage_key == stage_cache_key(
        "vh1", resident.describe().pin, "fine", []
    )
    assert result.stage_key == expected_stage_key(request, resident.describe())


def test_reexecute_refuses_a_foreign_base(resident):
    """Rule 5 — only a base this engine's own flavour produced."""
    recipe = fjellvik(PIN_V1)
    foreign = StageResult(
        stage_key="k", data=json.dumps({"engine": "infinigen-1x"}).encode(),
        artifact={}, mechanism="full-reeval",
    )
    with pytest.raises(ValueError, match="re-execute"):
        resident.reexecute(ReexecuteRequest(
            recipe=recipe, version_hash="vh1", stage="coarse", base=foreign))
    # …while the resident's own base is honoured (the label comes from the
    # backend's describe, so this also covers the cold-engine ordering)
    own = StageResult(
        stage_key="k", data=json.dumps({"engine": "fake-resident"}).encode(),
        artifact={}, mechanism="graph-edit",
    )
    loaded = resident.reexecute(ReexecuteRequest(
        recipe=recipe, version_hash="vh1", stage="coarse", base=own))
    assert loaded.data
    assert loaded.mechanism == "full-reeval"  # a fresh resident, a replace
    edited = with_params(recipe, "harbor.crates", count=5)
    redone = resident.reexecute(ReexecuteRequest(
        recipe=edited, version_hash="vh2", stage="coarse", base=own,
        ops=param_ops("harbor.crates", count=5)))
    assert redone.data
    assert redone.mechanism == "graph-edit"  # the scene moved by the diff


def test_export_refuses_what_it_cannot_do_and_does_what_it_can(resident):
    recipe = fjellvik(PIN_V1)
    with pytest.raises(ValueError, match="exports"):
        resident.export(ExportRequest(
            recipe=recipe, version_hash="vh1", format="ma"))
    # a cold engine must not refuse what it simply has not asked its
    # backend for yet — capabilities are the resident's report
    out = resident.export(ExportRequest(
        recipe=recipe, version_hash="vh1", format="usda"))
    assert out.format == "usda"
    assert json.loads(out.data)["engine"] == "fake-resident"


def test_a_preview_is_deterministic_in_the_whole_request(resident):
    recipe = fjellvik(PIN_V1)
    request = PreviewRequest(
        recipe=recipe, version_hash="vh1", subject="harbor.crates",
        rung=2, seed=7)
    assert resident.render_preview(request).data == \
        resident.render_preview(request).data


def test_the_mechanism_names_how_the_scene_moved(resident):
    recipe = fjellvik(PIN_V1)
    first = resident.generate_stage(stage_for(recipe, "vh1"))
    assert first.mechanism == "full-reeval"  # a fresh resident, a replace
    edited = resident.generate_stage(
        stage_for(with_params(recipe, "harbor.crates", count=5), "vh2"))
    assert edited.mechanism == "graph-edit"  # the scene moved by ops
    again = resident.generate_stage(
        stage_for(with_params(recipe, "harbor.crates", count=5), "vh2b"))
    assert again.mechanism == "full-reeval"  # already there


# ------------------------------------------------- the job: holding the scene


def test_the_scene_is_held_across_requests(resident):
    recipe = fjellvik(PIN_V1)
    for i in range(3):
        resident.generate_stage(
            stage_for(with_params(recipe, "harbor.crates", count=4 + i),
                      f"vh{i}"))
    stats = resident.stats()
    assert stats["resident_alive"]
    assert stats["restarts"] == 0  # one resident, kept warm throughout
    assert [r["op"] for r in resident.requests] == ["generate_stage"] * 3


def test_an_edit_moves_the_scene_in_place(resident):
    base = fjellvik(PIN_V1)
    resident.generate_stage(stage_for(base, "vh1"))
    assert resident.resident_state()["state"]["object_count"] == 8 + 3
    before = resident.resident_state()["digest"]
    resident.generate_stage(
        stage_for(with_params(base, "harbor.crates", count=12), "vh2"))
    state = resident.resident_state()
    assert state["state"]["object_count"] == 12 + 3
    assert state["digest"] != before  # the digest distinguishes two states


def test_builder_wait_warm_is_not_a_process_start(resident):
    """The number the brief is about: the first request pays the resident's
    start; the rest reach a process that is already holding the scene."""
    recipe = fjellvik(PIN_V1)
    first = resident.generate_stage(stage_for(recipe, "vh1")).wall_ms
    waits = [
        resident.generate_stage(
            stage_for(with_params(recipe, "harbor.crates", count=5 + i),
                      f"vh{i}")).wall_ms
        for i in range(5)
    ]
    assert max(waits) < first
    assert resident.stats()["restarts"] == 0


# ------------------------------------------------- the job: surviving a kill


def test_kill_9_then_the_next_request_recovers_exactly(resident):
    recipe = fjellvik(PIN_V1)
    edits = script_of_edits(recipe, 4)
    for i, edited in enumerate(edits):
        before = resident.generate_stage(stage_for(edited, f"vh{i}"))
    digest_before = resident.resident_state()["digest"]

    pid = resident.stats()["pid"]
    os.kill(pid, signal.SIGKILL)
    time.sleep(0.05)  # let the box reap it, the way a real crash does

    # the same request again (rule 3: a recovery is byte-identical)
    after = resident.generate_stage(stage_for(edits[-1], "vh3"))
    stats = resident.stats()
    assert stats["restarts"] == 1
    assert stats["recoveries"] == 1
    assert after.data == before.data  # bytes: a hit is byte-identical
    assert resident.resident_state()["digest"] == digest_before  # and exact


def test_a_crash_loses_no_history_and_undo_still_works(resident, tmp_path):
    """The journal is written before the scene moves, so the replay lands
    on the history the recipe describes — and a request for an *older*
    recipe after a crash is an undo by diff, not an error."""
    recipe = fjellvik(PIN_V1)
    edits = script_of_edits(recipe, 3)
    for i, edited in enumerate(edits):
        resident.generate_stage(stage_for(edited, f"vh{i}"))

    os.kill(resident.stats()["pid"], signal.SIGKILL)
    time.sleep(0.05)

    # the crash recovers on the *older* request (v1 after v3 was applied)
    undone = resident.generate_stage(stage_for(edits[0], "vh0"))
    cold = ResidentEngine(
        pin=PIN_V1, root=tmp_path / "cold", policy=warm_policy()
    )
    try:
        reference = cold.generate_stage(stage_for(edits[0], "vh0"))
        reference_digest = cold.resident_state()["digest"]
    finally:
        cold.stop()
    assert undone.data == reference.data
    assert resident.resident_state()["digest"] == reference_digest


def test_the_journal_holds_what_the_scene_holds(resident, tmp_path):
    recipe = fjellvik(PIN_V1)
    resident.generate_stage(stage_for(recipe, "vh0"))  # the first load
    for i, edited in enumerate(script_of_edits(recipe, 3)):
        resident.generate_stage(stage_for(edited, f"vh{i + 1}"))
    entries = resident._journal.read_entries()
    assert entries[0]["kind"] == "replace"
    assert [e["kind"] for e in entries[1:]] == ["ops"] * 3


def test_the_restart_budget_ends_in_an_honest_error(tmp_path):
    engine = ResidentEngine(
        pin=PIN_V1, root=tmp_path / "r",
        policy=warm_policy(max_restarts=0),
    )
    try:
        engine.generate_stage(stage_for(fjellvik(PIN_V1), "vh1"))
        os.kill(engine.stats()["pid"], signal.SIGKILL)
        time.sleep(0.05)
        with pytest.raises(EngineFailed, match="budget"):
            engine.generate_stage(stage_for(fjellvik(PIN_V1), "vh1"))
    finally:
        engine.stop()


def test_a_hung_resident_gets_one_honest_retry_then_the_failure(tmp_path):
    """A call that outlives its deadline is not "slow"; the resident is
    rebuilt and the call made once more — and if it hangs again, the
    timeout is the answer that crosses the seam. The fake backend takes a
    real 2 s per stage here, so the deadline is met by a genuinely slow
    resident, not by a microsecond race."""
    engine = ResidentEngine(
        pin=PIN_V1, root=tmp_path / "r",
        policy=warm_policy(request_timeout_s=0.3),
        env={"FAKE_SCENE_STAGE_DELAY_S": "2"},
    )
    try:
        with pytest.raises(ResidentTimeout):
            engine.generate_stage(stage_for(fjellvik(PIN_V1), "vh1"))
        assert engine.stats()["restarts"] == 1
    finally:
        engine.stop()


# --------------------------------------------------------- the four dials


def test_backoff_doubles_to_the_cap():
    policy = ResidentPolicy(
        restart_backoff_s=0.5, restart_backoff_cap_s=8.0)
    assert [policy.backoff_for(n) for n in (1, 2, 3, 4, 5)] == \
        [0.5, 1.0, 2.0, 4.0, 8.0]
    assert policy.backoff_for(9) == 8.0  # capped


def test_checkpoints_follow_the_cadence(tmp_path):
    engine = ResidentEngine(
        pin=PIN_V1, root=tmp_path / "r",
        policy=warm_policy(checkpoint_every_ops=2),
    )
    try:
        recipe = fjellvik(PIN_V1)
        engine.generate_stage(stage_for(recipe, "vh0"))
        for i, edited in enumerate(script_of_edits(recipe, 4)):
            engine.generate_stage(stage_for(edited, f"vh{i + 1}"))
        stats = engine.stats()
        assert stats["checkpoints"] == 2
        anchored = json.loads(
            (tmp_path / "r" / "checkpoint.json").read_text())
        # 1 replace + 4 op entries at the moment of the last checkpoint
        assert anchored["journal_entries"] == 5
        assert anchored["state_digest"] == engine.state_digest()
    finally:
        engine.stop()


def test_the_growth_guard_recycles_a_growing_resident(
        resident, monkeypatch):
    readings = iter([100.0, 100.0, 200.0, 200.0, 200.0, 200.0])

    def growing_rss(self):
        return next(readings, 200.0)

    monkeypatch.setattr(ResidentProcess, "rss_mb", growing_rss)
    recipe = fjellvik(PIN_V1)
    resident.generate_stage(stage_for(recipe, "vh0"))
    resident._policy = resident._policy.model_copy(
        update={"max_growth_mb": 10.0, "growth_check_every_ops": 1})
    for i, edited in enumerate(script_of_edits(recipe, 3)):
        resident.generate_stage(stage_for(edited, f"vh{i + 1}"))
    stats = resident.stats()
    assert stats["guard_recycles"] == 1
    assert stats["restarts"] == 1
    assert stats["resident_alive"]


def test_health_checks_are_periodic(resident, monkeypatch):
    resident.generate_stage(stage_for(fjellvik(PIN_V1), "vh1"))
    resident._policy = resident._policy.model_copy(
        update={"health_check_interval_s": 0.01})
    pings: list[float] = []
    real_ping = resident._process.ping

    def spy(*, timeout_s=5.0):
        pings.append(time.monotonic())
        return real_ping(timeout_s=timeout_s)

    monkeypatch.setattr(resident._process, "ping", spy)
    time.sleep(0.02)
    resident.generate_stage(
        stage_for(with_params(fjellvik(PIN_V1), "harbor.crates",
                              count=5), "vh2"))
    assert len(pings) == 1
    resident.generate_stage(
        stage_for(with_params(fjellvik(PIN_V1), "harbor.crates",
                              count=6), "vh3"))  # inside the interval
    assert len(pings) == 1


# ------------------------------------------------------------- the journal


def test_a_torn_last_line_is_tolerated(resident, tmp_path):
    """The half-written line a kill -9 can leave is skipped, not fatal."""
    recipe = fjellvik(PIN_V1)
    resident.generate_stage(stage_for(recipe, "vh1"))
    resident.stop()
    journal = tmp_path / "resident" / "journal.jsonl"
    with journal.open("ab") as fh:
        fh.write(b'{"kind": "ops", "ops": [{"op": "set", "path": "h')
    entries = resident._journal.read_entries()
    assert entries and all("seq" in e for e in entries)
    assert entries[-1]["kind"] in {"replace", "ops"}


def test_the_snapshot_is_periodic_not_per_edit(resident):
    """WS §5.3's finding made a test: the journal is O(1) per edit and the
    snapshot is written at checkpoints — never the whole file per edit
    (the spike measured 143 MiB written for a 255 KiB recipe)."""
    recipe = fjellvik(PIN_V1)
    resident.generate_stage(stage_for(recipe, "vh0"))  # the first load
    for i, edited in enumerate(script_of_edits(recipe, 20)):
        resident.generate_stage(stage_for(edited, f"vh{i + 1}"))
    writes = resident.stats()["journal"]
    assert writes["journal_entries"] == 21  # 1 replace + 20 edits
    assert writes["snapshot_writes"] == 0  # the cadence never fired
    resident.checkpoint()
    after = resident.stats()["journal"]
    assert after["snapshot_writes"] == 1
    assert after["amplification"] <= 2.0  # the document, written once


def test_the_journal_continues_under_a_new_adapter(resident, tmp_path):
    """A second adapter attaching to the same root continues the sequence —
    a checkpoint's ``journal_entries`` is a position in *this* file."""
    recipe = fjellvik(PIN_V1)
    resident.generate_stage(stage_for(recipe, "vh1"))
    resident.generate_stage(
        stage_for(with_params(recipe, "harbor.crates", count=5), "vh2"))
    resident.stop()
    second = ResidentEngine(
        pin=PIN_V1, root=tmp_path / "resident", policy=warm_policy()
    )
    try:
        second.generate_stage(
            stage_for(with_params(recipe, "harbor.crates", count=6), "vh3"))
        entries = second._journal.read_entries()
        assert [e["seq"] for e in entries] == list(range(len(entries)))
        assert len(entries) == 3  # replace, ops, replace
    finally:
        second.stop()


# -------------------------------------------------------- the wire protocol


def test_frames_round_trip_and_garbage_is_refused():
    frame = {"id": 1, "method": "ping", "params": {}}
    assert protocol.decode(protocol.encode(frame)) == frame
    with pytest.raises(protocol.ProtocolError):
        protocol.decode(b"{not json")


def test_the_mirror_hashes_exactly_like_the_core():
    document = fjellvik(PIN_V1).model_dump(mode="json")
    assert protocol.content_hash(document) == core_content_hash(document)


CHANGE_CASES = {
    "set-param": [dict(op="set", path="harbor.crates.params.count", value=5)],
    "set-seed": [dict(op="set", path="seeds.props", value=7)],
    "remove-entry": [dict(op="remove", path="harbor.racks")],
    "two-at-once": [
        dict(op="set", path="harbor.crates.params.count", value=2),
        dict(op="set", path="harbor.racks.params.count", value=9),
    ],
}


@pytest.mark.parametrize("ops", CHANGE_CASES.values(), ids=CHANGE_CASES)
def test_the_mirrored_op_applier_agrees_with_the_core(ops):
    """The resident applies ops with its own mirror of the core's grammar;
    this is the drift check made cheap, before the digest check on the
    wire makes it binding."""
    from core.records import Op

    base = fjellvik(PIN_V1)
    typed = [Op.model_validate(o) for o in ops]
    ours = core_apply_ops(base, typed).model_dump(mode="json")
    theirs = protocol.apply_ops(
        base.model_dump(mode="json"), ops)
    assert ours == theirs


def test_a_rejected_op_is_rejected_on_both_sides():
    from core.records import Op

    bad = [dict(op="remove", path="harbor.crates.params.absent")]
    with pytest.raises(CoreEditRejected):
        core_apply_ops(fjellvik(PIN_V1), [
            Op(op="remove", path="harbor.crates.params.absent")])
    with pytest.raises(protocol.EditRejected):
        protocol.apply_ops(fjellvik(PIN_V1).model_dump(mode="json"), bad)


def test_touched_entries_names_the_dirty_set():
    document = fjellvik(PIN_V1).model_dump(mode="json")
    ops = [
        dict(op="set", path="harbor.crates.params.count", value=5),
        dict(op="set", path="seeds.props", value=7),
        dict(op="remove", path="harbor.racks"),
    ]
    assert protocol.touched_entries(document, ops) == \
        ["harbor.crates", "harbor.racks"]


# ------------------------------------------- the worker, over a real pipe


def test_the_worker_answers_its_surface_over_the_wire(tmp_path):
    pin = PIN_V1.model_dump(mode="json")
    process = ResidentProcess(
        python=sys.executable, backend="fake",
        root=tmp_path / "r", log_path=tmp_path / "r" / "resident.log",
        pin=pin,
    )
    process.start(timeout_s=30)
    try:
        hello = process.ping()
        assert hello["pong"] and hello["protocol"] == protocol.PROTOCOL_VERSION
        described = process.call("describe")
        assert described["pin"] == pin  # the pin crossed, and came back
        document = fjellvik(PIN_V1).model_dump(mode="json")
        loaded = process.call(
            "sync", {"replace": True, "document": document, "ops": []})
        assert loaded["document_digest"] == protocol.content_hash(document)
        moved = process.call("sync", {
            "replace": False, "ops": CHANGE_CASES["set-param"]})
        assert moved["touched"] == ["harbor.crates"]
        state = process.call("state", {})
        assert state["state"]["object_count"] == 5 + 3
    finally:
        process.stop()


def test_an_unknown_method_is_a_refusal_not_a_guess(tmp_path):
    process = ResidentProcess(
        python=sys.executable, backend="fake",
        root=tmp_path / "r", log_path=tmp_path / "r" / "resident.log",
    )
    process.start(timeout_s=30)
    try:
        with pytest.raises(ResidentRefused, match="bogus"):
            process.call("bogus", {})
    finally:
        process.stop()


def test_stdout_chatter_lands_in_the_log_not_on_the_wire(tmp_path):
    """WS §5.5's silent failure, made loud: a backend that chats on stdout
    (Blender's render progress does) must not corrupt the protocol channel
    — the worker points stdout at the log file before importing anything."""
    process = ResidentProcess(
        python=sys.executable, backend="fake",
        root=tmp_path / "r", log_path=tmp_path / "r" / "resident.log",
        env={"FAKE_SCENE_CHATTER": "1"},
    )
    process.start(timeout_s=30)
    try:
        assert process.ping()["pong"]  # the channel is pristine
        assert process.call("describe")["backend"] == "fake"
        assert "chatter" in process.log_tail()
    finally:
        process.stop()


def test_kill_leaves_the_log_and_the_journal_for_the_postmortem(resident):
    resident.generate_stage(stage_for(fjellvik(PIN_V1), "vh1"))
    process = resident._process
    process.kill()
    assert (resident.root / "journal.jsonl").exists()
    assert (resident.root / "resident.log").exists()
