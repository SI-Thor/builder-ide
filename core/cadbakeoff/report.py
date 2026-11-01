#!/usr/bin/env python3
"""Build ``RESULT.json``: one file with every number the brief asks for.

The inputs are the artefacts of the run, not the run's own memory:

* ``out/result.json`` -- the per-prop, per-kernel records from
  ``run_experiment``;
* ``out/gen/replies.json`` -- what the model answered, and how many attempts
  it took to get a whole answer;
* ``out/sweep.json`` -- the parameter sweep;
* ``out/oracle.json`` -- SolidCraft's own oracle suite;
* ``out/sizes/`` and ``out/mem-*/`` -- the custom-fit binary's size and the
  memory a build takes with each binary.

Nothing here re-runs anything, so the file can be rebuilt from the artefacts
without the box.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import statistics
from typing import Any

from core.cadbakeoff.analytic import evaluate_prop
from core.cadbakeoff.specs import PROPS, PROP_NAMES

ROOT = pathlib.Path.home() / "lm-wt/cad-bakeoff"

#: The props the brief asks for an analytic ground truth on. The crate is all
#: boxes and the barrel is a tube, so both have a closed form.
ANALYTIC_PROPS = ("crate", "barrel")


def _read(path: pathlib.Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return default


def _rel(value: float | None, reference: float | None) -> float | None:
    """The relative error of ``value`` against ``reference``."""
    if value is None or reference is None or reference == 0:
        return None
    return abs(value - reference) / abs(reference)


def _body_totals(build: dict[str, Any]) -> dict[str, Any]:
    """The whole prop's mass properties, from the bodies the kernel measured.

    The kernel's own "assembly" total is not used for the centre of mass:
    SolidCraft's ``assembly.mass_properties`` reports the *rigid group* — the
    occurrences that move as one body — and a hinge is not rigid, so for a
    prop with a moving part that number is the static part's centre of mass,
    not the prop's. The prop's centre of mass is the mass-weighted mean of
    the bodies' own centres, which is what this computes.
    """
    bodies = build.get("bodies") or {}
    parts = [
        b
        for name, b in bodies.items()
        if not name.startswith("__") and b.get("volume_mm3") is not None
    ]
    volume = sum(b["volume_mm3"] for b in parts) if parts else None
    area = sum(b.get("area_mm2") or 0.0 for b in parts) if parts else None
    mass = sum(b.get("mass_kg") or 0.0 for b in parts) if parts else 0.0
    com: list[float] | None = None
    weighted = [
        b
        for b in parts
        if b.get("mass_kg") and b.get("center_of_mass_mm") and len(b["center_of_mass_mm"]) == 3
    ]
    if weighted and mass:
        com = [
            sum(b["mass_kg"] * b["center_of_mass_mm"][i] for b in weighted) / mass
            for i in range(3)
        ]
    return {"volume_mm3": volume, "area_mm2": area, "center_of_mass_mm": com}


def _prop_records(records: list[dict[str, Any]], prop: str) -> dict[str, dict[str, Any]]:
    return {r["kernel"]: r for r in records if r.get("prop") == prop and "kernel" in r}


def _kernel_summary(records: list[dict[str, Any]], kernel: str) -> dict[str, Any]:
    """The headline numbers for one kernel."""
    rows = [r for r in records if r.get("kernel") == kernel]
    built = [r for r in rows if r.get("built_first_try")]
    validation_failed = [r for r in rows if not (r.get("validation") or {}).get("ok")]
    build_failed = [
        r for r in rows
        if (r.get("validation") or {}).get("ok") and not (r.get("build") or {}).get("ok")
    ]
    action_ok = [r for r in rows if (r.get("action") or {}).get("ok")]
    urdf_ok = [r for r in rows if (r.get("urdf") or {}).get("ok")]
    times = [r["build_ms"] for r in rows if r.get("build_ms") is not None]
    return {
        "props": len(rows),
        "built_first_try": len(built),
        "built_first_try_rate": (len(built) / len(rows)) if rows else None,
        "validation_failures": len(validation_failed),
        "build_failures": len(build_failed),
        "urdf_ok": len(urdf_ok),
        "action_ok": len(action_ok),
        "build_ms_median": statistics.median(times) if times else None,
        "build_ms_by_prop": {
            r["prop"]: r["build_ms"] for r in sorted(rows, key=lambda x: str(x.get("prop")))
            if r.get("build_ms") is not None
        },
    }


def _cross_kernel(records: list[dict[str, Any]]) -> dict[str, Any]:
    """How well the two kernels agree, prop by prop."""
    out: dict[str, Any] = {}
    for prop in PROP_NAMES:
        pair = _prop_records(records, prop)
        sc, b1 = pair.get("solidcraft"), pair.get("build123d")
        if not sc or not b1:
            out[prop] = {"comparable": False}
            continue
        a = _body_totals(sc.get("build") or {})
        b = _body_totals(b1.get("build") or {})
        entry: dict[str, Any] = {
            "comparable": a["volume_mm3"] is not None and b["volume_mm3"] is not None,
            "solidcraft": {
                "volume_mm3": a["volume_mm3"],
                "area_mm2": a["area_mm2"],
                "center_of_mass_mm": a["center_of_mass_mm"],
            },
            "build123d": {
                "volume_mm3": b["volume_mm3"],
                "area_mm2": b["area_mm2"],
                "center_of_mass_mm": b["center_of_mass_mm"],
            },
        }
        if entry["comparable"]:
            entry["volume_relative_difference"] = _rel(b["volume_mm3"], a["volume_mm3"])
            entry["area_relative_difference"] = _rel(b["area_mm2"], a["area_mm2"])
            ca, cb = a["center_of_mass_mm"], b["center_of_mass_mm"]
            if ca and cb and len(ca) == 3 and len(cb) == 3:
                span = max(
                    abs(ca[i] - cb[i]) for i in range(3)
                )
                diag = sum(v * v for v in ca) ** 0.5 or 1.0
                entry["center_of_mass_max_difference_mm"] = span
                entry["center_of_mass_relative_difference"] = span / diag
        out[prop] = entry
    return out


def _analytic_section(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Each kernel against the closed form, for the two simple props."""
    out: dict[str, Any] = {}
    for prop in ANALYTIC_PROPS:
        truth = evaluate_prop(PROPS[prop])
        entry: dict[str, Any] = {
            "analytic": {
                "volume_mm3": truth.volume,
                "area_mm2": truth.area,
                "center_of_mass_mm": list(truth.centre),
                "mass_kg": truth.mass_kg,
            },
            "kernels": {},
        }
        for kernel, record in _prop_records(records, prop).items():
            totals = _body_totals(record.get("build") or {})
            entry["kernels"][kernel] = {
                "volume_mm3": totals["volume_mm3"],
                "area_mm2": totals["area_mm2"],
                "center_of_mass_mm": totals["center_of_mass_mm"],
                "volume_relative_error": _rel(totals["volume_mm3"], truth.volume),
                "area_relative_error": _rel(totals["area_mm2"], truth.area),
                "center_of_mass_max_error_mm": None,
            }
            ca, cb = totals["center_of_mass_mm"], list(truth.centre)
            if ca and cb and len(ca) == 3 and len(cb) == 3:
                entry["kernels"][kernel]["center_of_mass_max_error_mm"] = max(
                    abs(ca[i] - cb[i]) for i in range(3)
                )
        out[prop] = entry
    return out


