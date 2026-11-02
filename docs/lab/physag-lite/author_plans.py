#!/usr/bin/env python3
"""The cloud planner's plans for the ten props, written as data.

This script is the *authoring* of the plans; the plans themselves are the
JSON files in ``specs/``, and those are what the loop runs on. The
difference matters: a plan is a recipe, and a recipe is what gets reviewed,
diffed and replayed. The meshes are caches.

**Who wrote these.** The plans were written by a cloud model — the seat's
own session against MiniMax-M3.1-Flash, with the inference on MiniMax's
servers. No language model ran on the Thor (CLAUDE.md, "No LLMs on the
Thor"). The configured provider's credential store is not readable from
this session, so the plans could not be fetched through a scripted API
call; they were authored in the session and committed as data instead.
Every spec carries that record in its ``planner`` field.

**What a plan says.** For each prop: the parts and how to cut them out of
the mesh, the joint that carries the moving part, the action the check
executes, and the physical priors.

The cuts are where the honesty is. A geometric split cannot know where a
generated crate's lid begins — the mesh is one blob, and the lid is a
suggestion in the image. So each part carries two claims: the **cut**, which
says where to separate the mesh, and the **expectation**, which says where
the planner believes the functional part really is. The builder measures
the piece against the expectation, and the difference is the number that
tells us whether the split found the lid.

**The priors are guesses.** Every mass, friction and actuator limit below
is the planner's estimate, and every one of them is marked
``"basis": "estimated"``. The checker measures what it can measure; the
delivery record keeps the two apart.

Run it from the repository root::

    python3 docs/lab/physag-lite/author_plans.py
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO))

from core.physag.spec import (  # noqa: E402
    Action,
    Box,
    Cut,
    InteractionSpec,
    Joint,
    Part,
    Priors,
    save_spec,
)

#: The planner's record, copied into every spec it writes.
PLANNER = {
    "model": "MiniMax-M3.1-Flash",
    "mode": "cloud-session",
    "authored_by": "the physag-lite seat's own session; the inference ran on "
    "the provider's servers, not on the Thor",
    "note": "the configured provider credential store is not readable from "
    "this session, so the plans were authored here and committed as data "
    "rather than fetched through a scripted API call",
}

D90 = math.radians(90.0)


def _priors(
    mass_kg: float,
    friction: float,
    force_n: float,
    torque_nm: float,
    base_static: bool = False,
) -> Priors:
    return Priors(
        mass_kg=mass_kg,
        friction=friction,
        actuator_force_n=force_n,
        actuator_torque_nm=torque_nm,
        base_static=base_static,
    )


BASIS = {
    "mass_kg": "estimated",
    "friction": "estimated",
    "actuator_force_n": "estimated",
    "actuator_torque_nm": "estimated",
    "base_static": "estimated",
}


def _spec(
    prop: str,
    kind: str,
    prompt: str,
    parts: list[Part],
    joints: list[Joint],
    action: Action,
    priors: Priors,
) -> InteractionSpec:
    spec = InteractionSpec(
        prop=prop,
        kind=kind,
        image_prompt=prompt,
        parts=tuple(parts),
        joints=tuple(joints),
        action=action,
        priors=priors,
        basis=dict(BASIS),
        planner=dict(PLANNER),
    )
    spec.validate()
    return spec


def build_plans() -> list[InteractionSpec]:
    """The ten plans."""
    plans: list[InteractionSpec] = []

    # -- 1. crate --------------------------------------------------------
    plans.append(
        _spec(
            prop="crate",
            kind="crate",
            prompt=(
                "a weathered wooden shipping crate with iron banding, one "
                "plank lid on top, studio product photograph, neutral grey "
                "background, soft even lighting, sharp detail"
            ),
            parts=[
                Part(
                    name="body",
                    role="base",
                    cut=Cut(kind="rest"),
                    density_kg_m3=600.0,
                ),
                Part(
                    name="lid",
                    role="moving",
                    cut=Cut(kind="plane", axis="z", at=0.80, keep="above"),
                    expect=Box(min=(0.0, 0.0, 0.80), max=(1.0, 1.0, 1.0)),
                    density_kg_m3=600.0,
                ),
            ],
            joints=[
                Joint(
                    name="lid_hinge",
                    type="hinge",
                    parent="body",
                    child="lid",
                    axis=(1.0, 0.0, 0.0),
                    anchor=(0.5, 0.0, 0.80),
                    low=0.0,
                    high=D90,
                    damping=1.5,
                    armature=0.02,
                )
            ],
            action=Action(
                kind="joint",
                joint="lid_hinge",
                target=D90,
                duration_s=6.0,
                tolerance_rel=0.02,
                dwell_steps=40,
            ),
            priors=_priors(mass_kg=12.0, friction=0.6, force_n=90.0, torque_nm=18.0),
        )
    )

    # -- 2. chest --------------------------------------------------------
    plans.append(
        _spec(
            prop="chest",
            kind="chest",
            prompt=(
                "an old wooden treasure chest with iron straps and a domed "
                "hinged lid, studio product photograph, neutral grey "
                "background, soft even lighting, sharp detail"
            ),
            parts=[
                Part(
                    name="body",
                    role="base",
                    cut=Cut(kind="rest"),
                    density_kg_m3=650.0,
                ),
                Part(
                    name="lid",
                    role="moving",
                    cut=Cut(kind="plane", axis="z", at=0.68, keep="above"),
                    expect=Box(min=(0.0, 0.0, 0.68), max=(1.0, 1.0, 1.0)),
                    density_kg_m3=650.0,
                ),
            ],
            joints=[
                Joint(
                    name="lid_hinge",
                    type="hinge",
                    parent="body",
                    child="lid",
                    axis=(1.0, 0.0, 0.0),
                    anchor=(0.5, 0.0, 0.68),
                    low=0.0,
                    high=D90,
                    damping=1.8,
                    armature=0.03,
                )
            ],
            action=Action(
                kind="joint",
                joint="lid_hinge",
                target=D90,
                duration_s=6.0,
                tolerance_rel=0.02,
                dwell_steps=40,
            ),
            priors=_priors(mass_kg=20.0, friction=0.6, force_n=110.0, torque_nm=24.0),
        )
    )

    # -- 3. lantern ------------------------------------------------------
    # A hanging prop: the handle carries a ball joint to the world, and
    # the body hangs off the handle. The action is not a joint target but
    # a settling: the lantern has to end up hanging straight down.
    plans.append(
        _spec(
            prop="lantern",
            kind="lantern",
            prompt=(
                "a hanging iron lantern with a curved bail handle and a "
                "glass chamber, studio product photograph, neutral grey "
                "background, soft even lighting, sharp detail"
            ),
            parts=[
                Part(
                    name="handle",
                    role="moving",
                    cut=Cut(kind="plane", axis="z", at=0.78, keep="above"),
                    expect=Box(min=(0.3, 0.3, 0.78), max=(0.7, 0.7, 1.0)),
                    density_kg_m3=300.0,
                ),
                Part(
                    name="body",
                    role="base",
                    cut=Cut(kind="rest"),
                    density_kg_m3=300.0,
                ),
            ],
            joints=[
                Joint(
                    name="hang",
                    type="ball",
                    parent="world",
                    child="handle",
                    axis=(0.0, 0.0, 1.0),
                    anchor=(0.5, 0.5, 1.02),
                    low=0.0,
                    high=0.0,
                    damping=0.2,
                    armature=0.005,
                ),
                Joint(
                    name="handle_to_body",
                    type="fixed",
                    parent="handle",
                    child="body",
                    axis=(0.0, 0.0, 1.0),
                    anchor=(0.5, 0.5, 0.78),
                    low=0.0,
                    high=0.0,
                ),
            ],
            action=Action(
                kind="hang",
                joint="hang",
                target=0.0,
                duration_s=5.0,
                tolerance_rel=0.02,
                dwell_steps=50,
            ),
            priors=_priors(mass_kg=1.4, friction=0.4, force_n=20.0, torque_nm=2.0),
        )
    )

    # -- 4. door ---------------------------------------------------------
    # The door is cut out of a slab by a box, and the frame is what is
    # left. The hinge stands on the vertical axis at the door's edge.
    plans.append(
        _spec(
            prop="door",
            kind="door",
            prompt=(
                "a heavy wooden door panel with iron hinges and a brass "
                "handle, standing in a rough stone doorway frame, studio "
                "product photograph, neutral grey background, soft even "
                "lighting, sharp detail"
            ),
            parts=[
                Part(
                    name="frame",
                    role="base",
                    cut=Cut(kind="rest"),
                    density_kg_m3=700.0,
                ),
                Part(
                    name="door",
                    role="moving",
                    cut=Cut(
                        kind="box",
                        min=(0.16, 0.08, 0.0),
                        max=(0.92, 0.92, 1.0),
                    ),
                    expect=Box(min=(0.16, 0.08, 0.0), max=(0.92, 0.92, 1.0)),
                    density_kg_m3=700.0,
                ),
            ],
            joints=[
                Joint(
                    name="door_hinge",
                    type="hinge",
                    parent="frame",
                    child="door",
                    axis=(0.0, 0.0, 1.0),
                    anchor=(0.16, 0.5, 0.5),
                    low=0.0,
                    high=D90,
                    damping=2.5,
                    armature=0.05,
                )
            ],
            action=Action(
                kind="joint",
                joint="door_hinge",
                target=D90,
                duration_s=6.0,
                tolerance_rel=0.02,
                dwell_steps=40,
            ),
            priors=_priors(mass_kg=28.0, friction=0.55, force_n=140.0, torque_nm=32.0),
        )
    )

    # -- 5. drawer unit --------------------------------------------------
    plans.append(
        _spec(
            prop="drawer_unit",
            kind="drawer_unit",
            prompt=(
                "a small wooden chest of drawers with two pull-out drawers "
                "and round brass knobs, studio product photograph, neutral "
                "grey background, soft even lighting, sharp detail"
            ),
            parts=[
                Part(
                    name="carcass",
                    role="base",
                    cut=Cut(kind="rest"),
                    density_kg_m3=620.0,
                ),
                Part(
                    name="drawer",
                    role="moving",
                    cut=Cut(
                        kind="box",
                        min=(0.06, 0.12, 0.28),
                        max=(0.94, 0.88, 0.62),
                    ),
                    expect=Box(min=(0.06, 0.12, 0.28), max=(0.94, 0.88, 0.62)),
                    density_kg_m3=620.0,
                ),
            ],
            joints=[
                Joint(
                    name="drawer_slide",
                    type="slide",
                    parent="carcass",
                    child="drawer",
                    axis=(1.0, 0.0, 0.0),
                    anchor=(0.5, 0.5, 0.45),
                    low=0.0,
                    high=0.32,
                    damping=6.0,
                    armature=0.02,
                )
            ],
            action=Action(
                kind="joint",
                joint="drawer_slide",
                target=0.30,
                duration_s=5.0,
                tolerance_rel=0.02,
                dwell_steps=40,
            ),
            priors=_priors(mass_kg=18.0, friction=0.45, force_n=90.0, torque_nm=10.0),
        )
    )

    # -- 6. barrel -------------------------------------------------------
    plans.append(
        _spec(
            prop="barrel",
            kind="barrel",
            prompt=(
                "an oak barrel with iron hoops and a removable wooden head "
                "on top, studio product photograph, neutral grey background, "
                "soft even lighting, sharp detail"
            ),
            parts=[
                Part(
                    name="body",
                    role="base",
                    cut=Cut(kind="rest"),
                    density_kg_m3=750.0,
                ),
                Part(
                    name="lid",
                    role="moving",
                    cut=Cut(kind="plane", axis="z", at=0.86, keep="above"),
                    expect=Box(min=(0.0, 0.0, 0.86), max=(1.0, 1.0, 1.0)),
                    density_kg_m3=750.0,
                ),
            ],
            joints=[
                Joint(
                    name="lid_lift",
                    type="slide",
                    parent="body",
                    child="lid",
                    axis=(0.0, 0.0, 1.0),
                    anchor=(0.5, 0.5, 0.86),
                    low=0.0,
                    high=0.22,
                    damping=8.0,
                    armature=0.02,
                )
            ],
            action=Action(
                kind="joint",
                joint="lid_lift",
                target=0.20,
                duration_s=5.0,
                tolerance_rel=0.02,
                dwell_steps=40,
            ),
            priors=_priors(mass_kg=32.0, friction=0.5, force_n=140.0, torque_nm=14.0),
        )
    )

    # -- 7. cart ---------------------------------------------------------
    # A rolling prop: the action is measured on how far the chassis
    # travels, and the wheel joint is what the actuator drives.
    plans.append(
        _spec(
            prop="cart",
            kind="cart",
            prompt=(
                "a wooden hand cart with two spoked wheels and a flat bed, "
                "studio product photograph, neutral grey background, soft "
                "even lighting, sharp detail"
            ),
            parts=[
                Part(
                    name="chassis",
                    role="base",
                    cut=Cut(kind="rest"),
                    density_kg_m3=600.0,
                ),
                Part(
                    name="wheels",
                    role="moving",
                    cut=Cut(kind="plane", axis="z", at=0.22, keep="below"),
                    expect=Box(min=(0.0, 0.0, 0.0), max=(1.0, 1.0, 0.22)),
                    density_kg_m3=600.0,
                ),
            ],
            joints=[
                Joint(
                    name="wheel",
                    type="hinge",
                    parent="chassis",
                    child="wheels",
                    axis=(0.0, 1.0, 0.0),
                    anchor=(0.5, 0.5, 0.22),
                    low=0.0,
                    high=8.0,
                    damping=0.2,
                    armature=0.01,
                )
            ],
            action=Action(
                kind="displacement",
                joint="wheel",
                target=0.50,
                axis=(1.0, 0.0, 0.0),
                drive=6.0,
                duration_s=6.0,
                tolerance_rel=0.02,
                dwell_steps=40,
            ),
            priors=_priors(mass_kg=30.0, friction=0.8, force_n=120.0, torque_nm=10.0),
        )
    )

    # -- 8. gate ---------------------------------------------------------
    plans.append(
        _spec(
            prop="gate",
            kind="gate",
            prompt=(
                "a rustic wooden farm gate with diagonal bracing hanging on "
                "an iron post, studio product photograph, neutral grey "
                "background, soft even lighting, sharp detail"
            ),
            parts=[
                Part(
                    name="post",
                    role="base",
                    cut=Cut(kind="rest"),
                    density_kg_m3=680.0,
                ),
                Part(
                    name="leaf",
                    role="moving",
                    cut=Cut(
                        kind="box",
                        min=(0.12, 0.04, 0.10),
                        max=(0.95, 0.55, 0.92),
                    ),
                    expect=Box(min=(0.12, 0.04, 0.10), max=(0.95, 0.55, 0.92)),
                    density_kg_m3=680.0,
                ),
            ],
            joints=[
                Joint(
                    name="gate_hinge",
                    type="hinge",
                    parent="post",
                    child="leaf",
                    axis=(0.0, 0.0, 1.0),
                    anchor=(0.12, 0.30, 0.50),
                    low=0.0,
                    high=D90,
                    damping=1.2,
                    armature=0.02,
                )
            ],
            action=Action(
                kind="joint",
                joint="gate_hinge",
                target=D90,
                duration_s=6.0,
                tolerance_rel=0.02,
                dwell_steps=40,
            ),
            priors=_priors(mass_kg=16.0, friction=0.55, force_n=100.0, torque_nm=22.0),
        )
    )

    # -- 9. ladder -------------------------------------------------------
    plans.append(
        _spec(
            prop="ladder",
            kind="ladder",
            prompt=(
                "a wooden folding stepladder with two hinged sections and "
                "rungs, studio product photograph, neutral grey background, "
                "soft even lighting, sharp detail"
            ),
            parts=[
                Part(
                    name="lower",
                    role="base",
                    cut=Cut(kind="rest"),
                    density_kg_m3=600.0,
                ),
                Part(
                    name="upper",
                    role="moving",
                    cut=Cut(kind="plane", axis="z", at=0.48, keep="above"),
                    expect=Box(min=(0.0, 0.0, 0.48), max=(1.0, 1.0, 1.0)),
                    density_kg_m3=600.0,
                ),
            ],
            joints=[
                Joint(
                    name="fold_hinge",
                    type="hinge",
                    parent="lower",
                    child="upper",
                    axis=(1.0, 0.0, 0.0),
                    anchor=(0.5, 0.0, 0.48),
                    low=0.0,
                    high=math.radians(40.0),
                    damping=1.0,
                    armature=0.02,
                )
            ],
            action=Action(
                kind="joint",
                joint="fold_hinge",
                target=math.radians(40.0),
                duration_s=5.0,
                tolerance_rel=0.02,
                dwell_steps=40,
            ),
            priors=_priors(mass_kg=9.0, friction=0.6, force_n=70.0, torque_nm=10.0),
        )
    )

    # -- 10. table -------------------------------------------------------
    # A drop-leaf table: the top folds down about the back edge.
    plans.append(
        _spec(
            prop="table",
            kind="table",
            prompt=(
                "a wooden work table with a drop-leaf top hinged at the back "
                "edge and thick square legs, studio product photograph, "
                "neutral grey background, soft even lighting, sharp detail"
            ),
            parts=[
                Part(
                    name="frame",
                    role="base",
                    cut=Cut(kind="rest"),
                    density_kg_m3=640.0,
                ),
                Part(
                    name="top",
                    role="moving",
                    cut=Cut(kind="plane", axis="z", at=0.88, keep="above"),
                    expect=Box(min=(0.0, 0.0, 0.88), max=(1.0, 1.0, 1.0)),
                    density_kg_m3=640.0,
                ),
            ],
            joints=[
                Joint(
                    name="leaf_hinge",
                    type="hinge",
                    parent="frame",
                    child="top",
                    axis=(1.0, 0.0, 0.0),
                    anchor=(0.5, 0.0, 0.88),
                    low=0.0,
                    high=math.radians(45.0),
                    damping=1.4,
                    armature=0.03,
                )
            ],
            action=Action(
                kind="joint",
                joint="leaf_hinge",
                target=math.radians(45.0),
                duration_s=5.0,
                tolerance_rel=0.02,
                dwell_steps=40,
            ),
            priors=_priors(mass_kg=35.0, friction=0.55, force_n=130.0, torque_nm=20.0),
        )
    )

    return plans


def main() -> int:
    out_dir = HERE / "specs"
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for spec in build_plans():
        path = save_spec(spec, out_dir / f"{spec.prop}.json")
        written.append(path.name)
        print(f"wrote {path}")
    print(f"\n{len(written)} plans written to {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
