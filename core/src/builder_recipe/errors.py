"""The error taxonomy of the recipe store.

Every refusal is a typed exception: the API half turns these into HTTP
statuses and audit rows, so the reasons stay machine-readable.
"""

from __future__ import annotations

from typing import Any, Sequence

__all__ = [
    "RecipeError",
    "NotFound",
    "IntegrityError",
    "SchemaDefinitionError",
    "SchemaViolation",
    "ConstraintViolation",
    "EditRejected",
    "BranchError",
    "MergeConflict",
]


class RecipeError(Exception):
    """Base class for every refusal from the recipe store."""


class NotFound(RecipeError):
    """A recipe, version, branch or edit does not exist."""


class IntegrityError(RecipeError):
    """A blob is missing or does not match its hash — fails loud (§5.2)."""


class SchemaDefinitionError(RecipeError):
    """A vocabulary param schema is outside the §1.5 subset."""


class SchemaViolation(RecipeError):
    """Params are outside the vocabulary schema — refused at the door."""

    def __init__(self, violations: Sequence[Any]) -> None:
        self.violations = list(violations)
        detail = "; ".join(
            f"{getattr(v, 'path', '?')}: {getattr(v, 'message', str(v))}"
            for v in self.violations
        )
        super().__init__(detail or "params are outside the vocabulary schema")


class ConstraintViolation(RecipeError):
    """A machine-checkable pre-render constraint failed."""

    def __init__(self, checks: Sequence[Any]) -> None:
        self.checks = list(checks)
        failed = [c for c in self.checks if getattr(c, "status", "") == "fail"]
        detail = "; ".join(
            f"{getattr(c, 'constraint', None) and c.constraint.name}: {getattr(c, 'reason', '')}"
            for c in failed
        )
        super().__init__(detail or "a constraint failed")


class EditRejected(RecipeError):
    """An edit was refused; no version was committed."""


class BranchError(RecipeError):
    """A branch operation is not allowed."""


class MergeConflict(BranchError):
    """A three-way merge found conflicting entries — a question, not a guess."""

    def __init__(self, conflicts: Sequence[Any]) -> None:
        self.conflicts = list(conflicts)
        paths = ", ".join(str(getattr(c, "path", c)) for c in self.conflicts)
        super().__init__(paths or "merge conflict")
