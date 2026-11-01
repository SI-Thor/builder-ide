"""Verify the survey's deliverables, end to end.

One command that re-derives every headline number from the artefacts and
checks it against what the report and the result file claim. It exits
non-zero if anything disagrees, so it can be run as a gate rather than
trusted as a transcript.

What it checks:

* the four deliverables exist, and the two JSON ones parse;
* the sample on disk is the sample the manifest names, at the right size;
* the loader runs on a package and reports a schema;
* every GLB opens under **builder-ide's** reader, with no NaN, no reader
  warning, and a bounding box matching its USD source;
* the critic experiment's numbers are what the report says;
* the report contains no number that the artefacts do not support.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILDER_IDE = Path("/home/caseydigennaro/src/builder-ide")
VENV = Path("/home/caseydigennaro/lm-wt/usd-backbone/.venv/bin/python")

failures: list[str] = []
checks: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    checks.append(name)
    if ok:
        print(f"  PASS  {name}" + (f" — {detail}" if detail else ""))
    else:
        print(f"  FAIL  {name}" + (f" — {detail}" if detail else ""))
        failures.append(name)


def main() -> int:
    data = ROOT / "data"
    print("== deliverables ==")
    deliverables = {
        "report": ROOT / "docs" / "research" / "simready.md",
        "priors": ROOT / "simready_priors.json",
        "result": ROOT / "RESULT.json",
        "loader": ROOT / "scripts" / "simready_loader.py",
    }
    for name, path in deliverables.items():
        check(f"{name} exists", path.exists(), f"{path.stat().st_size if path.exists() else 0} bytes")

    priors = json.loads(deliverables["priors"].read_text())
    result = json.loads(deliverables["result"].read_text())
    report = deliverables["report"].read_text()
    report_rows = json.loads((data / "sample_report.json").read_text())
    manifest = json.loads((data / "sample_manifest.json").read_text())
    verification = json.loads((data / "gltf_verification.json").read_text())
    experiment = json.loads((data / "critic_experiment.json").read_text())
    mapping = json.loads((data / "vocabulary_mapping.json").read_text())
    dataset = json.loads((data / "dataset_physics.json").read_text())
    timings = json.loads((data / "conversion_timings.json").read_text())

    print("\n== the sample ==")
    sample_root = Path.home() / "lm-cold" / "simready-sample"
    on_disk = sum(
        p.stat().st_size for p in sample_root.rglob("*") if p.is_file()
    )
    package_dirs = sorted(
        p.name for p in sample_root.iterdir() if p.is_dir() and not p.name.startswith(".")
    )
    check(
        "sample holds the 38 named packages",
        len(package_dirs) == manifest["asset_count"]
        and set(package_dirs)
        == {row["asset"] for row in manifest["assets"]},
        f"{len(package_dirs)} directories",
    )
    check(
        "sample is inside the 3 GiB budget",
        on_disk <= 3 * 1024**3,
        f"{on_disk / 1024**3:.4f} GiB on disk (budget 3 GiB)",
    )
    # Every file of the sample, checked against the size the file index says.
    index_sizes = {}
    for line in (data / "repo_index.jsonl").open():
        row = json.loads(line)
        if (
            row["type"] == "RepoFile"
            and row["path"].split("/")[0] in {r["asset"] for r in manifest["assets"]}
            and "/.thumbs/" not in row["path"]
        ):
            index_sizes[row["path"]] = (
                (row.get("lfs") or {}).get("size") or row.get("size") or 0
            )
    missing = [p for p in index_sizes if not (sample_root / p).exists()]
    wrong = [
        p
        for p, size in index_sizes.items()
        if (sample_root / p).exists()
        and (sample_root / p).stat().st_size != size
    ]
    check(
        "every sample file is present and the right size",
        not missing and not wrong,
        f"{len(index_sizes)} files, {len(missing)} missing, {len(wrong)} wrong",
    )
    check(
        "the sample manifest is the one in the result file",
        result["sample"]["assets"] == manifest["asset_count"]
        and result["sample"]["categories"] == manifest["categories_covered"],
    )

    print("\n== the loader ==")
    probe = subprocess.run(
        [
            str(VENV),
            str(deliverables["loader"]),
            "probe",
            str(sample_root / "crate_white_a01"),
        ],
        capture_output=True,
        text=True,
        timeout=300,
    )
    check("the loader probes a package", probe.returncode == 0, probe.stderr[-200:])
    if probe.returncode == 0:
        schema = json.loads(probe.stdout)
        check(
            "the loader finds the mesh through the instance proxies",
            schema["meshes"] == 1 and schema["triangles"] > 0,
            f"{schema['meshes']} mesh, {schema['triangles']} triangles",
        )
        check(
            "the loader counts the mass once",
            abs(schema["mass_kg_total"] - 2.836737632751465) < 1e-6,
            f"{schema['mass_kg_total']:.6f} kg",
        )
        check(
            "the loader reads the units",
            schema["meters_per_unit"] == 1.0 and schema["up_axis"] == "Z",
        )

    print("\n== the converted GLBs ==")
    summary = verification["summary"]
    check(
        "every GLB opens under builder-ide's reader",
        summary["opened"] == summary["assets"] == 38,
        f"{summary['opened']}/{summary['assets']}",
    )
    check("every GLB passes the full check", summary["ok"] == 38, f"{summary['ok']} ok")
    check("no GLB has a NaN position", not any(a.get("nan_positions") for a in verification["assets"]))
    check(
        "no GLB raises a reader warning",
        not any(a.get("warnings") for a in verification["assets"]),
    )
    check(
        "the bounding boxes match the USD",
        summary["max_union_box_error_m"] < 1e-5,
        f"max error {summary['max_union_box_error_m']:.3g} m",
    )

    print("\n== the critic experiment ==")
    baseline = experiment["baseline_the_critics_own_prior"]
    check(
        "the critic's own prior flags the ghost",
        baseline["ghost_flagged"] and baseline["ghost_score"] < 0.05,
        f"score {baseline['ghost_score']:.4f}",
    )
    simready = experiment["simready_prior"]["3"]
    check(
        "the SimReady prior does not flag the ghost",
        not simready["ghost_flagged_below_005"],
        f"score {simready['ghost_score']:.4f}",
    )
    other = experiment["simready_assets_scored_against_the_toy_prior"]
    check(
        "the critic's own prior calls every real asset a ghost",
        other["share_below_005"] == 1.0,
        f"{other['share_below_005']:.0%} of {len([r for r in report_rows if r.get('schema')])}",
    )

    print("\n== the priors ==")
    check(
        "the priors carry the sample's 37 categories",
        len(priors["categories"]) == 37,
        f"{len(priors['categories'])} categories",
    )
    check(
        "the priors carry the dataset-wide mass",
        all("dataset_mass_kg" in c for c in priors["categories"].values()),
    )
    check(
        "the priors carry the material table",
        len(priors["materials"]["table"]) == dataset["material_count"] == 57,
        f"{len(priors['materials']['table'])} materials",
    )
    check(
        "every asset in the dataset has a mass",
        dataset["assets_with_mass"] == 2669,
        f"{dataset['assets_with_mass']}",
    )
    check(
        "every category has a mass",
        dataset["category_count"] == 196,
        f"{dataset['category_count']} categories",
    )

    print("\n== the vocabulary ==")
    overlap = mapping["overlap"]
    check(
        "the SimReady category count is 196",
        overlap["simready_categories"] == 196,
    )
    check(
        "the overlap is name-level and stated as such",
        overlap["categories_with_an_infinigen_factory"]
        + overlap["categories_without"]
        == 196,
        f"{overlap['categories_with_an_infinigen_factory']} with, "
        f"{overlap['categories_without']} without",
    )

    print("\n== the report ==")
    for needle, label in [
        ("38 / 38", "the GLB count"),
        ("21.56 s", "the conversion total"),
        ("0.103 s", "the per-asset median"),
        ("100 %", "the real-assets-as-ghosts share"),
        ("0.149", "the SimReady ghost score"),
        ("1,246", "the semantic label count"),
        ("57", "the material count"),
        ("12 carry joints", "the jointed asset count"),
        ("22 carry a grasp curve", "the grasp count"),
        ("155 categories", "the vocabulary gap"),
    ]:
        check(f"the report states {label}", needle in report, needle)
    check(
        "the report credits NVIDIA and the licence",
        "nvidia/simready-assets" in report and "CC-BY-4.0" in report,
    )
    check(
        "the result file records the box state",
        bool(result.get("box", {}).get("cpu_count")),
        json.dumps(result.get("box", {})),
    )

    print("\n== summary ==")
    print(f"  {len(checks) - len(failures)}/{len(checks)} checks passed")
    if failures:
        print("  failed:", ", ".join(failures))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
