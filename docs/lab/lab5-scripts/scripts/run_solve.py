# lab5 (round 5, IDEAS #4) — solve-only driver for the Infinigen Indoors
# constraint solver.
#
# Runs exactly the solve stages of infinigen_examples/generate_indoors.py's
# `compose_indoors` — solve_rooms + the large/medium/small object stages —
# with no terrain, cameras, renders or final asset population, so the
# annealing solver's wall time stands alone. `default_greedy_stages` and the
# stage sequence are copied verbatim from generate_indoors.py (thor-spike;
# identical in the v2 venv's checkout) — copied rather than imported so the
# heavy nature/camera imports stay out.
#
# Run inside the v2 venv (`~/lm-wt/v2-thor/.venv/bin/python`), which is used
# read-only. lab5's batched-proposal monkeypatch (solver_patch.py) is
# installed before solving when --arm batch.
#
# Output: one JSON per run (walls, per-stage results, per-candidate probes,
# the annealer's own per-step stats, optional impl profile).

from __future__ import annotations

import argparse
import json
import logging
import math
import sys
import time
from pathlib import Path

# logging before the heavy imports, mirroring generate_indoors.py
logging.basicConfig(
    format="[%(asctime)s.%(msecs)03d] [%(module)s] [%(levelname)s] | %(message)s",
    datefmt="%H:%M:%S",
    level=logging.WARNING,
)

import numpy as np  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))  # lab5/scripts
import solver_patch  # noqa: E402

import bpy  # noqa: E402  (starts the headless Blender session)
import gin  # noqa: E402

from infinigen.core import init  # noqa: E402
from infinigen.core import tags as t  # noqa: E402
from infinigen.core.constraints import checks  # noqa: E402
from infinigen.core.constraints import constraint_language as cl  # noqa: E402
from infinigen.core.constraints import reasoning as r  # noqa: E402
from infinigen.core.constraints.evaluator import evaluate  # noqa: E402
from infinigen.core.constraints.example_solver import (  # noqa: E402
    greedy,
    populate,
    state_def,
)
from infinigen.core.constraints.example_solver.solve import Solver  # noqa: E402
from infinigen_examples.constraints import home as home_constraints  # noqa: E402
from infinigen_examples.util.generate_indoors_util import restrict_solving  # noqa: E402

# The gin configs (configs_nature/base.gin included by base_indoors.gin) bind
# configurables that are only *registered* when their defining modules are
# imported — generate_indoors' import block (which pulls generate_nature,
# terrain, cameras, …) is what registers them. Import it in full; the cost is
# setup time, outside every timed stage.
import infinigen_examples.generate_indoors as generate_indoors  # noqa: E402,F401

default_greedy_stages = generate_indoors.default_greedy_stages
all_vars = generate_indoors.all_vars

logger = logging.getLogger("lab5.run_solve")

# ---- the driver -------------------------------------------------------------


def loadavg() -> str:
    try:
        return Path("/proc/loadavg").read_text().split()[0]
    except OSError:
        return "?"


