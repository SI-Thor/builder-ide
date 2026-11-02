#!/usr/bin/env python3
"""Run the Voyager port against a world and write the numbers down.

The brief's measurement: *"Measure on Minecraft for N hours of world:
unique items, tech-tree milestones (wood->stone->iron), skills admitted,
token cost per milestone (log every model call's tokens). Report
docs/lab/exp-voyager-port.md."*

This is the script that produces those numbers. It:

1. opens the world (Minecraft, Crafter, or a stub);
2. opens the **audit ledger** — a SQLite file in the world's own format
   (``core.night.ledger.SQLiteLedger``), so the drift detector can read
   the run afterwards;
3. builds the curriculum, the skill library and the three model roles;
4. runs the loop;
5. writes the results: ``run.json`` (the report), ``steps.jsonl`` (one
   line per turn), and the ledger.

Every model call's tokens are on the steps and in the report, and the
report carries the token cost **per milestone** — the number the brief
asks for.

Usage:

    # Minecraft, against the private sandbox
    ~/lm-wt/voyager-port/.venv/bin/python \\
        docs/lab/voyager-port-scripts/run_voyager.py \\
        --world minecraft --hours 2 --out docs/lab/voyager-port-scripts/results

    # Crafter, the fast lab
    ~/lm-wt/voyager-port/.venv/bin/python \\
        docs/lab/voyager-port-scripts/run_voyager.py \\
        --world crafter --hours 0.5 --out docs/lab/voyager-port-scripts/results

What it needs: the seat's venv, a DeepInfra key in
``~/.config/last-mile/secrets.env``, and (for Minecraft) the sandbox
running on 127.0.0.1:25600. How long it takes: ``--hours`` of world
time; the loop stops at the step or token limit too.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from core.night.ledger import SQLiteLedger  # noqa: E402
from core.tiles.models import Outcome  # noqa: E402

from core.voyager.budget import RunBudget  # noqa: E402
from core.voyager.curriculum import Curriculum  # noqa: E402
from core.voyager.llm import DEFAULT_MODELS, ModelRouter  # noqa: E402
from core.voyager.models import Milestone  # noqa: E402
from core.voyager.runner import LoopConfig, VoyagerLoop  # noqa: E402
from core.voyager.skills import SkillLibrary  # noqa: E402


def build_world(name: str, log):
    """The adapter for the world the run is in."""
    if name == "minecraft":
        from core.voyager.adapters.minecraft import MinecraftAdapter

        return MinecraftAdapter(log=log)
    if name == "crafter":
        from core.voyager.adapters.crafter import CrafterAdapter

        return CrafterAdapter(log=log)
    if name == "vibe-sandbox":
        from core.voyager.adapters.vibesandbox import VibeSandboxAdapter

        return VibeSandboxAdapter(log=log)
    if name == "bevy":
        from core.voyager.adapters.bevy import BevyAdapter

        return BevyAdapter(log=log)
    raise SystemExit(f"unknown world {name!r}")


def build_vocabulary(env):
    """The world's closed vocabulary of primitives."""
    from core.voyager.adapters.minecraft import mc_vocabulary
    from core.voyager.adapters.crafter import crafter_vocabulary
    from core.voyager.adapters.bevy import bevy_vocabulary
    from core.voyager.adapters.vibesandbox import vibe_vocabulary

    makers = {
        "minecraft": mc_vocabulary,
        "crafter": crafter_vocabulary,
        "vibe-sandbox": vibe_vocabulary,
        "bevy": bevy_vocabulary,
    }
    maker = makers.get(env.name)
    if maker is None:
        raise SystemExit(f"no vocabulary for the world {env.name!r}")
    return maker()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--world", default="minecraft",
                        choices=["minecraft", "crafter", "vibe-sandbox", "bevy"])
    parser.add_argument("--hours", type=float, default=2.0,
                        help="how much world time the run may take")
    parser.add_argument("--max-steps", type=int, default=120)
    parser.add_argument("--max-tokens", type=int, default=2_000_000)
    parser.add_argument("--out", default="docs/lab/voyager-port-scripts/results")
    parser.add_argument("--seed", type=int, default=7, help="the curriculum's seed")
    parser.add_argument("--planner-model", default=DEFAULT_MODELS["planner"])
    parser.add_argument("--coder-model", default=DEFAULT_MODELS["coder"])
    parser.add_argument("--verifier-model", default=DEFAULT_MODELS["verifier"])
    parser.add_argument("--agent", default="voyager")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    log_path = out / f"{args.world}-run.log"

    def log(message: str) -> None:
        line = f"[{time.strftime('%H:%M:%S')}] {message}"
        if not args.quiet:
            print(line, flush=True)
        with log_path.open("a") as handle:
            handle.write(line + "\n")

    started = time.time()
    log(f"the run starts: world={args.world} hours={args.hours} "
        f"max_steps={args.max_steps} max_tokens={args.max_tokens}")

    env = build_world(args.world, log)
    registry = build_vocabulary(env)
    ledger = SQLiteLedger(out / f"{args.world}-ledger.sqlite3")
    skills = SkillLibrary(
        registry=registry,
        ledger=ledger,
        bodies_dir=out / "bodies",
        adapter=args.world,
    )
    models = ModelRouter.from_models(
        {
            "planner": args.planner_model,
            "coder": args.coder_model,
            "verifier": args.verifier_model,
        }
    )
    log(f"the roles: planner={args.planner_model} coder={args.coder_model} "
        f"verifier={args.verifier_model}")

    milestones = getattr(env, "milestones", None)
    if milestones is None:
        milestones = ()
    curriculum = Curriculum(list(milestones), seed=args.seed)
    budget = RunBudget(
        max_steps=args.max_steps,
        max_wall_seconds=args.hours * 3600.0,
        max_tokens=args.max_tokens,
    )
    loop = VoyagerLoop(
        env=env,
        models=models,
        curriculum=curriculum,
        skills=skills,
        config=LoopConfig(),
        budget=budget,
        agent=args.agent,
        log=log,
    )

    report = None
    try:
        env.open()
        report = loop.run()
    except KeyboardInterrupt:
        log("the run was interrupted")
    finally:
        try:
            env.close()
        except Exception as exc:  # the world may already be gone
            log(f"the world did not close cleanly: {exc}")

    if report is None:
        log("no report: the run did not start")
        return 1

    payload = report.as_dict()
    payload["cost_book"] = models.cost.snapshot()
    payload["budget"] = budget.as_dict()
    payload["wall_seconds_measured"] = round(time.time() - started, 1)
    payload["models"] = {
        "planner": args.planner_model,
        "coder": args.coder_model,
        "verifier": args.verifier_model,
    }
    payload["seed"] = args.seed
    payload["box"] = {
        "free_mb": _free_mb(),
        "loadavg": os.getloadavg(),
    }
    (out / f"{args.world}-run.json").write_text(json.dumps(payload, indent=2, sort_keys=True))
    with (out / f"{args.world}-steps.jsonl").open("w") as handle:
        for step in report.steps:
            handle.write(json.dumps(step.as_dict(), sort_keys=True) + "\n")

    log(f"the run ends: steps={len(report.steps)} "
        f"unique_items={report.unique_items} "
        f"milestones={list(report.milestones_reached)} "
        f"admitted={report.skills_admitted} rejected={report.skills_rejected} "
        f"tokens={report.total_tokens}")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def _free_mb() -> int:
    """The box's free memory, for the record."""
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) // 1024
    except Exception:
        pass
    return -1


if __name__ == "__main__":
    raise SystemExit(main())
