"""The scripted critic: run the reference set through the checks and fold the
false-positive / false-negative table.

This is the seat's deliverable. The critic takes the reference set — real
renders with seeded defects — runs the scripted checks over every member, and
folds the verdicts into the table that ``core/critic/CALIBRATION.md``
publishes.

The counting rule is the cold-start seat's (:mod:`core.coldstart.calibration`),
and it is the rule that keeps the table honest:

* a planted defect of class K that the check targeting K does not fire on is
  a **false negative** — including a defect the check could not see at all,
  because a seeded defect is a seeded defect and the table must not hide a
  miss;
* a check firing on a member carrying a *different* class of planted defect
  is **excluded** from all four counts: the member is defective, so the
  report is neither true of its own class nor false;
* on a **clean control**, any firing is a false positive and any silence is
  a true negative.

The band is §1.9's: catch the seeded defects (no false negatives) and reject
no more than a set fraction of the clean ones (default one in ten).

Until a critic *model* is chosen and measured (X R4: the critic is "the
largest unchosen dependency in the whole stack"), every verdict wears
``verdict@scripted`` on its face. The table's first row is the baseline that
the model choice (week 3 item 18) has to beat.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Protocol, Sequence, runtime_checkable

from .checks import DEFAULT_THRESHOLDS, Thresholds, run_image_checks, run_mesh_checks
from .imaging import load_rgb
from .mesh import apply_mesh_defect, probe_scene
from .models import (
    DEFECT_KINDS,
    DEFECT_TARGETS,
    CheckOutcome,
    CriticVerdict,
    MeshStats,
)
from .set import MemberRecipe

__all__ = [
    "FP_BOUND",
    "ConfusionCounts",
    "CalibrationRow",
    "CalibrationTable",
    "Band",
    "CriticRunner",
    "ReferenceCritic",
    "score_member",
    "calibration_table",
]

#: §1.9's band: "reject no more than a set fraction of the clean ones" —
#: settable, defaulting to one in ten.
FP_BOUND = 0.10


@dataclass(frozen=True)
class ConfusionCounts:
    """One check's confusion over the reference set — counts, never percentages.

    TP: the check fired on a member carrying the defect it targets.
    FP: the check fired on a clean member.
    FN: a planted defect of the targeted class the check did not fire on.
    TN: a clean member the check left alone.
    """

    tp: int = 0
    fp: int = 0
    fn: int = 0
    tn: int = 0

    @property
    def fp_rate(self) -> float | None:
        return self.fp / (self.fp + self.tn) if (self.fp + self.tn) else None

    @property
    def fn_rate(self) -> float | None:
        return self.fn / (self.fn + self.tp) if (self.fn + self.tp) else None

    def add(self, key: str) -> "ConfusionCounts":
        from dataclasses import replace

        return replace(self, **{key: getattr(self, key) + 1})

    def as_dict(self) -> dict[str, Any]:
        return {
            "tp": self.tp,
            "fp": self.fp,
            "fn": self.fn,
            "tn": self.tn,
            "fp_rate": self.fp_rate,
            "fn_rate": self.fn_rate,
        }


@dataclass(frozen=True)
class CalibrationRow:
    """One published row: one defect class's confusion, over the whole set.

    The row is keyed by the **defect class**, not by the check, because that
    is what the brief asks for ("the first false-positive / false-negative
    table per defect class") and because it is what a reader needs: "when the
    scene has a hole in it, does the critic see it, and does it cry wolf on
    the clean frames?"
    """

    defect: str
    check: str
    counts: ConfusionCounts = field(default_factory=ConfusionCounts)
    label: str = "verdict@scripted"
    members: int = 0
    clean: int = 0

    @property
    def detected(self) -> bool:
        return self.counts.fn == 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "defect": self.defect,
            "check": self.check,
            "tp": self.counts.tp,
            "fp": self.counts.fp,
            "fn": self.counts.fn,
            "tn": self.counts.tn,
            "fp_rate": self.counts.fp_rate,
            "fn_rate": self.counts.fn_rate,
            "members": self.members,
            "clean": self.clean,
            "label": self.label,
        }


@dataclass(frozen=True)
class Band:
    """The target band (§1.9): catch the seeded defects; reject no more than a
    set fraction of the clean ones. A critic enters service only inside it."""

    fp_bound: float = FP_BOUND

    def holds_for(self, counts: ConfusionCounts) -> bool:
        if counts.fn > 0:
            return False
        rate = counts.fp_rate
        return rate is None or rate <= self.fp_bound

    def holds_for_table(self, table: "CalibrationTable") -> bool:
        return all(self.holds_for(row.counts) for row in table.rows)


@dataclass(frozen=True)
class CalibrationTable:
    """The reference set's FP/FN table: one row per defect class.

    ``in_band`` is the table's verdict: every row catches its seeded defects
    and none of them cries wolf on more than the band's fraction of the clean
    frames. When it is false the table says so, and the verdicts stay
    ``verdict@scripted`` — the plan's M2 named risk, as a measurement rather
    than a worry.
    """

    rows: tuple[CalibrationRow, ...] = ()
    totals: ConfusionCounts = field(default_factory=ConfusionCounts)
    band: Band = field(default_factory=Band)
    label: str = "verdict@scripted"
    night: str | None = None
    layers: tuple[str, ...] | None = None
    """The layers of the reference set the table was measured on.

    ``None`` means the whole set — the scripted critic sees both halves.
    A critic that reads pixels is measured on the image layer only, and the
    table says so rather than counting the classes it could not see.
    """

    @property
    def in_band(self) -> bool:
        return self.band.holds_for_table(self)

    def row_for(self, defect: str) -> CalibrationRow | None:
        for row in self.rows:
            if row.defect == defect:
                return row
        return None

    def as_dict(self) -> dict[str, Any]:
        return {
            "night": self.night,
            "label": self.label,
            "in_band": self.in_band,
            "band": {"fp_bound": self.band.fp_bound},
            "layers": list(self.layers) if self.layers is not None else None,
            "totals": self.totals.as_dict(),
            "rows": [row.as_dict() for row in self.rows],
        }


# -- scoring one member ------------------------------------------------------


def score_member(
    member: MemberRecipe,
    *,
    bases: Sequence[Any] = (),
    mesh_stats: MeshStats | None = None,
    thresholds: Thresholds | None = None,
    cache_dir: str | Path | None = None,
    blender_python: str | None = None,
) -> CriticVerdict:
    """The scripted critic's judgement of one member.

    An **image** member is scored by the image checks, on its derived image.
    A **mesh** member is scored by the mesh checks, on the base scene's
    geometry with the seeded defect applied — the defect lives in the mesh,
    so that is where it is looked for.

    The verdict carries every check's outcome, not just the fired ones, so
    the fold can tell a *miss* from a check that never ran.

    ``cache_dir`` is where the mesh probe's numbers are kept between runs:
    probing a scene means loading its ``.blend`` in Blender, which is slow,
    and the numbers do not change. The nightly re-score pays it once.
    """
    t = thresholds or DEFAULT_THRESHOLDS
    outcomes: list[CheckOutcome] = []

    if member.layer == "mesh":
        stats = mesh_stats
        if stats is None and member.mesh_path:
            stats = probe_scene(
                member.mesh_path,
                python=blender_python or _blender_python(),
                cache_dir=cache_dir,
            )
        if stats is None:
            raise ValueError(f"member {member.member_id!r} has no mesh to score")
        if member.defect:
            stats, recipe = apply_mesh_defect(stats, member.defect, seed=member.seed)
        outcomes.extend(run_mesh_checks(stats, t))
    else:
        if not member.derived_path:
            raise ValueError(f"member {member.member_id!r} has no derived image")
        image = load_rgb(member.derived_path)
        outcomes.extend(run_image_checks(image, t))
        # The mesh checks are run when the member has a mesh, so the table
        # can say what a mesh-bearing clean control looks like too.
        if member.mesh_path:
            try:
                stats = probe_scene(
                    member.mesh_path,
                    python=blender_python or _blender_python(),
                    cache_dir=cache_dir,
                )
                outcomes.extend(run_mesh_checks(stats, t))
            except Exception:  # noqa: BLE001 - a missing mesh is not a failure
                pass

    return CriticVerdict(
        member_id=member.member_id,
        base_id=member.base_id,
        defect=member.defect,
        checks=tuple(outcomes),
        layer=member.layer,
    )


def _blender_python() -> str | None:
    import os

    return os.environ.get("CRITIC_BLENDER_PYTHON") or os.environ.get(
        "CRITIC_INFINIGEN_PYTHON"
    )


# -- the fold -----------------------------------------------------------------


def calibration_table(
    verdicts: Iterable[CriticVerdict],
    *,
    night: str | None = None,
    fp_bound: float = FP_BOUND,
    layers: Sequence[str] | None = None,
) -> CalibrationTable:
    """Fold the verdicts into the FP/FN table — one row per defect class.

    A pure fold over the verdicts, so the table rebuilds from the members
    alone after a kill -9, and the same table comes out every time.

    ``layers`` says which layers of the reference set the critic was
    measured on. A critic that reads pixels cannot judge a defect that lives
    in the geometry — and the reference set's mesh defects are never
    re-rendered, so there is no picture of them to look at. Those members
    are **left out of the fold entirely**: they are neither a miss nor a
    clean control, and counting them as misses would measure the reference
    set's design rather than the critic. The rows for the classes the
    critic could not see come out empty, and the table says which layers it
    covers.
    """
    verdicts = list(verdicts)
    wanted_layers = tuple(layers) if layers is not None else None
    counts: dict[str, ConfusionCounts] = {d: ConfusionCounts() for d in DEFECT_KINDS}
    members: dict[str, int] = {d: 0 for d in DEFECT_KINDS}
    clean = 0

    for verdict in verdicts:
        if wanted_layers is not None and verdict.layer not in wanted_layers:
            continue
        defect = verdict.defect
        if defect is None:
            clean += 1
            # A clean control: every check that fires on it is a false
            # positive, and every check that leaves it alone is a true
            # negative. The check that *targets* a class is the one whose
            # false positives matter for that class's row.
            for outcome in verdict.checks:
                target = _class_targeted_by(outcome.check)
                if target is None:
                    continue
                counts[target] = counts[target].add("fp" if outcome.fired else "tn")
            continue

        if defect not in counts:
            continue
        members[defect] += 1
        target = DEFECT_TARGETS[defect]
        outcome = verdict.outcome(target)
        if outcome is None or not outcome.applicable:
            # The check could not even look: a defect nobody could see is a
            # free false negative, and the table must not hide a miss.
            counts[defect] = counts[defect].add("fn")
            continue
        counts[defect] = counts[defect].add("tp" if outcome.fired else "fn")

    rows = tuple(
        CalibrationRow(
            defect=defect,
            check=DEFECT_TARGETS[defect],
            counts=counts[defect],
            members=members[defect],
            clean=clean,
        )
        for defect in DEFECT_KINDS
    )
    totals = ConfusionCounts(
        tp=sum(r.counts.tp for r in rows),
        fp=sum(r.counts.fp for r in rows),
        fn=sum(r.counts.fn for r in rows),
        tn=sum(r.counts.tn for r in rows),
    )
    return CalibrationTable(
        rows=rows,
        totals=totals,
        band=Band(fp_bound=fp_bound),
        night=night,
        layers=wanted_layers,
    )


#: Which defect class each check is the *target* for. A check that targets
#: no class (there are none today, but the mapping is data) carries no
#: false-positive count.
_CLASS_BY_CHECK: dict[str, str] = {check: defect for defect, check in DEFECT_TARGETS.items()}


def _class_targeted_by(check: str) -> str | None:
    return _CLASS_BY_CHECK.get(check)


# -- the runner ---------------------------------------------------------------


@runtime_checkable
class ReferenceCritic(Protocol):
    """A critic that judges the reference set's members.

    The **seam** the critic selection sits in. Everything a critic has to be
    able to do to be measured on the reference set is here and nowhere else:

    * it names itself (``name``) — the name is on the verdict's face, so a
      verdict says which critic made it (``verdict@scripted``, ``verdict@…``);
    * it says which **layers** it can see (``layers``) — a critic that reads
      pixels cannot judge a defect that lives in the geometry, and saying so
      is how the fold keeps an out-of-domain class out of the table instead
      of counting it as a miss;
    * it scores a member (``score``) and returns a verdict carrying one
      outcome per defect class it judged.
    """

    name: str
    layers: tuple[str, ...]

    def score(
        self,
        member: MemberRecipe,
        *,
        bases: Sequence[Any] = (),
        thresholds: Thresholds | None = None,
        cache_dir: str | Path | None = None,
    ) -> CriticVerdict:
        """The critic's judgement of one member."""


class ScriptedReferenceCritic:
    """The scripted critic as a candidate: the checks, and nothing else.

    This is the **fallback** — the critic that is always there, needs no
    model, and is what the nightly re-score falls back to when the chosen
    critic cannot be built.
    """

    name = "scripted"
    layers = ("image", "mesh")

    def score(
        self,
        member: MemberRecipe,
        *,
        bases: Sequence[Any] = (),
        thresholds: Thresholds | None = None,
        cache_dir: str | Path | None = None,
        blender_python: str | None = None,
    ) -> CriticVerdict:
        return score_member(
            member,
            bases=bases,
            thresholds=thresholds,
            cache_dir=cache_dir,
            blender_python=blender_python,
        )


class CriticRunner:
    """Runs the reference set through a critic and keeps the verdicts.

    The runner holds the set's **recipes**, not its pixels: it re-derives a
    member's image from its base render when it needs to score it, which is
    what makes the set a recipe (the house rule) rather than a pile of
    pictures.

    The critic is a **parameter**: the default is the scripted one, and the
    selected critic is the one the night asks for (see
    :mod:`core.critic.select`).
    """

    def __init__(
        self,
        *,
        bases: Sequence[Any] = (),
        thresholds: Thresholds | None = None,
        blender_python: str | None = None,
        critic: ReferenceCritic | None = None,
        cache_dir: str | Path | None = None,
    ) -> None:
        self._bases = list(bases)
        self._thresholds = thresholds or DEFAULT_THRESHOLDS
        self._blender_python = blender_python
        self._critic = critic or ScriptedReferenceCritic()
        self._cache_dir = cache_dir
        self._verdicts: list[CriticVerdict] = []

    @property
    def critic(self) -> ReferenceCritic:
        """The critic this runner scores with."""
        return self._critic

    def score(self, member: MemberRecipe) -> CriticVerdict:
        """Score one member and remember the verdict."""
        verdict = self._critic.score(
            member,
            bases=self._bases,
            thresholds=self._thresholds,
            cache_dir=self._cache_dir,
            blender_python=self._blender_python,
        )
        self._verdicts.append(verdict)
        return verdict

    def score_all(self, members: Iterable[MemberRecipe]) -> list[CriticVerdict]:
        for member in members:
            self.score(member)
        return list(self._verdicts)

    @property
    def verdicts(self) -> list[CriticVerdict]:
        return list(self._verdicts)

    def table(self, *, night: str | None = None) -> CalibrationTable:
        """Fold the verdicts into the table.

        The table is measured on the layers the critic can see, so a critic
        that reads pixels is not charged with the geometry it never looked
        at.
        """
        return calibration_table(
            self._verdicts,
            night=night,
            layers=self._critic.layers,
        )
