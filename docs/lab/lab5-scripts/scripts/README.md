# lab5 scripts — batch the solver's proposals (round 5, IDEAS #4)

| file | what it is |
|---|---|
| `run_solve.py` | solve-only driver: the `compose_indoors` solve stages (rooms → large → populate-intermediate → medium → small) with no terrain/cameras/render. Arms: `baseline` (upstream semantics + probes) or `batch` (N candidates per step, mode best/sample/uniform, budget same-steps/equal). One JSON per run. |
| `solver_patch.py` | **the changed file**: `SimulatedAnnealingSolver.retry_attempt_proposals` copied out of `infinigen/core/constraints/example_solver/annealing.py` and rewritten to score N candidates per step (apply → evaluate → revert each, pick, re-apply, hand to the untouched Metropolis `step`). Installed by monkeypatch — the infinigen checkouts and the venv are never written. Also holds the per-candidate timing probes and the optional node-impl profiler (`--profile`). |
| `sweep.py` | the arm × seed sweep, interleaved by seed (round rule 4); arms per `exp-solver-batch.md` §3. Writes `runs/sweep_progress.txt`, box snapshots via `box_state.sh`. |
| `analyze.py` | tables (walls, final placement score, per-candidate cost split) + **the gate**: two-sample KS vs baseline, raw / tie-quantised / paired-by-seed (the seed is the independent unit — stages within a seed are sequential), plus Cliff's δ and violation counts. `python3 scripts/analyze.py [results_dir]`. |
| `probe_seeds.sh` | which seeds survive the upstream floor-plan solver (it crashes on degenerate rooms, e.g. seeds 2/3/4); the sweep uses five surviving seeds. |
| `box_state.sh` | the box's state beside every number (load, mem, rails, clocks). |
| `check_patch.py` | validates `patch/solver-batch.patch`: applies to a pristine upstream copy, `py_compile`s, and statically proves every `self.<attr>` the new method reads is assigned in `__init__` or defined on the class. |
| `smoke_patch.py` | runs the patched `retry_attempt_proposals_batched` on stub moves/state (no Blender): lexicographic best-of-N, deterministic moves reuse the cached score, stochastic moves re-score after re-apply, uniform/sample picking, invalid-budget cap. |

Run inside the v2 venv with `PYTHONPATH=pylibs` (Indoors-only deps installed
read-only into `lab5/pylibs`; see `exp-solver-batch.md` §3). Nothing here
writes to `~/src/infinigen-thor`, `~/lm-wt/v2-thor` or any other worktree.

Tests: `check_patch.py` + `smoke_patch.py` validate the upstreamable diff
(see `../patch/README.md`); the uniform-pick arm (`b8unifg`) is the sweep's
built-in control — its proposal kernel provably matches the baseline, so if
it *fails* the gate the harness is broken, not the idea.
