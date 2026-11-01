"""The fold: judgments, their outcomes, and the calibration report.

**A judgment is only worth scoring once something has happened.** The judge
writes a distribution; the tiles' play, the critic's verdict and the owner's
keep are what turn that distribution into a right or a wrong. This module is
the join between the two, and it is a fold over the ledger like every other
view in this repo: the same rows, read again, give the same report after a
kill -9.

**The join key is the scope.** A caller that asks the judge about a thing
names it: ``judge.judge(..., scope="wanted_style=plain")`` writes that scope
on the ``judge.verdict`` row, and the outcome row that speaks about the same
thing carries the same scope. The fold then asks each outcome source, in
ledger order, whether its row speaks about *this* answer, and takes the
first one that does **after** the judgment — the outcome of a judgment is
what happened next, not what happened before it.

Three sources ship with it:

* **the tiles** (``tile.played``) — a play of the tile the judgment answered,
  and whether that play won;
* **the critic** (``critic.verdict``) — the critic's verdict on the artifact,
  with the polarity read from the answer: a noul that says "true" means the
  artifact is good, so a "keep" verdict confirms it and a "fix" verdict
  refutes it;
* **the owner** (``taste.note.appended``) — the owner's keep or revert, with
  the same polarity.

A judgment nobody answered stays **unscored**, and the report says how many
there were: a cell that scores nothing is not a well-calibrated cell, it is
an unmeasured one, and the difference is the whole point of counting it.

**The nightly job** (:func:`run_calibration_job`) writes the full report —
every cell, every definition, the reliability curves, the escalation sweeps
and the recalibrations — into the night's reports directory. The **morning
report** (:func:`drift_lines`) carries one line per drifting model, read from
the same rows.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .calibration import (
    CANONICAL_CONFIDENCE,
    CONFIDENCE_DEFINITIONS,
    CalibrationCell,
    CalibrationSample,
    DriftLine,
    Recalibration,
    SweepRow,
    cell_of,
    cells_of,
    drift_of,
    escalation_sweep,
    recalibrate,
)
from .events import JUDGE_EVENT_TYPE
from .judge import fold_judgments

__all__ = [
    "OutcomeSource",
    "TilesOutcome",
    "CriticOutcome",
    "OwnerOutcome",
    "DEFAULT_SOURCES",
    "CalibrationCellReport",
    "CalibrationReport",
    "samples_from_events",
    "calibration_report",
    "drift_lines",
    "render_calibration_markdown",
    "write_calibration_report",
    "run_calibration_job",
]


# --- the outcome sources ---------------------------------------------------------


@dataclass(frozen=True)
class OutcomeSource:
    """Where an outcome comes from, and how to read it.

    ``scope`` is the row's join key; ``matches`` says whether the row speaks
    about the answer the judgment gave; ``truth`` says whether that answer was
    right.
    """

    name: str
    event_type: str

    def scope(self, event: Any) -> str | None:
        payload = getattr(event, "payload", {}) or {}
        scope = payload.get("scope")
        return str(scope) if scope else None

    def matches(self, event: Any, answer: str, kind: str) -> bool:
        raise NotImplementedError

    def truth(self, event: Any) -> bool:
        raise NotImplementedError


@dataclass(frozen=True)
class TilesOutcome(OutcomeSource):
    """The tiles' own outcome: the play of the tile the judgment answered.

    A play of a different tile says nothing about this judgment, so it does
    not match; a play of the answered tile does, and its result is the truth.
    """

    name: str = "tiles"
    event_type: str = "tile.played"

    def scope(self, event: Any) -> str | None:
        payload = getattr(event, "payload", {}) or {}
        scope = payload.get("scope")
        if scope:
            return str(scope)
        context = payload.get("context") or {}
        style = context.get("wanted_style")
        return f"wanted_style={style}" if style else None

    def matches(self, event: Any, answer: str, kind: str) -> bool:
        payload = getattr(event, "payload", {}) or {}
        return str(payload.get("tile_id", "")) == answer

    def truth(self, event: Any) -> bool:
        payload = getattr(event, "payload", {}) or {}
        outcome = payload.get("outcome") or {}
        return str(outcome.get("result", "")) == "win"


@dataclass(frozen=True)
class CriticOutcome(OutcomeSource):
    """The critic's verdict on the artifact the judgment spoke about.

    The polarity: a noul that answers "true" says the artifact is good, so a
    "keep" verdict confirms the answer and a "fix" verdict refutes it. A
    choice or score answer has no such polarity — the critic's verdict is
    about the artifact, not about which option was named — so it does not
    match a non-noul judgment.
    """

    name: str = "critic"
    event_type: str = "critic.verdict"

    def scope(self, event: Any) -> str | None:
        payload = getattr(event, "payload", {}) or {}
        scope = payload.get("scope")
        if scope:
            return str(scope)
        subject = getattr(event, "subject", {}) or {}
        entity_id = subject.get("entity_id")
        return str(entity_id) if entity_id else None

    def matches(self, event: Any, answer: str, kind: str) -> bool:
        if kind not in ("noul", "verify"):
            return False
        return answer in ("true", "false")

    def truth(self, event: Any) -> bool:
        payload = getattr(event, "payload", {}) or {}
        verdict = str(payload.get("verdict", ""))
        kept = payload.get("kept")
        if kept is not None:
            return bool(kept)
        return verdict == "keep"


@dataclass(frozen=True)
class OwnerOutcome(OutcomeSource):
    """The owner's own keep or revert — the last word on an artifact."""

    name: str = "owner"
    event_type: str = "taste.note.appended"

    def scope(self, event: Any) -> str | None:
        payload = getattr(event, "payload", {}) or {}
        row = payload.get("row") or {}
        subject = row.get("subject") or {}
        for key in ("id", "artifact_ref", "scope"):
            value = subject.get(key) or row.get(key)
            if value:
                return str(value)
        return None

    def matches(self, event: Any, answer: str, kind: str) -> bool:
        if kind not in ("noul", "verify"):
            return False
        return answer in ("true", "false")

    def truth(self, event: Any) -> bool:
        payload = getattr(event, "payload", {}) or {}
        row = payload.get("row") or {}
        return str(row.get("verdict", "")) == "keep"


