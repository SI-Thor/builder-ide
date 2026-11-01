"""The hybrid critic: the scripted checks first, the model only where they are out of band.

The scripted checks hold the band on eight of the nine defect classes
(``core/critic/CALIBRATION.md``). The ninth — ``floating_object`` — is the one
the checks miss: a prop hanging in the air looks, to a local statistic, like a
bump on a hillside, and the measurement that separates them is the one thing
the checks cannot do.

So the hybrid asks the model **only** about the classes the checks are out of
band on, and leaves the other eight to the checks. That is the whole idea,
and it is why it is cheap: the model runs on a minority of the classes, and
the majority of the work stays analytic.

The composition is on the verdict's face. Each outcome says which critic made
it, so a reader can see that the ``floating_object`` row came from the model
and the other rows came from the checks — and a table row is never the work
of two critics that cannot be told apart.
"""

from __future__ import annotations

from typing import Any, Sequence

from .checks import Thresholds
from .critic import ReferenceCritic, ScriptedReferenceCritic
from .models import DEFECT_TARGETS, CheckOutcome, CriticVerdict
from .set import MemberRecipe

__all__ = ["HybridCritic", "escalated_classes"]


def escalated_classes(
    scripted: ReferenceCritic | None = None,
    *,
    table: Any = None,
) -> tuple[str, ...]:
    """The classes the scripted critic is out of band on.

    Two ways to get the same answer, and the table wins when it has one:
    the **measured** table (the classes whose row the band does not hold)
    and the constant the published table currently says
    (:data:`core.critic.select.SCRIPTED_OUT_OF_BAND`). The table is the
    measurement, so it is preferred — a night that grows the set and moves a
    class out of band moves the hybrid's escalation with it.
    """
    if table is not None:
        failing = [
            row.defect
            for row in getattr(table, "rows", ())
            if getattr(row, "members", 0)
            and not _holds(row, table)
        ]
        if failing:
            return tuple(failing)
    from .select import SCRIPTED_OUT_OF_BAND

    return SCRIPTED_OUT_OF_BAND


def _holds(row: Any, table: Any) -> bool:
    band = getattr(table, "band", None)
    if band is None:
        return row.counts.fn == 0
    return band.holds_for(row.counts)


