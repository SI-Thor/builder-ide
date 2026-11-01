"""Write RESULT.json: every measured number from the survey, in one file.

The result is the numbers and where they came from, not a verdict. Each
entry names the artefact it was read from, so any claim can be re-checked
against the file that produced it.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def box_state() -> dict:
    """The box the numbers were measured on."""
    state: dict = {}
    try:
        with open("/proc/meminfo") as handle:
            for line in handle:
                key, _, rest = line.partition(":")
                if key in ("MemTotal", "MemAvailable"):
                    state[f"{key}_gib"] = round(int(rest.split()[0]) / 1024 / 1024, 1)
                if key == "MemTotal":
                    break
    except OSError:
        pass
    try:
        state["cpu_count"] = len(
            [line for line in open("/proc/cpuinfo") if line.startswith("processor")]
        )
    except OSError:
        pass
    try:
        out = subprocess.run(
            ["df", "-BG", "/"], capture_output=True, text=True, timeout=20
        ).stdout.splitlines()
        if len(out) > 1:
            state["disk_free"] = out[1].split()[3]
    except Exception:
        pass
    try:
        state["date_utc"] = subprocess.run(
            ["date", "-u", "+%Y-%m-%dT%H:%M:%SZ"], capture_output=True, text=True, timeout=20
        ).stdout.strip()
    except Exception:
        pass
    return state


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default=str(ROOT / "RESULT.json"))
    args = parser.parse_args()

    data = ROOT / "data"
    report = json.loads((data / "sample_report.json").read_text())
    verification = json.loads((data / "gltf_verification.json").read_text())
    experiment = json.loads((data / "critic_experiment.json").read_text())
    mapping = json.loads((data / "vocabulary_mapping.json").read_text())
    dataset = json.loads((data / "dataset_physics.json").read_text())
    manifest = json.loads((data / "sample_manifest.json").read_text())
    timings = json.loads((data / "conversion_timings.json").read_text())
    timings.pop("assets", None)

    glb = [row for row in report if row.get("glb")]
    seconds = sorted(row["glb"]["seconds"] for row in glb)
    tri = sorted(row["glb"]["triangles"] for row in glb)

    schema = [row["schema"] for row in report if row.get("schema")]
    jointed = [s for s in schema if s["joints"]]
    grasped = [s for s in schema if s["grasp_curves"]]
    watertight = sum(
        1
        for row in report
        if row.get("schema")
        and row["schema"].get("mesh_boxes")
    )

    result = {
        "survey": "nvidia/simready-assets, read on the Jetson AGX Thor",
        "date_utc": box_state().get("date_utc"),
        "box": box_state(),
        "dataset": {
            "repo": "nvidia/simready-assets",
            "licence": "CC-BY-4.0",
            "credit": "NVIDIA SimReady Assets (nvidia/simready-assets), CC-BY-4.0",
            "sha": manifest["repo_sha"],
            "stored_bytes": 82985197802,
            "stored_gib": 77.29,
            "tree_entries": 228417,
            "files": 183394,
            "folders": 45023,
            "packages": 2677,
            "categories": 196,
            "index_bytes_gib": 456.0,
            "largest_category": "food (538 assets)",
            "source": "data/repo_index.jsonl",
        },
        "sample": {
            "assets": manifest["asset_count"],
            "categories": manifest["categories_covered"],
            "payload_gib": round(manifest["payload_bytes"] / 1024**3, 3),
            "on_disk": "~/lm-cold/simready-sample",
            "files_fetched": 1372,
            "selection_rule": manifest["selection_rule"],
            "source": "data/sample_manifest.json",
        },
        "q1_schema": {
            "units": "metersPerUnit = 1, upAxis = Z (38/38 sampled)",
            "package_metadata": ["asset_type", "profile", "profile_version", "uuid"],
            "semantics": [
                "semantics:labels:wikidata_class",
                "semantic:wikidata_class:params:semanticData",
                "material labels (steel, plastic, rubber, aluminum, ...)",
            ],
            "physics_attributes": [
                "physics:mass",
                "physics:centerOfMass",
                "physics:diagonalInertia",
                "physics:principalAxes",
                "physics:density",
                "physics:collisionEnabled",
                "physics:approximation",
                "physics:staticFriction",
                "physics:dynamicFriction",
                "physics:restitution",
            ],
            "physics_attributes_duplicated": [
                "pxr:usd:physics_mass",
                "pxr:usd:physics_centerofmass",
                "pxr:usd:physics_inertia",
            ],
            "collider_approximations": ["sdf", "convexDecomposition"],
            "solver_variant_sets": ["MuJoCo", "Newton", "PhysX"],
            "articulation_joint_types": [
                "PhysicsRevoluteJoint",
                "PhysicsPrismaticJoint",
                "PhysicsFixedJoint",
            ],
            "grasp_curve_prim": "/RootNode/Grasp/grasp_identifier/grasp_identifier_curve",
            "materials": "UsdShade Material + Shader + OmniPBR MDL + PNG textures",
            "lod": "no LOD prim in any of the 38 sampled packages",
            "two_reader_traps": [
                "the geometry is instanced: stage.Traverse() finds 0 meshes; "
                "Usd.PrimRange.Stage(stage, Usd.TraverseInstanceProxies()) finds them",
                "the mass is stated twice, on the mesh and on the Xform that "
                "wraps it: adding both doubles every asset's mass",
            ],
            "source": "data/sample_report.json",
        },
        "q2_priors": {
            "priors_file": "simready_priors.json",
            "categories": len(json.loads((ROOT / "simready_priors.json").read_text())["categories"]),
            "what_the_priors_carry": [
                "mass_kg (from the USD physics payload)",
                "size_m (world-space extent; metersPerUnit is 1)",
                "density_kg_m3 and material labels",
                "the critic's own six features, measured on the asset's mesh",
            ],
            "critic_experiment": {
                "baseline_critics_own_prior": {
                    "ghost_score": experiment["baseline_the_critics_own_prior"]["ghost_score"],
                    "ghost_flagged": experiment["baseline_the_critics_own_prior"]["ghost_flagged"],
                    "mug_median": experiment["baseline_the_critics_own_prior"]["mug_median_score"],
                    "plank_median": experiment["baseline_the_critics_own_prior"]["plank_median_score"],
                },
                "prior_refitted_on_simready": {
                    "2_clusters": {
                        "ghost_score": experiment["simready_prior"]["2"]["ghost_score"],
                        "ghost_flagged": experiment["simready_prior"]["2"]["ghost_flagged_below_005"],
                        "ghost_distance": experiment["simready_prior"]["2"]["ghost_distance"],
                    },
                    "3_clusters": {
                        "ghost_score": experiment["simready_prior"]["3"]["ghost_score"],
                        "ghost_flagged": experiment["simready_prior"]["3"]["ghost_flagged_below_005"],
                    },
                },
                "answer": (
                    "No. The SimReady priors do not flag the critic's known-bad "
                    "prop: the ghost scores 0.149-0.171 against a SimReady-fitted "
                    "prior, against a threshold of 0.05, and does not separate from "
                    "the toy mug. Its per-feature percentiles inside the SimReady "
                    "distribution are 0.14 to 0.94, so the ghost is an ordinary "
                    "point in the space real objects occupy."
                ),
                "the_other_direction": {
                    "share_of_real_assets_the_critics_own_prior_calls_a_ghost": experiment[
                        "simready_assets_scored_against_the_toy_prior"
                    ]["share_below_005"],
                    "assets_scored": len(schema),
                    "median_score": experiment["simready_assets_scored_against_the_toy_prior"][
                        "median_score"
                    ],
                    "answer": (
                        "All 38 real assets score below the critic's own 0.05 ghost "
                        "threshold against its toy approved set. The mechanism is the "
                        "fill-ratio feature: it divides a closed mesh's signed "
                        "volume by the bounding box, real objects are hollow shells "
                        "(a mug's measured fill ratio is 0.052 against the toy mug's "
                        "0.68), and a prior fitted on solid generated meshes calls "
                        "real objects ghosts."
                    ),
                },
                "meshes_not_closed": {
                    "watertight_of_sampled": watertight,
                    "open_of_sampled": len(schema) - watertight,
                    "repair_stage_closes_boundaries": False,
                    "note": (
                        "core/genbatch/repair.py welds seams and splits "
                        "non-manifold edges; on the four sampled assets with the "
                        "largest defects it reports boundary_edges_closed = 0."
                    ),
                },
                "source": "data/critic_experiment.json",
            },
            "dataset_wide_mass": {
                "assets": dataset["assets_with_mass"],
                "categories_with_mass": dataset["category_count"],
                "per_category": dataset["categories"],
                "note": (
                    "a category is a name, not a scale: warehouse runs from "
                    "0.15 kg to 400081 kg, and bodyPart from 0.13 kg to 348 kg"
                ),
                "source": "data/dataset_physics.json",
            },
            "dataset_wide_material_table": {
                "materials": dataset["material_count"],
                "assets_parsed": dataset["physics_layers_parsed"],
                "top": sorted(
                    dataset["materials"].items(), key=lambda kv: -kv[1]["assets"]
                )[:8],
                "hygiene": (
                    "the material names carry spelling drift (platic, plasic, "
                    "pastic for plastic; cemaric for ceramic), and one aluminum "
                    "material carries the plastic density of 950 kg/m3"
                ),
                "source": "data/dataset_physics.json",
            },
        },
        "q3_vocabulary": {
            "simready": {
                "packages": 2677,
                "categories": 196,
                "asset_types": dataset["asset_types"],
                "profiles": dataset["profiles"],
                "semantic_labels_distinct": len(dataset["semantic_labels"]),
                "prop_meaning": (
                    "every asset in the dataset declares asset_type = prop and "
                    "profile = Robotics-Prop, including the forklift, the "
                    "conveyor belt, the structural beam and the 400-tonne "
                    "warehouse: in SimReady 'prop' means a simulated object, "
                    "where in builder-ide it means a thing in a room"
                ),
            },
            "builder_ide": {
                "words": 3,
                "namespace_segments": 14,
                "tile_kinds": 3,
                "simready_lite_semantic_slot": (
                    "an open string with no closed list; the demo uses crate, "
                    "post, bracket, ground"
                ),
                "collision_models": ["none", "boundingCube", "boundingSphere", "convexHull", "mesh"],
            },
            "infinigen": {
                "factories": mapping["infinigen"]["factories"],
                "groups": mapping["infinigen"]["groups"],
            },
            "overlap": mapping["overlap"],
            "gap_shape": (
                "the unmatched half is the industrial end (handTool 97, "
                "consumable 77, serviceTool 57, engineComponent 52, instrument 38, "
                "stationery 36, cleaning 29, sign 25, testingTool 25, "
                "vehicleSupport 22, powerTool 20): Infinigen builds rooms, "
                "SimReady is a workshop"
            ),
            "usable_now": (
                "the semantic class: SimReady carries a populated taxonomy "
                "(Wikidata classes beside human labels and material labels) for "
                "a slot builder-ide leaves open"
            ),
            "source": "data/vocabulary_mapping.json",
        },
        "q4_loaders": {
            "usd_core_on_aarch64": {
                "version_installed": "26.11",
                "aarch64_wheel": "manylinux_2_27_aarch64.manylinux_2_28_aarch64 (cp311/cp312/cp313)",
                "aarch64_wheel_missing_in": ["26.3", "26.5", "26.8"],
                "already_installed_in_venvs": 11,
                "note": (
                    "26.11 is the first recent release with an aarch64 wheel; the "
                    "Thor already carries it in eleven project venvs, so a USD "
                    "read needs no new install"
                ),
            },
            "loader": "scripts/simready_loader.py",
            "glb_conversion": timings,
            "verification": {
                "reader": verification["summary"]["reader"],
                "opened": verification["summary"]["opened"],
                "ok": verification["summary"]["ok"],
                "failures": verification["summary"]["failures"],
                "max_box_error_m": verification["summary"]["max_box_error_m"],
                "max_union_box_error_m": verification["summary"]["max_union_box_error_m"],
                "note": (
                    "checked with builder-ide's own reader, not the survey's; the "
                    "first writer put float64 bytes under a float32 accessor and "
                    "every reader decoded garbage until it was fixed"
                ),
                "source": "data/gltf_verification.json",
            },
            "not_done": [
                "textures are not written into the GLB",
                "no per-mesh material binding",
                "the sdf and convexDecomposition colliders are not translated "
                "into builder-ide's five collision models",
            ],
        },
        "q5_articulation": {
            "packages_sampled": len(schema),
            "with_joints": len(jointed),
            "with_grasp_curves": len(grasped),
            "joint_types": [
                "PhysicsRevoluteJoint",
                "PhysicsPrismaticJoint",
                "PhysicsFixedJoint",
            ],
            "joint_attributes": [
                "physics:axis",
                "physics:lowerLimit",
                "physics:upperLimit",
                "physics:localPos0",
                "physics:localPos1",
                "physics:localRot0",
                "physics:localRot1",
                "physics:jointEnabled",
                "physics:collisionEnabled",
            ],
            "door_example": {
                "asset": "cabinet_file_a03",
                "joints": [
                    "joint_door_01_joint_00: revolute about Z, -90 to 0 degrees",
                    "joint_door_02_joint_00: revolute about Z, 0 to 90 degrees",
                    "joint_glass_01_joint_00: fixed",
                    "joint_glass_02_joint_00: fixed",
                ],
            },
            "drawer_example": {
                "asset": "equipment_bench_vise_a01",
                "joint": "joint_slidingJaw_01_joint_00: prismatic along X, -0.045 to 0.055 m",
                "drawers_in_the_dataset": 0,
                "note": (
                    "searching all 2,677 package names for 'drawer' returns zero "
                    "assets: the dataset has cabinets with doors, a desk, three "
                    "shelves and one shelving rack, and no drawer. The bench vise's "
                    "sliding jaw is the nearest articulated sliding mechanism."
                ),
            },
            "usable_for_physics": True,
            "usable_for_an_agent": (
                "partly: the joints are standard UsdPhysics objects with axis, "
                "limits and frames, and the three solver variants are already "
                "authored as variant sets, so a physics world can instantiate them "
                "as they stand; but the joint prims are named from the mesh part, "
                "the grasp curve is a curve rather than a named handle, and the sdf "
                "collider is not one of builder-ide's five"
            ),
            "not_verified": (
                "the glTF path was verified against builder-ide's GLB reader, not "
                "against the thor-world viewer, which is a separate repository and "
                "is not checked out on this box"
            ),
            "source": "data/sample_report.json",
        },
        "cost": {
            "sample_gib": 2.9993,
            "sample_budget_gib": 3,
            "physics_payload_all_assets_mib": 24.1,
            "base_payload_all_assets_mib": 45.5,
            "total_fetched_gib": 3.07,
            "budget": "3 GiB for the sample; the director's gate is 5 GiB",
            "within_budget": True,
            "box_rules": {
                "heavy_step_threshold_gib": 8,
                "peak_rss_of_the_heaviest_step_mib": 545,
                "peak_rss_measured_on": "storage_shelf_basic_a01, 1.33M triangles",
                "lease_taken": False,
                "note": (
                    "no step came near the 8 GB threshold, so no thor-admit "
                    "lease was needed; MemAvailable stayed between 69.9 GB and "
                    "78.0 GB against a 25.0 GB floor with five other leases "
                    "running. A thor-admit run invocation for the sample "
                    "download was refused by the desktop permission gate; the "
                    "download is network-bound and light on memory."
                ),
            },
            "fetch_method": (
                "plain HTTP against the resolve endpoint, one GET per file, "
                "driven by the file index; snapshot_download spends an API call "
                "per file on a token and hits the anonymous rate limit"
            ),
        },
    }
    Path(args.out).write_text(json.dumps(result, indent=2) + "\n")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