def _sweep_section(sweep: Any) -> dict[str, Any]:
    """The sweep's headline numbers, per prop and per kernel.

    The sweep file holds one entry per prop, each with the records of every
    variant, every repeat, every kernel, and the summary the sweep itself
    computed.
    """
    out: dict[str, Any] = {}
    entries = sweep if isinstance(sweep, list) else []
    for entry in entries:
        prop = entry.get("prop")
        if not prop:
            continue
        rows = entry.get("results") or []
        summary = entry.get("summary") or {}
        per_kernel: dict[str, Any] = {}
        for kernel in ("solidcraft", "build123d"):
            kernel_rows = [r for r in rows if r.get("kernel") == kernel and "variant" in r]
            if not kernel_rows:
                continue
            by_variant: dict[int, list[dict[str, Any]]] = {}
            for r in kernel_rows:
                by_variant.setdefault(r["variant"], []).append(r)
            valid_all = 0
            valid_majority = 0
            times: list[float] = []
            for index, group in sorted(by_variant.items()):
                flags = [bool(g.get("valid")) for g in group]
                if flags and all(flags):
                    valid_all += 1
                if flags and sum(flags) > len(flags) / 2:
                    valid_majority += 1
                group_times = [g["build_ms"] for g in group if g.get("build_ms") is not None]
                if group_times:
                    times.append(statistics.median(group_times))
            own = summary.get(kernel) or {}
            per_kernel[kernel] = {
                "variants": len(by_variant),
                "repeats_per_variant": max(len(g) for g in by_variant.values()),
                "valid_variants_all_repeats": valid_all,
                "valid_variants_majority": valid_majority,
                "validity_rate_all": valid_all / len(by_variant) if by_variant else None,
                "validity_rate_majority": (
                    valid_majority / len(by_variant) if by_variant else None
                ),
                "build_ms_median_of_variant_medians": statistics.median(times) if times else None,
                "build_ms_total": sum(times) if times else None,
                "build_ms_min": own.get("build_ms_min"),
                "build_ms_max": own.get("build_ms_max"),
                "build_ms_mean": own.get("build_ms_mean"),
                "failures_by_stage": _count_stages(kernel_rows),
                "parameters_missing": sorted(
                    {m for r in kernel_rows for m in (r.get("parameters_missing") or [])}
                ),
            }
        out[prop] = {"kernels": per_kernel}
    return out


