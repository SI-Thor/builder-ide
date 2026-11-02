import json, random, sys
from pathlib import Path
REPO = Path("/home/caseydigennaro/lm-wt/refit-drift")
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "docs/lab/lab3-scripts"))
sys.path.insert(0, str(REPO / "docs/lab/refit-drift-scripts"))

from exp_refit_drift import (Config, load_real_tiles, run_once, BanditTarget,
                              truth_value, bucket_of, greedy_pick)
from core.tiles import evaluate, ContextualBandit

cfg = Config(nights=6, contexts_per_night=250)
tiles = load_real_tiles(REPO / "docs/lab/refit-drift-scripts/real_tiles.json")
run = run_once(cfg, "refit", 0, tiles)
recs = run.records
print("plays", len(recs))
print("mean realised reward", sum(r.reward for r in recs) / len(recs))
print("night-3 snapshot epsilon", run.snapshots[3].current_epsilon())

prev_log = recs[: run.nights[2].plays]
snap = run.snapshots[3]
keys = run.snapshot_keys[3]

# 1. the logging policy at the end of night 3 as the target: its value
#    should be close to the mean reward of the log it produced.
log_pol = ContextualBandit(feature_keys=keys, epsilon=cfg.epsilon, prior=cfg.prior, seed=0)
log_pol.fit(prev_log)
for name, tgt in [
    ("snapshot(same data)", BanditTarget(snap, keys, "snap")),
    ("snapshot(refit on all)", BanditTarget(log_pol, keys, "logpol")),
]:
    for method in ("ips", "snips"):
        est = evaluate(prev_log, tgt, method=method)
        print(f"  {name:22s} {method:5s} value={est.value:.4f} ci=[{est.ci_low:.4f},{est.ci_high:.4f}] "
              f"eff_n={est.effective_n:.1f} maxw={est.max_weight:.3f} support={est.support:.3f}")

t = truth_value(snap, keys, prev_log, run.tiles, cfg.outcome)
print("truth(snapshot)", t)

# 2. how far is the target's probability from what the logger actually did?
diffs = []
for r in prev_log:
    tgt = BanditTarget(snap, keys, "x")
    p = tgt.probability(r.context, r.tile_id, r.candidates)
    diffs.append((p, r.propensity))
print("mean target_p", sum(d for d, _ in diffs) / len(diffs))
print("mean logging_p", sum(d for _, d in diffs) / len(diffs))

# 3. what does the target think the eligible set / greedy pick is, vs the
#    tile that was actually played?
same = 0
for r in prev_log:
    b = bucket_of(r.context, keys)
    cand = list(r.candidates)
    best = greedy_pick(snap, b, cand, snap.stats()["overall"])
    if best == r.tile_id:
        same += 1
print("target greedy == logged tile:", same, "/", len(prev_log))

# 4. the realised reward split by whether the logged tile was the greedy one
greedy_rewards = [r.reward for r in prev_log
                  if greedy_pick(snap, bucket_of(r.context, keys), list(r.candidates),
                                 snap.stats()["overall"]) == r.tile_id]
other_rewards = [r.reward for r in prev_log
                 if greedy_pick(snap, bucket_of(r.context, keys), list(r.candidates),
                                snap.stats()["overall"]) != r.tile_id]
print("logged==greedy: n", len(greedy_rewards), "mean reward", sum(greedy_rewards)/max(1,len(greedy_rewards)))
print("logged!=greedy: n", len(other_rewards), "mean reward", sum(other_rewards)/max(1,len(other_rewards)))

# 5. the truth, computed per record, and the realised reward per record
tv = truth_value(snap, keys, prev_log, run.tiles, cfg.outcome)
print("truth vs mean realised:", tv, sum(r.reward for r in prev_log)/len(prev_log))

# 6. how good is the target really? recompute the truth by brute force over
#    the eligible set for a handful of records
import itertools
r0 = prev_log[0]
b0 = bucket_of(r0.context, keys)
c0 = list(r0.candidates)
best = greedy_pick(snap, b0, c0, snap.stats()["overall"])
eps = snap.current_epsilon()
print("example record: bucket", b0, "candidates", len(c0), "epsilon", round(eps, 4))
for t2 in c0:
    tile = run.tiles[t2]
    p = (1 - eps) + eps / len(c0) if t2 == best else eps / len(c0)
    print(f"    {t2:22s} p={p:.4f} p_win={cfg.outcome.p_win(tile, r0.context):.2f} "
          f"contrib={p*cfg.outcome.p_win(tile, r0.context):.4f}")
