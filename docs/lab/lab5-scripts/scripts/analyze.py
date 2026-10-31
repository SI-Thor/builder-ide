#!/usr/bin/env python3
# lab5 — analysis + the distribution gate for the round-5 sweep.
#
# The gate (BRIEF #4): the annealing's output *distribution* must be
# unchanged by batched proposals. Statistic = the final placement score
# (the full constraint graph's loss on the final state). Test = two-sample
# KS, baseline vs each arm, on
#   (a) the per-seed final losses (5 vs 5 — weak, reported anyway),
#   (b) the pooled per-stage final losses (stage × seed, more samples;
#       stages are comparable because rooms are identical per seed and the
#       stage schedule is the same),
# each also *tie-quantised*: round 2 measured that ~17 % of candidates have
# a tied closest edge, so score differences at the tie scale are not
# decisions but noise — quantising losses to the tie scale (0.5, the
# magnitude round 2 saw a tie flip move a term by) is the "respect the tie
# ambiguity" form of the test. Both raw and quantised are printed.

import json
import sys
from pathlib import Path

import numpy as np
from scipy import stats

LAB5 = Path(__file__).resolve().parent.parent
RESULTS = LAB5 / (sys.argv[1] if len(sys.argv) > 1 else "results")
BASE_TAG = "baseg"

ARMS = [
    (BASE_TAG, "baseline N=1 (upstream)"),
    ("b8bestg", "batch N=8 best"),
    ("b8unifg", "batch N=8 uniform (control)"),
    ("b8sampleg", "batch N=8 sample"),
    ("b64bestg", "batch N=64 best"),
    ("b64sampleg", "batch N=64 sample"),
    ("b512bestg", "batch N=512 best"),
]
TIE_SCALES = [0.5, 1.0]


def load(tag: str, seed: int):
    p = RESULTS / f"{tag}_seed{seed}.json"
    if not p.exists():
        return None
    return json.loads(p.read_text())


def seeds_of(tag: str):
    return sorted(
        int(p.name.split("seed")[1].split(".")[0])
        for p in RESULTS.glob(f"{tag}_seed*.json")
    )


def ks(a, b):
    if len(a) < 2 or len(b) < 2:
        return None
    r = stats.ks_2samp(a, b)
    return r.statistic, r.pvalue


