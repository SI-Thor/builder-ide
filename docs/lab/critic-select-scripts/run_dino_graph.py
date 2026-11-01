#!/usr/bin/env python3
"""The DINOv2 candidate's forward pass, eager and graphed, on the set's own pictures.

    flock ~/lm-wt/heavy.lock .venv-torch/bin/python docs/lab/critic-select-scripts/run_dino_graph.py

The brief asks for the candidates' **per-verdict latency, graphed zero-copy where
it applies**. It applies to exactly one of them: the DINOv2 probe is the only
candidate whose verdict is a neural network forward pass, and the box already
has a measured CUDA Graph path for that forward (``docs/lab/exp-critic-cuda-graph.md``).

The bake-off's probe paid the plain forward pass once per picture and cached the
features on disk, so its **per-verdict** numbers (1–70 ms for the kNN head) are
already the cached path. What the graph changes is the cost of the **first** pass
over a picture — which is what a night meets when the set grows. This script
measures both, on the reference set's own 21 derived pictures, and writes the
numbers with the box's state beside them.

Two arms, the same input tensor:

* **eager** — the candidate's path exactly: PIL decode, the processor's
  normalisation, the host-to-device copy, the forward, the descriptor;
* **graph** — the same preprocessing, then the forward captured once in a
  ``torch.cuda.CUDAGraph`` with a static input buffer: the picture is written
  into the static buffer and one replay answers it.

The graph's descriptor must be **bit-identical** to the eager one on every
picture, or the arm is not measuring the same thing.
"""

from __future__ import annotations

import json
import os
import statistics
import sys
import time
from pathlib import Path

os.environ.setdefault("HF_HUB_OFFLINE", "1")

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT))

from boxstate import box_state, warm_gpu  # noqa: E402

RESULTS = HERE / "results"
MANIFEST = ROOT / "core" / "critic" / "reference-set.json"
CACHE = ROOT / "core" / "critic" / ".cache"
MODEL = "facebook/dinov2-large"


def _derived_images() -> list[tuple[str, Path]]:
    """The set's 21 image members' derived pictures, this worktree's cache first."""
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    members = manifest["members"] if isinstance(manifest, dict) else manifest
    out: list[tuple[str, Path]] = []
    for member in members:
        if member.get("layer") != "image":
            continue
        local = CACHE / f"{member['member_id']}.png"
        path = local if local.is_file() else Path(member.get("derived_path") or "")
        if path.is_file():
            out.append((member["member_id"], path))
    return out


