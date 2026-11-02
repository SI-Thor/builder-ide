"""The ghost policy: what one ghost costs, under each of the three rules.

The prior's ghost gate is a rank against a group and can be wrong, so
night-v6 made the response a parameter (`--ghost-policy`): drop
(night-v5's behaviour — the prior's word is final), keep (record and keep
the score), and second_look (the default — the prop's mesh is rendered
and one cloud VLM call answers; the prop drops only if the cloud agrees).
These tests drive the real `NightPropCritic._score_mesh` branch with the
prior and the second look faked, and read the rows the branch records:
both verdicts ride one `night.ghost_second_look` row, and a second look
that cannot answer is not agreement — the prop stays, degraded, with the
error on the row.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "docs" / "lab" / "night-v6-scripts"
sys.path.insert(0, str(SCRIPTS))

import run_night  # noqa: E402

from core.models import FileRef  # noqa: E402
from core.night.iterate import CriticScore  # noqa: E402
from core.night.ledger import SQLiteLedger  # noqa: E402

TASK = "prop:lantern"
VARIANT = "prop:lantern_r2_v3"


class FakeStore:
    def __init__(self, glb: str | None) -> None:
        self.glb = glb

    def mesh(self, task_id, variant_id):
        return SimpleNamespace(occupied_volume=1.004, volume=1.003,
                               occupied_method="convex")

    def repair(self, task_id, variant_id):
        return SimpleNamespace(fidelity=1.0)

    def asset(self, task_id, variant_id):
        if self.glb is None:
            return None
        return SimpleNamespace(files=[
            FileRef(role="glb", path=self.glb, sha256="x", bytes=1)])


def _critic(tmp_path: Path, book, policy: str, look) -> run_night.NightPropCritic:
    return run_night.NightPropCritic(
        requests={TASK: SimpleNamespace(prompt="a brass lantern")},
        store=FakeStore(str(tmp_path / "prop.glb")),
        prior=object(),
        ledger=book,
        ghost_policy=policy,
        ghost_second_look=look,
        views_root=tmp_path,
    )


def _ghost_verdict():
    return SimpleNamespace(plausibility=0.0385, combined=0.196,
                           ambiguous=False, escalate=False,
                           line=lambda: "rank 1/13 in crate")


def _patch_prior(monkeypatch):
    monkeypatch.setattr(run_night, "features_from_report", lambda report: {})
    monkeypatch.setattr(run_night, "plausibility_judge",
                        lambda features, consistency, prior: _ghost_verdict())


def _score(critic) -> CriticScore:
    return critic._score_mesh(
        SimpleNamespace(id=TASK), SimpleNamespace(id=VARIANT),
        CriticScore(score=0.939, reason="scripted", degraded=False))


def _rows(book: SQLiteLedger, kind: str) -> list[dict]:
    return [event.payload for event in book.events() if event.type == kind]


def test_drop_policy_is_night_v5(tmp_path, monkeypatch) -> None:
    _patch_prior(monkeypatch)
    book = SQLiteLedger(tmp_path / "ledger.db")
    score = _score(_critic(tmp_path, book, "drop", look=None))
    assert score.score == 0.0 and score.degraded
    note = _rows(book, "night.prop_plausibility")[-1]
    assert note["ghost"] is True
    assert note["ghost_policy"] == "drop"
    assert note["ghost_outcome"] == "dropped_by_policy"
    assert _rows(book, "night.ghost_second_look") == []


def test_keep_policy_records_and_keeps(tmp_path, monkeypatch) -> None:
    _patch_prior(monkeypatch)
    book = SQLiteLedger(tmp_path / "ledger.db")
    score = _score(_critic(tmp_path, book, "keep", look=None))
    assert score.score == 0.939  # the scripted score stands
    assert score.degraded
    note = _rows(book, "night.prop_plausibility")[-1]
    assert note["ghost_outcome"] == "kept_by_policy"
    assert _rows(book, "night.ghost_second_look") == []


def _look(cloud_ghost):
    def _fake(*, prompt, glb, outdir, model):
        return {"ok": True, "model": model, "answer": "No. A solid cube.",
                "cloud_ghost": cloud_ghost, "wall_s": 8.1}
    return _fake


def test_second_look_agreement_drops(tmp_path, monkeypatch) -> None:
    _patch_prior(monkeypatch)
    book = SQLiteLedger(tmp_path / "ledger.db")
    score = _score(_critic(tmp_path, book, "second_look", _look(True)))
    assert score.score == 0.0 and score.degraded
    rows = _rows(book, "night.ghost_second_look")
    assert len(rows) == 1
    row = rows[0]
    assert row["prior_verdict"] == "ghost"
    assert row["prior"]["plausibility"] == 0.0385
    assert row["second_look"]["cloud_ghost"] is True
    assert row["outcome"] == "dropped_after_second_look"


def test_second_look_disagreement_keeps(tmp_path, monkeypatch) -> None:
    _patch_prior(monkeypatch)
    book = SQLiteLedger(tmp_path / "ledger.db")
    score = _score(_critic(tmp_path, book, "second_look", _look(False)))
    assert score.score == 0.939 and score.degraded
    row = _rows(book, "night.ghost_second_look")[-1]
    assert row["outcome"] == "kept_after_second_look"
    assert row["second_look"]["cloud_ghost"] is False


def test_a_silent_second_look_is_not_agreement(tmp_path, monkeypatch) -> None:
    _patch_prior(monkeypatch)

    def broken(*, prompt, glb, outdir, model):
        return {"ok": False, "error": "deepinfra returned HTTP 401",
                "cloud_ghost": None}

    book = SQLiteLedger(tmp_path / "ledger.db")
    score = _score(_critic(tmp_path, book, "second_look", broken))
    assert score.score == 0.939 and score.degraded
    row = _rows(book, "night.ghost_second_look")[-1]
    assert row["outcome"] == "kept_after_second_look"
    assert row["second_look"]["error"]


def test_no_glb_to_render_keeps_the_prop(tmp_path, monkeypatch) -> None:
    _patch_prior(monkeypatch)
    book = SQLiteLedger(tmp_path / "ledger.db")
    critic = run_night.NightPropCritic(
        requests={TASK: SimpleNamespace(prompt="a brass lantern")},
        store=FakeStore(None),
        prior=object(), ledger=book,
        ghost_policy="second_look",
        ghost_second_look=_look(True),  # would agree, but is never called
        views_root=tmp_path)
    score = _score(critic)
    assert score.score == 0.939 and score.degraded
    row = _rows(book, "night.ghost_second_look")[-1]
    assert row["outcome"] == "kept_after_second_look"
    assert "no GLB" in row["second_look"]["error"]
