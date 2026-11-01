"""The GGUF reader has to read the weights the way ggml wrote them.

The check is against the same model in another precision: the d1-2B
BF16 GGUF and the d1-2B Q8_0 GGUF are the same weights, so a correct
Q8_0 dequantisation must reproduce the BF16 weights to within the
quantisation error (a correlation of ~0.99999), and the tensors that are
F32 in both files must match exactly.

If the block layout or the scale were read wrong, the values would come
out uncorrelated — which is exactly what a wrong layout looks like.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from d1dec.gguf import GGUFFile  # noqa: E402

Q8 = "/home/caseydigennaro/models/d1-2B/d1-2B-Q8_0.gguf"
BF16 = "/home/caseydigennaro/models/d1-2B/d1-2B-BF16.gguf"

F32_TENSORS = [
    "blk.0.attn_norm.weight",
    "blk.0.shortconv.conv.weight",
    "output_norm.weight",
    "rope_freqs.weight",
]
Q8_TENSORS = [
    "blk.0.ffn_gate.weight",
    "blk.2.attn_q.weight",
    "blk.5.ffn_down.weight",
    "blk.12.attn_k.weight",
    "blk.2.attn_gate.weight",
]


def main() -> None:
    if not Path(BF16).exists():
        print(f"{BF16} is not on the box, skipping")
        return
    q = GGUFFile(Q8)
    b = GGUFFile(BF16)

    for n in F32_TENSORS:
        if n not in q.tensors or n not in b.tensors:
            continue
        a = q.get(n).astype(np.float32)
        c = b.get(n).astype(np.float32)
        assert a.shape == c.shape, (n, a.shape, c.shape)
        d = np.abs(a - c).max()
        print(f"  {n:32s} F32 in both, max|d| = {d:.2e}")
        assert d == 0.0, f"{n} differs between the two files"

    for n in Q8_TENSORS:
        if n not in q.tensors or n not in b.tensors:
            continue
        a = q.get(n).astype(np.float32)
        c = b.get(n).astype(np.float32)
        assert a.shape == c.shape, (n, a.shape, c.shape)
        corr = float(np.corrcoef(a.ravel(), c.ravel())[0, 1])
        rel = float((np.abs(a - c) / (np.abs(c) + 1e-6)).mean())
        print(f"  {n:32s} Q8_0 vs BF16, corr = {corr:.6f}, mean rel err = {rel:.5f}")
        assert corr > 0.999, f"{n} dequantised wrong (corr {corr})"
        assert rel < 0.05, f"{n} dequantised wrong (rel {rel})"

    # the metadata the engine reads
    assert q.meta["lfm3.block_count"] == 24
    assert q.meta["lfm3.embedding_length"] == 2048
    assert q.meta["lfm3.feed_forward_length"] == 7680
    assert q.meta["lfm3.shortconv.l_cache"] == 7
    assert len(q.meta["tokenizer.ggml.tokens"]) == 128000
    print("metadata OK")
    print("OK")


if __name__ == "__main__":
    main()