class HybridCritic:
    """The scripted checks, with a model on the classes they cannot hold.

    ``delegate`` is the critic that answers for the escalated classes — the
    model candidate the bake-off picked. ``escalate`` is the set of defect
    classes it answers for; it defaults to the classes the scripted critic
    is measured to be out of band on.
    """

    name = "hybrid"
    layers = ("image", "mesh")

    def __init__(
        self,
        delegate: ReferenceCritic,
        *,
        escalate: Sequence[str] | None = None,
        scripted: ReferenceCritic | None = None,
    ) -> None:
        self._scripted = scripted or ScriptedReferenceCritic()
        self._delegate = delegate
        self._escalate = tuple(
            escalate
            if escalate is not None
            else escalated_classes(self._scripted)
        )

    @property
    def delegate(self) -> ReferenceCritic:
        """The critic that answers for the escalated classes."""
        return self._delegate

    @property
    def escalate(self) -> tuple[str, ...]:
        """The defect classes the delegate answers for."""
        return self._escalate

    def score(
        self,
        member: MemberRecipe,
        *,
        bases: Sequence[Any] = (),
        thresholds: Thresholds | None = None,
        cache_dir: str | Path | None = None,
        blender_python: str | None = None,
    ) -> CriticVerdict:
        """The checks' verdict, with the delegate's on the escalated classes."""
        scripted = self._scripted.score(
            member,
            bases=bases,
            thresholds=thresholds,
            cache_dir=cache_dir,
        )
        targets = {
            DEFECT_TARGETS[defect]
            for defect in self._escalate
            if defect in DEFECT_TARGETS
        }
        if not targets:
            return self._verdict(scripted, scripted.checks)

        # The delegate is asked only when its answer can change the table:
        # on a member carrying an escalated class, and on a clean control
        # (where any firing is a false positive). A member of another class
        # is judged by the checks, and asking the model about it would cost
        # a call to learn nothing the fold would use.
        escalated_class = member.defect in self._escalate
        if not (escalated_class or member.defect is None):
            # The checks answer **by design** here: the hybrid's model is
            # only for the class they cannot hold. Nothing fell back, and
            # the verdict says so.
            return self._verdict(scripted, scripted.checks)
        if member.layer not in self._delegate.layers:
            # The hybrid needed its model and the model cannot see this
            # member. The checks stand in, and that **is** a fallback.
            return self._verdict(scripted, scripted.checks, degraded="scripted")

        try:
            delegate = self._delegate.score(
                member,
                bases=bases,
                thresholds=thresholds,
                cache_dir=cache_dir,
            )
        except Exception as exc:  # noqa: BLE001 - any failure is a fallback
            # The model could not be reached: no server, no weights, no GPU,
            # no key. That is a **fallback**, not a crash. The checks answer
            # for the class they can answer, the reason is on the verdict's
            # face, and the night never mistakes the fallback for a model
            # verdict.
            return self._verdict(
                scripted,
                [
                    CheckOutcome(
                        check=outcome.check,
                        fired=outcome.fired,
                        detail=(
                            f"{outcome.detail} — the delegate "
                            f"({self._delegate.name}) could not be reached "
                            f"({type(exc).__name__}: {exc})"
                        ),
                        measured=outcome.measured,
                        applicable=outcome.applicable,
                    )
                    for outcome in scripted.checks
                ],
                degraded="scripted",
            )
        merged: list[CheckOutcome] = []
        fell_back = False
        for outcome in scripted.checks:
            if outcome.check not in targets:
                merged.append(outcome)
                continue
            replacement = delegate.outcome(outcome.check)
            if replacement is None:
                # The delegate could not judge this class on this member
                # (a mesh member, or a class it does not see). The checks'
                # answer stands, and the verdict says the model was not used.
                fell_back = True
                merged.append(
                    CheckOutcome(
                        check=outcome.check,
                        fired=outcome.fired,
                        detail=(
                            f"{outcome.detail} — the delegate "
                            f"({self._delegate.name}) could not judge this class"
                        ),
                        measured=outcome.measured,
                        applicable=outcome.applicable,
                    )
                )
                continue
            merged.append(
                CheckOutcome(
                    check=replacement.check,
                    fired=replacement.fired,
                    detail=(
                        f"{replacement.detail} — judged by {self._delegate.name} "
                        f"(the scripted checks are out of band on this class)"
                    ),
                    measured=replacement.measured,
                    applicable=replacement.applicable,
                )
            )

        # A class the delegate judged but the checks never looked at (the
        # checks did not run for this member) still belongs in the verdict:
        # a clean control's false positives are counted over the checks that
        # fired, and the delegate's answer is a firing too.
        for outcome in delegate.checks:
            if outcome.check in targets and not any(
                o.check == outcome.check for o in merged
            ):
                merged.append(
                    CheckOutcome(
                        check=outcome.check,
                        fired=outcome.fired,
                        detail=(
                            f"{outcome.detail} — judged by {self._delegate.name} "
                            f"(the scripted checks are out of band on this class)"
                        ),
                        measured=outcome.measured,
                        applicable=outcome.applicable,
                    )
                )

        return self._verdict(
            scripted,
            merged,
            # The verdict names the critic that made it. The hybrid made
            # this one — unless it needed its model for an escalated class
            # and the model could not judge it, in which case the checks
            # stood in and the verdict says so ("scripted" is the engine's
            # name for the fallback mode).
            degraded="scripted" if fell_back else self.name,
        )

    def _verdict(
        self,
        scripted: CriticVerdict,
        checks: Sequence[CheckOutcome],
        *,
        degraded: str | None = None,
    ) -> CriticVerdict:
        """The hybrid's verdict: the checks' member identity, the hybrid's name."""
        return CriticVerdict(
            member_id=scripted.member_id,
            base_id=scripted.base_id,
            defect=scripted.defect,
            checks=tuple(checks),
            label=f"verdict@{self.name}",
            degraded=degraded or self.name,
            layer=scripted.layer,
        )
