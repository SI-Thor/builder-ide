#!/usr/bin/env python3
"""Exp C — a hysteresis gate and a precision-promotion gate on a real decision.

Two gates sit between a decision model and the world, and both are cheap to
add and easy to get wrong. This script measures them on a real d1 decision
(the tile-choice shape the tiles system uses), on the same recorded
probability vectors, so the gate policy is the only thing that varies.

The task. A quay-side scene is observed repeatedly. Four candidate tiles are
on the table and exactly one of them is right for the scene. The wording of
the observation varies from step to step (the same facts, phrased
differently) while the underlying truth holds; at one point in the episode
the scene changes materially and the truth flips. This is the shape of a
builder that keeps re-deciding the same thing all night: most of the churn
is noise, and a few flips are real.

Two gates.

* **Hysteresis.** Keep the committed tile until a challenger beats it by a
  margin delta. delta = 0 is the ungated baseline (switch whenever the
  model's preference flips). Large delta is too sticky.
* **Precision promotion.** When the model's top-two margin is below tau,
  ask a second, higher-precision copy of the same model and take its answer.

What we measure per setting: accuracy against the truth, how many times the
committed choice changed (churn), how many of those changes were spurious
(the truth had not flipped), and how long the gate took to notice a real
flip.

Everything is recorded once from the model and the gates are then simulated
offline, so every setting sees identical model outputs.

Run:
    python3 exp_c_gates.py --port 8291 --bf16-port 8293
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
from dataclasses import dataclass, field

import d1lab

# ---------------------------------------------------------------- the tiles

TILES = {
    "tarps": "Tarp the crates against the spray",
    "move": "Move the crates to the upper quay",
    "barricade": "Turn the barrows into a barricade at the quay edge",
    "lamp": "Put a lamp on each barrow and work after dark",
}
TILE_IDS = list(TILES)

# Four scene families, one per tile. Each has a cue that makes its tile right.
SCENES = {
    "tarps": {
        "cue": "salt spray is coming over the wall in gusts",
        "texts": [
            "At dusk on a small fishing quay, crates are stacked near the wall and {cue}. "
            "The harbourmaster says the crates should be covered before the wind turns.",
            "Crates sit stacked on the quay at dusk, and {cue}. The foreman asks that they be "
            "covered before the weather turns.",
            "The quay is stacked with crates after dark, and {cue}; the crew is told to protect "
            "the stack from the weather.",
            "Crates on a harbour quay at dusk, {cue}. The shift lead wants them covered against "
            "the coming weather.",
        ],
    },
    "move": {
        "cue": "the lower quay is already under water and the stack is standing in the tide",
        "texts": [
            "At dusk on a small fishing quay, crates are stacked low down and {cue}. "
            "The harbourmaster wants the stack lifted clear of the flood.",
            "Crates sit stacked on the lower quay at dusk, and {cue}. The foreman asks that they "
            "be carried to higher ground.",
            "The quay is stacked with crates after dark, and {cue}; the crew is told to lift the "
            "stack clear before it is reached.",
            "Crates on a harbour quay at dusk, {cue}. The shift lead wants the stack carried up "
            "out of the water.",
        ],
    },
    "barricade": {
        "cue": "the quay has to be closed to the public before the ferry lands",
        "texts": [
            "At dusk on a small fishing quay, crates are stacked in the walkway and {cue}. "
            "The harbourmaster wants the way blocked.",
            "Crates sit stacked across the quay at dusk, and {cue}. The foreman asks that the "
            "way be blocked off.",
            "The quay is stacked with crates after dark, and {cue}; the crew is told to block the "
            "way through.",
            "Crates on a harbour quay at dusk, {cue}. The shift lead wants the way closed off.",
        ],
    },
    "lamp": {
        "cue": "there is no light left on the quay and the last of the daylight is going",
        "texts": [
            "At dusk on a small fishing quay, crates are stacked in the dark and {cue}. "
            "The harbourmaster wants the crew able to keep working.",
            "Crates sit stacked on the quay after dark, and {cue}. The foreman asks that light be "
            "provided so the work can go on.",
            "The quay is stacked with crates at nightfall, and {cue}; the crew is told to be able "
            "to see and to keep working.",
            "Crates on a harbour quay in the dark, {cue}. The shift lead wants light on the quay "
            "so the work can continue.",
        ],
    },
}

# A weak cue for a tile that is NOT the right one, so the model sees evidence
# for two tiles and its confidence lands somewhere interesting.
DISTRACTOR = {
    "tarps": "There is some salt spray in the air.",
    "move": "The lower ground near the quay is wet.",
    "barricade": "People are walking along the quay.",
    "lamp": "It is getting dark over the harbour.",
}


@dataclass
class Step:
    t: int
    family: str
    variant: int
    truth: str
    probs: dict[str, float] = field(default_factory=dict)
    bf16_probs: dict[str, float] = field(default_factory=dict)
    input_tokens: int = 0
    wall_ms: float = 0.0


def make_episode(rng: random.Random, n_steps: int, flip_at: int) -> list[tuple[str, int]]:
    """A run of observations. The truth holds, then flips once."""
    first = rng.choice(TILE_IDS)
    second = rng.choice([t for t in TILE_IDS if t != first])
    plan = []
    for t in range(n_steps):
        family = first if t < flip_at else second
        variant = rng.randrange(len(SCENES[family]["texts"]))
        plan.append((family, variant))
    return plan


def state_text(family: str, variant: int, rng: random.Random) -> str:
    scene = SCENES[family]
    text = scene["texts"][variant].format(cue=scene["cue"])
    other = rng.choice([t for t in TILE_IDS if t != family])
    return f"{text} {DISTRACTOR[other]}"


def question() -> dict:
    return {
        "tile": {
            "type": "choice",
            "instructions": "Which tile should the builder play next?",
            "criteria": {k: v for k, v in TILES.items()},
        }
    }


# ---------------------------------------------------------------- recording


def record_episode(port: int, bf16_port: int, plan, rng: random.Random) -> list[Step]:
    q = question()
    steps: list[Step] = []
    for t, (family, variant) in enumerate(plan):
        text = state_text(family, variant, rng)
        resp, dt = d1lab.systemone(port, text, q)
        probs = resp["answers"]["tile"]["probabilities"]
        step = Step(
            t=t,
            family=family,
            variant=variant,
            truth=family,
            probs={k: float(v) for k, v in probs.items()},
            input_tokens=resp["usage"]["input_tokens"],
            wall_ms=dt * 1e3,
        )
        if bf16_port:
            bresp, _ = d1lab.systemone(bf16_port, text, q)
            step.bf16_probs = {
                k: float(v) for k, v in bresp["answers"]["tile"]["probabilities"].items()
            }
        steps.append(step)
    return steps


# ---------------------------------------------------------------- the gates


def hysteresis_gate(steps: list[Step], delta: float) -> dict:
    """Commit to a tile; switch only when a challenger beats the incumbent by
    more than delta."""
    committed: str | None = None
    correct = 0
    switches = 0
    spurious = 0
    truth_flips = 0
    latency_at_flip: list[int] = []
    pending_flip_step: int | None = None

    for step in steps:
        if step.t > 0 and steps[step.t - 1].truth != step.truth:
            truth_flips += 1
            pending_flip_step = step.t

        if committed is None:
            committed = max(step.probs, key=step.probs.get)
        else:
            challenger = max(
                (k for k in step.probs if k != committed),
                key=step.probs.get,
                default=None,
            )
            if challenger is not None:
                margin = step.probs[challenger] - step.probs[committed]
                if margin > delta:
                    committed = challenger
                    switches += 1
                    if pending_flip_step is None or step.truth == steps[pending_flip_step].truth:
                        spurious += 1
                    else:
                        latency_at_flip.append(step.t - pending_flip_step)
                        pending_flip_step = None

        if committed == step.truth:
            correct += 1
        elif pending_flip_step is not None:
            # still wrong after a flip; keep measuring the latency
            pass

    n = len(steps)
    return {
        "delta": delta,
        "accuracy": correct / n if n else 0.0,
        "switches": switches,
        "spurious_switches": spurious,
        "churn_per_step": switches / n if n else 0.0,
        "truth_flips": truth_flips,
        "switch_latency_after_flip": latency_at_flip,
        "mean_latency_after_flip": (
            statistics.mean(latency_at_flip) if latency_at_flip else None
        ),
    }


def promote_gate(steps: list[Step], tau: float) -> dict:
    """Take the small model's answer unless the top-two margin is below tau;
    then take the promoted (higher precision) model's answer."""
    correct = 0
    promoted = 0
    changed = 0
    correct_small = 0
    correct_big = 0
    for step in steps:
        if not step.bf16_probs:
            continue
        ordered = sorted(step.probs.items(), key=lambda kv: -kv[1])
        margin = ordered[0][1] - (ordered[1][1] if len(ordered) > 1 else 0.0)
        small = ordered[0][0]
        big = max(step.bf16_probs, key=step.bf16_probs.get)
        if margin < tau:
            promoted += 1
            if big != small:
                changed += 1
            choice = big
            if big == step.truth:
                correct_big += 1
        else:
            choice = small
        if small == step.truth:
            correct_small += 1
        if choice == step.truth:
            correct += 1
    n = len([s for s in steps if s.bf16_probs])
    return {
        "tau": tau,
        "accuracy_gated": correct / n if n else 0.0,
        "accuracy_small_only": correct_small / n if n else 0.0,
        "accuracy_big_only": correct_big / n if n else 0.0,
        "promoted_steps": promoted,
        "promotion_rate": promoted / n if n else 0.0,
        "promotion_changed_answer": changed,
    }


