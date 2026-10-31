"""Pre-render constraint checks — core-spec v2 §1.1 and §2.3.5.

The pipeline checks constraints **before** renders and before the critic: the
drip-line constraint failed *before* the critic ran (D §04:2x). The checks are
scripted analytic computations over the recipe's own parameters, run on the CPU
lane and deterministic — there is no physics engine in this system and no
"sim" (X R11, §7.14).

One analytic reading per constraint kind (the spec fixes the kinds, not their
arithmetic; this is the recipe-side reading and is documented so the engine can
re-implement it identically):

==================  ==========================  ==========================
kind                parameter                   test
==================  ==========================  ==========================
``load_floor``      ``load_factor``             ``load_factor >= value``
``keep_clear``      ``clearance_m``             ``clearance_m >= value``
``reachability``    ``reach_m``                 ``reach_m >= value``
``scale_bounds``    ``scale``                   ``abs(scale - 1) <= value``
``budget_custom``   ``budget``                  ``budget <= value``
``watertight``      —                           deferred to the geometry check
==================  ==========================  ==========================

``watertight`` is a geometry kind: the mesh does not exist yet at edit time, so
the check is deferred to the merge gate's geometry check, which runs after the
build and before the critic (§2.3.3). A deferred check is not a failure.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from core.recipe.models import Constraint, Recipe
from core.recipe.noderegistry import NodeRegistry

__all__ = ["ConstraintCheck", "ConstraintChecker", "ANALYTIC_KINDS"]

CheckStatus = Literal["pass", "fail", "deferred"]

#: kind -> (parameter, comparison)
ANALYTIC_KINDS: dict[str, tuple[str, str]] = {
    "load_floor": ("load_factor", "min"),
    "keep_clear": ("clearance_m", "min"),
    "reachability": ("reach_m", "min"),
    "scale_bounds": ("scale", "scale"),
    "budget_custom": ("budget", "max"),
}


@dataclass(frozen=True)
class ConstraintCheck:
    """The outcome of one constraint against one document."""

    name: str
    kind: str
    status: CheckStatus
    entry_path: str | None
    reason: str
    value: float | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "kind": self.kind,
            "status": self.status,
            "entry_path": self.entry_path,
            "reason": self.reason,
            "value": self.value,
        }


class ConstraintChecker:
    """Checks the constraints that can be checked before anything is rendered."""

    def __init__(self, registry: NodeRegistry | None = None) -> None:
        self.registry = registry

    def check(
        self, recipe: Recipe, touched: set[str] | None = None
    ) -> list[ConstraintCheck]:
        """Check project-level constraints and the touched entries' own ones."""
        checks: list[ConstraintCheck] = []

        for constraint in recipe.constraints:
            checks.append(self._check_one(recipe, constraint, owner=None))

        for path, entry in sorted(recipe.entries.items()):
            if touched is not None and path not in touched:
                continue
            for constraint in entry.constraints:
                checks.append(self._check_one(recipe, constraint, owner=path))

        return checks

    # -- internals -------------------------------------------------------

    def _resolve_target(
        self, recipe: Recipe, constraint: Constraint, owner: str | None
    ) -> tuple[str | None, CheckStatus | None, str]:
        """Resolve the entry a constraint refers to.

        Returns (entry_path, status, reason). ``status`` is None when the
        referent resolved; otherwise it says whether the check is deferred
        (the referent is not knowable yet) or fails (it is knowable and
        wrong).
        """
        if constraint.ref is None:
            if owner is not None:
                return owner, None, ""
            return None, "deferred", "the constraint names no referent"

        if constraint.ref in recipe.entries:
            return constraint.ref, None, ""

        if self.registry is not None:
            node = self.registry.resolve_node(constraint.ref)
            if node is not None:
                if node.entry_path in recipe.entries:
                    return node.entry_path, None, ""
                return (
                    None,
                    "fail",
                    f"node {constraint.ref!r} points at a missing entry",
                )

        if self.registry is not None and self.registry.published:
            return (
                None,
                "fail",
                f"the constraint references unknown node {constraint.ref!r}",
            )

        return (
            None,
            "deferred",
            f"node {constraint.ref!r} cannot be resolved: the node registry "
            "has not been published for this version",
        )

    def _check_one(
        self, recipe: Recipe, constraint: Constraint, owner: str | None
    ) -> ConstraintCheck:
        def result(status: CheckStatus, reason: str, entry_path: str | None = None) -> ConstraintCheck:
            return ConstraintCheck(
                name=constraint.name,
                kind=constraint.kind,
                status=status,
                entry_path=entry_path,
                reason=reason,
                value=constraint.value,
            )

        if constraint.kind == "watertight":
            return result(
                "deferred",
                "watertight is a geometry check: it runs after the build and "
                "before the critic",
                owner,
            )

        if constraint.kind not in ANALYTIC_KINDS:
            return result("deferred", f"no analytic reading for kind {constraint.kind!r}", owner)

        if constraint.value is None:
            return result("deferred", "the constraint carries no threshold", owner)

        entry_path, refusal, reason = self._resolve_target(recipe, constraint, owner)
        if entry_path is None:
            return result(refusal or "deferred", reason or "the referent could not be resolved", owner)

        entry = recipe.entries.get(entry_path)
        if entry is None:
            return result("fail", f"the referenced entry {entry_path!r} is not in the recipe")

        parameter, comparison = ANALYTIC_KINDS[constraint.kind]
        if parameter not in entry.params:
            return result(
                "fail",
                f"there is no {parameter!r} parameter to check on {entry_path!r}",
                entry_path,
            )

        actual = entry.params[parameter]
        if isinstance(actual, bool) or not isinstance(actual, (int, float)):
            return result(
                "fail",
                f"{parameter!r} on {entry_path!r} is not a number",
                entry_path,
            )

        threshold = constraint.value
        if comparison == "min":
            if actual < threshold:
                return result(
                    "fail",
                    f"{parameter} {actual} is below the required {threshold}",
                    entry_path,
                )
        elif comparison == "max":
            if actual > threshold:
                return result(
                    "fail",
                    f"{parameter} {actual} is above the allowed {threshold}",
                    entry_path,
                )
        elif comparison == "scale":
            if abs(float(actual) - 1.0) > threshold:
                return result(
                    "fail",
                    f"{parameter} {actual} is outside the tolerance {threshold}",
                    entry_path,
                )

        return result("pass", f"{parameter} {actual} satisfies the constraint", entry_path)
