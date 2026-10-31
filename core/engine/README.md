# The engine adapter — one seam, so a v1 → v2 change is one adapter

The recipe is the source of truth and it is **ours**; the engine that
compiles and renders it is pinned per project and **swappable**. This
package is the thin seam between the two (core-spec §1.1/§1.9; the engine
decision, `docs/research/ig2-procfunc.md` — whose first falsifier, *alpha
churn*, is mitigated exactly by putting our schema above the engine):

> Define our own recipe schema *above* procfunc, so an upstream change is
> a re-implementation of one adapter rather than a change to every recipe
> we have written. — E, "What would make this recommendation wrong"

Plan §3 week-1 item 3, with its pass/fail: *a recipe written today
survives an engine swap under it; the adapter is the only thing that
changes.*

```
core.recipe (ours, above the engine)              the engine, behind adapters
──────────────────────────────────────           ──────────────────────────
Recipe / RecipeEntry / EnginePin      ──►  generate_stage / reexecute
version_hash + seeds + ops (the diff) ──►  render_preview
the compiled-output rule (§7.11)      ◄──  export
```

## The contract's five rules (`contract.py`)

1. **The recipe is ours.** Every request carries the recipe in our schema
   (`core.records.Recipe`). An engine never sees an engine-native format;
   a generator reference is a *name* the adapter resolves, not code.
2. **The pin is checked.** `request.recipe.engine_pin` must equal the
   engine's own reported pin — repo, commit, **config hash**, blender,
   python (RV patch 13: the config hash is load-bearing). A mismatch is
   `EnginePinMismatch`, because an engine that honoured a foreign pin
   would poison the stage cache with work built under different settings
   than the pin promises. A swap is an explicit pin edit, never a silent
   reinterpretation (X R9).
3. **Same request, same bytes.** Determinism is the stage-hit invariant
   (§1.9 — a hit is byte-identical to re-evaluation) and what job dedup
   (§5.3) converges on. No wall-clock, hostname or ambient state reaches
   the bytes. Content determines the bytes; the version hash determines
   the key.
4. **Stage keys are canonical.** `StageResult.stage_key` *is*
   `core.recipe.stagecache.stage_cache_key(version_hash, pin, stage,
   dep_keys)` — one home for the arithmetic; engines report it, callers
   verify it (`expected_stage_key`).
5. **The lower layer belongs to the engine.** What a stage's `data` *is*
   differs by flavour — v1 a stage output blob, v2 the traced instance
   graph (E §2: the recipe's lower layer, the missing half of the stage
   cache). Only `reexecute` interprets it, and only for a base its own
   flavour produced.

## The flavours

