"""The fold: judgments, their outcomes, and the calibration report.

A judgment is only worth scoring once something has happened, so this file
exercises the join between a judgment and the outcome that answers it:

* the **scope** is the join key — the caller names the thing it judged, and
  the outcome row that speaks about the same thing carries the same name;
* the outcome has to come **after** the judgment — the outcome of a
  judgment is what happened next;
* a judgment nobody answered stays **unscored**, and the report counts it,
  because "unmeasured" and "measured and badly calibrated" are different
  facts.

It then exercises the report the nightly job writes and the one-line drift
the morning report carries.
"""

from __future__ import annotations

import json

import pytest

from core.judge.backends import BackendReply, FakeBackend
from core.judge.judge import Judge
from core.judge.models import Question
from core.judge.tracking import (
    DEFAULT_SOURCES,
    CriticOutcome,
    OwnerOutcome,
    TilesOutcome,
    calibration_report,
    drift_lines,
    render_calibration_markdown,
    run_calibration_job,
    samples_from_events,
    write_calibration_report,
)
from core.night.ledger import InMemoryLedger
from core.records import Actor

TILE_CHOICE = Question(
    qid="tile",
    kind="choice",
    instructions="Which tile?",
    criteria={"tile_a": "a", "tile_b": "b"},
)

NOUL = Question(qid="alive", kind="noul", instructions="The root is alive.")


class ScriptedBackend(FakeBackend):
    """A backend whose answer comes from a callable."""

    def __init__(self, responder, name="d1", model="d1-2B"):
        super().__init__()
        self.name = name
        self.model = model
        self._responder = responder

    def ask(self, state, questions):
        distributions = {}
        confidences = {}
        for question in questions:
            distributions[question.qid] = self._responder(question)
            confidences[question.qid] = max(distributions[question.qid].values())
        return BackendReply(
            backend=self.name,
            model=self.model,
            distributions=distributions,
            confidences=confidences,
            input_tokens=1,
            wall_seconds=0.001,
        )


def _play(
    ledger: InMemoryLedger,
    *,
    tile_id: str,
    result: str,
    scope: str,
    at: str,
    style: str = "plain",
) -> None:
    """One ``tile.played`` row — the tiles' own outcome."""
    ledger.append(
        type="tile.played",
        actor=Actor(kind="core", id="tile-chooser", via="tile"),
        subject={"entity_kind": "tile", "entity_id": tile_id},
        payload={
            "tile_id": tile_id,
            "context": {"wanted_style": style},
            "outcome": {"result": result},
            "scope": scope,
        },
        at=at,
    )


def _critic(
    ledger: InMemoryLedger,
    *,
    verdict: str,
    scope: str,
    at: str,
    entity_id: str = "art_1",
) -> None:
    """One ``critic.verdict`` row."""
    ledger.append(
        type="critic.verdict",
        actor=Actor(kind="core", id="critic", via="critic"),
        subject={"entity_kind": "artifact", "entity_id": entity_id},
        payload={"verdict": verdict, "scope": scope},
        at=at,
    )


def _owner(
    ledger: InMemoryLedger,
    *,
    verdict: str,
    scope: str,
    at: str,
) -> None:
    """One ``taste.note.appended`` row — the owner's keep or revert."""
    ledger.append(
        type="taste.note.appended",
        actor=Actor(kind="owner", id="casey", via="owner"),
        subject={"entity_kind": "taste_note", "entity_id": scope},
        payload={
            "row": {
                "id": scope,
                "subject": {"id": scope},
                "artifact_ref": scope,
                "verdict": verdict,
            }
        },
        at=at,
    )


# --- the join -------------------------------------------------------------------


def test_a_judgment_is_joined_to_the_play_that_answers_it():
    ledger = InMemoryLedger()
    judge = Judge(
        ScriptedBackend(lambda q: {"tile_a": 0.8, "tile_b": 0.2}),
        ledger=ledger,
    )
    judge.judge(task="tiles", state="s", questions=[TILE_CHOICE], scope="bucket-1")
    _play(ledger, tile_id="tile_a", result="win", scope="bucket-1", at="2026-10-31T01:00:00Z")

    samples = samples_from_events(ledger.events())
    assert len(samples) == 1
    sample = samples[0]
    assert sample.outcome is True
    assert sample.answer == "tile_a"
    assert sample.truth == "tile_a"
    assert sample.backend == "d1"
    assert sample.model == "d1-2B"
    assert sample.task == "tiles"
    assert sample.cell == ("d1", "d1-2B", "tiles")


