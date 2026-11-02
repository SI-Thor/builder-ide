"""Fork-at-point: cut a branch of the canon at a point, and leave the original.

A rewind is a fork, never a deletion (§2.4 of the design note). The canon's
own branch does not move backwards and its versions are never removed: the
fork is a new branch whose head is the version the rewind happened at, and
whose base says where it was cut from. The original branch stays exactly
where it was.
"""

from __future__ import annotations

from dataclasses import dataclass

from core.recipe.models import Actor, Branch
from core.recipe.store import RecipeStore

__all__ = [
    "RewindPoint",
    "points",
    "point_at_version",
    "fork_at_point",
    "main_branch",
]


@dataclass(frozen=True)
class RewindPoint:
    """Where a rewind happens: the version, and the ledger's seq there.

    The seq is what makes the point a *point*: the events after it are the
    ones in play, and the events before it are the prefix the fork shares
    with the canon.
    """

    version: str
    seq: int
    at: str = ""
    recipe: str = ""


def points(store: RecipeStore) -> list[RewindPoint]:
    """The canon's timeline: every committed version, in ledger order."""
    found: list[RewindPoint] = []
    for event in store.ledger.events(types=["version.committed"]):
        version = event.payload.get("version")
        if not version:
            continue  # the spine's spelling; the recipe store skips it too
        found.append(
            RewindPoint(
                version=str(version),
                seq=int(event.seq or 0),
                at=event.at,
                recipe=str(event.payload.get("recipe") or ""),
            )
        )
    return found


def point_at_version(store: RecipeStore, version: str) -> RewindPoint:
    """The rewind point of one version."""
    for point in points(store):
        if point.version == version:
            return point
    raise LookupError(f"no version {version!r} in the ledger")


def fork_at_point(
    store: RecipeStore,
    *,
    version: str,
    name: str,
    actor: Actor,
    purpose: str = "work-order",
    protected: bool = False,
) -> Branch:
    """Cut a branch of the canon at a version.

    The canon's own branch is not touched: nothing is deleted and no head
    moves backwards. The fork's head is the version it was cut at, and its
    base is that same version — the prefix the fork and the canon share.
    """
    record = store.get_version(version)
    return store.create_branch(
        name=name,
        recipe=record.recipe,
        head=version,
        purpose=purpose,
        actor=actor,
        base=version,
        protected=protected,
    )


def main_branch(store: RecipeStore, recipe: str) -> Branch:
    """The canon's branch: the one ``main`` points at."""
    for branch in store.list_branches(recipe_id=recipe):
        if branch.purpose == "main":
            return branch
    raise LookupError(f"recipe {recipe!r} has no main branch")
