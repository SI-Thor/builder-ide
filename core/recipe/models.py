"""The recipe models of core-spec v2 §1.1, §1.2, §1.4.0 and §1.8.

The records themselves live in :mod:`core.records` — one definition each,
shared with every other seat. This module re-exports them (so
``from core.recipe.models import Recipe`` still works and
``core.recipe.models.Recipe is core.records.Recipe`` is true) and adds the
three records only the recipe store owns: the recipe's own projection, a
kid actor's pending branch proposal, and the report of the pre-render
checks.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from core.records import (
    MAX_EDIT_MESSAGE_CHARS,
    MAX_OPS_PER_EDIT,
    Actor,
    ActorKind,
    AuditEvent,
    Branch,
    BranchPurpose,
    Constraint,
    ConstraintKind,
    EnginePin,
    EntryKind,
    GeneratorRef,
    NodeRef,
    Op,
    Recipe,
    RecipeEdit,
    RecipeEntry,
    RecipeVersion,
)

__all__ = [
    "Actor",
    "ActorKind",
    "EntryKind",
    "ConstraintKind",
    "BranchPurpose",
    "EnginePin",
    "GeneratorRef",
    "Constraint",
    "RecipeEntry",
    "Recipe",
    "Op",
    "RecipeEdit",
    "RecipeVersion",
    "Branch",
    "NodeRef",
    "AuditEvent",
    "RecipeRecord",
    "BranchProposal",
    "ValidationReport",
    "MAX_OPS_PER_EDIT",
    "MAX_EDIT_MESSAGE_CHARS",
]


class RecipeRecord(BaseModel):
    """The projection of a recipe: its identity and its root version."""

    id: str
    name: str
    root_version: str
    created_at: str


class BranchProposal(BaseModel):
    """A kid actor's branch choice, pending the owner's confirmation.

    Magnus's apply is a proposal, not an edit: a branch apply is a real edit,
    so his is ``branch.proposed`` until Casey confirms it (§7.15).
    """

    id: str
    branch: str
    proposed_head: str
    by: Actor
    at: str
    state: Literal["pending", "confirmed", "declined"] = "pending"


class ValidationReport(BaseModel):
    """What the pre-render checks found about a candidate document."""

    ok: bool
    touched: list[str] = Field(default_factory=list)
    schema_violations: list[dict[str, Any]] = Field(default_factory=list)
    constraint_checks: list[dict[str, Any]] = Field(default_factory=list)