def test_a_play_that_lost_makes_the_judgment_wrong():
    ledger = InMemoryLedger()
    judge = Judge(
        ScriptedBackend(lambda q: {"tile_a": 0.8, "tile_b": 0.2}),
        ledger=ledger,
    )
    judge.judge(task="tiles", state="s", questions=[TILE_CHOICE], scope="bucket-1")
    _play(ledger, tile_id="tile_a", result="lose", scope="bucket-1", at="2026-10-31T01:00:00Z")

    samples = samples_from_events(ledger.events())
    assert samples[0].outcome is False
    assert samples[0].truth == "tile_b"


def test_a_judgment_with_no_scope_is_not_scored():
    """Nothing names it, so nothing answers it."""
    ledger = InMemoryLedger()
    judge = Judge(
        ScriptedBackend(lambda q: {"tile_a": 0.8, "tile_b": 0.2}),
        ledger=ledger,
    )
    judge.judge(task="tiles", state="s", questions=[TILE_CHOICE])
    _play(ledger, tile_id="tile_a", result="win", scope="bucket-1", at="2026-10-31T01:00:00Z")

    assert samples_from_events(ledger.events()) == []


def test_a_play_of_another_tile_does_not_answer_the_judgment():
    ledger = InMemoryLedger()
    judge = Judge(
        ScriptedBackend(lambda q: {"tile_a": 0.8, "tile_b": 0.2}),
        ledger=ledger,
    )
    judge.judge(task="tiles", state="s", questions=[TILE_CHOICE], scope="bucket-1")
    _play(ledger, tile_id="tile_b", result="win", scope="bucket-1", at="2026-10-31T01:00:00Z")

    assert samples_from_events(ledger.events()) == []


def test_an_outcome_before_the_judgment_does_not_answer_it():
    """The outcome of a judgment is what happened next."""
    ledger = InMemoryLedger()
    judge = Judge(
        ScriptedBackend(lambda q: {"tile_a": 0.8, "tile_b": 0.2}),
        ledger=ledger,
    )
    _play(ledger, tile_id="tile_a", result="win", scope="bucket-1", at="2026-10-31T00:00:00Z")
    judge.judge(task="tiles", state="s", questions=[TILE_CHOICE], scope="bucket-1")

    assert samples_from_events(ledger.events()) == []


def test_the_first_outcome_after_the_judgment_is_the_one_that_answers_it():
    ledger = InMemoryLedger()
    judge = Judge(
        ScriptedBackend(lambda q: {"tile_a": 0.8, "tile_b": 0.2}),
        ledger=ledger,
    )
    judge.judge(task="tiles", state="s", questions=[TILE_CHOICE], scope="bucket-1")
    _play(ledger, tile_id="tile_a", result="lose", scope="bucket-1", at="2026-10-31T01:00:00Z")
    _play(ledger, tile_id="tile_a", result="win", scope="bucket-1", at="2026-10-31T02:00:00Z")

    samples = samples_from_events(ledger.events())
    assert len(samples) == 1
    assert samples[0].outcome is False


def test_the_critics_verdict_answers_a_noul():
    ledger = InMemoryLedger()
    judge = Judge(
        ScriptedBackend(lambda q: {"true": 0.9, "false": 0.1}),
        ledger=ledger,
    )
    judge.judge(task="alive", state="s", questions=[NOUL], scope="art_1")
    _critic(ledger, verdict="keep", scope="art_1", at="2026-10-31T01:00:00Z")

    samples = samples_from_events(ledger.events())
    assert len(samples) == 1
    assert samples[0].outcome is True
    assert samples[0].answer == "true"
    assert samples[0].truth == "true"


def test_a_fix_verdict_refutes_a_noul():
    ledger = InMemoryLedger()
    judge = Judge(
        ScriptedBackend(lambda q: {"true": 0.9, "false": 0.1}),
        ledger=ledger,
    )
    judge.judge(task="alive", state="s", questions=[NOUL], scope="art_1")
    _critic(ledger, verdict="fix", scope="art_1", at="2026-10-31T01:00:00Z")

    samples = samples_from_events(ledger.events())
    assert samples[0].outcome is False
    assert samples[0].truth == "false"


