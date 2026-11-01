"""The GGUF reader has to read the weights the way ggml wrote them.

The check is against **gguf-py**, the reference reader that ships with
llama.cpp (``gguf-py/gguf/gguf_reader.py``): every tensor of the d1-2B
Q8_0 file is compared with the reference, byte for byte for the
quantised ones and value for value for the others.

This is the test that catches the axis order. ggml stores a tensor with
its **first** dimension varying fastest, and the GGUF file keeps that
order on disk, while numpy's C order has the **last** dimension varying
fastest. gguf-py therefore reads the buffer with the dimensions reversed
and transposes it back. A reader that forgets the transpose does not
crash and does not look wrong: it reads every multi-dimensional tensor
in the wrong order, and the model still answers — confidently and
wrongly. The Q8_0 blocks then run along the wrong axis as well.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from d1dec.gguf import GGML_TYPE_Q8_0, GGUFFile  # noqa: E402

Q8 = "/home/caseydigennaro/models/d1-2B/d1-2B-Q8_0.gguf"
BF16 = "/home/caseydigennaro/models/d1-2B/d1-2B-BF16.gguf"


def _reference_reader():
    """gguf-py, from the llama.cpp checkout on this box."""
    for candidate in (
        Path.home() / "llama.cpp-upstream/gguf-py",
        Path("/home/caseydigennaro/llama.cpp-upstream/gguf-py"),
    ):
        if (candidate / "gguf" / "gguf_reader.py").is_file():
            sys.path.insert(0, str(candidate))
            break
    else:
        return None
    try:
        from gguf import GGUFReader  # noqa: PLC0415

        return GGUFReader
    except Exception:
        return None


def main() -> None:
    if not Path(Q8).exists():
        print(f"{Q8} is not on the box, skipping")
        return

    mine = GGUFFile(Q8)

    # -- the Q8_0 file, against gguf-py ------------------------------------
    GGUFReader = _reference_reader()
    if GGUFReader is None:
        print("gguf-py is not available, only the self-checks below run")
    else:
        ref = GGUFReader(Q8)
        assert len(ref.tensors) == len(mine.tensors), (len(ref.tensors), len(mine.tensors))
        n_quant = 0
        n_plain = 0
        for t in ref.tensors:
            name = t.name
            if name not in mine.tensors:
                continue
            if mine.tensors[name].dtype == GGML_TYPE_Q8_0:
                # gguf-py hands out the raw bytes of a quantised tensor
                a = t.data.view(np.uint8).reshape(-1)
                b = mine.raw(name)
                assert a.shape == b.shape, (name, a.shape, b.shape)
                assert np.array_equal(a, b), f"{name}: the quantised bytes differ"
                n_quant += 1
            else:
                # gguf-py reads the buffer with the dimensions reversed
                a = t.data
                b = mine.get(name)
                assert a.shape == b.T.shape, (name, a.shape, b.shape)
                assert np.array_equal(a.astype(np.float32), b.T.astype(np.float32)), (
                    f"{name}: the values differ"
                )
                n_plain += 1
        print(f"against gguf-py: {n_quant} quantised tensors byte-identical, "
              f"{n_plain} plain tensors value-identical")

    # -- the Q8_0 file against the BF16 file ------------------------------
    if Path(BF16).exists():
        b = GGUFFile(BF16)
        for name in ("blk.2.attn_q.weight", "blk.5.ffn_down.weight", "blk.12.attn_k.weight"):
            if name not in mine.tensors or name not in b.tensors:
                continue
            x = mine.get(name).astype(np.float32)
            y = b.get(name).astype(np.float32)
            assert x.shape == y.shape, (name, x.shape, y.shape)
            corr = float(np.corrcoef(x.ravel(), y.ravel())[0, 1])
            assert corr > 0.999, f"{name}: corr {corr}"
            print(f"  {name:28s} Q8_0 vs BF16, corr = {corr:.6f}")

    # -- the metadata the engine reads ------------------------------------
    assert mine.meta["lfm3.block_count"] == 24
    assert mine.meta["lfm3.embedding_length"] == 2048
    assert mine.meta["lfm3.feed_forward_length"] == 7680
    assert mine.meta["lfm3.shortconv.l_cache"] == 7
    assert mine.meta["lfm3.attention.layer_norm_rms_epsilon"] == 9.999999747378752e-06
    assert len(mine.meta["tokenizer.ggml.tokens"]) == 128000
    print("metadata OK")
    print("OK")


if __name__ == "__main__":
    main()
