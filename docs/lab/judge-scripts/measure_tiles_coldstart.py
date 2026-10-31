#!/usr/bin/env python3
"""The tiles cold-start measurement: judge-first versus bandit-from-zero.

Liquid-study Part 3, item 1's smallest experiment, on the tiles
acceptance rig's own shapes (tests/tiles/test_acceptance_learning.py):
six tiles in the M1 slice's crates word, 600 plays over the same seeded
context sequence, the same simulated game (a play wins with p=0.85 when
the tile's style is the one the context asked for and 0.15 otherwise —
the draws are sha256-seeded by (tile, bucket, play index), so **every
arm plays the identical game**).

Three arms:

* **bandit** — the contextual bandit from zero (the acceptance rig's
  chooser; the floor to beat);
* **judge-prior** — JudgePriorChooser: the judge seeds the prior of a
  cold context bucket (one judgment per bucket), the bandit learns from
  every play. The brief's wiring.
* **judge-only** — every play through the judge, acting on its argmax
  only at or above τ; below τ it is *surfaced, not acted on*, and the
  play falls back to a seeded uniform pick. This is the pure cold-start
  prior, the arm E1's T3 caution (one-shot d1-2B 0.450 on the tiles
  toy, majority 0.250) speaks to.

What is reported, with the box state beside every number:

* the **cold-start curve**: win rate by play-index bucket (12 × 50) per
  arm — the primary reading;
* **agreement**: the share of play indices where the judge-prior arm's
  pick equals the bandit arm's pick, and where judge-only's does;
* **latency**: per judge call, p50/p90 (§4.3 measured 32.2 ms p50 for
  d1-2B on short states — the number to compare against);
* the **surfaced rate**: the share of judge calls (and, for judge-only,
  plays) that fell below τ with nowhere to escalate;
* a **τ sweep computed offline** from the recorded distributions — the
  trace is saved, so the gate's policy can be re-read without touching
  the GPU again (the §4.3 pattern);
* peak memory: the server's VmHWM, and the minimum MemAvailable sampled
  while the run was in flight.

The server is NOT started here: `run_coldstart.sh` takes the heavy
lock, serves d1-2B Q8, checks `free -g` ≥ 25 after the load, runs this
script, and stops the server.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from core.judge.backends import D1Backend  # noqa: E402
from core.judge.gate import DEFAULT_TAU  # noqa: E402
from core.judge.judge import Judge  # noqa: E402
from core.judge.models import Question  # noqa: E402
from core.judge.shortlist import JudgePriorChooser  # noqa: E402
from core.night.ledger import InMemoryLedger  # noqa: E402
from core.tiles.chooser import ContextualBandit  # noqa: E402
from core.tiles.library import TileLibrary  # noqa: E402
from core.tiles.models import Outcome, TileStep, build_tile  # noqa: E402
from core.tiles.models import TileAuthor  # noqa: E402
from core.tiles.plays import record_play  # noqa: E402
from core.vocab.registry import VocabularyRegistry  # noqa: E402
from core.vocab.words import default_entries  # noqa: E402

# ---------------------------------------------------------------- the rig ----

#: The acceptance rig's constants, kept identical so the numbers sit
#: beside its published ones.
STYLES = ("plain", "weathered", "stained")
P_MATCH, P_MISS = 0.85, 0.15

FAKE_AUTHOR = TileAuthor(
    model="fake/scripted-v1", provider="fake",
    prompt_hash="sha256:" + "0" * 64, cost_cents=0,
)


def author_tiles(library: TileLibrary):
    """The scripted cloud author's six tiles: two per style, as the rig has."""
    tiles = []
    for style in STYLES:
        for take in (1, 2):
            tiles.append(
                build_tile(
                    family="harbor.crates.style",
                    kind="recipe_edit",
                    title=f"{style} crates, take {take}",
                    steps=(
                        TileStep(
                            word="props.harbor.crates",
                            path="harbor.crates",
                            params={"count": 12, "style": style, "from_library": 0},
                        ),
                    ),
                    author=FAKE_AUTHOR,
                )
            )
    for tile in tiles:
        library.add(tile)
    return tiles