#: The three sources, in the order they are asked.
DEFAULT_SOURCES: tuple[OutcomeSource, ...] = (
    TilesOutcome(),
    CriticOutcome(),
    OwnerOutcome(),
)


# --- the fold --------------------------------------------------------------------


def _answer_of(distribution: Mapping[str, float], kind: str) -> str:
    """The answer a judgment gave: the argmax, as a key."""
    top = max(sorted(distribution), key=lambda key: float(distribution[key]))
    if kind in ("noul", "verify"):
        return "true" if top == "true" else "false"
    return top


def samples_from_events(
    events: Sequence[Any],
    *,
    sources: Sequence[OutcomeSource] = DEFAULT_SOURCES,
) -> list[CalibrationSample]:
    """The scored judgments: every ``judge.verdict`` row that an outcome answers.

    One sample per judgment, in ledger order. A judgment with no scope, or
    with no outcome row that speaks about its answer, is left out — the
    report counts them separately, because "unmeasured" and "measured and
    badly calibrated" are different facts.
    """
    outcomes: dict[tuple[str, str], list[tuple[int, Any]]] = {}
    for index, event in enumerate(events):
        event_type = getattr(event, "type", None)
        for source in sources:
            if event_type != source.event_type:
                continue
            scope = source.scope(event)
            if scope is None:
                continue
            outcomes.setdefault((source.event_type, scope), []).append((index, event))

    samples: list[CalibrationSample] = []
    for index, event in enumerate(events):
        if getattr(event, "type", None) != JUDGE_EVENT_TYPE:
            continue
        payload = getattr(event, "payload", {}) or {}
        scope = payload.get("scope")
        backend = str(payload.get("backend", ""))
        model = str(payload.get("model", ""))
        task = str(payload.get("task", ""))
        for entry in fold_judgments([event]):
            judgment = entry.get("judgment")
            if judgment is None:
                continue
            distribution = judgment.distribution
            answer = _answer_of(distribution, judgment.kind)
            truth: str | None = None
            outcome: bool | None = None
            if scope:
                for source in sources:
                    for at, candidate in outcomes.get((source.event_type, str(scope)), ()):
                        if at <= index:
                            continue  # the outcome has to come after the judgment
                        if not source.matches(candidate, answer, judgment.kind):
                            continue
                        outcome = source.truth(candidate)
                        truth = answer if outcome else _other(answer, distribution)
                        break
                    if outcome is not None:
                        break
            if outcome is None:
                continue
            samples.append(
                CalibrationSample(
                    backend=backend,
                    model=model,
                    task=task,
                    kind=judgment.kind,
                    qid=judgment.qid,
                    distribution=dict(distribution),
                    outcome=outcome,
                    answer=answer,
                    truth=truth,
                    at=str(getattr(event, "at", "")),
                )
            )
    return samples


