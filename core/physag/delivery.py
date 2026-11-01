"""The delivery record: what was verified, what was estimated, and what it cost.

The record is the seat's contract with the morning. It says, per prop, what
the simulation *measured* and what the planner *guessed*, and it keeps the
two in separate places — a guess that ends up in the verified column is a
lie, and the Hy4 guard is explicit about it.

The statuses are the ones PhysAg3D's own delivery record uses, because the
point of this seat is to compare against it:

``interaction_status``
    ``completed`` — the action reached its band and stayed there;
    ``incomplete`` — it did not;
    ``not_run`` — the model was never built.

``physics_status``
    ``stable`` — the prop stood still, nothing penetrated, the actuator
    stayed inside its limit;
    ``unstable`` — the prop moved, tipped or jammed;
    ``invalid`` — the score cannot be trusted: the prop was not stable at
    rest, or the collider was not faithful to the mesh.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, fields as dataclass_fields
from pathlib import Path
from typing import Any

from core.physag.check import CheckResult
from core.physag.mjcf import BuiltProp
from core.physag.segment import Segmentation
from core.physag.spec import InteractionSpec

__all__ = ["Delivery", "write_delivery"]


@dataclass(frozen=True)
class Delivery:
    """What one prop delivered, and the honest record of how."""

    prop: str
    arm: str
    interaction_status: str
    physics_status: str
    spec: InteractionSpec
    #: The measured numbers. Nothing estimated is allowed in here.
    verified: dict[str, Any]
    #: The guessed numbers, each with the basis that says it is a guess.
    estimated: dict[str, Any]
    #: The basis for every prior, measured / estimated / derived.
    basis: dict[str, str]
    #: The wall time and the GPU time, in seconds.
    timings: dict[str, float]
    segmentation: dict[str, Any]
    collider: dict[str, Any]
    check: dict[str, Any] | None
    #: The repair round, when there was one.
    repair: dict[str, Any] | None = None
    #: The manual ground-truth check on the part-to-spec mapping.
    ground_truth: dict[str, Any] | None = None
    #: Whether the prop counts towards the completion rate.
    counted: bool = True
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "prop": self.prop,
            "arm": self.arm,
            "interaction_status": self.interaction_status,
            "physics_status": self.physics_status,
            "counted": self.counted,
            "verified": self.verified,
            "estimated": self.estimated,
            "basis": self.basis,
            "timings": {k: round(float(v), 4) for k, v in self.timings.items()},
            "segmentation": self.segmentation,
            "collider": self.collider,
            "check": self.check,
            "repair": self.repair,
            "ground_truth": self.ground_truth,
            "notes": list(self.notes),
        }

    def save(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2) + "\n")
        return path


def build_delivery(
    *,
    prop: str,
    arm: str,
    spec: InteractionSpec,
    built: BuiltProp | None,
    segmentation: Segmentation | None,
    result: CheckResult | None,
    timings: dict[str, float],
    repair: dict[str, Any] | None = None,
    ground_truth: dict[str, Any] | None = None,
    counted: bool = True,
    notes: tuple[str, ...] = (),
) -> Delivery:
    """Assemble the record from what the run produced.

    The split between verified and estimated is enforced here, not left to
    the caller: a value from the spec's priors goes into ``estimated``
    with its basis, and a value the simulation measured goes into
    ``verified``.
    """
    verified: dict[str, Any] = {}
    estimated: dict[str, Any] = {}

    for prior_field in dataclass_fields(spec.priors):
        value = getattr(spec.priors, prior_field.name)
        basis = spec.basis.get(prior_field.name, "estimated")
        if basis == "measured":
            verified[prior_field.name] = value
        else:
            estimated[prior_field.name] = {"value": value, "basis": basis}

    if built is not None:
        verified["total_mass_kg"] = round(built.total_mass_kg, 4)
        verified["collider_volume_m3"] = round(built.collider_volume_m3, 9)
        verified["mesh_volume_m3"] = round(built.mesh_volume_m3, 9)
        # An open mesh has no volume for the ratio to divide by, and the
        # record says so rather than inventing a number: the guards that
        # do work on an open mesh carry the score instead.
        verified["collider_volume_ratio"] = (
            None if built.volume_ratio is None else round(built.volume_ratio, 6)
        )
        verified["bodies"] = list(built.bodies)
        verified["joints"] = list(built.joints)
        verified["actuator"] = built.actuator
        verified["base_free"] = built.free_base

    if segmentation is not None:
        verified["segmentation"] = segmentation.to_dict()

    if result is not None:
        verified["check"] = result.to_dict()
        verified["interaction_status"] = result.interaction_status
        verified["physics_status"] = result.physics_status

    basis = {f: spec.basis.get(f, "estimated") for f in spec.priors.fields()}
    # The mass the simulation used is derived from the prior and the
    # geometry: it is arithmetic on a guess, and it says so.
    basis["total_mass_kg"] = "derived"

    return Delivery(
        prop=prop,
        arm=arm,
        interaction_status=result.interaction_status if result else "not_run",
        physics_status=result.physics_status if result else "invalid",
        spec=spec,
        verified=verified,
        estimated=estimated,
        basis=basis,
        timings=dict(timings),
        segmentation=segmentation.to_dict() if segmentation else {},
        collider=result.collider if result else (built.to_dict() if built else {}),
        check=result.to_dict() if result else None,
        repair=repair,
        ground_truth=ground_truth,
        counted=counted,
        notes=notes,
    )


def write_delivery(delivery: Delivery, path: str | Path) -> Path:
    """Write a delivery record to disk."""
    return delivery.save(path)
