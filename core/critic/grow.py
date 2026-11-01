"""The set grows nightly: add the sweep's new renders and re-score.

This is the function the night runner calls. It does three things, in this
order:

1. **Harvest** the sweep's real renders (read-only — the sweep belongs to
   another night's work).
2. **Grow** the reference set: for each base that is not already in the set,
   add the members it earns, up to the target. The members already in the
   set are never rebuilt and never duplicated, so the set grows rather than
   churning.
3. **Re-score** the whole set and publish the table.

The set's target is §1.9's "~30 renders with seeded defects", and the growth
is **sized to the night's unused lane** — the same rule the cold-start seat
uses (:func:`core.coldstart.calibration.plan_nightly_growth`): at most a
night's cap, never past the target, and never more than the leftover rail
affords. The cost per member is the CPU-lane cost of a scripted check, and
the GPU lane is untouched by design — no model, no prediction, no GPU.

The function is deliberately **pure with respect to the ledger**: it returns
the verdicts and the table, and it writes the manifest and the published
table to disk. The caller (the night runner) is the one that audits them.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from .critic import CalibrationTable, CriticRunner, ReferenceCritic
from .harvest import harvest
from .set import (
    DEFAULT_SEED,
    TARGET_MEMBER_COUNT,
    MemberRecipe,
    build_members,
    materialise,
    read_bases,
    read_manifest,
    write_manifest,
)

__all__ = [
    "MAX_MEMBERS_PER_NIGHT",
    "COST_PER_MEMBER_WALL_MINUTES",
    "NightBudget",
    "GrowthResult",
    "plan_growth",
    "grow",
    "ensure_derived",
]

#: How many members one night's unused lane may add at most — the
#: cold-start seat's cap (8).
MAX_MEMBERS_PER_NIGHT = 8

#: One member's cost: a scripted analytic check on the CPU lane. GPU-minutes
#: are zero by design — the scripted critic runs no model.
COST_PER_MEMBER_WALL_MINUTES = 0.5


@dataclass(frozen=True)
class NightBudget:
    """The night's leftover lane — the budget the growth is sized to.

    The same three axes as the core's :class:`core.records.Rail`, and the
    same rule: the batch is "the cheapest data the project will ever buy",
    so it is sized to what the night did not spend.
    """

    wall_minutes: float = 0.0
    gpu_minutes: float = 0.0
    hosted_cents: int = 0

    def can_afford(self, count: int) -> bool:
        return count * COST_PER_MEMBER_WALL_MINUTES <= self.wall_minutes


@dataclass(frozen=True)
class GrowthResult:
    """What one night's growth did."""

    added: tuple[MemberRecipe, ...] = ()
    verdicts: tuple[Any, ...] = ()
    table: CalibrationTable | None = None
    manifest_path: str | None = None
    table_path: str | None = None
    bases_seen: int = 0
    already_known: int = 0
    critic: str = "scripted"
    """The critic the set was scored with — the parameter, and its name."""

    @property
    def added_count(self) -> int:
        return len(self.added)

    def as_dict(self) -> dict[str, Any]:
        return {
            "added": [m.as_dict() for m in self.added],
            "bases_seen": self.bases_seen,
            "already_known": self.already_known,
            "critic": self.critic,
            "manifest_path": self.manifest_path,
            "table_path": self.table_path,
            "table": self.table.as_dict() if self.table else None,
        }


