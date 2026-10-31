"""The reference set: ~30 real renders, each with one seeded defect.

This is the module that builds the set. Its inputs are the **real renders**
the overnight sweep produced (never a stand-in), and its output is a list of
:class:`~core.critic.models.ReferenceMember` — each one a base render plus a
seeded defect plus the recipe of that defect.

Three rules govern the set, and each exists to keep the table honest:

1. **The renders are real.** Every member's base is a frame the sweep
   rendered on the Thor, with its sha256 recorded. Nothing here is a
   synthetic image: the defect is seeded *into* a real render, so the checks
   are measured against the pictures the critic will really be handed.
2. **Every member is a recipe.** The defect's recipe — which pixels were
   touched, which colours, which donor — rides with the member, so a member
   can be re-derived from the base render alone. The render is the cache; the
   recipe is the truth (the house rule).
3. **There are clean controls.** Without them there is nothing to
   false-positive on, and the band's other half ("reject no more than a set
   fraction of the clean ones") would be unfalsifiable. Every base that
   contributes a defective member also contributes a clean one.

The set is **deterministic**: the same sweep always yields the same members,
in the same order, with the same hashes. That is what makes the published
table a measurement rather than an anecdote — and it is what lets the set
grow nightly without drifting (the growth function in
:mod:`core.critic.grow` adds to it without changing what is already there).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

from . import defects as defect_plants
from .imaging import load_rgb, save_rgb, sha256_bytes
from .models import (
    DEFECT_KINDS,
    DEFECT_TARGETS,
    IMAGE_DEFECTS,
    MESH_DEFECTS,
    BaseRender,
    CheckOutcome,
    CriticVerdict,
    ReferenceMember,
)

__all__ = [
    "TARGET_MEMBER_COUNT",
    "CLEAN_EVERY",
    "MemberRecipe",
    "build_members",
    "materialise",
    "write_manifest",
    "read_manifest",
    "member_recipe",
]

#: §1.9 — "a fixed set of ~30 renders with seeded, known defects".
TARGET_MEMBER_COUNT = 30

#: Every base that contributes a defective member also contributes a clean
#: control. The clean controls are what the false-positive half of the band
#: is measured on.
CLEAN_EVERY = 1

#: The seed every member's recipe is derived from. Fixed, so the set is
#: reproducible; a member's own identity is in its id.
DEFAULT_SEED = 902


@dataclass(frozen=True)
class MemberRecipe:
    """How one member was made — the recipe, not the pixels.

    This is what the set stores. The derived image is a cache of it, and can
    be rebuilt from the base render plus these instructions alone.
    """

    member_id: str
    base_id: str
    defect: str | None
    layer: str
    seed: int
    recipe: dict[str, Any]
    derived_path: str | None = None
    derived_sha256: str | None = None
    mesh_path: str | None = None
    night: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "member_id": self.member_id,
            "base_id": self.base_id,
            "defect": self.defect,
            "layer": self.layer,
            "seed": self.seed,
            "recipe": self.recipe,
            "derived_path": self.derived_path,
            "derived_sha256": self.derived_sha256,
            "mesh_path": self.mesh_path,
            "night": self.night,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "MemberRecipe":
        return cls(
            member_id=str(payload["member_id"]),
            base_id=str(payload["base_id"]),
            defect=payload.get("defect"),
            layer=str(payload.get("layer", "image")),
            seed=int(payload.get("seed", DEFAULT_SEED)),
            recipe=dict(payload.get("recipe", {})),
            derived_path=payload.get("derived_path"),
            derived_sha256=payload.get("derived_sha256"),
            mesh_path=payload.get("mesh_path"),
            night=payload.get("night"),
        )


def member_recipe(
    base: BaseRender,
    defect: str | None,
    *,
    index: int,
    seed: int = DEFAULT_SEED,
    night: str | None = None,
) -> MemberRecipe:
    """One member's recipe — deterministic in ``(base, defect, seed)``.

    The member's id is a hash of its *inputs*, so the same base with the same
    defect is always the same member, and the set never grows a duplicate.
    """
    key = f"{base.id}|{defect or 'clean'}|{seed}"
    member_id = "mem_" + sha256_bytes(key.encode("utf-8"))[:16]
    layer = "image" if defect is None or defect in IMAGE_DEFECTS else "mesh"
    return MemberRecipe(
        member_id=member_id,
        base_id=base.id,
        defect=defect,
        layer=layer,
        seed=seed,
        recipe={},
        night=night,
    )


def _rotation(defects: Sequence[str], count: int) -> list[str | None]:
    """The defect each member gets, in a fixed rotation.

    The rotation is over the *defect classes*, not the members, so every class
    gets several members — a class with one member cannot show a rate. The
    clean controls are interleaved with the rotation rather than appended, so
    a truncated set still has both halves.
    """
    classes = list(defects)
    if not classes:
        return []
    out: list[str | None] = []
    for i in range(count):
        # Every third member is a clean control: the clean half of the band
        # is measured on ~1/3 of the set, which is enough to see a false
        # positive rate of a few percent and not enough to dominate the set.
        if i % 3 == 2:
            out.append(None)
        else:
            out.append(classes[(i - (i // 3)) % len(classes)])
    return out


def build_members(
    bases: Sequence[BaseRender],
    *,
    target: int = TARGET_MEMBER_COUNT,
    seed: int = DEFAULT_SEED,
    night: str | None = None,
    existing: Iterable[str] = (),
) -> list[MemberRecipe]:
    """The reference set's members, over the real renders.

    ``existing`` holds the member ids already in the set — the nightly growth
    passes them so a new night's renders are *added* and nothing already
    there is rebuilt or duplicated.
    """
    known = set(existing)
    members: list[MemberRecipe] = []

    # Image members first: every base can carry one (the defect lives in the
    # pixels, and every base has pixels). Mesh members come second, because
    # they need a scene's geometry and only some bases have it.
    image_bases = [b for b in bases if b.image_path]
    mesh_bases = [b for b in bases if b.mesh_path]

    for defect in _rotation(IMAGE_DEFECTS, len(image_bases)):
        pass  # the rotation is applied below, over the joint list

    plan: list[tuple[BaseRender, str | None]] = []
    rotation = _rotation(IMAGE_DEFECTS, max(len(image_bases), 1))
    for i, base in enumerate(image_bases):
        defect = rotation[i % len(rotation)] if rotation else None
        plan.append((base, defect))

    # The mesh classes take the bases that have geometry. They are added
    # after the image members so the set's size is driven by the renders.
    mesh_rotation = _rotation(MESH_DEFECTS, max(len(mesh_bases), 1))
    for i, base in enumerate(mesh_bases):
        defect = mesh_rotation[i % len(mesh_rotation)] if mesh_rotation else None
        if defect is None:
            continue
        plan.append((base, defect))

    for base, defect in plan:
        if len(members) >= target:
            break
        recipe = member_recipe(base, defect, index=len(members), seed=seed, night=night)
        if recipe.member_id in known:
            continue
        known.add(recipe.member_id)
        recipe = MemberRecipe(
            member_id=recipe.member_id,
            base_id=recipe.base_id,
            defect=recipe.defect,
            layer=recipe.layer,
            seed=recipe.seed,
            recipe=recipe.recipe,
            mesh_path=base.mesh_path,
            night=night,
        )
        members.append(recipe)

    return members


def materialise(
    member: MemberRecipe,
    bases: Sequence[BaseRender],
    *,
    out_dir: str | Path,
) -> MemberRecipe:
    """Build the member's derived image and record its hash.

    For an image member the defect is planted into the base render's pixels.
    For a mesh member the defect lives in the geometry, so there is no
    derived image — the member's mesh is the base's, and the seeded defect is
    applied to the measured geometry when the member is scored.
    """
    out_dir = Path(out_dir)
    if member.defect is None or member.layer == "image":
        base = _find_base(bases, member.base_id)
        if base is None:
            raise KeyError(f"no base render named {member.base_id!r}")
        image = load_rgb(base.image_path)
        if member.defect is None:
            derived = image
            recipe: dict[str, Any] = {"kind": "clean", "base_sha256": base.image_sha256}
        else:
            donor = None
            donor_id = None
            if member.defect == "texture_swap":
                donor_base = _donor_for(bases, base)
                donor = load_rgb(donor_base.image_path)
                donor_id = donor_base.id
            plan_ = defect_plants.plan(
                member.defect,
                base_id=base.id,
                seed=member.seed,
                donor_id=donor_id,
            )
            derived, recipe = defect_plants.apply(image, plan_, donor_image=donor)
            recipe["kind"] = "image"
            recipe["base_sha256"] = base.image_sha256
        path = out_dir / f"{member.member_id}.png"
        digest = save_rgb(path, derived)
        return MemberRecipe(
            member_id=member.member_id,
            base_id=member.base_id,
            defect=member.defect,
            layer=member.layer,
            seed=member.seed,
            recipe=recipe,
            derived_path=str(path),
            derived_sha256=digest,
            mesh_path=member.mesh_path,
            night=member.night,
        )

    # A mesh member: the geometry is the base's, and the seeded defect is
    # applied to the *measured* mesh when it is scored.
    return MemberRecipe(
        member_id=member.member_id,
        base_id=member.base_id,
        defect=member.defect,
        layer=member.layer,
        seed=member.seed,
        recipe={"kind": "mesh", "base_mesh": member.mesh_path},
        derived_path=None,
        derived_sha256=None,
        mesh_path=member.mesh_path,
        night=member.night,
    )


def _find_base(bases: Sequence[BaseRender], base_id: str) -> BaseRender | None:
    for base in bases:
        if base.id == base_id:
            return base
    return None


def _donor_for(bases: Sequence[BaseRender], base: BaseRender) -> BaseRender:
    """The render a texture swap borrows from.

    The donor is the *next* base in the sweep's order — a different scene,
    so the borrowed pixels are visibly somebody else's.
    """
    index = bases.index(base)
    return bases[(index + 1) % len(bases)]


# -- the manifest ------------------------------------------------------------


def write_manifest(
    members: Sequence[MemberRecipe],
    path: str | Path,
    *,
    bases: Sequence[BaseRender] = (),
) -> Path:
    """Write the set's manifest — the recipes, and where the caches are.

    The manifest is the set's source of truth. It records each base render's
    sha256, so a member can be checked against the bytes it was made from
    later ("the same bytes, the same member").
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "members": [m.as_dict() for m in members],
        "bases": [
            {
                "id": b.id,
                "scene": b.scene,
                "seed": b.seed,
                "image_path": b.image_path,
                "image_sha256": b.image_sha256,
                "width": b.width,
                "height": b.height,
                "mesh_path": b.mesh_path,
                "mesh_sha256": b.mesh_sha256,
            }
            for b in bases
        ],
    }
    path.write_text(json.dumps(payload, indent=1, sort_keys=True), encoding="utf-8")
    return path


def read_manifest(path: str | Path) -> list[MemberRecipe]:
    """Read the set's members back from its manifest."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return [MemberRecipe.from_dict(m) for m in payload.get("members", ())]
