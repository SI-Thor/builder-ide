"""The merge gate's engine rungs over the seam — §2.3 answered by any engine."""

from __future__ import annotations

from core.engine import EngineGateEngine, FakeEngine
from core.engine.contract import Engine, StageRequest

from .conftest import PIN_V1, fjellvik


class _NondeterministicEngine(FakeEngine):
    """An engine that breaks rule 3 — the gate must catch it, not pass it.
    The drift is per call (a counter), because a constant suffix would be
    deterministic too."""

    def __init__(self, pin):
        super().__init__(pin)
        self._n = 0

    def generate_stage(self, request: StageRequest):
        self._n += 1
        result = super().generate_stage(request)
        return result.model_copy(update={
            "data": result.data + f"\ncall {self._n}".encode()})


def _gate(engine: Engine):
    recipe = fjellvik(PIN_V1)
    return (
        EngineGateEngine(
            engine,
            recipe_at=lambda: (recipe, "sha256:" + "a" * 64),
        ),
        recipe,
    )


def test_deterministic_rebuild_really_byte_compares():
    """§2.3.1 checked for real: the stage is generated twice and compared —
    a deterministic engine passes with its evidence, a drifting one fails
    the gate instead of passing it by construction."""
    gate, _ = _gate(FakeEngine(PIN_V1))
    ok = gate.deterministic_rebuild("ed_0001")
    assert ok["ok"] is True and ok["byte_identical"] is True
    assert ok["stage_key"].startswith("sha256:")
    assert "fake-engine" in ok["engine"]

    drifting, _ = _gate(_NondeterministicEngine(PIN_V1))
    bad = drifting.deterministic_rebuild("ed_0001")
    assert bad["ok"] is False and bad["byte_identical"] is False


def test_the_gate_reads_the_recipe_at_gate_time_not_at_boot():
    """The gate runs during the night, after commits: its recipe_at is
    answered per call, so the recipe it checks is the one that exists when
    the gate runs (a new version is a new check)."""
    holder = {"recipe": fjellvik(PIN_V1), "hash": "sha256:" + "a" * 64}
    gate = EngineGateEngine(
        FakeEngine(PIN_V1),
        recipe_at=lambda: (holder["recipe"], holder["hash"]),
    )
    first = gate.deterministic_rebuild(None)["stage_key"]
    holder["recipe"] = fjellvik(PIN_V1, crates=99)
    holder["hash"] = "sha256:" + "b" * 64
    second = gate.deterministic_rebuild(None)["stage_key"]
    assert first != second


def test_the_render_rung_wears_verdict_scripted_on_its_face():
    """RV patch 15: no critic model has been chosen, so the verdict is a
    scripted check and says so — the *render* is the engine's, the *verdict*
    never pretends otherwise."""
    gate, _ = _gate(FakeEngine(PIN_V1))
    rung = gate.render_rung(2, 42)
    assert rung["label"] == "verdict@scripted"
    assert rung["degraded"] is True
    assert rung["rung"] == 2 and rung["seed"] == 42
    assert rung["artifact"]["sha256"].startswith("sha256:")
    assert "fake-engine" in rung["summary"]


def test_the_analytic_checks_stay_scripted_and_engine_labelled():
    gate, _ = _gate(FakeEngine(PIN_V1))
    results = gate.run_checks([
        {"kind": "constraint", "spec": {"path": "structure.south_span.params.load_factor",
                                        "op": ">=", "value": 2.0}},
        {"kind": "geometry", "spec": {"check": "watertight"}},
    ])
    assert all(r["ok"] for r in results)
    assert all(r["label"] == "verdict@scripted" for r in results)
    assert all("no physics engine" in r["method"] for r in results)
    assert all("fake-engine" in r["engine"] for r in results)