def plan_growth(
    *,
    existing: int,
    budget: NightBudget,
    target: int = TARGET_MEMBER_COUNT,
    max_per_night: int = MAX_MEMBERS_PER_NIGHT,
) -> int:
    """How many members tonight's unused lane may add.

    The lane's leftover wall-clock is the budget; the plan never exceeds the
    night's cap, the set's target, or what the leftover affords.
    """
    affordable = max_per_night
    if COST_PER_MEMBER_WALL_MINUTES > 0:
        affordable = min(
            affordable,
            int(budget.wall_minutes // COST_PER_MEMBER_WALL_MINUTES),
        )
    return max(0, min(max_per_night, max(0, target - existing), affordable))


def _has_geometry(member: MemberRecipe, cache_dir: str | Path) -> bool:
    """Does the member's scene hold any props to judge?

    Two of the rebuilt scenes hold no props at all — the sweep planted them
    but the assets never arrived — and a mesh member built on one of them
    judges nothing, so it is left out of the set.
    """
    from .checks import props_of
    from .mesh import probe_scene

    if not member.mesh_path:
        return False
    try:
        stats = probe_scene(member.mesh_path, cache_dir=cache_dir)
    except Exception:  # noqa: BLE001 - no probe, no mesh member
        return False
    return bool(props_of(stats))


def ensure_derived(
    members: Sequence[MemberRecipe],
    bases: Sequence[Any],
    cache_dir: str | Path,
) -> list[MemberRecipe]:
    """Re-derive the members whose derived image is not on disk.

    The derived image is a **cache**: the recipe is the truth, and a member
    whose cache was cleared — or whose manifest still points at a cache in
    another tree — is re-derived from its base render and its own recipe.

    Without this the nightly re-score dies on the first missing file, and the
    table never comes back. The set is a recipe; this is what makes it one.

    A member whose plant cannot be re-made (its base render is gone) is left
    alone and reported by the caller, rather than being silently dropped: a
    member that cannot be scored is a hole in the table, and the table says
    so.
    """
    cache = Path(cache_dir)
    out: list[MemberRecipe] = []
    for member in members:
        if member.layer != "image":
            out.append(member)
            continue
        if member.derived_path and Path(member.derived_path).is_file():
            out.append(member)
            continue
        try:
            out.append(materialise(member, bases, out_dir=cache))
        except (KeyError, OSError, ValueError):
            out.append(member)
    return out


def grow(
    *,
    sweep_root: str | Path | None = None,
    manifest_path: str | Path,
    cache_dir: str | Path,
    table_path: str | Path | None = None,
    night: str | None = None,
    budget: NightBudget | None = None,
    target: int = TARGET_MEMBER_COUNT,
    seed: int = DEFAULT_SEED,
    thresholds: Any = None,
    blender_python: str | None = None,
    publish: bool = True,
    critic: ReferenceCritic | None = None,
) -> GrowthResult:
    """Grow the reference set from the sweep and re-score it.

    The night runner calls this. It is safe to call every night: the second
    call with no new renders adds nothing and re-publishes the same table.

    ``critic`` is the critic the set is scored with — the **parameter**. It
    defaults to the scripted checks, which are also the fallback when the
    chosen critic cannot be built.
    """
    manifest_path = Path(manifest_path)
    cache_dir = Path(cache_dir)

    existing = read_manifest(manifest_path) if manifest_path.is_file() else []
    known = {m.member_id for m in existing}
    known_bases = {m.base_id for m in existing}

    bases = list(harvest(sweep_root))
    budget = budget or NightBudget(wall_minutes=30.0)

    # A member's recipe names the render it was made from — and, for a
    # texture swap, the render it borrowed from. Re-deriving a member needs
    # *those* bases, so the manifest's own bases are read back for them.
    recipe_bases = read_bases(manifest_path) if manifest_path.is_file() else []
    if recipe_bases:
        bases = recipe_bases + [b for b in bases if b.id not in {x.id for x in recipe_bases}]

    room = plan_growth(existing=len(existing), budget=budget, target=target)
    if room <= 0:
        # No room: the set is at its target. Re-score what is there, so the
        # published table still reflects the current sweep.
        scored = ensure_derived(existing, bases, cache_dir)
        runner = CriticRunner(
            bases=bases,
            thresholds=thresholds,
            blender_python=blender_python,
            critic=critic,
            cache_dir=cache_dir,
        )
        verdicts = runner.score_all(scored)
        table = runner.table(night=night)
        written = None
        if publish and table_path is not None:
            from .publish import publish_table

            written = publish_table(
                table,
                table_path,
                members=scored,
                critic=getattr(critic, "name", "scripted") if critic else "scripted",
            )
        return GrowthResult(
            added=(),
            verdicts=tuple(verdicts),
            table=table,
            manifest_path=str(manifest_path) if manifest_path.is_file() else None,
            table_path=str(written) if written else None,
            bases_seen=len(bases),
            already_known=len(known),
            critic=getattr(critic, "name", "scripted") if critic else "scripted",
        )

    # The plan is made over **every** base, not only the fresh ones: the
    # defect classes are handed out in a rotation over the bases, and if
    # the rotation restarted each night it would hand out the same first
    # classes every night — and two of the nine classes would never get a
    # member at all. The bases already in the set are skipped by their
    # member id, so the set does not churn.
    candidates = build_members(
        bases,
        target=room,
        seed=seed,
        night=night,
        existing=known,
    )

    built = []
    for member in candidates:
        built_member = materialise(member, bases, out_dir=cache_dir)
        if built_member.recipe.get("placed") is False:
            # The plant could not make this defect visible in this frame —
            # a member that does not exist is not a false negative.
            continue
        if built_member.layer == "mesh" and not _has_geometry(built_member, cache_dir):
            continue
        built.append(built_member)

    # The whole set is scored, not just the new members: the table is a
    # property of the set, and the set just grew.
    all_members = ensure_derived(list(existing) + list(built), bases, cache_dir)
    runner = CriticRunner(
        bases=bases,
        thresholds=thresholds,
        blender_python=blender_python,
        critic=critic,
        cache_dir=cache_dir,
    )
    verdicts = runner.score_all(all_members)
    table = runner.table(night=night)

    write_manifest(all_members, manifest_path, bases=bases)
    written = None
    if publish and table_path is not None:
        from .publish import publish_table

        written = publish_table(
            table,
            table_path,
            members=all_members,
            critic=getattr(critic, "name", "scripted") if critic else "scripted",
        )

    return GrowthResult(
        added=tuple(built),
        verdicts=tuple(verdicts),
        table=table,
        manifest_path=str(manifest_path),
        table_path=str(written) if written else None,
        bases_seen=len(bases),
        already_known=len(known),
        critic=getattr(critic, "name", "scripted") if critic else "scripted",
    )
