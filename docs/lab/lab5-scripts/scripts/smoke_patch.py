#!/usr/bin/env python3
# lab5 — runtime smoke test of patch/solver-batch.patch's batched method.
#
# check_patch.py proves the patch applies, compiles and only touches
# attributes that exist. This script goes one step further and *runs* the
# patched `retry_attempt_proposals_batched` on stub moves/state (no Blender,
# no infinigen imports): it applies the patch to a temp copy of the upstream
# annealing.py, extracts the method, and checks the behaviours the sweep
# depended on:
#   1. best-of-N is (violations, loss)-lexicographic — the annealer's order
#   2. a deterministic-class pick (Translate/Rotate/Deletion) reuses the
#      cached batch score (no second evaluate)
#   3. a stochastic-class pick is re-applied AND re-scored (the realization
#      the annealer judges is the one in the state)
#   4. uniform picks any candidate, exactly one stays applied
#   5. all-invalid applies stop at N * max_invalid_candidates and leave the
#      state untouched
#   6. sample at temp -> 0 puts all weight on the min-loss candidate
# Read-only everywhere; the patched copy lives in a temp dir.

import ast
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace

LAB5 = Path(__file__).resolve().parent.parent
UPSTREAM = Path.home() / (
    "src/infinigen-thor/src/infinigen/core/constraints/example_solver/annealing.py"
)
PATCH = LAB5 / "patch/solver-batch.patch"
NEW_METHOD = "retry_attempt_proposals_batched"


def patched_method() -> str:
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        rel = UPSTREAM.relative_to(Path.home() / "src/infinigen-thor")
        dst = tdp / rel
        dst.parent.mkdir(parents=True)
        dst.write_bytes(UPSTREAM.read_bytes())
        subprocess.run(["patch", "-p1", "-s", "-i", str(PATCH)], cwd=tdp, check=True)
        src = dst.read_text()
    tree = ast.parse(src)
    cls = next(n for n in ast.walk(tree)
               if isinstance(n, ast.ClassDef) and n.name == "SimulatedAnnealingSolver")
    fn = next(n for n in cls.body
              if isinstance(n, ast.FunctionDef) and n.name == NEW_METHOD)
    return ast.get_source_segment(src, fn)


def main() -> int:
    import logging
    import typing

    import numpy as np

    class TranslateMove: pass  # noqa: E701
    class RotateMove: pass  # noqa: E701
    class Deletion: pass  # noqa: E701

    g = {"np": np, "logging": logging, "logger": logging.getLogger("t"),
         "typing": typing,
         "eval_memo": SimpleNamespace(evict_memo_for_move=lambda *a: None),
         "TranslateMove": TranslateMove, "RotateMove": RotateMove,
         "Deletion": Deletion}
    exec(patched_method(), g)  # noqa: S102 — the method under test, sandboxed stubs
    batched = g[NEW_METHOD]

    class Res:
        def __init__(s, viol, loss):
            s._viol, s._loss = viol, loss
        def viol_count(s):
            return s._viol
        def loss(s):
            return s._loss

    class Move:
        def __init__(s, i, viol, loss):
            s.i, s.viol, s.loss = i, viol, loss
        def apply(s, state):
            state.applied.add(s.i)
            return True
        def revert(s, state):
            state.applied.discard(s.i)

    class DetMove(Move, TranslateMove):  # a deterministic-class move
        pass

    state = SimpleNamespace(applied=set())
    calls = []

    def propose(moves):
        def f(cg, st, fd, temp):
            yield from moves
        return f

    class Self:
        batch_size, batch_mode, max_invalid_candidates, eval_memo = 4, "best", 10, {}
        def _move(s, cg, st, m, fd):
            calls.append(m.i)
            return Res(m.viol, m.loss)

    # 1) deterministic pick: cached batch score returned, no re-score
    state.applied.clear(); calls.clear()
    mv, res, n_inv = batched(Self(), propose([DetMove(i, 0, 50.0 - i) for i in range(4)]),
                             None, state, 1.0, None)
    assert (mv.i, res.loss(), n_inv, state.applied, calls) == (3, 47.0, 0, {3}, [0, 1, 2, 3])

    # 2) stochastic pick: re-applied AND re-scored
    state.applied.clear(); calls.clear()
    mv, res, n_inv = batched(Self(), propose([Move(i, 0, 50.0 - i) for i in range(4)]),
                             None, state, 1.0, None)
    assert (mv.i, res.loss(), state.applied, calls) == (3, 47.0, {3}, [0, 1, 2, 3, 3])

    # 3) best is (viol, loss)-lexicographic
    state.applied.clear(); calls.clear()
    mv, res, _ = batched(Self(), propose([Move(0, 2, 1.0), DetMove(1, 0, 40.0)]),
                         None, state, 1.0, None)
    assert (mv.i, res.loss()) == (1, 40.0)

    # 4) uniform: any pick, exactly one applied
    Self.batch_mode = "uniform"
    state.applied.clear()
    mv, res, _ = batched(Self(), propose([Move(i, 0, 1.0) for i in range(4)]),
                         None, state, 1.0, None)
    assert mv.i in range(4) and state.applied == {mv.i}

    # 5) all-invalid: budget = N*max_invalid, state untouched
    class Bad(Move):
        def apply(s, st):
            return False
    state.applied.clear()
    mv2, res2, n_inv2 = batched(Self(), lambda *a: iter(Bad(10 + i, 0, 0) for i in range(50)),
                                None, state, 1.0, None)
    assert res2 is None and n_inv2 == 40 and not state.applied, (res2, n_inv2, state.applied)

    # 6) sample at temp -> 0: all weight on the min-loss candidate
    Self.batch_mode = "sample"
    state.applied.clear()
    mv, res, _ = batched(Self(), propose([Move(i, 0, float(i)) for i in range(4)]),
                         None, state, 0.0, None)
    assert mv.i == 0 and state.applied == {0}

    print("smoke_patch OK (6 cases): lexicographic best; deterministic reuses the"
          " cached score; stochastic re-scores after re-apply; uniform/sample pick;"
          " invalid budget = N*max_invalid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