def raw_choice_stats(steps: list[Step]) -> dict:
    """The ungated baseline: take the model's top option every step."""
    correct = 0
    flips = 0
    prev = None
    for step in steps:
        pick = max(step.probs, key=step.probs.get)
        if pick != prev:
            flips += 1
        prev = pick
        if pick == step.truth:
            correct += 1
    n = len(steps)
    margins = []
    for step in steps:
        ordered = sorted(step.probs.values(), reverse=True)
        margins.append(ordered[0] - (ordered[1] if len(ordered) > 1 else 0.0))
    return {
        "accuracy": correct / n if n else 0.0,
        "flips_per_step": flips / n if n else 0.0,
        "mean_top2_margin": statistics.mean(margins) if margins else 0.0,
        "median_top2_margin": statistics.median(margins) if margins else 0.0,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8291)
    ap.add_argument("--bf16-port", type=int, default=8293)
    ap.add_argument("--episodes", type=int, default=8)
    ap.add_argument("--steps", type=int, default=10)
    ap.add_argument("--seed", type=int, default=20261031)
    ap.add_argument("--deltas", type=float, nargs="+",
                    default=[0.0, 0.02, 0.05, 0.10, 0.20, 0.35, 0.60])
    ap.add_argument("--taus", type=float, nargs="+",
                    default=[0.05, 0.10, 0.20, 0.35, 0.50])
    ap.add_argument("--out", default="exp_c_gates")
    args = ap.parse_args()

    if not d1lab.health(args.port):
        raise SystemExit(f"no server on 127.0.0.1:{args.port}")
    bf16_port = args.bf16_port if d1lab.health(args.bf16_port) else None
    if bf16_port is None:
        print(f"note: no BF16 server on {args.bf16_port}; running the gate arm only")

    before = d1lab.box_state()
    print(f"box BEFORE: {before.brief()}", flush=True)
    d1lab.warm_gpu(6.0)

    rng = random.Random(args.seed)
    episodes: list[list[Step]] = []
    for e in range(args.episodes):
        flip_at = rng.randrange(args.steps // 2, args.steps)
        plan = make_episode(rng, args.steps, flip_at)
        ep = record_episode(args.port, bf16_port, plan, rng)
        episodes.append(ep)
        print(
            f"  episode {e}: truth {ep[0].truth} -> {ep[-1].truth}, "
            f"mean margin {raw_choice_stats(ep)['mean_top2_margin']:.3f}, "
            f"raw acc {raw_choice_stats(ep)['accuracy']:.2f}",
            flush=True,
        )

    all_steps = [s for ep in episodes for s in ep]

    raw = raw_choice_stats(all_steps)
    print(f"\nraw (ungated) over {len(all_steps)} steps: {raw}", flush=True)

    hy = [hysteresis_gate(all_steps, d) for d in args.deltas]
    print("\nhysteresis sweep:", flush=True)
    for h in hy:
        print(
            f"  delta={h['delta']:<5} acc={h['accuracy']:.3f} "
            f"switches={h['switches']:>3} spurious={h['spurious_switches']:>3} "
            f"churn/step={h['churn_per_step']:.3f} "
            f"mean latency after flip={h['mean_latency_after_flip']}",
            flush=True,
        )

    pr = []
    if bf16_port:
        pr = [promote_gate(all_steps, t) for t in args.taus]
        print("\nprecision-promotion sweep (Q8 -> BF16 on low margin):", flush=True)
        for p in pr:
            print(
                f"  tau={p['tau']:<5} gated acc={p['accuracy_gated']:.3f} "
                f"small-only={p['accuracy_small_only']:.3f} "
                f"big-only={p['accuracy_big_only']:.3f} "
                f"promoted={p['promoted_steps']:>3} "
                f"changed={p['promotion_changed_answer']:>3}",
                flush=True,
            )

    # how often do the two precisions disagree at all?
    disagree = 0
    both = 0
    for s in all_steps:
        if s.bf16_probs:
            both += 1
            if max(s.probs, key=s.probs.get) != max(s.bf16_probs, key=s.bf16_probs.get):
                disagree += 1

    after = d1lab.box_state()
    d1lab.emit(
        args.out,
        {
            "experiment": "C — hysteresis gate and precision promotion on a real d1 decision",
            "task": (
                "quay-side scene observed repeatedly; 4 candidate tiles; one is right; "
                "the wording varies while the truth holds, then the scene changes and the "
                "truth flips once per episode"
            ),
            "tiles": TILES,
            "box_before": before.__dict__,
            "box_after": after.__dict__,
            "episodes": [
                [s.__dict__ for s in ep] for ep in episodes
            ],
            "raw_ungated": raw,
            "hysteresis_sweep": hy,
            "promotion_sweep": pr,
            "precision_disagreement": {
                "steps_compared": both,
                "disagreements": disagree,
                "rate": disagree / both if both else 0.0,
            },
        },
    )


if __name__ == "__main__":
    main()