def solve_stage_name(solver, consgraph, stages, limits, state, stage_name, group,
                     n_steps, desc_prefix="", **kwargs):
    """generate_indoors.solve_stage_name, with lab5's probes and timing."""
    assignments = greedy.iterate_assignments(stages[stage_name], state, all_vars, limits)
    rows = []
    for i, vars in enumerate(assignments):
        desc = f"{desc_prefix}{stage_name}_{i}"
        solver_patch.set_stage(desc)
        n0 = len(state.objs)
        t0 = time.perf_counter()
        solver.solve_objects(
            consgraph,
            stages[stage_name],
            vars,
            n_steps=n_steps,
            desc=desc,
            abort_unsatisfied=False,
            **kwargs,
        )
        wall = time.perf_counter() - t0
        res = solver.optim.curr_result
        rows.append(
            dict(
                stage=desc,
                n_steps=n_steps,
                wall=wall,
                final_loss=res.loss() if res is not None else None,
                final_viol=res.viol_count() if res is not None else None,
                n_objs_start=n0,
                n_objs_end=len(state.objs),
            )
        )
        logger.info(
            "stage %s: wall=%.1fs loss=%.4f viol=%s objs %d→%d",
            desc, wall, rows[-1]["final_loss"] or float("nan"),
            rows[-1]["final_viol"], n0, len(state.objs),
        )
    return rows


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--seed", type=int, required=True)
    p.add_argument("--arm", default="baseline", choices=["baseline", "batch"])
    p.add_argument("--N", type=int, default=1, help="candidates per step (batch arm)")
    p.add_argument("--mode", default="best", choices=["best", "sample", "uniform"])
    p.add_argument(
        "--budget",
        default="same-steps",
        choices=["equal", "same-steps"],
        help="same-steps: the upstream step count, N candidates scored per "
        "step (the natural upstream change; what a free scorer buys). "
        "equal: steps/N steps — same candidate *attempts*, but N-fold fewer "
        "annealing decisions (a compressed schedule, kept as a datapoint)",
    )
    p.add_argument(
        "--steps-override",
        default=None,
        help="comma ints 'large,medium,small' overriding the gin-configured "
        "solve_steps_* (the quarter schedule used for the N-sweep so the "
        "N=512 same-steps arm fits the day)",
    )
    p.add_argument("--stages", default="large,medium,small",
                   help="comma list from {large,medium,small}")
    p.add_argument("--profile", action="store_true", help="time every node impl")
    p.add_argument("--out", type=Path, required=True, help="result JSON path")
    p.add_argument("--scratch", type=Path, default=None, help="solver scratch dir")
    args = p.parse_args()

    logging.getLogger("infinigen").setLevel(logging.INFO)
    logging.getLogger("lab5").setLevel(logging.INFO)

    t_setup0 = time.perf_counter()
    # init.parse_seed reads the seed as a *hex string*; pass it through as one
    # (seeds are small ints, where decimal and hex agree)
    scene_seed = init.apply_scene_seed(str(args.seed))
    gin_overrides = []
    if args.steps_override:
        groups = ("large", "medium", "small")
        vals = [int(v) for v in args.steps_override.split(",")]
        gin_overrides += [f"compose_indoors.solve_steps_{g} = {v}"
                          for g, v in zip(groups, vals)]
    init.apply_gin_configs(
        configs=["base", "base_indoors", "fast_solve", "singleroom"],
        overrides=gin_overrides,
        config_folders=[
            "infinigen_examples/configs_indoor",
            "infinigen_examples/configs_nature",
        ],
    )
    t_setup = time.perf_counter() - t_setup0

    steps_cfg = {
        g: int(gin.query_parameter(f"compose_indoors.solve_steps_{g}"))
        for g in ("large", "medium", "small")
    }

    def arm_budget(group: str) -> tuple[int, int]:
        """(n_steps, candidates-per-step) for this arm and stage group.

        budget='equal' spends the *same total number of candidates* as the
        baseline's steps_cfg — the fair comparison at equal CPU cost, and the
        question the gate asks: does choosing best-of-N (vs sequential
        Metropolis) change where the annealer ends up, per unit budget?
        budget='same-steps' keeps the upstream schedule and multiplies the
        candidate count by N (what a free-GPU scorer would buy).
        """
        base = steps_cfg[group]
        if args.arm == "baseline" or args.budget == "same-steps":
            return base, (1 if args.arm == "baseline" else args.N)
        n_steps = max(1, math.ceil(base / args.N))
        n_per_step = min(args.N, math.ceil(base / n_steps))
        return n_steps, n_per_step

    out = dict(
        meta=dict(
            arm=args.arm, N=args.N, mode=args.mode, budget=args.budget,
            seed=args.seed, scene_seed=scene_seed,
            steps_cfg=steps_cfg, stages=args.stages,
            python=sys.version.split()[0],
            load_start=loadavg(), t_setup_s=t_setup,
        ),
        walls={}, stage_results=[], final={},
    )

    solver_patch.install(args.arm, N=args.N, mode=args.mode)
    if args.profile:
        solver_patch.enable_profile()

    consgraph = home_constraints.home_furniture_constraints()
    consgraph_rooms = home_constraints.home_room_constraints()
    stages = default_greedy_stages()
    checks.check_all(consgraph, stages, all_vars)
    stages, consgraph, limits = restrict_solving(stages, consgraph)  # gin: solve_max_rooms=1

    scratch = args.scratch or (args.out.parent / f"scratch_seed{args.seed}")
    scratch.mkdir(parents=True, exist_ok=True)

    solver = Solver(output_folder=scratch)
    state: state_def.State = None

    walls = out["walls"]

    # -- solve_rooms (the floor plan; identical code+seed in every arm)
    solver_patch.set_stage("solve_rooms")
    t0 = time.perf_counter()
    state = solver.solve_rooms(scene_seed, consgraph_rooms, stages["rooms"])
    walls["solve_rooms"] = time.perf_counter() - t0
    out["meta"]["n_rooms"] = sum(
        1 for o in state.objs.values() if t.Semantics.Room in o.tags
    )
    logger.info("solve_rooms: wall=%.1fs objs=%d", walls["solve_rooms"], len(state.objs))

    # -- solve_large
    if "large" in args.stages:
        n_steps, n_eff = arm_budget("large")
        out["meta"]["large_steps_n"] = [n_steps, n_eff]
        solver_patch.install(args.arm, N=n_eff, mode=args.mode)
        solver_patch.set_stage("solve_large")
        t0 = time.perf_counter()
        for name in ("on_floor_and_wall", "on_floor_freestanding"):
            out["stage_results"] += solve_stage_name(
                solver, consgraph, stages, limits, state, name, "large",
                n_steps=n_steps,
            )
        walls["solve_large"] = time.perf_counter() - t0

    # -- populate_intermediate_pholders (asset spawning, not solving; timed
    #    separately and excluded from the solve wall — its cost belongs to
    #    the asset factories, and it must run before the medium/small stages
    #    exactly as compose_indoors orders it)
    if "medium" in args.stages or "small" in args.stages:
        solver_patch.set_stage("populate_intermediate")
        t0 = time.perf_counter()
        populate.populate_state_placeholders(
            solver.state, filter=t.Semantics.AssetPlaceholderForChildren, final=False
        )
        walls["populate_intermediate"] = time.perf_counter() - t0

    # -- solve_medium
    if "medium" in args.stages:
        n_steps, n_eff = arm_budget("medium")
        out["meta"]["medium_steps_n"] = [n_steps, n_eff]
        solver_patch.install(args.arm, N=n_eff, mode=args.mode)
        solver_patch.set_stage("solve_medium")
        t0 = time.perf_counter()
        for name in ("on_wall", "on_ceiling", "side_obj"):
            out["stage_results"] += solve_stage_name(
                solver, consgraph, stages, limits, state, name, "medium",
                n_steps=n_steps,
            )
        walls["solve_medium"] = time.perf_counter() - t0

    # -- solve_small
    if "small" in args.stages:
        n_steps, n_eff = arm_budget("small")
        out["meta"]["small_steps_n"] = [n_steps, n_eff]
        solver_patch.install(args.arm, N=n_eff, mode=args.mode)
        solver_patch.set_stage("solve_small")
        t0 = time.perf_counter()
        out["stage_results"] += solve_stage_name(
            solver, consgraph, stages, limits, state, "obj_ontop_obj", "small",
            n_steps=n_steps, addition_weight_scalar=3,
        )
        out["stage_results"] += solve_stage_name(
            solver, consgraph, stages, limits, state, "obj_on_support", "small",
            n_steps=n_steps, restrict_moves=["addition"],
        )
        walls["solve_small"] = time.perf_counter() - t0

    walls["solve_total"] = sum(
        walls.get(k, 0.0)
        for k in ("solve_rooms", "solve_large", "solve_medium", "solve_small")
    )

    # -- final placement score over the whole (restricted) problem
    solver_patch.set_stage("final")
    final = evaluate.evaluate_problem(consgraph, state, None)
    out["final"] = dict(
        loss=final.loss(),
        viol=final.viol_count(),
        n_objs=len(state.objs),
        n_objs_placed=sum(1 for o in state.objs.values() if t.Semantics.Room not in o.tags),
    )

    # -- the annealer's own per-step stats + lab5 probes
    out["annealer_stats"] = [
        {k: (v if v is None or isinstance(v, (int, float, bool)) else str(v))
         for k, v in row.items()}
        for row in solver.optim.stats
    ]
    cands, steps, profile = solver_patch.drain()
    out["n_candidates"] = len(cands)
    ok = [c for c in cands if c["ok"]]
    out["candidate_summary"] = dict(
        n=len(cands), n_ok=len(ok),
        t_apply_s=sum(c["t_apply"] for c in cands),
        t_eval_s=sum(c["t_eval"] for c in cands),
        t_revert_s=sum(c["t_revert"] for c in cands),
        eval_cands_per_s=(len(ok) / sum(c["t_eval"] for c in cands))
        if ok and sum(c["t_eval"] for c in cands) > 0 else None,
    )
    # raw probes kept only for ok candidates, capped, to bound the JSON size
    out["candidates_sample"] = cands[:20000]
    out["steps"] = steps[:20000]
    if args.profile:
        out["profile"] = {
            k: dict(t=round(v["t"], 4), n=v["n"]) for k, v in profile.items()
        }

    out["meta"]["load_end"] = loadavg()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=1))
    logger.info(
        "DONE arm=%s N=%s mode=%s seed=%s solve_wall=%.1fs final loss=%.4f viol=%s",
        args.arm, args.N, args.mode, args.seed,
        walls["solve_total"], out["final"]["loss"], out["final"]["viol"],
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
