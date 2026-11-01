"""Reference table: the same task set answered by three decision models.

Not one of the brief's four experiments -- this is the reference the
recommendation leans on.  Three models answer the identical cases with the
identical questions:

  clef-flash   Cloudflare Clef-flash 9B, Workers AI
  clef-27B     Cloudflare Clef 27B, Workers AI
  jev          TypeSafe Jev, System One API

For each: accuracy against the code-computed ground truth, latency, and
pairwise agreement.  A pair of models that agree is only useful if they
agree on the right answer, so accuracy is reported next to agreement.

Jev's key is read from ~/.config/last-mile/secrets.env and never printed.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import cascade
from cascade import Harness, build_all
from decision_client import (ClefAI, DecisionClient, MODELS, jev_backend, pct)

RESULTS = Path(__file__).resolve().parent.parent / "results"
RESULTS.mkdir(exist_ok=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="ref-threeway.json")
    ap.add_argument("--scenes", type=int, default=80)
    ap.add_argument("--defects", type=int, default=60)
    ap.add_argument("--tiles", type=int, default=60)
    ap.add_argument("--url", default="http://127.0.0.1:8797")
    args = ap.parse_args()

    backend = ClefAI(url=args.url)
    models = {
        "clef-flash": DecisionClient(backend, MODELS["flash"]),
        "clef-27B": DecisionClient(backend, MODELS["clef27"]),
    }
    try:
        models["jev"] = DecisionClient(jev_backend(), "jev-latest")
    except Exception as e:  # noqa: BLE001
        print(f"jev unavailable: {e}")

    cases = build_all(args.scenes, args.defects, args.tiles)
    by_id = {c.id: c for c in cases}
    harness = Harness(name="plain")

    runs: dict[str, dict] = {}
    for name, client in models.items():
        t0 = time.perf_counter()
        run = cascade.run_harness(harness, cases, client,
                                  client.model or MODELS["flash"], tag=name)
        runs[name] = run
        lat = sorted(c["ms"] for c in run["cases"] if c.get("status") == 200)
        n_ok = len(lat)
        hits: dict[str, list[int]] = {}
        for c in run["cases"]:
            case = by_id.get(c["id"])
            if case is None or c.get("status") != 200:
                continue
            for qid in case.question_ids:
                a = (c.get("decided") or {}).get(qid)
                want = case.truth.get(qid)
                if a is None or want is None:
                    continue
                hits.setdefault(case.task, []).append(
                    1 if a.get("answer") == want else 0)
        allh = [x for v in hits.values() for x in v]
        print(f"{name:11s} n_ok={n_ok}/{len(cases)} "
              f"p50={pct(lat,.5):.0f}ms p95={pct(lat,.95):.0f}ms "
              f"acc={sum(allh)/max(1,len(allh)):.4f} "
              f"by_task={ {k: round(sum(v)/len(v),3) for k,v in hits.items()} } "
              f"[{time.perf_counter()-t0:.0f}s]", flush=True)

    # pairwise agreement
    pairs = {}
    names = list(runs)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            da = {c["id"]: c.get("decided") or {} for c in runs[a]["cases"]
                  if c.get("status") == 200}
            db = {c["id"]: c.get("decided") or {} for c in runs[b]["cases"]
                  if c.get("status") == 200}
            common = sorted(set(da) & set(db))
            same = tot = 0
            per_task: dict[str, list[int]] = {}
            for cid in common:
                case = by_id[cid]
                for qid in case.question_ids:
                    x, y = da[cid].get(qid), db[cid].get(qid)
                    if x is None or y is None:
                        continue
                    eq = (x.get("answer") == y.get("answer"))
                    tot += 1
                    same += 1 if eq else 0
                    per_task.setdefault(case.task, []).append(1 if eq else 0)
            pairs[f"{a} vs {b}"] = {
                "n_compared": tot,
                "agreement": round(same / tot, 4) if tot else None,
                "agreement_by_task": {k: round(sum(v) / len(v), 4)
                                      for k, v in sorted(per_task.items())},
            }
            print(f"  {a} vs {b}: agreement={pairs[f'{a} vs {b}']['agreement']}")

    out = {
        "experiment": "reference table: three decision models, one task set",
        "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "n_cases": len(cases),
        "models": list(runs),
        "pairwise": pairs,
        "neurons_total": round(backend.total_neurons, 2),
        "usd_total": round(backend.total_neurons / 1000 * 0.011, 6),
    }
    (RESULTS / args.out).write_text(json.dumps(out, indent=1))
    (RESULTS / (args.out.replace(".json", "") + "-runs.json")).write_text(
        json.dumps(runs, indent=1))
    print(f"\nneurons={backend.total_neurons:.1f} usd={out['usd_total']} "
          f"-> results/{args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