def cliffs_delta(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    if len(a) == 0 or len(b) == 0:
        return None
    gt = (a[:, None] > b[None, :]).sum()
    lt = (a[:, None] < b[None, :]).sum()
    return float((gt - lt) / (len(a) * len(b)))  # -1..1; 0 = identical distributions


def main() -> int:
    seeds = seeds_of(BASE_TAG)
    print(f"results dir: {RESULTS}\nbaseline seeds found: {seeds}\n")

    # ---- wall + final score table ------------------------------------------
    print("== per-arm: solve wall (s) and final placement score, per seed ==")
    hdr = f"{'arm':<28}" + "".join(f"  s{k}" for k in seeds) + "   | med"
    walls, losses, viols, cands = {}, {}, {}, {}
    for tag, label in ARMS:
        rows = [load(tag, k) for k in seeds]
        have = [(k, r) for k, r in zip(seeds, rows) if r]
        if not have:
            continue
        ws = [r["walls"]["solve_total"] for _, r in have]
        ls = [r["final"]["loss"] for _, r in have]
        vs = [r["final"]["viol"] for _, r in have]
        walls[tag], losses[tag], viols[tag] = ws, ls, vs
        cs = [r["candidate_summary"] for _, r in have]
        cands[tag] = dict(
            n=sum(c["n"] for c in cs),
            n_ok=sum(c["n_ok"] for c in cs),
            t_apply=sum(c["t_apply_s"] for c in cs),
            t_eval=sum(c["t_eval_s"] for c in cs),
            t_revert=sum(c["t_revert_s"] for c in cs),
        )
        print(f"\n{label}  ({len(have)}/{len(seeds)} seeds)")
        print(f"  wall_s : " + " ".join(f"{w:7.1f}" for w in ws) + f"   | {np.median(ws):7.1f}")
        print(f"  loss   : " + " ".join(f"{l:7.2f}" for l in ls) + f"   | {np.median(ls):7.2f}")
        print(f"  viol   : " + " ".join(f"{v:7d}" for v in vs))

    # ---- candidate cost decomposition (the CPU-side story) ------------------
    print("\n== candidate cost decomposition (all seeds pooled) ==")
    print("(att = every apply() tried; ok = applicable candidates that were scored;")
    print(" ms/att and ms/ok each spread apply+eval+revert over their own base)")
    print(f"{'arm':<28}{'att':>7}{'ok':>6}{'t_apply':>9}{'t_eval':>9}{'t_revert':>9}{'ms/att':>8}{'ms/ok':>8}")
    for tag, label in ARMS:
        if tag not in cands or cands[tag]["n_ok"] == 0:
            continue
        c = cands[tag]
        tot = c["t_apply"] + c["t_eval"] + c["t_revert"]
        print(
            f"{label:<28}{c['n']:>7}{c['n_ok']:>6}{c['t_apply']:>9.1f}{c['t_eval']:>9.1f}"
            f"{c['t_revert']:>9.1f}{1000*tot/c['n']:>8.1f}{1000*tot/c['n_ok']:>8.1f}"
        )

    # ---- by-move-type cost split (what a GPU scorer can and cannot replace) --
    # pose moves (Translate/Rotate/ReinitPose/RelationPlaneChange) are
    # scoreable as hypothetical poses against static geometry — the thing
    # round 2's GPU kernel does; structural moves (Addition/Deletion/Resample)
    # spawn or delete geometry per candidate and are not pose scoring.
    print("\n== time by move type (all seeds pooled, attempts incl. invalid) ==")
    print(f"{'arm':<28}{'move':<22}{'att':>7}{'ok':>6}{'t_apply':>9}{'t_eval':>9}{'t_rev':>8}{'share':>7}")
    for tag, label in ARMS:
        rows = []
        for k in seeds:
            r = load(tag, k)
            if r:
                rows += r.get("candidates_sample", [])
        if not rows:
            continue
        tot_arm = sum(c["t_apply"] + c["t_eval"] + c["t_revert"] for c in rows)
        by = {}
        for c in rows:
            s = by.setdefault(c["move"], dict(n=0, ok=0, ta=0.0, te=0.0, tr=0.0))
            s["n"] += 1
            s["ok"] += 1 if c["ok"] else 0
            s["ta"] += c["t_apply"]
            s["te"] += c["t_eval"]
            s["tr"] += c["t_revert"]
        for mv, s in sorted(by.items(), key=lambda kv: -(kv[1]["ta"] + kv[1]["te"] + kv[1]["tr"])):
            t = s["ta"] + s["te"] + s["tr"]
            print(f"{label:<28}{mv:<22}{s['n']:>7}{s['ok']:>6}{s['ta']:>9.1f}{s['te']:>9.1f}{s['tr']:>8.1f}{t/tot_arm:>7.0%}")

    # ---- the gate: KS over final placement scores ---------------------------
    print("\n== THE GATE: KS over final placement scores vs baseline ==")
    if BASE_TAG not in losses:
        print("no baseline runs found")
        return 1

    # pooled per-stage final losses (stage+seed matched: rooms identical per seed)
    def stage_losses(tag):
        vals, meta = [], {}
        for k in seeds:
            r = load(tag, k)
            if not r:
                continue
            for row in r["stage_results"]:
                vals.append(row["final_loss"])
                meta[row["stage"]] = meta.get(row["stage"], 0) + 1
        return [v for v in vals if v is not None]

    print(f"\n(a) per-seed final loss (n={len(losses.get(BASE_TAG, []))} vs n_arm)")
    print(f"{'arm':<28}{'D':>7}{'p':>10}{'Δmedian':>10}{'cliff δ':>9}")
    for tag, label in ARMS:
        if tag == BASE_TAG or tag not in losses:
            continue
        r = ks(losses[BASE_TAG], losses[tag])
        if r is None:
            continue
        dm = np.median(losses[tag]) - np.median(losses[BASE_TAG])
        cd = cliffs_delta(losses[tag], losses[BASE_TAG])
        flag = "  <-- DISTRIBUTION CHANGED (p<0.05)" if r[1] < 0.05 else ""
        print(f"{label:<28}{r[0]:>7.3f}{r[1]:>10.3f}{dm:>10.2f}{cd:>9.2f}{flag}")

    print("\n(b) pooled per-stage final loss (stage×seed)")
    print("    (caveat: stages within a seed share the room and each other's state,")
    print("     so pooled p-values are anti-conservative — the paired view in (b2)")
    print("     is the one that respects the seed as the independent unit)")
    print(f"{'arm':<28}{'D':>7}{'p':>10}{'Δmedian':>10}{'cliff δ':>9}")
    base_stages = stage_losses(BASE_TAG)
    for tag, label in ARMS:
        if tag == BASE_TAG:
            continue
        vals = stage_losses(tag)
        r = ks(base_stages, vals)
        if r is None:
            continue
        dm = np.median(vals) - np.median(base_stages)
        cd = cliffs_delta(vals, base_stages)
        flag = "  <-- DISTRIBUTION CHANGED (p<0.05)" if r[1] < 0.05 else ""
        print(f"{label:<28}{r[0]:>7.3f}{r[1]:>10.3f}{dm:>10.2f}{cd:>9.2f}{flag}")

    # paired by seed: stages within a seed are sequential and correlated (a
    # bad early state propagates through later stages), so the seed is the
    # independent unit — per-seed median Δ over stages, sign test over seeds
    print("\n(b2) paired by seed: median per-(seed,stage) loss Δ, arm − baseline")
    print(f"{'arm':<28}{'seeds':>6}{'med<0':>7}{'med>0':>7}  per-seed medians (by seed)")
    for tag, label in ARMS:
        if tag == BASE_TAG:
            continue
        meds = []
        for k in seeds:
            a, b = load(tag, k), load(BASE_TAG, k)
            if not a or not b:
                continue
            ds = [ra["final_loss"] - rb["final_loss"]
                  for ra, rb in zip(a["stage_results"], b["stage_results"])
                  if ra["final_loss"] is not None and rb["final_loss"] is not None]
            if ds:
                meds.append((k, float(np.median(ds))))
        if not meds:
            continue
        lower = sum(1 for _, m in meds if m < 0)
        higher = sum(1 for _, m in meds if m > 0)
        flag = ""
        if min(lower, higher) == 0 and len(meds) >= 2:
            flag = f"  (all {len(meds)} seeds one side; sign-test p={2 ** -len(meds):.4f})"
        per_seed = " ".join(f"s{k}:{m:+.1f}" for k, m in meds)
        print(f"{label:<28}{len(meds):>6}{lower:>7}{higher:>7}  {per_seed}{flag}")

    print("\n(c) tie-quantised variants (losses rounded to the tie scale; the")
    print("    round-2 ambiguity means sub-scale differences are noise)")
    for q in TIE_SCALES:
        print(f"\n  quantise = {q}")
        qb = [round(v / q) * q for v in base_stages]
        for tag, label in ARMS:
            if tag == BASE_TAG:
                continue
            vals = stage_losses(tag)
            if not vals:
                continue
            qv = [round(v / q) * q for v in vals]
            r = ks(qb, qv)
            if r is None:
                continue
            flag = "  <-- CHANGED (p<0.05)" if r[1] < 0.05 else ""
            print(f"  {label:<26}{r[0]:>7.3f}{r[1]:>10.3f}{flag}")

    # violation counts (the hard-constraint half of the score)
    print("\n(d) final violation counts (median per arm)")
    for tag, label in ARMS:
        if tag in viols and viols[tag]:
            print(f"  {label:<28} median={np.median(viols[tag]):.0f}  all={viols[tag]}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