def contexts(n: int, seed: int = 17) -> list[dict]:
    """The night's contexts — the acceptance rig's own generator."""
    rng = random.Random(seed)
    styles = [STYLES[index % len(STYLES)] for index in range(n)]
    rng.shuffle(styles)
    return [{"phase": "dusk", "wanted_style": style} for style in styles]


def game_draw(tile_id: str, bucket: str, play_index: int) -> float:
    """A seeded draw in [0, 1) — reproducible, identical across arms."""
    digest = hashlib.sha256(f"{tile_id}|{bucket}|{play_index}".encode()).hexdigest()
    return int(digest[:8], 16) / 0xFFFFFFFF


def play_outcome(tile, context: dict, bucket: str, play_index: int) -> Outcome:
    """The simulated game's verdict — the acceptance rig's, verbatim in shape."""
    style = tile.steps[0].params["style"]
    chance = P_MATCH if style == context["wanted_style"] else P_MISS
    won = game_draw(tile.id, bucket, play_index) < chance
    return Outcome(
        result="win" if won else "lose",
        measure="critic",
        detail="the crates read the way the context asked for"
        if won
        else "the crates read wrong",
    )


# ------------------------------------------------------- the judge's view ----

def render_state(context: dict) -> str:
    """What the judge sees of the scene: the context, in plain words."""
    return (
        f"A harbour scene at {context['phase']}. The builder asked for the "
        f"crates to read {context['wanted_style']}: the wood should carry "
        f"the {context['wanted_style']} look before anything else is judged."
    )


def candidate_text(tile) -> str:
    """One candidate, as the judge sees it: what the tile does, in its body."""
    params = tile.steps[0].params
    return (
        f"{tile.title} ({tile.family}): sets harbor.crates with "
        f"count={params.get('count')}, style={params.get('style')}"
    )


# ------------------------------------------------------------ the box state --

_TG_RE = {
    "ram_used_mb": re.compile(r"RAM (\d+)/(\d+)MB"),
    "gpu_temp_c": re.compile(r"gpu@([\d.]+)C"),
    "vdd_gpu_w": re.compile(r"VDD_GPU (\d+)mW"),
}


def box_state() -> dict:
    state: dict = {"ts": time.time()}
    try:
        state["load1"] = round(os.getloadavg()[0], 2)
    except OSError:
        pass
    try:
        with open("/proc/meminfo") as handle:
            for line in handle:
                if line.startswith("MemAvailable:"):
                    state["mem_available_gb"] = round(int(line.split()[1]) / 1048576, 1)
                    break
    except OSError:
        pass
    try:
        out = subprocess.run(
            ["timeout", "1", "tegrastats", "--interval", "250"],
            capture_output=True, text=True, timeout=8,
        ).stdout.strip().splitlines()
        line = out[-1] if out else ""
        for key, pattern in _TG_RE.items():
            match = pattern.search(line)
            if key == "ram_used_mb":
                state["ram_used_mb"] = int(match.group(1))
            elif key == "gpu_temp_c":
                state["gpu_temp_c"] = float(match.group(1))
            elif key == "vdd_gpu_w":
                state["vdd_gpu_w"] = int(match.group(1)) / 1000.0
    except Exception:
        pass
    return state


def vm_hwm_mb(pid: int) -> float | None:
    """The server's peak resident set, from /proc — the load's own cost."""
    try:
        with open(f"/proc/{pid}/status") as handle:
            for line in handle:
                if line.startswith("VmHWM:"):
                    return round(int(line.split()[1]) / 1024.0, 1)
    except OSError:
        return None
    return None


def percentile(values: list[float], p: float) -> float:
    if not values:
        return float("nan")
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round((len(ordered) - 1) * p / 100.0)))
    return ordered[index]


# --------------------------------------------------------------- the arms ----

