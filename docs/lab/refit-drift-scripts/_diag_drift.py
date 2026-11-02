import sys
from pathlib import Path
REPO = Path("/home/caseydigennaro/lm-wt/refit-drift")
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "docs/lab/refit-drift-scripts"))

from exp_refit_drift import (Config, load_real_tiles, run_once, BanditTarget,
                              truth_value, bucket_of, greedy_pick)
from core.tiles import evaluate, ContextualBandit

cfg = Config(nights=6, contexts_per_night=250)
tiles = load_real_tiles(REPO / "docs/lab/refit-drift-scripts/real_tiles.json")

CLIPS = [None, 50.0, 20.0, 10.0, 5.0]

print("seed night  |  truth_now  truth_prev  truth_drift |  snips_drift(clip)          |  eff_n  maxw")
for seed in (0, 1, 2):
    run = run_once(cfg, "refit", seed, tiles)
    for night in (2, 3, 4, 5):
        prev = run.snapshots[night - 1]
        snap = run.snapshots[night]
        keys = run.snapshot_keys[night]
        prev_log = run.records[: run.nights[night - 2].plays]
        t_now = truth_value(snap, keys, prev_log, run.tiles, cfg.outcome)
        t_prev = truth_value(prev, run.snapshot_keys[night - 1], prev_log, run.tiles, cfg.outcome)
        tp = BanditTarget(prev, run.snapshot_keys[night - 1], "p")
        tn = BanditTarget(snap, keys, "n")
        parts = []
        eff = maxw = 0
        for clip in CLIPS:
            a = evaluate(prev_log, tp, method="snips", clip=clip)
            b = evaluate(prev_log, tn, method="snips", clip=clip)
            parts.append(f"c={clip}: {b.value - a.value:+.4f}")
            eff, maxw = b.effective_n, b.max_weight
        print(f"{seed:4d} {night:5d} |  {t_now:.4f}    {t_prev:.4f}    {t_now - t_prev:+.4f}   |  "
              + "  ".join(parts) + f"  |  {eff:.1f} {maxw:.1f}")
