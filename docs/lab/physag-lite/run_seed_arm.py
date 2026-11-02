#!/usr/bin/env python3
"""The seed-159 arm: SimReady's priors against the planner's, in the sim.

The planner asserts a mass and a friction for every prop. SimReady assets
carry *authored* physics — a mass in the USD payload, a density and a
friction per material — and the simready-survey measured 37 categories of
them. The question this arm answers is the one seed 159 asked: do the
planner's guesses matter, and would SimReady's evidence have done better?

Two things come out of the run.

**The scoring.** Every planner prior with a SimReady counterpart is put
against the range the survey measured for the closest category: the
deviation from the range's midpoint, and whether the range is *tight* —
within ±10 % of its midpoint, which is the bar a referee needs. A range
that spans an order of magnitude cannot tell a good guess from a bad one,
and the record says so instead of grading against it. Most of the SimReady
ranges here are single observations, which are tight by construction and
worth exactly one asset: the flag travels with the number.

**The sim.** The same mesh, the same segmentation, the same action — only
the priors change. The mass is SimReady's, scaled by volume from the
category's asset to the plan's size (a 0.9 m drum is not a 0.4 m crate);
the friction is the SimReady material's; the actuator limits stay the
planner's, because SimReady has no actuators, and the record says so.
Completion and stability then run through the same checker, and the two
columns stand beside the planner's.

The mapping from prop to category is recorded with the reason, because
SimReady's own taxonomy has no doors, no drawers, no lanterns and no
tables — the survey found 0 drawers in 2,677 assets — and the honest arm
names what it borrowed rather than pretending the category fits.

Usage::

    python docs/lab/physag-lite/run_seed_arm.py \\
        --meshes artifacts/physag-lite/meshes \\
        --specs docs/lab/physag-lite/specs \\
        --out artifacts/physag-lite/run-seed \\
        --priors ~/lm-wt/simready-survey/simready_priors.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from core.physag.pipeline import delivery_for, run_prop  # noqa: E402
from core.physag.spec import Priors, load_spec  # noqa: E402

#: The prop-to-category mapping, with the reason it holds and how well it
#: does. ``direct`` is the same object; ``borrowed`` is the nearest thing
#: SimReady has, which for four of the ten props is not very near.
CATEGORY_MAP: dict[str, dict[str, str]] = {
    "crate": {"category": "crate", "confidence": "direct", "reason": "the same object"},
    "chest": {
        "category": "container",
        "confidence": "borrowed",
        "reason": "no chest category; a lidded container is the nearest by function",
    },
    "lantern": {
        "category": "lighting",
        "confidence": "borrowed",
        "reason": "no lantern category; lighting is the family, though the sampled asset is a 202 kg overhead LED and the size scaling carries the comparison",
    },
    "door": {
        "category": "cabinet",
        "confidence": "borrowed",
        "reason": "no door category at all; a cabinet door is the nearest moving panel, per the survey's own note",
    },
    "drawer_unit": {
        "category": "cabinet",
        "confidence": "borrowed",
        "reason": "SimReady has no drawers — the survey measured 0 in 2,677 assets — so the cabinet stands in, per the survey's note",
    },
    "barrel": {"category": "drum", "confidence": "direct", "reason": "a barrel is a drum"},
    "cart": {
        "category": "pallet",
        "confidence": "borrowed",
        "reason": "no cart category; a pallet is the nearest wooden platform in the right mass class",
    },
    "gate": {
        "category": "structure",
        "confidence": "borrowed",
        "reason": "no gate category; structure beam is the nearest structural member",
    },
    "ladder": {
        "category": "rack",
        "confidence": "borrowed",
        "reason": "no ladder category; a rack is the nearest climbing/storage structure",
    },
    "table": {
        "category": "pallet",
        "confidence": "borrowed",
        "reason": "no table category; a pallet is the nearest flat wooden platform on blocks",
    },
}

#: The prop-to-material mapping for the friction prior. The props are
#: wood; the lantern carries glass and brass, and the record says which
#: label was used.
MATERIAL_MAP: dict[str, str] = {
    "crate": "wood",
    "chest": "wood",
    "lantern": "wood",
    "door": "wood",
    "drawer_unit": "wood",
    "barrel": "wood",
    "cart": "wood",
    "gate": "wood",
    "ladder": "wood",
    "table": "wood",
}

#: A range referees a guess only when it spans at most ±10 % around its
#: midpoint (guard 5 on the seed arm).
TIGHT_RATIO = 1.2


def _range_stats(rng: dict[str, Any] | None) -> dict[str, Any] | None:
    """A range's midpoint, spread, and whether it can referee a guess."""
    if not rng or not rng.get("n"):
        return None
    lo, hi = float(rng["min"]), float(rng["max"])
    if hi < lo:
        lo, hi = hi, lo
    mid = (lo + hi) / 2.0
    ratio = hi / lo if lo > 0 else float("inf")
    return {
        "min": lo,
        "max": hi,
        "mid": mid,
        "n": int(rng["n"]),
        "spread_ratio": round(ratio, 4) if ratio != float("inf") else None,
        "tight": bool(ratio <= TIGHT_RATIO),
        "single_observation": bool(int(rng["n"]) == 1),
    }