def _other(answer: str, distribution: Mapping[str, float]) -> str | None:
    """The other option of a binary distribution — the truth when the answer was wrong.

    Only the answer itself is excluded: a noul's distribution is over
    ``true`` and ``false``, so excluding both of them would leave nothing
    and the truth would be lost on every refuted judgment.
    """
    others = [key for key in distribution if key != answer]
    if len(others) == 1:
        return others[0]
    return None


# --- the report ------------------------------------------------------------------


@dataclass(frozen=True)
class CalibrationCellReport:
    """One cell's numbers, its recalibration and its drift."""

    cell: CalibrationCell
    recalibration: Recalibration
    sweeps: Mapping[str, tuple[SweepRow, ...]] = field(default_factory=dict)
    drift: tuple[DriftLine, ...] = ()

    @property
    def key(self) -> tuple[str, str, str]:
        return self.cell.key

    def as_dict(self) -> dict[str, Any]:
        return {
            "cell": self.cell.as_dict(),
            "recalibration": self.recalibration.as_dict(),
            "sweeps": {
                name: [row.as_dict() for row in rows] for name, rows in self.sweeps.items()
            },
            "drift": [line.as_dict() for line in self.drift],
        }


@dataclass(frozen=True)
class CalibrationReport:
    """The whole calibration picture, as one object."""

    generated_at: str
    n_judgments: int
    n_scored: int
    cells: tuple[CalibrationCellReport, ...] = ()
    drift: tuple[DriftLine, ...] = ()
    definitions: tuple[str, ...] = CONFIDENCE_DEFINITIONS

    @property
    def n_unscored(self) -> int:
        """The judgments no outcome answered."""
        return max(0, self.n_judgments - self.n_scored)

    @property
    def confidence_definition(self) -> str:
        """The one definition every confidence in this report was computed under."""
        return CANONICAL_CONFIDENCE

    def as_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "confidence_definition": CANONICAL_CONFIDENCE,
            "definitions": list(self.definitions),
            "n_judgments": self.n_judgments,
            "n_scored": self.n_scored,
            "n_unscored": self.n_unscored,
            "cells": [cell.as_dict() for cell in self.cells],
            "drift": [line.as_dict() for line in self.drift],
        }


def _split_for_recalibration(
    samples: Sequence[CalibrationSample], fit_fraction: float
) -> tuple[list[CalibrationSample], list[CalibrationSample]]:
    """The fit/holdout split: the older outcomes fit, the newer ones read.

    Chronological, because a calibration fitted on the future describes
    nothing about the past.
    """
    if not samples:
        return [], []
    cut = max(1, min(len(samples) - 1, int(len(samples) * fit_fraction)))
    return list(samples[:cut]), list(samples[cut:])


