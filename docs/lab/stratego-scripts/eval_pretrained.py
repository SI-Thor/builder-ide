#!/usr/bin/env python3
"""(b) The pretrained model against a random baseline, over N games.

The desk brief asks for "(b) the pretrained model vs a random/baseline policy
over N games". The baseline is the environment's own uniform sampler over legal
actions (`sample_random_legal_action`), which is the natural null policy: it
plays legal moves and nothing else.

Three matchups are played, each in both seats (the evaluation helper plays the
first agent as player 0 and then as player 1 over the same setups):

  ema    : the pretrained EMA weights   vs random
  weights: the pretrained raw weights    vs random
  self   : the pretrained EMA weights   vs the pretrained EMA weights
           (the reference: a strong agent against itself must score 0)

Usage (from the stratego checkout, with its .venv on PATH):
    python eval_pretrained.py --num-envs 256 --num-games 1024 --out results/eval.json
"""

import argparse
import json
import os
import random
import time

import torch

from pyengine.core.env import Stratego
from pyengine.core.evaluation import evaluate
from pyengine.utils.pretrained_loading import load_pretrained_rl_model
from pyengine.utils.load_pystratego import get_pystratego
from pyengine import utils

pystratego = get_pystratego()


def box_state() -> dict:
    out = {}
    try:
        with open("/proc/loadavg") as f:
            out["loadavg"] = f.read().split()[:3]
    except OSError:
        pass
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    out["mem_available_gb"] = round(int(line.split()[1]) / 1024 / 1024, 1)
    except OSError:
        pass
    return out


def fallback_arrangements(n: int = 2000) -> tuple[list[str], list[str]]:
    """Arrangement strings, if the checkpoint carries none."""
    gen = pystratego.PieceArrangementGenerator(pystratego.BoardVariant.CLASSIC)
    ids = [random.randint(0, gen.num_possible_arrangements()) for _ in range(n)]
    arrs = gen.generate_string_arrangements(ids)
    return list(arrs), list(arrs)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--num-envs", type=int, default=256)
    ap.add_argument("--num-games", type=int, default=1024,
                    help="games per seat per matchup")
    ap.add_argument("--model-dir", default="pretrained/final_run")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    torch.manual_seed(args.seed)
    random.seed(args.seed)

    weights_path = os.path.join(args.model_dir, "model42400.pthw")
    ema_path = os.path.join(args.model_dir, "model42400.pthm")

    ema_model, ema_arrs = load_pretrained_rl_model(ema_path)
    raw_model, raw_arrs = load_pretrained_rl_model(weights_path)
    ema_model.eval()
    raw_model.eval()

    if not ema_arrs or not ema_arrs[0]:
        ema_arrs = fallback_arrangements()
        raw_arrs = ema_arrs
    print(f"arrangements: {len(ema_arrs[0])} red / {len(ema_arrs[1])} blue", flush=True)

    env = Stratego(
        num_envs=args.num_envs,
        traj_len_per_player=4000 // 2 + 101,
        quiet=1,
        move_memory=86,
        max_num_moves=4000,
        max_num_moves_between_attacks=100,
    )
    env.seed_action_sampler(args.seed)

    def random_agent(legal_action_mask):
        return env.sample_random_legal_action()

    matchups = [
        ("ema_vs_random", ema_model, ema_arrs, random_agent, ema_arrs),
        ("weights_vs_random", raw_model, raw_arrs, random_agent, raw_arrs),
        ("ema_vs_ema", ema_model, ema_arrs, ema_model, ema_arrs),
    ]

    results = []
    with torch.no_grad(), utils.eval_mode(ema_model, raw_model):
        for name, agent_a, arrs_a, agent_b, arrs_b in matchups:
            t0 = time.perf_counter()
            outcomes = evaluate(agent_a, arrs_a, agent_b, arrs_b, env)
            elapsed = time.perf_counter() - t0

            games = outcomes.numel()
            wins = int((outcomes > 0).sum())
            losses = int((outcomes < 0).sum())
            ties = int((outcomes == 0).sum())
            r = {
                "matchup": name,
                "games": games,
                "wins": wins,
                "losses": losses,
                "ties": ties,
                "win_rate": round(wins / games, 4),
                "loss_rate": round(losses / games, 4),
                "tie_rate": round(ties / games, 4),
                "mean_reward": round(outcomes.mean().item(), 4),
                "elapsed_s": round(elapsed, 2),
                "games_per_s": round(games / elapsed, 1),
            }
            results.append(r)
            print(
                f"{name:>18}: {wins:>5}W {losses:>5}L {ties:>5}T "
                f"(win {r['win_rate']:.3f} / loss {r['loss_rate']:.3f} / "
                f"tie {r['tie_rate']:.3f})  mean reward {r['mean_reward']:+.4f}  "
                f"[{r['elapsed_s']:.1f}s, {r['games_per_s']:.0f} games/s]",
                flush=True,
            )

    payload = {
        "num_envs": args.num_envs,
        "num_games_per_seat": args.num_games,
        "seed": args.seed,
        "model_dir": args.model_dir,
        "results": results,
        "box": box_state(),
    }
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w") as f:
            json.dump(payload, f, indent=2)
        print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