def run_arm_bandit(tiles, contexts_list, n_plays, library, seed=7):
    """Arm A: the acceptance rig's bandit, from zero."""
    ledger = InMemoryLedger()
    chooser = ContextualBandit(
        feature_keys=("wanted_style",),
        epsilon=0.25, epsilon_decay=0.995, min_epsilon=0.02, seed=seed,
    )
    picks, wins = [], []
    for index, context in enumerate(contexts_list[:n_plays]):
        bucket = chooser.bucket(context)
        choice = chooser.choose(context, tiles)
        tile = next(t for t in tiles if t.id == choice.tile_id)
        outcome = play_outcome(tile, context, bucket, index)
        record = record_play(
            ledger=ledger, library=library, tile=tile, context=context,
            outcome=outcome, chooser=chooser.name, chooser_version=chooser.version,
            propensity=choice.propensity,
        )
        chooser.update(record)
        picks.append(choice.tile_id)
        wins.append(outcome.result == "win")
    return {"picks": picks, "wins": wins, "chooser": chooser.name}


def run_arm_judge_prior(tiles, contexts_list, n_plays, judge, library, seed=7):
    """Arm B: JudgePriorChooser — the judge seeds each cold bucket's prior."""
    ledger = InMemoryLedger()
    chooser = JudgePriorChooser(
        judge, task="tiles.shortlist",
        feature_keys=("wanted_style",),
        epsilon=0.25, epsilon_decay=0.995, min_epsilon=0.02, seed=seed,
    )
    picks, wins, judged = [], [], []
    for index, context in enumerate(contexts_list[:n_plays]):
        bucket = chooser.bucket(context)
        choice = chooser.choose(context, tiles)
        tile = next(t for t in tiles if t.id == choice.tile_id)
        outcome = play_outcome(tile, context, bucket, index)
        record = record_play(
            ledger=ledger, library=library, tile=tile, context=context,
            outcome=outcome, chooser=chooser.name, chooser_version=chooser.version,
            propensity=choice.propensity,
        )
        chooser.update(record)
        picks.append(choice.tile_id)
        wins.append(outcome.result == "win")
        judged.append(chooser.priors.get(bucket) is not None)
    return {"picks": picks, "wins": wins, "chooser": chooser.name,
            "judged_buckets": judged,
            "judge_calls": chooser.judge_calls, "judge_surfaced": chooser.judge_surfaced}


def run_arm_judge_only(tiles, contexts_list, n_plays, judge, library, tau, seed=99):
    """Arm C: every play through the judge; below τ is surfaced, not acted on.

    The policy made concrete: act on the argmax at or above τ; below τ
    the answer is surfaced (recorded, flagged) and the play falls back
    to a seeded uniform pick among the eligible tiles.
    """
    rng = random.Random(seed)
    question = Question(
        qid="tile",
        kind="choice",
        instructions="Which tile should be played next?",
        criteria={tile.id: candidate_text(tile) for tile in tiles},
    )
    picks, wins, gates, traces = [], [], [], []
    for index, context in enumerate(contexts_list[:n_plays]):
        bucket = f"wanted_style={context['wanted_style']}"
        answer = judge.judge("tiles.shortlist", render_state(context), (question,))
        judgment = answer.judgment("tile")
        traces.append({
            "play_index": index,
            "bucket": bucket,
            "distribution": judgment.distribution,
            "confidence": judgment.confidence,
            "tau": judgment.tau,
            "gate": judgment.gate,
            "latency_seconds": answer.latency_seconds,
            "cost": answer.cost.model_dump(),
            "author": judgment.author,
        })
        if judgment.gate == "act":
            tile_id = judgment.answer  # the argmax, ties broken by sorted key
            gates.append("act")
        else:
            tile_id = rng.choice([tile.id for tile in tiles])  # surfaced: uniform
            gates.append("surfaced")
        picks.append(tile_id)
        tile = next(t for t in tiles if t.id == tile_id)
        outcome = play_outcome(tile, context, bucket, index)
        wins.append(outcome.result == "win")
    return {"picks": picks, "wins": wins, "gates": gates, "traces": traces}


# ------------------------------------------------------------ the analysis ---