def calibration_report(
    events: Sequence[Any],
    *,
    sources: Sequence[OutcomeSource] = DEFAULT_SOURCES,
    bins: int = 10,
    window: int = 50,
    fit_fraction: float = 0.5,
    taus: Sequence[float] = (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9),
    generated_at: str | None = None,
) -> CalibrationReport:
    """The calibration report, read out of the ledger.

    Every cell gets: the numbers under each confidence definition, the
    reliability curve, the escalation sweep under each definition, the
    recalibration fitted on the older half and read on the newer half, and
    the drift measured against the cell's own history.
    """
    samples = samples_from_events(events, sources=sources)
    n_judgments = sum(
        len((getattr(event, "payload", {}) or {}).get("judgments", []) or [])
        for event in events
        if getattr(event, "type", None) == JUDGE_EVENT_TYPE
    )
    grouped: dict[tuple[str, str, str], list[CalibrationSample]] = {}
    for sample in samples:
        grouped.setdefault(sample.cell, []).append(sample)

    cell_reports: list[CalibrationCellReport] = []
    drift: list[DriftLine] = []
    for key in sorted(grouped):
        cell_samples = grouped[key]
        cell = cell_of(cell_samples, bins=bins)
        fit, holdout = _split_for_recalibration(cell_samples, fit_fraction)
        recalibration = recalibrate(fit, holdout)
        sweeps = {
            definition: tuple(
                escalation_sweep(cell_samples, taus, definition=definition)
            )
            for definition in CONFIDENCE_DEFINITIONS
        }
        lines = tuple(drift_of(cell_samples, window=window, bins=bins))
        cell_reports.append(
            CalibrationCellReport(
                cell=cell,
                recalibration=recalibration,
                sweeps=sweeps,
                drift=lines,
            )
        )
        drift.extend(lines)

    return CalibrationReport(
        generated_at=generated_at
        or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        n_judgments=n_judgments,
        n_scored=len(samples),
        cells=tuple(cell_reports),
        drift=tuple(drift),
    )


def drift_lines(
    events: Sequence[Any],
    *,
    sources: Sequence[OutcomeSource] = DEFAULT_SOURCES,
    bins: int = 10,
    window: int = 50,
) -> list[DriftLine]:
    """The drifting models, one line each — what the morning report carries."""
    return list(
        calibration_report(
            events, sources=sources, bins=bins, window=window
        ).drift
    )


# --- the nightly job -------------------------------------------------------------


def render_calibration_markdown(report: CalibrationReport) -> str:
    """The report as readable text — the same numbers the JSON carries."""
    lines: list[str] = []
    add = lines.append
    add(f"# Calibration — {report.generated_at}")
    add("")
    add(
        f"Confidence definition: **{CANONICAL_CONFIDENCE}**. "
        f"Judgments: {report.n_judgments}; scored: {report.n_scored}; "
        f"unscored (no outcome answered them): {report.n_unscored}."
    )
    add("")
    if not report.cells:
        add("No cell has a scored judgment yet.")
        return "\n".join(lines) + "\n"
    add("| cell | n | accuracy | Brier | ECE | mean confidence |")
    add("|---|---|---|---|---|---|")
    for cell_report in report.cells:
        cell = cell_report.cell
        add(
            f"| {cell.backend}:{cell.model} · {cell.task} | {cell.n} | "
            f"{_fmt(cell.accuracy)} | {_fmt(cell.brier)} | {_fmt(cell.ece)} | "
            f"{_fmt(cell.mean_confidence)} |"
        )
    add("")
    add("## The recalibrations")
    add("")
    for cell_report in report.cells:
        recalibration = cell_report.recalibration
        add(
            f"* **{cell_report.cell.name}** — {recalibration.kind}: "
            f"{recalibration.reason}"
        )
    add("")
    add("## The drift")
    add("")
    if not report.drift:
        add("No cell drifted.")
    for line in report.drift:
        add(f"* **{line.name}** — {line.kind}: {line.detail}")
        if line.retune:
            add(f"  * retune: {line.retune}")
    return "\n".join(lines) + "\n"


def _fmt(value: float | None) -> str:
    return "—" if value is None else f"{value:.4f}"


def write_calibration_report(report: CalibrationReport, directory: Path) -> Path:
    """Write the calibration report — the JSON and the readable text."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "calibration.json"
    path.write_text(
        json.dumps(report.as_dict(), indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )
    (directory / "calibration.md").write_text(
        render_calibration_markdown(report), encoding="utf-8"
    )
    return path


def run_calibration_job(
    ledger: Any,
    directory: Path,
    *,
    sources: Sequence[OutcomeSource] = DEFAULT_SOURCES,
    bins: int = 10,
    window: int = 50,
    fit_fraction: float = 0.5,
) -> tuple[Path, CalibrationReport]:
    """The nightly job: read the ledger, write the calibration report.

    The job reads the whole ledger, so it is a fold like every other view —
    the report it writes is the same one a cold process would compute.
    """
    report = calibration_report(
        ledger.events(), sources=sources, bins=bins, window=window, fit_fraction=fit_fraction
    )
    path = write_calibration_report(report, directory)
    return path, report
