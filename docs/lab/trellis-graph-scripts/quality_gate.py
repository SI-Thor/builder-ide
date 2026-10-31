"""The quality gate: does the fp8 path change the prop?

The speed of the fused fp8 path is only worth having if the prop it makes is
the prop the bf16 path makes.  This script asks that question of the meshes
the arms actually produced, on the same seeds, and answers it with two
numbers:

* **the critic's score** — the same graded verdict the night gives a
  variant, run over the mesh each arm produced.  It is the number the night
  ranks variants by, so a dtype that quietly makes worse props shows up
  here as a lower score;
* **the silhouette IoU** — the overlap of the prop's outline between the
  two arms, seen from six directions (``core.genbatch.fidelity``).  This is
  the number that catches a dtype that changes the *shape* of the prop
  without changing the checks: the critic's checks are analytic and coarse
  (a volume, a surface, a triangle count), while the outline is what a
  camera would see.

Both are computed on the same seed's mesh in both arms, so the comparison is
between two meshes of the same prop — not between two different props.

    python quality_gate.py --root ~/lm-wt/trellis/out/fp8real \\
        --control bf16 --candidate fp8-fixed --out artifacts/fp8-real/quality.json

The verdict is printed as well as written: a dtype that costs quality is
reported plainly, and the default stays bf16.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from core.genbatch.critic import judge  # noqa: E402
from core.genbatch.fidelity import silhouette_iou  # noqa: E402
from core.genbatch.glb import read_glb  # noqa: E402
from core.genbatch.mesh import measure_mesh  # noqa: E402
from core.genbatch.models import PropRequest  # noqa: E402

#: The prompt the arms run, and the request the critic judges against.
#: The same one ``run_one_prop.py`` sends, so the verdict is about the
#: dtype and not about a different request.
PROMPT = (
    "a weathered wooden crate with iron banding, studio product photo, "
    "single object, plain light grey background"
)
NEGATIVE = (
    "blurry, low quality, watermark, text, deformed, disfigured, "
    "multiple objects, cropped"
)

#: The critic's floor, as this gate reads it: the candidate's score may not
#: sit below the control's by more than this.  The critic is graded, and
#: two runs of the *same* prop on the *same* seed do not score identically
#: (the sampler is stochastic and the mesh tail is not bit-reproducible), so
#: the floor is a small band and not a point.
SCORE_FLOOR = 0.02

#: The silhouette's floor: the prop's outline must be the same prop.  The
#: repair stage's own fidelity check holds 0.9995 on a good repair, so 0.95
#: is a wide margin around "the same shape".
IOU_FLOOR = 0.95


def _request() -> PropRequest:
    """The request the arms' props answer."""
    return PropRequest(
        id="crate",
        prompt=PROMPT,
        negative=NEGATIVE,
        seeds=1,
    )


def _find(root: Path, arm: str, seed: int) -> Path | None:
    """The GLB one arm wrote for one seed.

    The arms write into ``<root>/<arm>-r<n>/s<seed>/``, and the glob says
    exactly that — ``{arm}-r*``, not ``{arm}*``.  The loose form would also
    match the one-off probe runs that share the arm's name's prefix
    (``fp8-fixed-probe1``, the first ``fp8-fixed`` rehearsal), whose meshes
    are not rounds of this grid, and — because ComfyUI counts output files
    per directory — a directory that still holds a mesh from a superseded
    grid would hand the gate that mesh instead of this grid's.  The rounds
    sort by name, so the first match is the earliest round.
    """
    matches = sorted(root.glob(f"{arm}-r*/s{seed}/prop_s{seed}_*.glb"))
    return matches[0] if matches else None


def _score(glb: Path, request: PropRequest) -> dict[str, Any]:
    """The critic's verdict on one mesh."""
    mesh = read_glb(glb).mesh
    report = measure_mesh(mesh)
    verdict = judge(report, request)
    return {
        "glb": str(glb),
        "score": verdict.score,
        "reason": verdict.reason,
        "degraded": verdict.degraded,
        "triangles": report.triangles,
        "vertices": report.vertices,
        "watertight": report.watertight,
        "checks": {
            check.name: {"score": check.score, "weight": check.weight}
            for check in verdict.checks
        },
    }


def _iou(control_glb: Path, candidate_glb: Path) -> float:
    """How much of the prop's outline survived the change of dtype."""
    control = read_glb(control_glb).mesh
    candidate = read_glb(candidate_glb).mesh
    return silhouette_iou(control, candidate)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="quality_gate.py")
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.home() / "lm-wt" / "trellis" / "out" / "fp8real",
        help="where the arms wrote their meshes",
    )
    parser.add_argument("--control", default="bf16", help="the arm to compare against")
    parser.add_argument("--candidate", default="fp8-fixed", help="the arm to judge")
    parser.add_argument("--seeds", type=int, nargs="*", default=[101, 102, 103])
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    request = _request()
    rows: dict[str, Any] = {}
    for seed in args.seeds:
        control_glb = _find(args.root, args.control, seed)
        candidate_glb = _find(args.root, args.candidate, seed)
        if control_glb is None or candidate_glb is None:
            missing = args.control if control_glb is None else args.candidate
            print(f"skipping seed {seed}: no mesh from {missing}", file=sys.stderr)
            continue
        control = _score(control_glb, request)
        candidate = _score(candidate_glb, request)
        rows[str(seed)] = {
            "control": control,
            "candidate": candidate,
            "score_delta": candidate["score"] - control["score"],
            "silhouette_iou": _iou(control_glb, candidate_glb),
        }

    if not rows:
        print("no meshes to compare", file=sys.stderr)
        return 1

    control_scores = [row["control"]["score"] for row in rows.values()]
    candidate_scores = [row["candidate"]["score"] for row in rows.values()]
    ious = [row["silhouette_iou"] for row in rows.values()]
    deltas = [row["score_delta"] for row in rows.values()]

    score_ok = min(deltas) >= -SCORE_FLOOR
    iou_ok = min(ious) >= IOU_FLOOR
    verdict = "pass" if (score_ok and iou_ok) else "fail"

    document = {
        "control": args.control,
        "candidate": args.candidate,
        "request": {"prompt": PROMPT, "negative": NEGATIVE},
        "floors": {"score": SCORE_FLOOR, "silhouette_iou": IOU_FLOOR},
        "seeds": rows,
        "summary": {
            "control_score_median": statistics.median(control_scores),
            "candidate_score_median": statistics.median(candidate_scores),
            "score_delta_median": statistics.median(deltas),
            "score_delta_min": min(deltas),
            "silhouette_iou_min": min(ious),
            "silhouette_iou_median": statistics.median(ious),
        },
        "verdict": verdict,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(document, indent=2) + "\n")

    print(json.dumps({"summary": document["summary"], "verdict": verdict}, indent=2))
    for seed, row in rows.items():
        print(
            f"  seed {seed}: score {row['control']['score']:.4f} -> "
            f"{row['candidate']['score']:.4f} "
            f"({row['score_delta']:+.4f}), silhouette IoU {row['silhouette_iou']:.4f}"
        )
    if verdict == "fail":
        print(
            "the quality gate FAILED: "
            f"score delta {min(deltas):+.4f} (floor -{SCORE_FLOOR}), "
            f"silhouette IoU {min(ious):.4f} (floor {IOU_FLOOR})",
            file=sys.stderr,
        )
    return 0 if verdict == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