def _deviation(value: float, mid: float) -> float | None:
    """How far a guess is from the range's midpoint, as a fraction."""
    if mid == 0:
        return None
    return round((value - mid) / mid, 4)


def compare_priors(spec_priors: Priors, survey: dict, prop: str) -> dict[str, Any]:
    """The planner's priors against SimReady's, per field.

    The size scaling is explicit: the category's mass belongs to an asset
    of the category's size, and scaling it by volume to the plan's size is
    the only way the two numbers are about the same object. The unscaled
    comparison is kept too, because the scaling is itself an assumption.
    """
    mapping = CATEGORY_MAP[prop]
    category = survey["categories"].get(mapping["category"])
    if category is None:
        return {"category": mapping["category"], "error": "the category is not in the survey"}

    mass = _range_stats(category.get("mass_kg"))
    dataset_mass = _range_stats(category.get("dataset_mass_kg"))
    sizes = category.get("size_m", {}).get("largest_axis")
    size = _range_stats(sizes)
    density = _range_stats(category.get("density_kg_m3"))

    material_label = MATERIAL_MAP[prop]
    material = (survey.get("materials", {}).get("table") or {}).get(material_label)
    friction = _range_stats(material.get("static_friction")) if material else None

    out: dict[str, Any] = {
        "category": mapping["category"],
        "confidence": mapping["confidence"],
        "reason": mapping["reason"],
        "material_label": material_label,
    }

    # The mass, scaled by volume from the sampled asset's size to the
    # plan's size.
    planner_mass = float(spec_priors.mass_kg)
    if mass and mass["mid"] and size and size["mid"]:
        plan_size = spec_priors.size_m or size["mid"]
        scale = (plan_size / size["mid"]) ** 3
        out["mass_kg"] = {
            "planner": planner_mass,
            "simready_asset": mass,
            "simready_scaled": round(mass["mid"] * scale, 4),
            "scaling": f"(size_m {plan_size:.3g} / asset {size['mid']:.3g})^3 = {scale:.3g}",
            "deviation_from_asset_mid": _deviation(planner_mass, mass["mid"]),
            "deviation_from_scaled_mid": _deviation(planner_mass, mass["mid"] * scale),
            "refereeing": mass["tight"],
        }
    if dataset_mass:
        out["mass_kg_dataset"] = {
            "range": dataset_mass,
            "planner_in_range": dataset_mass["min"] <= planner_mass <= dataset_mass["max"],
            "deviation_from_mid": _deviation(planner_mass, dataset_mass["mid"]),
            "refereeing": dataset_mass["tight"],
            "note": (
                "the dataset range spans every asset in the category; a "
                "guess inside it means nothing"
            ),
        }

    planner_friction = float(spec_priors.friction)
    if friction:
        out["friction"] = {
            "planner": planner_friction,
            "simready": friction,
            "deviation_from_mid": _deviation(planner_friction, friction["mid"]),
            "refereeing": friction["tight"],
        }

    if density:
        out["density_kg_m3"] = {
            "simready": density,
            "note": "the planner's densities live on the parts (600 for wood); the category's is the authored per-material density",
        }

    if size and spec_priors.size_m:
        out["size_m"] = {
            "planner": spec_priors.size_m,
            "simready": size,
            "deviation_from_mid": _deviation(spec_priors.size_m, size["mid"]),
            "refereeing": size["tight"],
        }
    return out