| module | what it is | what is real today | the named missing piece |
|---|---|---|---|
| `fake.py` | the deterministic test double | everything — it *is* the fake | none; it is not supposed to grow one |
| `infinigen1.py` | v1 as the spike runs it (`docs/research/spike-phase1.md`): one pinned subprocess per stage | the whole subprocess contract: argv, task flags, the rung ladder, content-addressed outputs, the config-bundle verification, every refusal | the engine repo's `infinigen_thor.stage_runner` (our fork's half of the seam) and the entries→gin translation; without the checkout, `EngineUnavailable` names it |
| `infinigen2.py` | 2.0 + procfunc in-process — the decision's engine (E §3, option C) | the translation: our entries → generator calls (the `_rand_from_params` convention), our edit ops → graph edits; the envelope that names the lower layer | the imported runtime (procfunc pins `bpy==4.2.0` / Python `==3.11.*`; this core is 3.12 — E §2) and the mesh exporter (v2 ships none; `builder_usd` is its natural home) |
| `venv2.py` | **2.0 through its own venv's CLI** — the subprocess boundary that renders on the Thor today (the confirming experiment's venv, `~/lm-wt/v2-thor`, read-only) | **the render rung and the traced stage, live**: `render` is the subject entry's chain through `render_cycles` (Cycles CUDA) at the ladder's resolution/samples; `trace` is `--trace graph` at `RANDOM_CONTROL`, **normalized to byte-stability** (the experiment §3.3's two wobbles — the `$repr` pointer leak, the `generator_times` wall-clock — removed); the **pin is interrogated** from the venv (resolved packages + clone commit → the config hash); the licence row comes from the venv's own metadata | `replace`/`execute` (single-node re-execution needs the engine-side instrumentation the experiment built in its `choice_tool.py`; upstream ships no CLI for it) and `export` (v2 ships no exporter) |
| `gate.py` | the merge gate's engine rungs (`core.ports.MergeGateEngine`, §2.3) over any engine | the deterministic-rebuild rung really byte-compares two generated stages; the render rung renders through the seam | the verdict's critic half (stays `verdict@scripted` until a critic is calibrated, RV patch 15) |
| `registry.py` | `open_engine(spec)` / `engine_from_env()` | everything | nothing — this *is* the configuration story |

The subprocess boundary (v1) and the procfunc boundary (v2) are one
injectable callable each (`CommandRunner`, `ProcfuncRuntime`), so the
contract tests drive the adapters' own halves without a checkout on the
box. The venv boundary (v2's CLI) is a `ProcfuncRuntime` whose two
CLI-crossing ops are real and whose three refusals name their pieces.

## Pointing the core at a real engine is configuration

```python
from core.engine import open_engine

# today — the tests and the acceptance suites (seats/engine.py::SPEC)
engine = open_engine({"flavour": "fake", "pin": ENGINE_PIN})

# the decision's engine, on the box today — the venv's CLI as the boundary
# (this is what the M1 real-engine run puts in BUILDER_ENGINE)
engine = open_engine({
    "flavour": "infinigen-2-procfunc",
    "runtime": "venv",
    "python": "~/lm-wt/v2-thor/.venv/bin/python",
    "repo": "~/lm-wt/v2-thor/src/infinigen-upstream",
    "generators": {"crates": "storage_cabinet_with_door_rand", ...},
    "output_dir": "$BUILDER_HOME/engine",
    # no "pin": the venv is asked; one may be given, and drift is refused
})

# the spike's engine, when its stage runner lands in the fork
engine = open_engine({
    "flavour": "infinigen-1x",
    "pin": {...},                      # repo, commit, config hash, blender, python
    "repo": "~/src/infinigen-thor",
    "python": "~/src/infinigen-thor/.venv/bin/python",
    "config_files": [".../base.gin", ".../fast_solve.gin"],
    "output_dir": "$BUILDER_HOME/stages",
})

# the decision's engine in-process, when the v2 gate (week-1 item 2) lands
engine = open_engine({"flavour": "infinigen-2-procfunc", "pin": {...}})
```

The same shape reads from `BUILDER_ENGINE` (JSON) via `engine_from_env()`,
so deploying a real engine to the Thor is one environment variable on the
service — no code change, no recipe change. An unset environment returns
`None`; the core never invents an engine to fill the gap.

## The engine swap test (the standing gate, plan §6)

`tests/engine/test_contract.py::test_the_engine_swap_a_recipe_written_today_survives`:
the same two entries, written under the v1 pin, replay under the v2
adapter after **one pin edit** — no entry is rewritten, only the pin and
the adapter change; every stage key changes (the cache invalidates
honestly rather than serving stale bytes); and the new engine refuses to
re-execute the old engine's recorded stages, so nothing rides through the
swap.

## Where it plugs in

- **The acceptance suites** (`tests/acceptance/m1`, `tests/acceptance/week`):
  the render rungs and the gate's engine half run on this seam behind the
  fake engine by default; `BUILDER_ENGINE` (or `seats/engine.py::SPEC`) is
  the line a real engine changes — and the M1 suite's `-m engine` run has
  pointed it at the v2 venv and rendered for real (see below). The door's
  `render_job` renders the **committed version** — the render is of the
  version the seal names.
- **The night runner** (`core/night/executor.py`): the `TaskExecutor` seam
  (plan/run) is the scheduler's half; an engine-backed executor composes
  this seam with rails and the iteration loop — that wiring is the
  render-rung item (week-1 item 4).
- **The stage cache** (`core/recipe/stagecache.py`): the keys this seam
  reports; the on-disk cache and partial regeneration are week-2 item 9.

## The render rung, measured (2026-10-31, first live run)

The M1 session's `-m engine` run put the venv runtime behind the seam end
to end (box state beside every number, per the standing rule): load
average 22–23 on the 14 cores, GPU idle before the renders, Cycles CUDA
during. `infinigen 2.0.0a3 @ 224598d4` · `procfunc 0.37.0` · `bpy 4.2.0`
· Python 3.11.13.

- **Renders** (rung 2 = 960×540 at 16 samples): **5.45 s** (crates' chain,
  seed 42) and **4.33 s** (racks' chain, seed 43) wall per render,
  PNGs of ~395–407 KB with the artifact hash, provenance (engine pin +
  resolved generator + the exact ask) and the licence row in the ledger.
  The whole 31-step session, real renders included, played in ~33 s.
- **Stages**: a stage generated twice through the venv — all three
  entries traced at `RANDOM_CONTROL` — is **byte-identical** across
  generations (~2 s per trace), which is the stage-hit invariant holding
  on real engine bytes, and what the gate's rebuild rung byte-compares.
- **The pin swap happened for real**: the run performed the explicit pin
  edit (`SI-Thor/infinigen-thor@9f31c0e` → `princeton-vl/infinigen@
  224598d4`, the venv's own interrogated pin) as a session step, and every
  stage key changed with it.
- One resolution note: the CLI's framing code asserts an integral sensor
  width, so rung 2 asks 960×540, not the nominal 854×480 (`venv2.py::
  RESOLUTION_DIMENSIONS` says why).

## Honest limits

- **The venv boundary has run live** (the rung above); the v1 and the
  in-process v2 halves have not — that is the point of their named
  missing pieces. The adapters' own halves (translations, argv,
  envelopes, refusals) are tested without a checkout; the engine halves
  are one configuration line away and refuse loudly until then
  (`EngineUnavailable` names the exact missing piece; never an import
  traceback).
- The venv runtime's renders are not promised byte-reproducible (Cycles'
  GPU accumulation, ±1 LSB — the experiment §5.4); its **stages** are
  byte-stable by construction. Its generator resolution is the box's
  configuration table, recorded in every provenance row — a name without
  a resolution is refused, never guessed.
- `ImportedProcfuncRuntime`'s five operations raise `NotImplementedError`
  after the import check: tracing through the imported engine lands with
  the v2 gate (week-1 item 2, `~/lm-wt/v2-thor`), whose four questions
  decide whether the runtime is the recipe substrate or an analysis tool
  (E, "The first experiment that would confirm it").
- The v1 reexecution is an honest full re-evaluation — E's table: v1's
  only cheaper mechanism is `resample_scene` (material re-noise in
  place), which is not a general diff mechanism. The per-entry stage
  keys are what make full re-evaluation affordable.