def _count_stages(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for r in rows:
        if r.get("valid"):
            continue
        stage = str(r.get("stage") or "unknown")
        counts[stage] = counts.get(stage, 0) + 1
    return counts


def _oracle_section(oracle: list[dict[str, Any]]) -> dict[str, Any]:
    if not oracle:
        return {"ran": False}
    checks = sum(len(c.get("checks") or []) for c in oracle)
    passed = sum(
        1 for c in oracle for ch in (c.get("checks") or []) if ch.get("ok")
    )
    known = sum(1 for c in oracle if c.get("known_failure"))
    return {
        "ran": True,
        "cases": len(oracle),
        "checks": checks,
        "checks_passed": passed,
        "checks_failed": checks - passed,
        "cases_marked_known_failure": known,
        "all_passed": checks == passed,
    }


def _rust_section() -> dict[str, Any]:
    """The custom-fit crate set, its size, and the memory a build takes."""
    sizes: dict[str, Any] = {}
    for name, label in (("solidcraft-cli", "full CLI"), ("solidcraft-prop", "custom-fit")):
        raw = ROOT / "solidcraft" / "target" / "release" / name
        stripped = ROOT / "out" / "sizes" / f"{name}.stripped"
        entry: dict[str, Any] = {"label": label}
        if raw.exists():
            entry["binary_bytes"] = raw.stat().st_size
        if stripped.exists():
            entry["stripped_bytes"] = stripped.stat().st_size
        sizes[name] = entry
    for name, entry in sizes.items():
        mem = ROOT / "out" / f"mem-{name}" / "stderr.txt"
        if mem.exists():
            text = mem.read_text()
            for line in text.splitlines():
                if "Maximum resident set size" in line:
                    entry["build_peak_rss_kb"] = int(line.split(":")[1].strip())
                if "Elapsed (wall clock)" in line:
                    entry["build_wall_s"] = line.split(":")[-1].strip()
    full = sizes.get("solidcraft-cli", {})
    slim = sizes.get("solidcraft-prop", {})
    out: dict[str, Any] = {
        "crates": [
            "solidcraft-engine (the command engine and the session)",
            "solidcraft-kernel (the geometry kernel: solids, booleans, mass properties)",
            "solidcraft-geom (the primitives the kernel is built on)",
            "serde_json",
        ],
        "dropped": [
            "solidcraft-gpu (the GPU renderer)",
            "solidcraft-render (the renderer)",
            "solidcraft-mcp (the MCP server)",
            "solidcraft-ui-egui (the desktop UI)",
            "solidcraft-web (the web app)",
            "the benchmark and fuzz harness (xtask, the oracle corpus driver)",
        ],
        "binary": sizes,
    }
    for key in ("binary_bytes", "stripped_bytes", "build_peak_rss_kb"):
        a, b = full.get(key), slim.get(key)
        if a and b:
            out.setdefault("savings", {})[key] = {
                "full": a,
                "custom_fit": b,
                "saved": a - b,
                "relative": (a - b) / a,
            }
    return out


def _generation_section(replies: dict[str, Any]) -> dict[str, Any]:
    """How the model answered, and how many attempts each artefact took."""
    per: dict[str, Any] = {}
    attempts_total = 0
    for key, record in sorted(replies.items()):
        attempts = int(record.get("attempt") or 0)
        attempts_total += attempts
        per[key] = {
            "status": record.get("status"),
            "attempts": attempts,
            "output_tokens": record.get("output_tokens"),
            "script_tokens": record.get("script_tokens"),
            "duration_ms": record.get("duration_ms"),
            "prompt_sha256": record.get("prompt_sha256"),
        }
    return {
        "model": "minimax/MiniMax-M3 (through the seat CLI, tools off, one turn)",
        "artefacts": per,
        "total_attempts": attempts_total,
        "transport_retries": attempts_total - len(replies),
    }


def build_result(root: pathlib.Path = ROOT) -> dict[str, Any]:
    records = _read(root / "out" / "result.json", []) or []
    sweep = _read(root / "out" / "sweep.json", []) or []
    oracle = _read(root / "out" / "oracle.json", []) or []
    replies = _read(root / "out" / "gen" / "replies.json", {}) or {}

    per_prop: dict[str, Any] = {}
    for prop in PROP_NAMES:
        pair = _prop_records(records, prop)
        entry: dict[str, Any] = {"kernels": {}}
        for kernel, record in sorted(pair.items()):
            validation = record.get("validation") or {}
            build = record.get("build") or {}
            action = record.get("action") or {}
            urdf = record.get("urdf") or {}
            repair = record.get("repair")
            entry["kernels"][kernel] = {
                "built_first_try": record.get("built_first_try"),
                "validation_ok": validation.get("ok"),
                "validation_error": validation.get("error"),
                "build_ok": build.get("ok"),
                "build_error": build.get("error"),
                "build_ms": record.get("build_ms"),
                "process_ms": build.get("process_ms"),
                "mass_properties": _body_totals(build),
                "script_tokens": (replies.get(f"{prop}.{kernel}") or {}).get("script_tokens"),
                "urdf": {
                    "ok": urdf.get("ok"),
                    "problems": urdf.get("problems"),
                    "method": (
                        "SolidCraft's own file.export (native)"
                        if kernel == "solidcraft"
                        else "a deterministic generator driven by the frozen spec"
                    ),
                },
                "action_check": action,
                "box_state": record.get("box_state"),
                "repair": repair,
                "urdf_comparison": record.get("urdf_comparison"),
            }
        if "urdf_comparison" in entry.get("kernels", {}).get("solidcraft", {}) or True:
            comparison = None
            for kernel in ("solidcraft", "build123d"):
                r = pair.get(kernel)
                if r and r.get("urdf_comparison"):
                    comparison = r["urdf_comparison"]
                    break
            if comparison is not None:
                entry["urdf_comparison"] = comparison
        per_prop[prop] = entry

    result = {
        "experiment": "cad-bakeoff: SolidCraft vs build123d for prop recipes",
        "props": list(PROP_NAMES),
        "kernels": ["solidcraft", "build123d"],
        "summary": {
            "solidcraft": _kernel_summary(records, "solidcraft"),
            "build123d": _kernel_summary(records, "build123d"),
        },
        "per_prop": per_prop,
        "cross_kernel_agreement": _cross_kernel(records),
        "analytic_ground_truth": _analytic_section(records),
        "sweep": _sweep_section(sweep),
        "solidcraft_oracle": _oracle_section(oracle),
        "rust_custom_fit": _rust_section(),
        "generation": _generation_section(replies),
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--out", default=str(ROOT / "out" / "RESULT.json"))
    parser.add_argument(
        "--markdown",
        action="store_true",
        help="also print the report's tables as markdown, so the numbers in the report come from the same file",
    )
    args = parser.parse_args()
    root = pathlib.Path(args.root).expanduser()
    result = build_result(root)
    out = pathlib.Path(args.out).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=1))
    print(f"wrote {out}")
    if args.markdown:
        print(markdown_tables(result))
    return 0


