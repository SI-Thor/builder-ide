#!/usr/bin/env python3
"""Drive topview-3d-cli over three scenes built from our own prop prompts.

What this measures (BRIEF item 1): the check-then-render vocabulary of
topview-3d-builder end to end on the Thor (aarch64), with every step's wall
time and output recorded, on scenes derived from the prompts our props use
(`core/cadbakeoff/fixtures/props/*.prompt.txt`, encoded in
`prop_scenes.json`).

How to run, from the ingame-phase2 worktree root (needs the tool set up by
`third_party/topview-setup2.sh`, about 6 min and one Chromium download):

    .venv/bin/python docs/lab/ingame-phase2-scripts/run_topview_scenes.py

Outputs land in `docs/lab/ingame-phase2-scripts/results/topview-scenes/`
(step timings and the CLI's JSON answers) while the projects themselves —
and their renders — stay under `third_party/topview-scenes/`, because the
built-in characters/poses are CC BY 4.0 and are never copied into the repo.
This script renders primitives only: no CC-BY asset is used at all.

Time: about 3-5 min for the three scenes at load ~11 (Chromium is started
once per browser-using command).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
REPO = SCRIPTS.parents[2]
CLI = REPO / "third_party" / "topview-3d-builder" / "agent" / ".venv" / "bin" / "topview-3d-cli"
PROJECTS = REPO / "third_party" / "topview-scenes"
OUT = SCRIPTS / "results" / "topview-scenes"
SPECS = SCRIPTS / "prop_scenes.json"

NODE_BIN = Path.home() / ".nvm" / "versions" / "node" / "v24.22.2" / "bin"


def env() -> dict[str, str]:
    e = dict(os.environ)
    e["PATH"] = f"{NODE_BIN}:{e.get('PATH', '')}"
    return e


def run_cli(args: list[str], step: str, rows: list[dict], scene: str) -> dict:
    """One CLI call, timed, its JSON answer kept and summarised."""
    t0 = time.perf_counter()
    proc = subprocess.run([str(CLI), *args], capture_output=True, text=True, env=env())
    dt = time.perf_counter() - t0
    out = (proc.stdout or "") + (proc.stderr or "")
    try:
        parsed = json.loads(out)
    except json.JSONDecodeError:
        parsed = {"raw": out[-2000:]}
    rows.append({"scene": scene, "step": step, "argv": args[1:], "seconds": round(dt, 3),
                 "exit": proc.returncode, "output": parsed})
    print(f"  [{scene}] {step}: {dt:.2f}s exit={proc.returncode}", flush=True)
    return parsed


def find_rows(obj, key: str) -> list[dict]:
    """Find the first list of dicts under `key`, wherever it sits."""
    if isinstance(obj, dict):
        v = obj.get(key)
        if isinstance(v, list) and v and isinstance(v[0], dict):
            return v
        for value in obj.values():
            found = find_rows(value, key)
            if found:
                return found
    elif isinstance(obj, list):
        for value in obj:
            found = find_rows(value, key)
            if found:
                return found
    return []


def summary(scene: str, answers: dict[str, dict]) -> dict:
    """The numbers the report quotes, pulled out of the step answers."""
    node_answer = answers.get("inspect nodes", {})
    nodes = find_rows(node_answer, "nodes")
    pairs = find_rows(node_answer, "pairs")
    views = answers.get("inspect views", {})
    ev = answers.get("evaluate", {})
    s: dict = {"scene": scene}
    s["groundTolerance"] = node_answer.get("groundTolerance")
    s["nodes_inspected"] = [n.get("id") or n.get("nodeId") for n in nodes]
    s["grounding"] = {(n.get("id") or n.get("nodeId")): (n.get("grounding") or {}).get("status") for n in nodes}
    s["ground_bottom_offset"] = {(n.get("id") or n.get("nodeId")): (n.get("grounding") or {}).get("bottomOffset") for n in nodes}
    s["pairs_intersecting"] = [
        "-".join(p.get("nodeIds", ["?", "?"])) for p in pairs if p.get("boundsIntersect")
    ]
    s["evaluate"] = {k: ev.get(k) for k in ("ok", "persisted", "evaluation", "geometry", "frames") if k in ev}
    s["checksComplete"] = views.get("checksComplete")
    s["checksBlockedBy"] = views.get("checksBlockedBy")
    s["views"] = views.get("views")
    s["visualStatus"] = views.get("visualStatus")
    show = answers.get("renders show", {})
    s["contact_sheet"] = {k: show.get(k) for k in ("path", "sizeBytes", "sha256", "runId") if k in show}
    render = answers.get("render", {})
    s["render"] = {k: render.get(k) for k in ("ok", "runId", "frames", "warnings", "contactSheet") if k in render}
    return s


def build_scene(spec: dict, name: str, rows: list[dict]) -> dict:
    """project init -> one atomic node batch -> validate -> evaluate -> inspect."""
    pdir = PROJECTS / name
    answers: dict[str, dict] = {}
    answers["project init"] = run_cli(["project", "init", str(pdir), "--force"], "project init", rows, name)

    changes = []
    for node in spec["nodes"]:
        change = {
            "action": "add_primitive",
            "nodeId": node["id"],
            "name": node["id"],
            "primitive": {"kind": node["kind"], "parameters": node["parameters"]},
            "position": node["position"],
        }
        if "rotation" in node:
            change["rotation"] = node["rotation"]
        changes.append(change)
    # `project init` already creates the default camera `cam-main`; the batch only
    # re-aims it (the tool refuses to create a second camera with the same id, and
    # refuses a view change that also carries position/rotation/distance/subject).
    cam = spec["camera"]
    changes.append({
        "action": "update",
        "nodeId": cam["id"],
        "name": f"{name}-cam",
        "fov": cam.get("fov", 50),
        "view": cam["view"],
    })
    # The batch goes in through stdin.
    t0 = time.perf_counter()
    proc = subprocess.run([str(CLI), "node", "batch", str(pdir), "-"], input=json.dumps({"changes": changes}),
                          capture_output=True, text=True, env=env())
    dt = time.perf_counter() - t0
    try:
        answers["node batch"] = json.loads((proc.stdout or "") + (proc.stderr or ""))
    except json.JSONDecodeError:
        answers["node batch"] = {"raw": ((proc.stdout or "") + (proc.stderr or ""))[-2000:]}
    rows.append({"scene": name, "step": "node batch", "argv": ["node", "batch", str(pdir), "-"],
                 "seconds": round(dt, 3), "exit": proc.returncode,
                 "output": answers["node batch"]})
    print(f"  [{name}] node batch: {dt:.2f}s exit={proc.returncode}", flush=True)

    ids = [n["id"] for n in spec["nodes"]] + [cam["id"]]
    answers["document validate"] = run_cli(["document", "validate", str(pdir)], "document validate", rows, name)
    answers["document get"] = run_cli(["document", "get", str(pdir), "--summary"], "document get --summary", rows, name)
    answers["evaluate"] = run_cli(["evaluate", str(pdir)], "evaluate", rows, name)
    answers["inspect nodes"] = run_cli(["inspect", "nodes", str(pdir), *ids], "inspect nodes", rows, name)
    answers["inspect views"] = run_cli(["inspect", "views", str(pdir), "--camera", cam["id"], "--frames", "0,24"],
                                       "inspect views", rows, name)
    payload = pdir / "render-payload.json"
    payload.write_text(json.dumps({"frames": [0, 24], "width": 960, "height": 540}))
    answers["render"] = run_cli(["render", str(pdir), str(payload)], "render", rows, name)
    answers["renders show"] = run_cli(["renders", "show", str(pdir)], "renders show", rows, name)
    return answers


def main() -> int:
    if not CLI.is_file():
        sys.exit(f"missing CLI at {CLI}; run third_party/topview-setup2.sh first")
    OUT.mkdir(parents=True, exist_ok=True)
    PROJECTS.mkdir(parents=True, exist_ok=True)
    specs = json.loads(SPECS.read_text())["scenes"]

    rows: list[dict] = []
    summaries = []
    for name, spec in specs.items():
        print(f"== scene {name} (from {spec['prompt']})", flush=True)
        answers = build_scene(spec, name, rows)
        summaries.append(summary(name, answers))

    (OUT / "steps.json").write_text(json.dumps(rows, indent=2))
    (OUT / "summary.json").write_text(json.dumps(summaries, indent=2))
    print(json.dumps(summaries, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())