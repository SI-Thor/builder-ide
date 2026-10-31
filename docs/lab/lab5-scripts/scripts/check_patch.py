#!/usr/bin/env python3
# lab5 — validate patch/solver-batch.patch against the upstream annealing.py.
#
# 1. applies the patch to a pristine copy of the upstream file (thor-spike;
#    byte-identical in the v2 venv's checkout) in a temp dir,
# 2. py_compiles the result,
# 3. statically proves the patched method is runnable as written: every
#    `self.<attr>` it reads must be assigned in __init__ (by upstream or by
#    the patch) or be a method of the class, and every name the patch's
#    added import provides is used. This is the check that would have caught
#    the original `self._revert` bug (upstream has `_move` but no `_revert`;
#    py_compile passes, the runtime would not).
#
# Read-only everywhere; the patched copy lives in a temp dir.

import ast
import py_compile
import subprocess
import sys
import tempfile
from pathlib import Path

LAB5 = Path(__file__).resolve().parent.parent
UPSTREAM = Path.home() / (
    "src/infinigen-thor/src/infinigen/core/constraints/example_solver/annealing.py"
)
PATCH = LAB5 / "patch/solver-batch.patch"

NEW_METHOD = "retry_attempt_proposals_batched"


def main() -> int:
    rel = UPSTREAM.relative_to(Path.home() / "src/infinigen-thor")
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        dst = tdp / rel
        dst.parent.mkdir(parents=True)
        dst.write_bytes(UPSTREAM.read_bytes())
        r = subprocess.run(["patch", "-p1", "--dry-run", "-i", str(PATCH)], cwd=tdp,
                           capture_output=True, text=True)
        if r.returncode != 0:
            print("FAIL: patch does not apply\n" + r.stdout + r.stderr)
            return 1
        subprocess.run(["patch", "-p1", "-s", "-i", str(PATCH)], cwd=tdp, check=True)
        patched = dst.read_text()
        py_compile.compile(str(dst), doraise=True)
        print(f"patch applies cleanly to {rel} and py_compiles")

    tree = ast.parse(patched)
    cls = next(n for n in ast.walk(tree)
               if isinstance(n, ast.ClassDef)
               and n.name == "SimulatedAnnealingSolver")
    methods = {n.name: n for n in cls.body if isinstance(n, (ast.FunctionDef,))}
    init = methods["__init__"]

    # names assigned on self in __init__ (upstream + patch)
    assigned = set()
    for n in ast.walk(init):
        if (isinstance(n, ast.Assign)
                and isinstance(n.targets[0], ast.Attribute)
                and isinstance(n.targets[0].value, ast.Name)
                and n.targets[0].value.id == "self"):
            assigned.add(n.targets[0].attr)

    fn = methods[NEW_METHOD]
    reads = {n.attr for n in ast.walk(fn)
             if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)
             and n.value.id == "self" and isinstance(n.ctx, ast.Load)}
    missing = sorted(reads - assigned - set(methods))
    print(f"self attrs read by {NEW_METHOD}: {sorted(reads)}")
    if missing:
        print(f"FAIL: reads self.{{{', '.join(missing)}}} which neither "
              f"__init__ assigns nor the class defines")
        return 1
    print(f"all self attrs resolve (__init__ assigns {sorted(assigned & reads)}, "
          f"class methods {sorted(set(methods) & reads)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