# ---------------------------------------------------------------------------
# the report's tables
# ---------------------------------------------------------------------------


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:.2f} %"


def _num(value: float | None, digits: int = 3) -> str:
    if value is None:
        return "—"
    return f"{value:,.{digits}f}"


def markdown_tables(result: dict[str, Any]) -> str:
    """The tables the report carries, rendered from the result file."""
    out: list[str] = []
    summary = result["summary"]

    out.append("### Per prop and kernel\n")
    out.append(
        "| prop | kernel | validation | build | action | URDF | build ms | script tokens |"
    )
    out.append("|---|---|---|---|---|---|---|---|")
    for prop in result["props"]:
        for kernel in result["kernels"]:
            entry = result["per_prop"].get(prop, {}).get("kernels", {}).get(kernel)
            if not entry:
                out.append(f"| {prop} | {kernel} | — | — | — | — | — | — |")
                continue
            repair = entry.get("repair") or {}
            inner = repair.get("result") or {}
            build_ok = entry.get("build_ok")
            action_ok = entry.get("action_check", {}).get("ok")
            urdf_ok = entry.get("urdf", {}).get("ok")
            stage = "ok"
            if not entry.get("validation_ok"):
                stage = "validation failed"
            elif not build_ok:
                stage = "build failed"
            final = ""
            if repair:
                inner_build = (inner.get("build") or {}).get("ok")
                inner_action = (inner.get("action") or {}).get("ok")
                flag = ", design changed (excluded)" if repair.get("design_changed") else ""
                final = (
                    f"; after repair: build {inner_build}, action {inner_action}{flag}"
                )
            out.append(
                f"| {prop} | {kernel} | {stage} | {build_ok} | {action_ok} | {urdf_ok} | "
                f"{_num(entry.get('build_ms'), 1)} | {entry.get('script_tokens')}{final} |"
            )

    out.append("\n### Cross-kernel agreement, against the closed form\n")
    out.append(
        "| prop | kernel | volume (mm³) | rel. error | area (mm²) | rel. error | "
        "CoM max error (mm) |"
    )
    out.append("|---|---|---|---|---|---|---|")
    for prop, entry in result["analytic_ground_truth"].items():
        truth = entry["analytic"]
        for kernel, data in entry["kernels"].items():
            out.append(
                f"| {prop} (analytic {truth['volume_mm3']:,.0f}) | {kernel} | "
                f"{_num(data['volume_mm3'], 0)} | {_pct(data['volume_relative_error'])} | "
                f"{_num(data['area_mm2'], 0)} | {_pct(data['area_relative_error'])} | "
                f"{_num(data['center_of_mass_max_error_mm'], 3)} |"
            )

    out.append("\n### Cross-kernel agreement, prop by prop\n")
    out.append("| prop | volume rel. difference | area rel. difference | CoM max difference (mm) |")
    out.append("|---|---|---|---|")
    for prop, entry in result["cross_kernel_agreement"].items():
        if not entry.get("comparable"):
            out.append(f"| {prop} | — | — | — |")
            continue
        out.append(
            f"| {prop} | {_pct(entry.get('volume_relative_difference'))} | "
            f"{_pct(entry.get('area_relative_difference'))} | "
            f"{_num(entry.get('center_of_mass_max_difference_mm'), 3)} |"
        )

    out.append("\n### The sweep\n")
    out.append(
        "| prop | kernel | variants | valid (all repeats) | valid (majority) | "
        "median build ms | failures by stage |"
    )
    out.append("|---|---|---|---|---|---|---|")
    for prop, entry in result["sweep"].items():
        for kernel, data in entry["kernels"].items():
            out.append(
                f"| {prop} | {kernel} | {data['variants']} | "
                f"{data['valid_variants_all_repeats']} ({_pct(data['validity_rate_all'])}) | "
                f"{data['valid_variants_majority']} ({_pct(data['validity_rate_majority'])}) | "
                f"{_num(data['build_ms_median_of_variant_medians'], 1)} | "
                f"{data['failures_by_stage']} |"
            )

    out.append("\n### The Rust custom fit\n")
    rust = result["rust_custom_fit"]
    out.append("| | full CLI | custom-fit | saved |")
    out.append("|---|---|---|---|")
    full = rust["binary"]["solidcraft-cli"]
    slim = rust["binary"]["solidcraft-prop"]
    for key, label in (
        ("binary_bytes", "binary, with debuginfo (B)"),
        ("stripped_bytes", "binary, stripped (B)"),
        ("build_peak_rss_kb", "peak RSS of one build (kB)"),
    ):
        a, b = full.get(key), slim.get(key)
        saved = rust.get("savings", {}).get(key, {})
        out.append(
            f"| {label} | {_num(a, 0)} | {_num(b, 0)} | "
            f"{_num(saved.get('saved'), 0)} ({_pct(saved.get('relative'))}) |"
        )

    out.append("\n### The model\n")
    generation = result["generation"]
    out.append("| artefact | attempts | script tokens | output tokens |")
    out.append("|---|---|---|---|")
    for key, data in generation["artefacts"].items():
        out.append(
            f"| {key} | {data['attempts']} | {data['script_tokens']} | {data['output_tokens']} |"
        )
    out.append(
        f"\nTotal model calls: {generation['total_attempts']} for {len(generation['artefacts'])} "
        f"artefacts ({generation['transport_retries']} transport retries)."
    )
    return "\n".join(out)


if __name__ == "__main__":
    raise SystemExit(main())
