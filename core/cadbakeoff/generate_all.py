#!/usr/bin/env python3
"""Run the generator over several processes, one per kernel or prop group.

The model call is the slow part and it is independent per prop, so the arms
are split across processes. Each process writes its own replies file; the
driver merges them.

A reply that comes back truncated is a transport problem, not a prop problem.
So the driver makes more than one pass: the pairs that are still missing after
a pass are asked again on their own. The number of passes is recorded.
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent.parent
PYTHON = pathlib.Path.home() / "lm-wt/cad-bakeoff/harness/bin/python"
OUT = pathlib.Path.home() / "lm-wt/cad-bakeoff/out/gen"

GROUPS = [
    ("solidcraft-a", "solidcraft", ["crate", "chest", "lantern", "door", "drawer_unit"]),
    ("solidcraft-b", "solidcraft", ["barrel", "cart", "gate", "ladder", "table"]),
    ("build123d-a", "build123d", ["crate", "chest", "lantern", "door", "drawer_unit"]),
    ("build123d-b", "build123d", ["barrel", "cart", "gate", "ladder", "table"]),
]

#: How many times the driver goes round asking for what is still missing.
PASSES = 4


def artifact_path(prop: str, kernel: str) -> pathlib.Path:
    suffix = ".json" if kernel == "solidcraft" else ".py"
    return OUT / f"{prop}.{kernel}{suffix}"


def spawn(name: str, kernel: str, props: list[str], records: pathlib.Path):
    cmd = [
        str(PYTHON),
        "-m",
        "core.cadbakeoff.generate",
        "--out",
        str(OUT),
        "--records",
        str(records),
        "--kernels",
        kernel,
        "--props",
        *props,
    ]
    log = (OUT / f"log-{name}.txt").open("a")
    return name, subprocess.Popen(cmd, cwd=str(REPO), stdout=log, stderr=subprocess.STDOUT), log


def missing_pairs() -> list[tuple[str, str]]:
    out = []
    for _, kernel, props in GROUPS:
        for prop in props:
            if not artifact_path(prop, kernel).exists():
                out.append((prop, kernel))
    return out


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    codes: list[int] = []
    for attempt in range(PASSES):
        todo = missing_pairs()
        if not todo:
            break
        if attempt:
            print(f"--- pass {attempt + 1}: asking again for {todo}", flush=True)
        else:
            print(f"--- pass 1: {len(todo)} pairs", flush=True)
        # Split the missing pairs by kernel so the two arms never share a
        # process, and keep them in groups of at most five.
        by_kernel: dict[str, list[str]] = {}
        for prop, kernel in todo:
            by_kernel.setdefault(kernel, []).append(prop)
        procs = []
        for kernel, props in sorted(by_kernel.items()):
            for index in range(0, len(props), 5):
                chunk = props[index : index + 5]
                name = f"{kernel}-retry{attempt}-{index}"
                procs.append(spawn(name, kernel, chunk, OUT / f"replies-{name}.json"))
        for name, proc, log in procs:
            codes.append(proc.wait())
            log.close()
            print("finished", name, codes[-1], flush=True)

    merged: dict = {}
    for path in sorted(OUT.glob("replies-*.json")):
        merged.update(json.loads(path.read_text()))
    (OUT / "replies.json").write_text(json.dumps(merged, indent=1))

    todo = missing_pairs()
    print("merged", len(merged), "records", flush=True)
    print("missing:", todo, flush=True)
    return 0 if not todo else 1


if __name__ == "__main__":
    raise SystemExit(main())