def seed_priors(spec_priors: Priors, comparison: dict[str, Any]) -> tuple[Priors, list[str]]:
    """The SimReady side of the comparison, as a Priors the checker runs.

    Mass is the scaled SimReady mass; friction is the material's median.
    The actuator limits stay the planner's — SimReady has no actuators —
    and stay marked as its guesses.
    """
    notes: list[str] = []
    mass = spec_priors.mass_kg
    friction = spec_priors.friction
    if "mass_kg" in comparison and comparison["mass_kg"].get("simready_scaled"):
        mass = float(comparison["mass_kg"]["simready_scaled"])
    else:
        notes.append("no SimReady mass for this prop; the planner's mass stayed")
    if "friction" in comparison and comparison["friction"].get("simready"):
        friction = float(comparison["friction"]["simready"]["mid"])
    return (
        replace(
            spec_priors,
            mass_kg=mass,
            friction=friction,
        ),
        notes,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--meshes", required=True, type=Path)
    parser.add_argument("--specs", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument(
        "--priors",
        required=True,
        type=Path,
        help="the simready-survey's simready_priors.json",
    )
    parser.add_argument("--props", default="", help="a space-separated list; default: every spec")
    args = parser.parse_args()

    survey = json.loads(args.priors.read_text())
    args.out.mkdir(parents=True, exist_ok=True)

    if args.props:
        props = args.props.split()
    else:
        props = sorted(p.stem for p in args.specs.glob("*.json") if not p.stem.endswith(".repair"))

    records: list[dict[str, Any]] = []
    for prop in props:
        spec_path = args.specs / f"{prop}.json"
        mesh_path = args.meshes / f"{prop}.glb"
        if not spec_path.exists() or not mesh_path.exists():
            print(f"!! {prop}: no plan or no mesh; skipped", file=sys.stderr)
            continue
        if prop not in CATEGORY_MAP:
            print(f"!! {prop}: no SimReady category mapping; skipped", file=sys.stderr)
            continue

        plan = load_spec(spec_path)
        comparison = compare_priors(plan.priors, survey, prop)
        priors, seed_notes = seed_priors(plan.priors, comparison)
        spec = replace(
            plan,
            priors=priors,
            planner={**plan.planner, "priors_source": f"simready:{comparison['category']}"},
        )

        prop_dir = args.out / prop
        prop_dir.mkdir(parents=True, exist_ok=True)
        print(f"== {prop} (seed: {comparison['category']}, {comparison['confidence']})")
        started = time.perf_counter()
        try:
            run = run_prop(
                spec,
                mesh_path,
                out_dir=prop_dir,
                planner=None,
                allow_repair=False,
            )
        except Exception as exc:
            print(f"!! {prop}: {type(exc).__name__}: {exc}", file=sys.stderr)
            (prop_dir / "error.txt").write_text(f"{type(exc).__name__}: {exc}\n")
            records.append(
                {
                    "prop": prop,
                    "arm": "seed",
                    "interaction_status": "not_run",
                    "physics_status": "invalid",
                    "counted": False,
                    "comparison": comparison,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            continue
        wall = time.perf_counter() - started

        delivery = delivery_for(run, arm="seed")
        delivery.timings["wall_s"] = round(wall, 3)
        seed_note = (
            f"priors from SimReady ({comparison['category']}, {comparison['confidence']}); "
            + "; ".join(seed_notes)
            if seed_notes
            else f"priors from SimReady ({comparison['category']}, {comparison['confidence']})"
        )
        delivery = replace(delivery, notes=tuple(run.notes) + (seed_note,))
        delivery.save(prop_dir / "delivery.json")
        (prop_dir / "priors_comparison.json").write_text(json.dumps(comparison, indent=2) + "\n")

        result = run.result
        print(
            f"   interaction={delivery.interaction_status} "
            f"physics={delivery.physics_status} "
            f"mass={spec.priors.mass_kg} friction={spec.priors.friction} wall={wall:.1f}s"
        )
        if result is not None and result.stability.reasons:
            for reason in result.stability.reasons:
                print(f"      ! {reason}")

        records.append(
            {
                "prop": prop,
                "arm": "seed",
                "interaction_status": delivery.interaction_status,
                "physics_status": delivery.physics_status,
                "counted": delivery.counted,
                "timings": delivery.timings,
                "comparison": comparison,
                "check": delivery.check,
            }
        )

    # -- the summary -------------------------------------------------------
    counted = [r for r in records if r.get("counted")]
    completed = [r for r in counted if r.get("interaction_status") == "completed"]
    stable = [r for r in counted if r.get("physics_status") == "stable"]

    scoring: dict[str, Any] = {}
    for record in records:
        comparison = record.get("comparison") or {}
        fields = {}
        for field in ("mass_kg", "friction", "size_m"):
            entry = comparison.get(field)
            if entry and "deviation_from_mid" in entry:
                fields[field] = {
                    "planner": entry.get("planner"),
                    "deviation_from_mid": entry.get("deviation_from_mid"),
                    "refereeing": entry.get("refereeing"),
                }
            elif field == "mass_kg" and "mass_kg" in comparison:
                entry = comparison["mass_kg"]
                fields[field] = {
                    "planner": entry.get("planner"),
                    "deviation_from_scaled_mid": entry.get("deviation_from_scaled_mid"),
                    "refereeing": entry.get("refereeing"),
                }
        scoring[record["prop"]] = {
            "category": comparison.get("category"),
            "confidence": comparison.get("confidence"),
            "fields": fields,
            "refereeing_fields": [
                name for name, f in fields.items() if f.get("refereeing")
            ],
        }

    refereed = [name for name, s in scoring.items() if s["refereeing_fields"]]
    summary = {
        "arm": "seed",
        "props": len(records),
        "counted": len(counted),
        "completed": len(completed),
        "completion_rate": round(len(completed) / len(counted), 4) if counted else None,
        "stable": len(stable),
        "stable_of_counted": round(len(stable) / len(counted), 4) if counted else None,
        "priors_scoring": {
            "props": len(scoring),
            "props_with_a_refereeing_range": len(refereed),
            "refereed_props": refereed,
            "note": (
                "a range referees only when it spans at most ±10 % around its "
                "midpoint; a single observation is tight by construction and "
                "worth one asset, and the dataset ranges span an order of "
                "magnitude and referee nothing"
            ),
            "per_prop": scoring,
        },
        "not_counted": [r["prop"] for r in records if not r.get("counted")],
        "statuses": {
            r["prop"]: {
                "interaction_status": r.get("interaction_status"),
                "physics_status": r.get("physics_status"),
                "counted": r.get("counted"),
            }
            for r in records
        },
        "wall_s_total": round(sum(r.get("timings", {}).get("wall_s", 0.0) for r in records), 2),
    }
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print()
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
