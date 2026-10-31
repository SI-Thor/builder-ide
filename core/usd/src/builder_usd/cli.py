"""The command line — compile, verify, read, probe.

``python -m builder_usd demo --out /tmp/fjellvik``
    compile the built-in recipe into a layered USD stage.

``python -m builder_usd compile --recipe recipe.json --out /tmp/stage``
    compile a recipe file.

``python -m builder_usd verify --recipe recipe.json --out /tmp/stage``
    re-emit into a temporary directory and compare, byte for byte.

``python -m builder_usd read --out /tmp/stage``
    open the composed stage and print what is in it.

``python -m builder_usd probe``
    measure whether this process has any path to the GPU.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

from builder_usd.compile import compile_recipe
from builder_usd.demo import demo_bundle
from builder_usd.provenance import Provenance
from builder_usd.recipe_source import StubRecipeSource, document_from_dict
from builder_usd.verify import compare_emissions, describe_stage, open_stage

__all__ = ["main", "load_bundle"]


def load_bundle(data: dict[str, Any]) -> tuple[StubRecipeSource, dict[str, Provenance]]:
    """Split a recipe file into its recipe document and its provenance records.

    A file may be a bare recipe document, or a bundle of ``{"recipe": ...,
    "provenance": {...}}`` — the provenance map is what the scheduler stamps
    (core-spec v2 §1.6) and is kept out of the recipe document so the recipe
    stays exactly the shape core-spec v2 §1.1 gives it.
    """
    if "recipe" in data and isinstance(data["recipe"], dict):
        recipe_data = data["recipe"]
        provenance_data = data.get("provenance") or {}
    else:
        recipe_data = data
        provenance_data = {}
    records = {
        path: Provenance.from_dict(record) for path, record in provenance_data.items()
    }
    return StubRecipeSource(document_from_dict(recipe_data)), records


def _cmd_compile(args: argparse.Namespace) -> int:
    if args.demo:
        bundle = demo_bundle()
        source, records = load_bundle(bundle)
    else:
        data = json.loads(Path(args.recipe).read_text(encoding="utf-8"))
        source, records = load_bundle(data)
    result = compile_recipe(source, Path(args.out), records)
    print(f"recipe:  {result.recipe_hash}")
    print(f"stage:   {result.out_dir}")
    for concern, name in sorted(result.layers.items()):
        print(f"  layer  {concern:<12} {name}")
    for path, asset in sorted(result.assets.items()):
        print(
            f"  asset  {path:<22} {asset.glb.path} "
            f"({asset.glb.bytes} B, sha256 {asset.glb.sha256[7:19]})"
        )
    print(f"  files  {len(result.files)} written + manifest.json")
    return 0


def _cmd_verify(args: argparse.Namespace) -> int:
    if args.demo:
        source, records = load_bundle(demo_bundle())
    else:
        data = json.loads(Path(args.recipe).read_text(encoding="utf-8"))
        source, records = load_bundle(data)
    out_dir = Path(args.out)
    with tempfile.TemporaryDirectory(prefix="builder-usd-verify-") as tmp:
        compile_recipe(source, Path(tmp), records)
        differences = compare_emissions(out_dir, Path(tmp))
    if not differences:
        print(f"IDENTICAL: {out_dir} re-emits byte for byte")
        return 0
    print(f"DIFFERENT: {len(differences)} file(s) differ")
    for difference in differences:
        print(f"  {difference}")
    return 1


def _cmd_read(args: argparse.Namespace) -> int:
    stage = open_stage(Path(args.out) / "root.usda")
    print(describe_stage(stage))
    return 0


def _cmd_probe(args: argparse.Namespace) -> int:
    from builder_usd.probe import probe

    result = probe()
    print(f"gpu free:      {result.gpu_free}")
    print(f"gpu mappings:  {len(result.gpu_mappings)}")
    print(f"gpu fds:       {len(result.gpu_fds)}")
    print(f"peak rss:      {result.peak_rss_kb} kB")
    for note in result.notes:
        print(f"note:          {note}")
    return 0 if result.gpu_free else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="builder_usd", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    compile_parser = sub.add_parser("compile", help="compile a recipe into layered USD")
    compile_parser.add_argument("--recipe", help="recipe JSON file")
    compile_parser.add_argument("--demo", action="store_true", help="use the built-in recipe")
    compile_parser.add_argument("--out", required=True, help="output directory")
    compile_parser.set_defaults(func=_cmd_compile)

    verify_parser = sub.add_parser("verify", help="re-emit and compare, byte for byte")
    verify_parser.add_argument("--recipe", help="recipe JSON file")
    verify_parser.add_argument("--demo", action="store_true", help="use the built-in recipe")
    verify_parser.add_argument("--out", required=True, help="the directory to verify")
    verify_parser.set_defaults(func=_cmd_verify)

    read_parser = sub.add_parser("read", help="open the composed stage and print it")
    read_parser.add_argument("--out", required=True, help="the stage directory")
    read_parser.set_defaults(func=_cmd_read)

    probe_parser = sub.add_parser("probe", help="measure whether this process can touch the GPU")
    probe_parser.set_defaults(func=_cmd_probe)

    args = parser.parse_args(argv)
    if args.command in ("compile", "verify") and not args.demo and not args.recipe:
        parser.error("--recipe or --demo is required")
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