def main() -> int:
    import argparse

    import numpy as np
    import torch
    from PIL import Image
    from transformers import AutoImageProcessor, AutoModel

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--no-warm",
        action="store_true",
        help="do not warm the GPU first: measures what a cold process pays",
    )
    parser.add_argument(
        "--out",
        default=str(RESULTS / "dino-graph.json"),
        help="where to write the result file",
    )
    args = parser.parse_args()
    no_warm = args.no_warm

    pictures = _derived_images()
    if not pictures:
        print("no derived pictures: the set's cache is gone")
        return 1
    print(f"pictures: {len(pictures)}")

    before = box_state()
    print(f"box before: {before.get('mem_mib', {})}")

    # The lab's rule: warm the GPU before timing anything. On this box the
    # idle clock is 315 MHz against a 1 575 MHz ceiling, a 2.6x error on a
    # forward pass. The clock goes beside the numbers.
    #
    # ``--no-warm`` turns that off, and that is the point of the flag: it
    # measures what a *cold* process pays, which is the number a fresh set
    # costs before anything is cached.
    warm = {"skipped": True}
    if not no_warm:
        warm = warm_gpu(seconds=2.0)
        print(f"warm-up: clock {warm.get('clock_before_mhz')} -> "
              f"{warm.get('clock_after_mhz')} MHz")

    processor = AutoImageProcessor.from_pretrained(MODEL)
    model = (
        AutoModel.from_pretrained(MODEL, dtype=torch.bfloat16).to("cuda").eval()
    )
    params = sum(p.numel() for p in model.parameters()) / 1e6
    print(f"model: {MODEL} bf16, {params:.0f} M params, device {model.device}")

    def prepare(path: Path) -> "torch.Tensor":
        """The candidate's front end: PIL → processor → device tensor."""
        image = Image.open(path).convert("RGB")
        inputs = processor(images=image, return_tensors="pt")
        return inputs["pixel_values"].to("cuda", dtype=torch.bfloat16)

    def forward(x: "torch.Tensor") -> "torch.Tensor":
        """The descriptor: the CLS token and the mean of the patch tokens."""
        hidden = model(pixel_values=x).last_hidden_state
        return torch.cat([hidden[:, 0], hidden[:, 1:].mean(dim=1)], dim=-1)[0]

    # -- the graph: the forward captured once, with a static input buffer ------
    sample = prepare(pictures[0][1])
    static_in = torch.zeros_like(sample)
    stream = torch.cuda.Stream()
    stream.wait_stream(torch.cuda.current_stream())
    with torch.cuda.stream(stream):
        with torch.no_grad():
            forward(static_in)
    torch.cuda.current_stream().wait_stream(stream)
    graph = torch.cuda.CUDAGraph()
    with torch.cuda.graph(graph):
        with torch.no_grad():
            static_out = forward(static_in)

    def graph_step(x: "torch.Tensor") -> "torch.Tensor":
        static_in.copy_(x)
        graph.replay()
        return static_out

    # -- the two arms --------------------------------------------------------
    rows = []
    for member_id, path in pictures:
        # eager: the whole path, the way the candidate pays it
        torch.cuda.synchronize()
        started = time.perf_counter()
        x = prepare(path)
        with torch.no_grad():
            eager_vec = forward(x)
        torch.cuda.synchronize()
        eager_total_ms = (time.perf_counter() - started) * 1000.0

        # eager, forward only (the model call inside the arm above)
        torch.cuda.synchronize()
        started = time.perf_counter()
        with torch.no_grad():
            forward(x)
        torch.cuda.synchronize()
        eager_forward_ms = (time.perf_counter() - started) * 1000.0

        # graphed: the same front end, then one replay
        torch.cuda.synchronize()
        started = time.perf_counter()
        gx = prepare(path)
        graph_vec = graph_step(gx)
        torch.cuda.synchronize()
        graph_total_ms = (time.perf_counter() - started) * 1000.0

        # the replay alone
        torch.cuda.synchronize()
        started = time.perf_counter()
        graph_step(gx)
        torch.cuda.synchronize()
        graph_replay_ms = (time.perf_counter() - started) * 1000.0

        eager_np = eager_vec.float().cpu().numpy()
        graph_np = graph_vec.float().cpu().numpy()
        exact = bool(np.array_equal(eager_np, graph_np))
        max_diff = float(np.abs(eager_np - graph_np).max())

        rows.append(
            {
                "member_id": member_id,
                "eager_total_ms": round(eager_total_ms, 3),
                "eager_forward_ms": round(eager_forward_ms, 3),
                "graph_total_ms": round(graph_total_ms, 3),
                "graph_replay_ms": round(graph_replay_ms, 3),
                "bit_exact": exact,
                "max_abs_diff": max_diff,
            }
        )
        print(
            f"  {member_id}  eager {eager_total_ms:8.1f} ms (forward {eager_forward_ms:7.1f})  "
            f"graph {graph_total_ms:7.1f} ms (replay {graph_replay_ms:6.1f})  exact={exact}"
        )

    after = box_state()

    def med(key: str) -> float:
        return statistics.median(r[key] for r in rows)

    payload = {
        "note": (
            "The DINOv2 candidate's forward path on the reference set's own "
            "pictures: the candidate's eager path against the same forward "
            "captured in a CUDA Graph with a static input buffer. The joules "
            "are the box's rails for the whole window — the seed sweep and "
            "other seats share this box — so they are context, not an "
            "attribution to the critic."
        ),
        "model": MODEL,
        "params_m": round(params, 1),
        "dtype": "bfloat16",
        "device": "cuda",
        "pictures": len(rows),
        "warm_up": warm,
        "box_before": before,
        "box_after": after,
        "median_eager_total_ms": round(med("eager_total_ms"), 1),
        "median_eager_forward_ms": round(med("eager_forward_ms"), 1),
        "median_graph_total_ms": round(med("graph_total_ms"), 1),
        "median_graph_replay_ms": round(med("graph_replay_ms"), 1),
        "all_bit_exact": all(r["bit_exact"] for r in rows),
        "rows": rows,
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    out = Path(args.out)
    out.write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8")
    print(
        f"\nmedian per picture: eager {payload['median_eager_total_ms']:.0f} ms "
        f"(forward {payload['median_eager_forward_ms']:.0f})  "
        f"graph {payload['median_graph_total_ms']:.0f} ms "
        f"(replay {payload['median_graph_replay_ms']:.1f})  "
        f"bit-exact: {payload['all_bit_exact']}"
    )
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
