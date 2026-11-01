"""The batched engine must give the same answer as one sequence at a time.

This is the claim the whole design rests on: a batch is only worth
having if it is *exact*. The test builds a small LFM3-d1 shaped model
with random weights, runs a reference forward pass in numpy (one
sequence at a time, written straight from llama.cpp's graph), and
compares it with the batched engine on

* a batch of several sequences of different lengths, and
* the same sequences run one at a time.

The two must agree to float32 noise, and the batch must agree with the
per-sequence runs.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from d1dec.model import D1Model  # noqa: E402

torch.manual_seed(0)
rng = np.random.default_rng(0)

N_EMBD = 64
N_FF = 128
N_LAYER = 6
N_HEAD = 4
N_HEAD_DIM = 16
N_HEAD_KV = 2
D_CONV = 4
N_VOCAB = 71
EPS = 1e-5
WINDOW = 3
FREQ_BASE = 10000.0
FREQ_BASE_SWA = 1000.0
ROPE_FREQS = np.concatenate(
    [
        np.ones(N_HEAD_DIM // 4, dtype=np.float32),
        np.full(N_HEAD_DIM // 4, 1e30, dtype=np.float32),
    ]
)

# layer kinds: conv, dense attention, sliding-window attention
LAYER_KINDS = ["conv", "attn_dense", "attn_swa", "conv", "attn_swa", "attn_dense"]


def _norm(rng: np.random.Generator, n: int) -> np.ndarray:
    return (rng.standard_normal(n).astype(np.float32) * 0.2 + 1.0).astype(np.float32)


def build_random_model() -> D1Model:
    """A D1Model with random weights, small enough for a CPU test."""
    m = D1Model.__new__(D1Model)
    m.device = "cpu"
    m.dtype = torch.float32
    m.n_embd = N_EMBD
    m.n_ff = N_FF
    m.n_layer = N_LAYER
    m.n_head = N_HEAD
    m.n_head_dim = N_HEAD_DIM
    m.n_rot = N_HEAD_DIM
    m.n_vocab = N_VOCAB
    m.d_conv = D_CONV
    m.n_ctx = 4096
    m.eps = EPS
    m.rope_freq_base = FREQ_BASE
    m.rope_freq_base_swa = FREQ_BASE_SWA
    m.sliding_window = WINDOW
    m.causal = False
    m.n_head_kv = [0 if k == "conv" else N_HEAD_KV for k in LAYER_KINDS]
    m.is_swa = [k == "attn_swa" for k in LAYER_KINDS]
    m.temperature = {"choice": 1.0, "score": 1.0, "noul": 1.0}
    m.attn_dtype = torch.float32
    m.attn_chunk = 8
    m.forward_chunk = 0
    m.rope_mode = "native"
    m.conv_mode = "native"
    m.gqa = False
    m._rope_cache = {}

    def t(a: np.ndarray) -> torch.Tensor:
        return torch.from_numpy(np.ascontiguousarray(a)).float()

    m.tok_embd = t(rng.standard_normal((N_EMBD, N_VOCAB)).astype(np.float32) * 0.1)
    m.output_norm = t(_norm(rng, N_EMBD))

    from d1dec.model import LayerWeights

    layers = []
    for il, kind in enumerate(LAYER_KINDS):
        lw = LayerWeights(
            attn_norm=t(_norm(rng, N_EMBD)),
            ffn_norm=t(_norm(rng, N_EMBD)),
            attn_post_norm=t(_norm(rng, N_EMBD)),
            ffn_post_norm=t(_norm(rng, N_EMBD)),
            is_conv=kind == "conv",
            is_swa=kind == "attn_swa",
        )
        lw.ffn_gate = t(rng.standard_normal((N_EMBD, N_FF)).astype(np.float32) * 0.05)
        lw.ffn_up = t(rng.standard_normal((N_EMBD, N_FF)).astype(np.float32) * 0.05)
        lw.ffn_down = t(rng.standard_normal((N_FF, N_EMBD)).astype(np.float32) * 0.05)
        if kind == "conv":
            lw.conv = t(rng.standard_normal((D_CONV + 1, N_EMBD)).astype(np.float32) * 0.1)
            lw.conv_in = t(rng.standard_normal((N_EMBD, 3 * N_EMBD)).astype(np.float32) * 0.05)
            lw.conv_out = t(rng.standard_normal((N_EMBD, N_EMBD)).astype(np.float32) * 0.05)
        else:
            lw.wq = t(rng.standard_normal((N_EMBD, N_HEAD * N_HEAD_DIM)).astype(np.float32) * 0.05)
            lw.wk = t(rng.standard_normal((N_EMBD, N_HEAD_KV * N_HEAD_DIM)).astype(np.float32) * 0.05)
            lw.wv = t(rng.standard_normal((N_EMBD, N_HEAD_KV * N_HEAD_DIM)).astype(np.float32) * 0.05)
            lw.wo = t(rng.standard_normal((N_HEAD * N_HEAD_DIM, N_EMBD)).astype(np.float32) * 0.05)
            lw.q_norm = t(_norm(rng, N_HEAD_DIM))
            lw.k_norm = t(_norm(rng, N_HEAD_DIM))
            lw.wgate = t(rng.standard_normal((N_EMBD, N_HEAD)).astype(np.float32) * 0.05)
            if kind == "attn_dense":
                lw.rope_freqs = t(ROPE_FREQS)
        layers.append(lw)
    m.layers = layers
    return m


# --------------------------------------------------------------------------
# the reference, in numpy, one sequence at a time
# --------------------------------------------------------------------------

def rms_norm(x: np.ndarray, w: np.ndarray, eps: float = EPS) -> np.ndarray:
    xf = x.astype(np.float64)
    scale = 1.0 / np.sqrt((xf * xf).mean(-1, keepdims=True) + eps)
    return (xf * scale * w.astype(np.float64)).astype(np.float32)


def short_conv(x: np.ndarray, lw, d_conv: int) -> np.ndarray:
    """x is [L, n_embd]; the convolution looks d_conv tokens back."""
    bcx = x @ lw.conv_in.numpy()  # [L, 3*n_embd]
    b, c, xx = np.split(bcx, 3, axis=-1)
    v = b * xx  # [L, n_embd]
    out = np.zeros_like(v)
    for t in range(v.shape[0]):
        acc = np.zeros(v.shape[1], dtype=np.float64)
        for k in range(d_conv + 1):
            j = t + k - d_conv
            if 0 <= j < v.shape[0]:
                acc += lw.conv.numpy()[k].astype(np.float64) * v[j].astype(np.float64)
        out[t] = acc
    return (c * out).astype(np.float32) @ lw.conv_out.numpy()


def rope_neox(x: np.ndarray, pos: int, freq_base: float, freqs: np.ndarray | None) -> np.ndarray:
    """x is [n_head, n_head_dim]."""
    d = x.shape[-1] // 2
    theta_scale = freq_base ** (-2.0 / x.shape[-1])
    theta = pos * (theta_scale ** np.arange(d, dtype=np.float64))
    if freqs is not None:
        theta = theta / freqs.astype(np.float64)
    cos = np.cos(theta).astype(np.float32)
    sin = np.sin(theta).astype(np.float32)
    x0 = x[..., :d].astype(np.float64)
    x1 = x[..., d:].astype(np.float64)
    out = np.concatenate([x0 * cos - x1 * sin, x0 * sin + x1 * cos], axis=-1)
    return out.astype(np.float32)


def attention(q: np.ndarray, k: np.ndarray, v: np.ndarray, swa: bool) -> np.ndarray:
    """q is [L, H, D], k/v are [L, H_kv, D].

    The dense layers of a d1 read the prompt both ways, so they attend
    to every position; the sliding-window layers stay causal and see the
    last WINDOW positions.
    """
    L, H, D = q.shape
    H_kv = k.shape[1]
    group = H // H_kv
    kk = np.repeat(k, group, axis=1)
    vv = np.repeat(v, group, axis=1)
    out = np.zeros((L, H, D), dtype=np.float32)
    scale = 1.0 / np.sqrt(D)
    for h in range(H):
        for t in range(L):
            if swa:
                lo, hi = max(0, t - WINDOW + 1), t
            else:
                lo, hi = 0, L - 1
            s = (kk[lo : hi + 1, h].astype(np.float64) @ q[t, h].astype(np.float64)) * scale
            e = np.exp(s - s.max())
            p = e / e.sum()
            out[t, h] = (p[:, None] * vv[lo : hi + 1, h].astype(np.float64)).sum(0)
    return out.astype(np.float32)


def reference_forward(model: D1Model, tokens: list[int]) -> np.ndarray:
    """The logits at the last token, one sequence at a time."""
    L = len(tokens)
    h = model.tok_embd.numpy()[:, np.asarray(tokens)].T.astype(np.float32)  # [L, n_embd]
    for il, lw in enumerate(model.layers):
        prev = h
        x = rms_norm(h, lw.attn_norm.numpy())
        if lw.is_conv:
            x = short_conv(x, lw, model.d_conv)
        else:
            q = (x @ lw.wq.numpy()).reshape(L, model.n_head, model.n_head_dim)
            k = (x @ lw.wk.numpy()).reshape(L, model.n_head_kv[il], model.n_head_dim)
            v = (x @ lw.wv.numpy()).reshape(L, model.n_head_kv[il], model.n_head_dim)
            q = rms_norm(q, lw.q_norm.numpy())
            k = rms_norm(k, lw.k_norm.numpy())
            fb = model.rope_freq_base_swa if lw.is_swa else model.rope_freq_base
            fr = None if lw.is_swa else lw.rope_freqs.numpy()
            for t in range(L):
                q[t] = rope_neox(q[t], t, fb, fr)
                k[t] = rope_neox(k[t], t, fb, fr)
            o = attention(q, k, v, lw.is_swa)
            o = o.reshape(L, model.n_head * model.n_head_dim)
            gate = 1.0 / (1.0 + np.exp(-(x @ lw.wgate.numpy())))
            o = o.reshape(L, model.n_head, model.n_head_dim) * gate[:, :, None]
            o = o.reshape(L, model.n_head * model.n_head_dim)
            x = o @ lw.wo.numpy()
        x = rms_norm(x, lw.attn_post_norm.numpy())
        h = (prev + x).astype(np.float32)
        f = rms_norm(h, lw.ffn_norm.numpy())
        gate = (f @ lw.ffn_gate.numpy()).astype(np.float32)
        up = (f @ lw.ffn_up.numpy()).astype(np.float32)
        f = (gate / (1.0 + np.exp(-gate)) * up).astype(np.float32)
        f = f @ lw.ffn_down.numpy()
        f = rms_norm(f, lw.ffn_post_norm.numpy())
        h = (h + f).astype(np.float32)
    h = rms_norm(h, model.output_norm.numpy())
    return (h[-1:] @ model.tok_embd.numpy())[0]


def main() -> None:
    model = build_random_model()
    seqs = [
        [1, 5, 9, 13, 17, 21, 25, 29],
        [2, 6, 10, 14, 18, 22, 26],
        [3, 7, 11, 15, 19, 23, 27, 31, 35, 39],
        [4, 8, 12],
    ]

    # the reference
    refs = [reference_forward(model, s) for s in seqs]

    # every form of the engine has to be exact: the rotary can be
    # written as a complex product or in fp16, and the convolution can
    # run in fp16, but a batch still has to be the same as one
    # sequence at a time
    for rope_mode, conv_mode, gqa in (
        ("native", "native", False),
        ("cplx", "native", False),
        ("cplx", "fp16", True),
        ("fp16", "native", True),
    ):
        model.rope_mode = rope_mode
        model.conv_mode = conv_mode
        model.gqa = gqa
        print(f"\n=== the engine as {rope_mode} rope, {conv_mode} conv, "
              f"{'gqa' if gqa else 'repeated kv'} ===")

        # the batched engine
        with torch.inference_mode():
            batched = model.forward_last(seqs).numpy()
            singles = np.stack([model.forward_last([s]).numpy()[0] for s in seqs])

        def report(name: str, a: np.ndarray, b: np.ndarray) -> float:
            d = np.abs(a - b)
            rel = d / (np.abs(b) + 1e-6)
            print(
                f"  {name}: max|dlogit|={d.max():.3e}  max|rel|={rel.max():.3e}  "
                f"corr={np.corrcoef(a.ravel(), b.ravel())[0, 1]:.8f}"
            )
            return d.max()

        print("batched engine vs numpy reference:")
        worst = 0.0
        for i in range(len(seqs)):
            worst = max(worst, report(f"seq{i}", batched[i], refs[i]))
        print("batched engine vs the same engine, one sequence at a time:")
        worst2 = 0.0
        for i in range(len(seqs)):
            worst2 = max(worst2, report(f"seq{i}", batched[i], singles[i]))

        # the ranking of the label tokens has to survive, that is what the
        # agreement bar is about
        print("argmax agreement:")
        ok = 0
        for i in range(len(seqs)):
            if int(np.argmax(batched[i])) == int(np.argmax(refs[i])):
                ok += 1
        print(f"  {ok}/{len(seqs)}")

        assert worst < 2e-3, f"the batch disagrees with the reference by {worst}"
        assert worst2 < 1e-4, f"the batch disagrees with the single runs by {worst2}"
        assert ok == len(seqs), "the argmax moved"

    print("\nOK")


if __name__ == "__main__":
    main()
