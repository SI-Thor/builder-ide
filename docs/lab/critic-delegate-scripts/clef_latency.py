#!/usr/bin/env python3
"""Where the cloud delegate's time goes.

The cloud path is Thor → SSH forward → the ProArt's ``wrangler dev --remote``
proxy → Workers AI. The Worker reports its own time (the edge's work), and the
critic measures the wall time, so the difference is the transport: the upload
of the picture and the proxy in front of the model.

This script asks the **same frame** twice — once with the hybrid's single
escalated question, once with all six — and prints the wall time and the
edge's own time for each, so the two can be compared with each other rather
than with a remembered number.

    python docs/lab/critic-delegate-scripts/clef_latency.py --repeat 3
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SELECT = HERE.parent / "critic-select-scripts"
for path in (str(HERE), str(SELECT)):
    if path not in sys.path:
        sys.path.insert(0, path)

from harness import CACHE, MANIFEST, load_set  # noqa: E402

from core.critic.candidates.clef import ask_clef  # noqa: E402
from core.critic.candidates.questions import CLASS_QUESTIONS  # noqa: E402
from core.critic.candidates.clef import CLEF_MODEL  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--member", default="mem_718023ba022732d4")
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--manifest", default=str(MANIFEST))
    args = parser.parse_args()

    members, _bases = load_set(args.manifest, CACHE)
    member = next((m for m in members if m.member_id == args.member), None)
    if member is None or not member.derived_path:
        print(f"! no such member: {args.member}")
        return 1

    one = {"floating_object": CLASS_QUESTIONS["floating_object"]}
    every = dict(CLASS_QUESTIONS)

    print(f"the frame: {member.member_id} ({member.base_id})")
    rows = []
    for label, questions in (("one question", one), ("six questions", every)):
        walls, edges = [], []
        for _ in range(max(1, args.repeat)):
            _, elapsed, worker_ms, _usage = ask_clef(
                "http://127.0.0.1:8797",
                member.derived_path,
                questions,
                model=CLEF_MODEL,
            )
            walls.append(elapsed)
            edges.append(worker_ms)
        rows.append(
            {
                "label": label,
                "questions": len(questions),
                "wall_median_ms": statistics.median(walls) * 1000,
                "edge_median_ms": statistics.median(edges),
                "transport_median_ms": statistics.median(
                    [w - e / 1000 for w, e in zip(walls, edges)]
                )
                * 1000,
                "walls_ms": [round(w * 1000) for w in walls],
            }
        )
        print(
            f"  {label:14s} wall {rows[-1]['wall_median_ms']:8.0f} ms   "
            f"edge {rows[-1]['edge_median_ms']:6.0f} ms   "
            f"transport {rows[-1]['transport_median_ms']:8.0f} ms"
        )

    out = HERE / "results" / "clef-latency.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"member": args.member, "rows": rows}, indent=1))
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
