"""C2 -- the same model in two places.

The same question sets, asked of the same weights (Cloudflare Clef-flash):
  cloud   Workers AI, through the local `wrangler dev --remote` proxy.
  local   the Thor's llama.cpp server on :8096, reached over an SSH tunnel.

What we compare: agreement (do the two places give the same decision?),
latency, and accuracy against the code-computed ground truth.

The Thor is asked for as little as possible: the server was already defined
there as a systemd unit, it is started under the shared heavy lock, and it
is stopped again when this run is done.
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
import gates
import tasks
from decision_client import ClefAI, DecisionClient, MODELS, SystemOne, pct

RESULTS = Path(__file__).resolve().parent.parent / "results"
RESULTS.mkdir(exist_ok=True)


def ask_pack(client, model, seed: int, pack: str):
    q, t = (gates.one_gate_pack(seed) if pack == "q1"
            else gates.build_gates(seed))
    g, a, b, es = tasks._world(seed)
    state = tasks.scene_state(g, a, b, es)
    status, answers, ms, raw = client.ask(state, q, model)
    return status, answers, ms, raw, t


def summarize(rows: list[dict], label: str) -> dict:
    ok = [r for r in rows if r["status"] == 200]
    lat = sorted(r["ms"] for r in ok)
    errs = [r for r in rows if r["status"] != 200]
    per_gate_hits: list[int] = []
    for r in ok:
        per_gate_hits.extend(r["hits"])
    return {
        "label": label,
        "n": len(rows), "n_ok": len(ok), "n_err": len(errs),
        "error_rate": round(len(errs) / max(1, len(rows)), 4),
        "errors": [e.get("err") for e in errs][:5],
        "latency_ms": {
            "p50": round(pct(lat, .50), 1) if lat else None,
            "p95": round(pct(lat, .95), 1) if lat else None,
            "p99": round(pct(lat, .99), 1) if lat else None,
            "mean": round(statistics.mean(lat), 1) if lat else None,
        },
        "accuracy": round(sum(per_gate_hits) / max(1, len(per_gate_hits)), 4),
        "n_gates_scored": len(per_gate_hits),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="c2-two-places.json")
    ap.add_argument("--cloud-url", default="http://127.0.0.1:8797")
    ap.add_argument("--local-url", default="http://127.0.0.1:8096")
    ap.add_argument("--seeds", type=int, default=40)
    ap.add_argument("--packs", default="q1,q64")
    args = ap.parse_args()

    cloud_b = ClefAI(url=args.cloud_url)
    cloud = DecisionClient(cloud_b, MODELS["flash"])
    local = DecisionClient(SystemOne(url=args.local_url.rstrip("/") + "/v1/systemone",
                                     model="clef-flash", name="clef-local",
                                     send_model=False),
                            "clef-flash")

    packs = [p.strip() for p in args.packs.split(",") if p.strip()]
    seeds = list(range(1000, 1000 + args.seeds))

    out = {"experiment": "C2 same model in two places",
           "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
           "cloud": f"Workers AI {MODELS['flash']} via {args.cloud_url}",
           "local": f"Thor llama.cpp clef-flash Q4_K_M via {args.local_url}",
           "n_seeds": args.seeds, "packs": {}}

    for pack in packs:
        rows = {"cloud": [], "local": []}
        raw_answers = {"cloud": {}, "local": {}}
        for seed in seeds:
            for place, client, model in (("cloud", cloud, MODELS["flash"]),
                                         ("local", local, "clef-flash")):
                st, ans, ms, raw, truth = ask_pack(client, model, seed, pack)
                rec = {"seed": seed, "status": st, "ms": ms,
                       "err": None if st == 200 else str(raw)[:220]}
                if st == 200:
                    hits = []
                    for qid, want in truth.items():
                        a = ans.get(qid) or {}
                        if a.get("type") == "noul":
                            hits.append(1 if ((float(a.get("p", 0)) >= 0.5) == want)
                                        else 0)
                        else:
                            hits.append(1 if a.get("answer") == want else 0)
                    rec["hits"] = hits
                    raw_answers[place][seed] = {
                        qid: (round(float((ans.get(qid) or {}).get("p", 0.0)), 4)
                              if (ans.get(qid) or {}).get("type") == "noul"
                              else (ans.get(qid) or {}).get("answer"))
                        for qid in truth}
                else:
                    rec["hits"] = []
                rows[place].append(rec)

        # agreement, per question, between the two places
        agree_n = agree_d = 0
        per_q: dict[str, list[int]] = {}
        for seed in seeds:
            c = raw_answers["cloud"].get(seed)
            l = raw_answers["local"].get(seed)
            if c is None or l is None:
                continue
            for qid in c:
                if qid not in l:
                    continue
                if qid.startswith("g") and qid[1:3].isdigit():
                    cv = c[qid] >= 0.5 if isinstance(c[qid], float) else c[qid]
                    lv = l[qid] >= 0.5 if isinstance(l[qid], float) else l[qid]
                else:
                    cv, lv = c[qid], l[qid]
                same = (cv == lv)
                agree_n += 1
                agree_d += 1 if same else 0
                per_q.setdefault(qid, []).append(1 if same else 0)

        out["packs"][pack] = {
            "cloud": summarize(rows["cloud"], "cloud"),
            "local": summarize(rows["local"], "local"),
            "agreement_overall": round(agree_d / agree_n, 4) if agree_n else None,
            "n_compared": agree_n,
            "agreement_by_question": {k: round(sum(v) / len(v), 4)
                                       for k, v in sorted(per_q.items())},
            "n_compared_local": len(raw_answers["local"]),
            "n_compared_cloud": len(raw_answers["cloud"]),
        }
        p = out["packs"][pack]
        print(f"pack {pack}: cloud p50={p['cloud']['latency_ms']['p50']} "
              f"p95={p['cloud']['latency_ms']['p95']} acc={p['cloud']['accuracy']} "
              f"err={p['cloud']['error_rate']} | "
              f"local p50={p['local']['latency_ms']['p50']} "
              f"p95={p['local']['latency_ms']['p95']} acc={p['local']['accuracy']} "
              f"err={p['local']['error_rate']} | "
              f"agreement={p['agreement_overall']}", flush=True)

    (RESULTS / args.out).write_text(json.dumps(out, indent=1))
    print(f"\n-> results/{args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