def test_the_owners_keep_answers_a_noul():
    ledger = InMemoryLedger()
    judge = Judge(
        ScriptedBackend(lambda q: {"true": 0.9, "false": 0.1}),
        ledger=ledger,
    )
    judge.judge(task="alive", state="s", questions=[NOUL], scope="art_1")
    _owner(ledger, verdict="keep", scope="art_1", at="2026-10-31T01:00:00Z")

    samples = samples_from_events(ledger.events())
    assert len(samples) == 1
    assert samples[0].outcome is True


def test_the_owners_revert_refutes_a_noul():
    ledger = InMemoryLedger()
    judge = Judge(
        ScriptedBackend(lambda q: {"true": 0.9, "false": 0.1}),
        ledger=ledger,
    )
    judge.judge(task="alive", state="s", questions=[NOUL], scope="art_1")
    _owner(ledger, verdict="reject", scope="art_1", at="2026-10-31T01:00:00Z")

    samples = samples_from_events(ledger.events())
    assert samples[0].outcome is False


def test_the_three_sources_are_asked_in_order():
    assert [source.name for source in DEFAULT_SOURCES] == ["tiles", "critic", "owner"]
    assert isinstance(DEFAULT_SOURCES[0], TilesOutcome)
    assert isinstance(DEFAULT_SOURCES[1], CriticOutcome)
    assert isinstance(DEFAULT_SOURCES[2], OwnerOutcome)


def test_the_tiles_source_reads_the_bucket_when_the_row_carries_no_scope():
    """A play of the tiles rig carries the bucket in its context."""
    ledger = InMemoryLedger()
    judge = Judge(
        ScriptedBackend(lambda q: {"tile_a": 0.8, "tile_b": 0.2}),
        ledger=ledger,
    )
    judge.judge(task="tiles", state="s", questions=[TILE_CHOICE], scope="wanted_style=plain")
    ledger.append(
        type="tile.played",
        actor=Actor(kind="core", id="tile-chooser", via="tile"),
        subject={"entity_kind": "tile", "entity_id": "tile_a"},
        payload={
            "tile_id": "tile_a",
            "context": {"wanted_style": "plain"},
            "outcome": {"result": "win"},
        },
        at="2026-10-31T01:00:00Z",
    )
    samples = samples_from_events(ledger.events())
    assert len(samples) == 1
    assert samples[0].outcome is True


# --- the report -----------------------------------------------------------------


def _a_cell_of_judgments(ledger: InMemoryLedger, n: int, p_true: float, right: bool) -> None:
    """``n`` judgments on one scope, each answered by a play."""
    for index in range(n):
        scope = f"bucket-{index}"
        judge = Judge(
            ScriptedBackend(lambda q: {"true": p_true, "false": round(1.0 - p_true, 10)}),
            ledger=ledger,
        )
        judge.judge(task="alive", state="s", questions=[NOUL], scope=scope)
        _critic(
            ledger,
            verdict="keep" if right else "fix",
            scope=scope,
            at=f"2026-10-31T{index + 10:02d}:00:00Z",
        )


def test_the_report_counts_the_judgments_it_scored_and_the_ones_it_did_not():
    ledger = InMemoryLedger()
    _a_cell_of_judgments(ledger, 4, 0.9, right=True)
    # one judgment nobody answered
    judge = Judge(
        ScriptedBackend(lambda q: {"true": 0.9, "false": 0.1}),
        ledger=ledger,
    )
    judge.judge(task="alive", state="s", questions=[NOUL], scope="nobody-answers-this")

    report = calibration_report(ledger.events())
    assert report.n_judgments == 5
    assert report.n_scored == 4
    assert report.n_unscored == 1
    assert len(report.cells) == 1
    cell = report.cells[0].cell
    assert cell.n == 4
    assert cell.accuracy == pytest.approx(1.0)
    assert cell.brier == pytest.approx(0.01)
    assert cell.mean_confidence == pytest.approx(0.9)


