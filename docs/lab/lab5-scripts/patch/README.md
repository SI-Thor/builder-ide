# lab5 patch — the minimal upstreamable change

`solver-batch.patch` — against
`src/infinigen/core/constraints/example_solver/annealing.py` (applies cleanly
with `patch -p1` from the repo root; verified against the thor-spike branch
and the v2 venv's identical checkout). Validated by `../scripts/check_patch.py`
(applies + compiles + every `self.<attr>` the new method reads exists — the
check that caught and killed a `self._revert` call in the first draft of this
diff: upstream has `_move` but no `_revert`, and `py_compile` alone passes
that bug) and `../scripts/smoke_patch.py` (runs the patched method on stub
moves/state: lexicographic best, cached-vs-rescored apply paths, uniform and
sample picking, invalid-budget cap):

1. `SimulatedAnnealingSolver.__init__` gains two gin-configurable knobs,
   **`batch_size = 1`** (N candidates per step) and **`batch_mode = "best"`**
   (`best` | `sample` | `uniform`). At `batch_size = 1` the original
   single-candidate path runs untouched — the default is behaviour-identical,
   so the knob is safe to land upstream inert.
2. `retry_attempt_proposals` grows a batched sibling used when
   `batch_size > 1`: draw N applicable candidates from the same generator,
   score each (apply → evaluate → revert), pick one (fewest-violations-then-
   lowest-loss / Boltzmann at the current temperature / uniformly), re-apply
   it, and hand it to `step()`'s unchanged Metropolis accept. Stochastic
   applies (Addition/Resample/ReinitPose/RelationPlaneChange) are re-scored
   after re-apply; deterministic ones (Translate/Rotate/Deletion) reuse the
   batch score.

**The scheduler-side knob** (builder-ide's side): N is one gin override —
`SimulatedAnnealingSolver.batch_size = <N>` (+ `batch_mode`), i.e. exactly
how `solve_steps_large` etc. are already driven by
`compose_indoors`/`fast_solve.gin`. The scheduler treats it as a load knob:
`1` under GPU contention, raised when the box is idle — no new plumbing, and
the same override string works for the venv CLI (`-p` overrides) as for an
in-process engine.

The measured caveat that decides the default is in `../exp-solver-batch.md`:
`best` shifts the annealer's output distribution (greedier kernel); `sample`
does not. `annealing.py.new`/`.orig` are the working copies this diff was
generated from.
