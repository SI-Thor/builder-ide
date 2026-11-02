"""Run one prompt end to end: generate -> Blender -> critic -> outbox ->
viewer hot-load -> playtest -> gate. The gate passes -> the room's record is
committed; it fails -> the findings go back to the generator as repairs,
for at most MAX_RETRIES more attempts.

Every stage runs under a thor-admit lease (tier ``study``: this lane is
measurement) with an honest peak, and writes a ledger row with its wall time
and the box's state. The viewer is a plain Node server (no lease: it is a
static file server, tens of MB) that the runner starts if it is not up.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

from common import (
    ARTIFACTS,
    FRAME_P95_MAX_MS,
    LANE,
    MAX_RETRIES,
    OUTBOX,
    REPO,
    RESULTS,
    VIEWER_PORT,
    box_state,
    ensure_dirs,
    event,
    run_leased,
    viewer_alive,
)

VENV_PY = LANE / ".venv/bin/python"
BLENDER = "/usr/bin/blender"
NODE = Path.home() / ".nvm/versions/node/v24.22.2/bin/node"
NODE_ENV_PATH = str(Path.home() / ".nvm/versions/node/v24.22.2/bin")


def _stage_ms(t0: float) -> float:
    return round((time.perf_counter() - t0) * 1000.0)


def start_viewer() -> None:
    if viewer_alive():
        return
    log = ARTIFACTS / "viewer.log"
    env = dict(os.environ, PATH=NODE_ENV_PATH + ":" + os.environ["PATH"])
    proc = subprocess.Popen(
        [str(NODE), str(LANE / "viewer/server.js")],
        stdout=open(log, "ab"),
        stderr=subprocess.STDOUT,
        start_new_session=True,
        env=env,
    )
    for _ in range(50):  # wait for the listener
        if viewer_alive():
            break
        time.sleep(0.1)
    event("-", 0, "viewer", "started", detail={"pid": proc.pid})


def attempt(spec_path: Path, room: str, n: int, prev: dict | None) -> dict:
    """One attempt; returns the per-stage timings and the merged gate verdict."""
    d = ARTIFACTS / room / f"a{n}"
    d.mkdir(parents=True, exist_ok=True)
    times: dict[str, float] = {}

    cmd = [str(VENV_PY), str(LANE / "generate.py"), "--spec", str(spec_path), "--out", str(d)]
    if prev:
        cmd += ["--qa", str(prev["qa"]), "--critic", str(prev["critic"])]
    t0 = time.perf_counter()
    r = run_leased("study", "4G", f"vibe-sandbox.generate.{room}", cmd)
    times["generate_ms"] = _stage_ms(t0)
    if r.returncode != 0:
        event(room, n, "generate", "error", times["generate_ms"], {"tail": r.stderr[-400:]})
        raise RuntimeError(f"generate failed: {r.stderr[-400:]}")
    event(room, n, "generate", "ok", times["generate_ms"], box_state())

    t0 = time.perf_counter()
    r = run_leased(
        "study",
        "6G",
        f"vibe-sandbox.blender.{room}",
        [
            BLENDER,
            "--background",
            "--python",
            str(LANE / "blender_stage.py"),
            "--",
            "--spec",
            str(d / "scene.json"),
            "--parts",
            str(d / "parts"),
            "--out",
            str(d / "room.glb"),
            "--blend",
            str(d / "room.blend"),
            "--report",
            str(d / "blender_report.json"),
        ],
    )
    times["blender_ms"] = _stage_ms(t0)
    if r.returncode != 0 or not (d / "room.glb").exists():
        event(room, n, "blender", "error", times["blender_ms"], {"tail": r.stderr[-400:]})
        raise RuntimeError(f"blender failed: {r.stderr[-400:]}")
    event(room, n, "blender", "ok", times["blender_ms"], box_state())

    t0 = time.perf_counter()
    r = run_leased(
        "study",
        "6G",
        f"vibe-sandbox.critic.{room}",
        [
            str(VENV_PY),
            str(LANE / "critic_stage.py"),
            "--blend",
            str(d / "room.blend"),
            "--glb",
            str(d / "room.glb"),
            "--out",
            str(d / "critic_report.json"),
        ],
    )
    times["critic_ms"] = _stage_ms(t0)
    if r.returncode != 0:
        event(room, n, "critic", "error", times["critic_ms"], {"tail": r.stderr[-400:]})
        raise RuntimeError(f"critic failed: {r.stderr[-400:]}")
    critic = json.loads((d / "critic_report.json").read_text())
    event(
        room,
        n,
        "critic",
        critic["verdict"],
        times["critic_ms"],
        {"findings": critic["findings"], **box_state()},
    )

    # publish to the outbox, atomically: stage under a temp name, then swap
    glb_out = OUTBOX / f"{room}.glb"
    shutil.copyfile(d / "room.glb", glb_out)
    scene = json.loads((d / "scene.json").read_text())
    manifest = {
        "room_id": room,
        "attempt": n,
        "glb": f"/outbox/{room}.glb",
        "scene": scene,
        "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    tmp = OUTBOX / "manifest.json.tmp"
    tmp.write_text(json.dumps(manifest, sort_keys=True))
    os.replace(tmp, OUTBOX / "manifest.json")
    times["export_ms"] = 0.0
    event(room, n, "export", "ok", 0.0, {"glb_bytes": (d / "room.glb").stat().st_size})

    start_viewer()
    t0 = time.perf_counter()
    r = run_leased(
        "study",
        "4G",
        f"vibe-sandbox.playtest.{room}",
        [
            str(NODE),
            str(LANE / "playtest.mjs"),
            f"http://127.0.0.1:{VIEWER_PORT}/",
            str(d / "qa_report.json"),
            room,
        ],
    )
    times["playtest_ms"] = _stage_ms(t0)
    if r.returncode != 0 or not (d / "qa_report.json").exists():
        event(room, n, "playtest", "error", times["playtest_ms"], {"tail": (r.stderr or "?")[-400:]})
        raise RuntimeError(f"playtest failed: {(r.stderr or '?')[-400:]}")
    qa = json.loads((d / "qa_report.json").read_text())
    frame_ok = qa.get("metrics", {}).get("frame_ms_p95", 0) <= FRAME_P95_MAX_MS
    event(
        room,
        n,
        "playtest",
        "ok" if (qa["ok"] and frame_ok) else "fail",
        times["playtest_ms"],
        {"findings": qa["findings"], "frame_p95": qa.get("metrics", {}).get("frame_ms_p95"), **box_state()},
    )

    # the gate: the critic's findings and the QA's findings, merged
    findings = critic["findings"] + qa["findings"]
    if not frame_ok:
        findings = findings + [
            {"kind": "frame_budget", "source": "gate", "detail": f"p95 frame > {FRAME_P95_MAX_MS}ms"}
        ]
    return {
        "attempt": n,
        "dir": str(d),
        "times": times,
        "critic": str(d / "critic_report.json"),
        "qa": str(d / "qa_report.json"),
        "verdict": "pass" if not findings else "fail",
        "findings": findings,
        "repairable": any(f.get("kind") in {"floating_object", "blocked_door", "prop_unreachable", "scale_bounds"} for f in findings),
    }


def commit_pass(spec_path: Path, room: str, res: dict) -> None:
    """The spec's phase-4/5 gate action: a passing room's record is committed
    (the recipe and the reports; the GLB is a cache and stays untracked)."""
    dest = RESULTS / room
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(spec_path, dest / "spec.json")
    shutil.copyfile(res["qa"], dest / "qa_report.json")
    shutil.copyfile(res["critic"], dest / "critic_report.json")
    glb = Path(res["dir"]) / "room.glb"
    (dest / "room.glb").write_bytes(glb.read_bytes())  # few-KB build123d rooms
    subprocess.run(
        ["git", "add", str(dest.relative_to(REPO))],
        cwd=REPO,
        check=True,
    )
    stages = res["times"]
    msg = (
        f"vibe-sandbox room {room}: passed the gate on attempt {res['attempt']}\n\n"
        f"generate {stages['generate_ms']:.0f} ms, blender {stages['blender_ms']:.0f} ms, "
        f"critic {stages['critic_ms']:.0f} ms, playtest {stages['playtest_ms']:.0f} ms. "
        "Spec, QA report and critic report under docs/lab/vibe-sandbox-scripts/results/."
    )
    subprocess.run(["git", "commit", "-q", "-m", msg], cwd=REPO, check=True)
    event(room, res["attempt"], "gate", "committed", detail={"dir": str(dest)})


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--spec", required=True)
    ap.add_argument("--commit-on-pass", action="store_true")
    args = ap.parse_args()
    ensure_dirs()

    spec_path = Path(args.spec).resolve()
    room = json.loads(spec_path.read_text())["room_id"]
    t_start = time.perf_counter()
    prev = None
    history = []
    for n in range(1, MAX_RETRIES + 2):
        res = attempt(spec_path, room, n, prev)
        history.append(res)
        if res["verdict"] == "pass":
            break
        if not res["repairable"] or n == MAX_RETRIES + 1:
            break
        prev = res

    final = history[-1]
    summary = {
        "room_id": room,
        "attempts": len(history),
        "verdict": final["verdict"],
        "wall_ms": round((time.perf_counter() - t_start) * 1000),
        "box": box_state(),
        "attempt_times": [h["times"] for h in history],
        "findings_by_attempt": [h["findings"] for h in history],
        "repairable": final["repairable"],
    }
    out = ARTIFACTS / room
    (out / "summary.json").write_text(json.dumps(summary, indent=1, sort_keys=True))
    event(room, len(history), "gate", final["verdict"], summary["wall_ms"], box_state())
    if final["verdict"] == "pass" and args.commit_on_pass:
        commit_pass(spec_path, room, final)
    print(json.dumps(summary))
    return 0 if final["verdict"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