def test_the_report_carries_the_numbers_under_every_definition():
    ledger = InMemoryLedger()
    _a_cell_of_judgments(ledger, 6, 0.9, right=True)
    report = calibration_report(ledger.events())
    per_definition = report.cells[0].cell.per_definition
    assert set(per_definition) == {
        "top_probability",
        "normalised_margin",
        "entropy_normalised",
    }
    # the Brier score is computed over the whole vector, so it does not move
    # with the definition; the mean confidence does
    assert per_definition["top_probability"]["brier"] == pytest.approx(
        per_definition["entropy_normalised"]["brier"]
    )
    assert per_definition["top_probability"]["mean_confidence"] == pytest.approx(0.9)
    assert per_definition["normalised_margin"]["mean_confidence"] == pytest.approx(0.8)


def test_the_report_sweeps_the_escalation_under_every_definition():
    ledger = InMemoryLedger()
    _a_cell_of_judgments(ledger, 4, 0.9, right=True)
    report = calibration_report(ledger.events())
    sweeps = report.cells[0].sweeps
    assert set(sweeps) == {
        "top_probability",
        "normalised_margin",
        "entropy_normalised",
    }
    assert [row.tau for row in sweeps["top_probability"]] == [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]


def test_the_report_names_the_definition_it_used():
    ledger = InMemoryLedger()
    _a_cell_of_judgments(ledger, 2, 0.9, right=True)
    report = calibration_report(ledger.events())
    assert report.as_dict()["confidence_definition"] == "top_probability"


def test_the_judgment_row_says_which_definition_it_used():
    ledger = InMemoryLedger()
    judge = Judge(
        ScriptedBackend(lambda q: {"tile_a": 0.8, "tile_b": 0.2}),
        ledger=ledger,
    )
    judge.judge(task="tiles", state="s", questions=[TILE_CHOICE], scope="bucket-1")
    payload = ledger.events()[0].payload
    assert payload["confidence_definition"] == "top_probability"
    assert payload["scope"] == "bucket-1"
    judgment = payload["judgments"][0]
    assert judgment["confidence"] == pytest.approx(0.8)
    assert judgment["confidence_definition"] == "top_probability"


def test_the_backends_own_number_rides_beside_the_canonical_one():
    """The edge between the two is worth having on the log."""
    ledger = InMemoryLedger()
    judge = Judge(
        ScriptedBackend(lambda q: {"tile_a": 0.8, "tile_b": 0.2}),
        ledger=ledger,
    )
    judge.judge(task="tiles", state="s", questions=[TILE_CHOICE], scope="bucket-1")
    judgment = ledger.events()[0].payload["judgments"][0]
    assert judgment["backend_confidence"] == pytest.approx(0.8)
    assert judgment["confidence"] == pytest.approx(0.8)


# --- the nightly job ------------------------------------------------------------


def test_the_nightly_job_writes_the_json_and_the_readable_text(tmp_path):
    ledger = InMemoryLedger()
    _a_cell_of_judgments(ledger, 4, 0.9, right=True)
    path, report = run_calibration_job(ledger, tmp_path)

    assert path.name == "calibration.json"
    assert (tmp_path / "calibration.md").exists()
    payload = json.loads(path.read_text())
    assert payload["confidence_definition"] == "top_probability"
    assert payload["n_scored"] == 4
    assert payload["cells"][0]["cell"]["task"] == "alive"
    assert report.n_scored == 4


def test_the_readable_report_carries_the_numbers_and_the_drift():
    ledger = InMemoryLedger()
    _a_cell_of_judgments(ledger, 4, 0.9, right=True)
    report = calibration_report(ledger.events())
    text = render_calibration_markdown(report)
    assert "top_probability" in text
    assert "d1:d1-2B · alive" in text
    assert "No cell drifted." in text


def test_the_readable_report_says_when_nothing_has_been_measured():
    report = calibration_report([])
    text = render_calibration_markdown(report)
    assert "No cell has a scored judgment yet." in text


def test_the_drift_lines_are_the_ones_the_morning_report_carries():
    ledger = InMemoryLedger()
    _a_cell_of_judgments(ledger, 4, 0.9, right=True)
    assert drift_lines(ledger.events()) == []


def test_the_report_is_written_where_it_is_told(tmp_path):
    ledger = InMemoryLedger()
    _a_cell_of_judgments(ledger, 2, 0.9, right=True)
    report = calibration_report(ledger.events())
    path = write_calibration_report(report, tmp_path / "reports")
    assert path.exists()
    assert (tmp_path / "reports" / "calibration.md").exists()