def curve(wins: list[bool], buckets: int = 12) -> list[dict]:
    size = max(1, len(wins) // buckets)
    out = []
    for start in range(0, len(wins), size):
        chunk = wins[start:start + size]
        out.append({
            "plays": f"{start + 1}-{start + len(chunk)}",
            "wins": sum(chunk),
            "n": len(chunk),
            "win_rate": round(sum(chunk) / len(chunk), 4) if chunk else None,
        })
    return out


def agreement(a: list[str], b: list[str]) -> float:
    if not a:
        return 0.0
    return round(sum(1 for x, y in zip(a, b) if x == y) / len(a), 4)


# ------------------------------------------------------------------- main ----

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8295)
    parser.add_argument("--plays", type=int, default=600)
    parser.add_argument("--model", default="d1-2B")
    parser.add_argument("--seed", type=int, default=20261031)
    parser.add_argument("--server-pid", type=int, default=0,
                        help="the llama-server pid, for the peak-RSS read")
    parser.add_argument("--out", default=str(Path(__file__).parent / "results" / "judge-tiles-coldstart.json"))
    args = parser.parse_args()

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    registry = VocabularyRegistry(default_entries())
    ledger = InMemoryLedger()
    library = TileLibrary(registry=registry, ledger=ledger)
    tiles = author_tiles(library)
    contexts_list = contexts(args.plays)

    backend = D1Backend(port=args.port, model=args.model)
    judge_ledger = InMemoryLedger()
    judge = Judge(backend=backend, ledger=judge_ledger)

    result = {
        "experiment": "judge tiles cold-start — judge-first vs bandit-from-zero",
        "brief": "liquid-study Part 3 item 1, smallest experiment",
        "rig": "tests/tiles/test_acceptance_learning.py's, verbatim in shape: 6 tiles, "
               "600 plays, p_match=0.85/p_miss=0.15, sha256-seeded draws",
        "model": args.model,
        "port": args.port,
        "tau_default": DEFAULT_TAU,
        "n_plays": args.plays,
        "seed": args.seed,
        "started": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ"),
        "box_at_start": box_state(),
    }

    # warm the GPU clocks before timing anything (IDEAS.md rule 3)
    warm_question = Question(
        qid="warm", kind="noul", instructions="The scene is a harbour at dusk."
    )
    warm = {"requests": 0}
    t0 = time.time()
    while time.time() - t0 < 3.0:
        judge.judge("warmup", "warmup state", (warm_question,))
        warm["requests"] += 1
    result["warmup"] = {**warm, "seconds": round(time.time() - t0, 2)}

    arm_bandit = run_arm_bandit(tiles, contexts_list, args.plays, library)
    arm_judge_prior = run_arm_judge_prior(tiles, contexts_list, args.plays, judge, library)
    arm_judge_only = run_arm_judge_only(tiles, contexts_list, args.plays, judge, library, DEFAULT_TAU)

    n = args.plays
    rates = {
        arm: round(sum(arm_["wins"]) / n, 4)
        for arm, arm_ in (("bandit", arm_bandit), ("judge_prior", arm_judge_prior),
                          ("judge_only", arm_judge_only))
    }
    result["win_rates"] = rates
    result["cold_start_curve"] = {
        arm: curve(arm_["wins"])
        for arm, arm_ in (("bandit", arm_bandit), ("judge_prior", arm_judge_prior),
                          ("judge_only", arm_judge_only))
    }
    result["first_second_half"] = {
        arm: [
            round(sum(arm_["wins"][: n // 2]) / (n // 2), 4),
            round(sum(arm_["wins"][n // 2 :]) / (n - n // 2), 4),
        ]
        for arm, arm_ in (("bandit", arm_bandit), ("judge_prior", arm_judge_prior),
                          ("judge_only", arm_judge_only))
    }
    result["agreement_with_bandit"] = {
        "judge_prior": agreement(arm_judge_prior["picks"], arm_bandit["picks"]),
        "judge_only": agreement(arm_judge_only["picks"], arm_bandit["picks"]),
        "judge_prior_vs_judge_only": agreement(
            arm_judge_prior["picks"], arm_judge_only["picks"]
        ),
    }
    result["judge_prior"] = {
        "judge_calls": arm_judge_prior["judge_calls"],
        "judge_surfaced": arm_judge_prior["judge_surfaced"],
        "judged_buckets_in_first_12_plays": arm_judge_prior["judged_buckets"][:12],
    }

    # the judge-only trace: latencies, gates, the offline τ sweep
    traces = arm_judge_only["traces"]
    latencies = [row["latency_seconds"] * 1000.0 for row in traces]
    result["judge_latency_ms"] = {
        "n": len(latencies),
        "p50": round(percentile(latencies, 50), 2),
        "p90": round(percentile(latencies, 90), 2),
        "mean": round(sum(latencies) / len(latencies), 2) if latencies else None,
    }
    result["judge_only_gates"] = {
        "act": sum(1 for g in arm_judge_only["gates"] if g == "act"),
        "surfaced": sum(1 for g in arm_judge_only["gates"] if g == "surfaced"),
    }
    input_tokens = [row["cost"]["input_tokens"] for row in traces]
    result["input_tokens_per_call"] = {
        "p50": percentile(input_tokens, 50),
        "min": min(input_tokens) if input_tokens else None,
        "max": max(input_tokens) if input_tokens else None,
    }
    gpu_minutes = sum(row["cost"]["gpu_minutes"] for row in traces)
    result["cost"] = {
        "hosted_cents": 0.0,
        "gpu_minutes_total": round(gpu_minutes, 4),
    }

    # the τ sweep needs, per (play, tau): whether the τ-argmax pick would win.
    # Recompute from the recorded distributions and the seeded game.
    sweep_rows = []
    for tau in (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9):
        rng = random.Random(99)
        acted = 0
        wins_if = 0
        for row in traces:
            confidence = row["confidence"] or 0.0
            bucket = row["bucket"]
            if confidence >= tau:
                acted += 1
                top = max(sorted(row["distribution"]), key=lambda k: row["distribution"][k])
                tile = next(t for t in tiles if t.id == top)
                index = row["play_index"]
                outcome = play_outcome(tile, {"wanted_style": bucket.split("=")[1]}, bucket, index)
                wins_if += outcome.result == "win"
            else:
                tile_id = rng.choice([t.id for t in tiles])
                tile = next(t for t in tiles if t.id == tile_id)
                index = row["play_index"]
                outcome = play_outcome(tile, {"wanted_style": bucket.split("=")[1]}, bucket, index)
                wins_if += outcome.result == "win"
        sweep_rows.append({
            "tau": tau,
            "act_rate": round(acted / len(traces), 4) if traces else None,
            "judge_only_win_rate": round(wins_if / len(traces), 4) if traces else None,
        })
    result["tau_sweep_offline"] = sweep_rows

    # the judge-prior arm's judgments, for the record — straight from its
    # judge.verdict rows
    prior_rows = []
    for event in judge_ledger.events():
        payload = event.payload
        if payload.get("task") != "tiles.shortlist" or payload.get("refused"):
            continue
        judgments = payload.get("judgments") or []
        if not judgments:
            continue
        distribution = judgments[0].get("distribution", {})
        confidence = judgments[0].get("confidence")
        prior_rows.append({
            "author": payload.get("author"),
            "n_questions": payload.get("n_questions"),
            "n_candidates": len(distribution),
            "confidence": confidence,
            "tau": payload.get("tau"),
            "gate": judgments[0].get("gate"),
            "latency_ms": round(payload.get("latency_seconds", 0.0) * 1000.0, 2),
            "input_tokens": payload.get("cost", {}).get("input_tokens"),
            "distribution_top": max(distribution, key=lambda k: distribution[k]) if distribution else None,
        })
    result["judge_prior_judgments"] = prior_rows

    result["box_at_end"] = box_state()
    if args.server_pid:
        result["server_peak_rss_mb"] = vm_hwm_mb(args.server_pid)
    result["finished"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")

    # the full judge-only trace: the analysis can be redone without the GPU
    result["judge_only_trace"] = traces
    out_path.write_text(json.dumps(result, indent=2, default=str))
    summary = {key: result[key] for key in (
        "win_rates", "agreement_with_bandit", "judge_latency_ms",
        "judge_only_gates", "box_at_start", "server_peak_rss_mb",
    ) if key in result}
    print(json.dumps(summary, indent=2))
    print(f"\nwrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
