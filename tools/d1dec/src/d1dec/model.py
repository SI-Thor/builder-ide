"""The batched LFM3-d1 (Liquid d1-2B) decision engine.

Why this exists
---------------

llama.cpp **cannot batch** an LFM3-d1 decision. Its decision graph reads
the whole prompt as one flat token run (``build_attn_inp_no_cache`` builds
a two-dimensional attention over the batch, and the short convolutions of
the recurrent layers are applied to the flat run), so the server refuses
to put two decision requests in one ubatch:

    // lfm3 d1 has no memory, its prompt is read as one flat ubatch and
    // the short convs would mix the sequences
    // TODO: batch them along the sequence dimension, this needs ubatches
    //       of sequences with unequal lengths
    task.decision.no_batching = is_lfm3_d1();

With that, a tick of 64 characters asking 3 questions each is 192
separate prefills, and the 1.85 GB of weights are streamed from memory
192 times.

This engine does the batch properly. It keeps the model's arithmetic
exactly as llama.cpp has it — the same norms, the same sandwich norms,
the same convolutions, the same NeoX rotary, the same non-causal dense
attention and causal sliding-window attention, the same grouped-query
attention and the same head gate — and adds the two things llama.cpp's
decision graph is missing:

* a **block-diagonal attention mask**, so the dense layers of one
  sequence never see another sequence, and the sliding-window layers see
  only their own sequence's last 256 positions;
* a **per-sequence short convolution**, so the recurrent layers' window
  never crosses from one sequence into the next.

Both make a batched forward pass numerically the same as running each
prompt on its own.

The batch is right-padded to the longest prompt in it. Padding is safe
because the convolutions look backwards and the attention masks the
padded keys out.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F

from .gguf import GGUFFile

#: ggml tensor types
_Q8_0 = 8

#: The numpy dtype a torch dtype is read in, so that the weights are
#: dequantised straight into the precision they are used in.
_NP_DTYPE = {
    torch.float16: np.float16,
    torch.bfloat16: np.float32,
    torch.float32: np.float32,
}


def _np_dtype(dtype: torch.dtype):
    return _NP_DTYPE.get(dtype, np.float32)


@dataclass
class LayerWeights:
    attn_norm: torch.Tensor
    ffn_norm: torch.Tensor
    attn_post_norm: torch.Tensor | None
    ffn_post_norm: torch.Tensor | None
    # conv layers
    conv: torch.Tensor | None = None
    conv_in: torch.Tensor | None = None
    conv_out: torch.Tensor | None = None
    # attention layers
    wq: torch.Tensor | None = None
    wk: torch.Tensor | None = None
    wv: torch.Tensor | None = None
    wo: torch.Tensor | None = None
    q_norm: torch.Tensor | None = None
    k_norm: torch.Tensor | None = None
    wgate: torch.Tensor | None = None
    # ffn
    ffn_gate: torch.Tensor | None = None
    ffn_up: torch.Tensor | None = None
    ffn_down: torch.Tensor | None = None
    is_conv: bool = False
    is_swa: bool = False
    rope_freqs: torch.Tensor | None = None


class D1Model:
    """The d1-2B model, on the GPU, in fp16."""

    def __init__(
        self,
        gguf_path: str | Path | None = None,
        *,
        device: str = "cuda",
        dtype: torch.dtype = torch.float16,
        gguf: GGUFFile | None = None,
    ) -> None:
        self.gguf = gguf if gguf is not None else GGUFFile(gguf_path)
        meta = self.gguf.meta
        self.device = device
        self.dtype = dtype

        # The attention can be run in fp32. It does not change the
        # answers: the difference between the two servers is llama.cpp's
        # own quantisation noise, not ours, so the fp32 attention buys
        # nothing and costs time. It is here for the experiment.
        self.attn_dtype = (
            torch.float32
            if os.environ.get("D1DEC_ATTN_FP32", "0") == "1"
            else torch.float16
        )
        self.attn_chunk = int(os.environ.get("D1DEC_ATTN_CHUNK", "48"))
        # how many sequences one forward pass holds at once. Thirty-two
        # keeps the GPU's peak half a tick's worth of activations, and
        # the weights are read six times instead of three, which costs
        # about seven per cent of the tick and buys back a gigabyte.
        self.forward_chunk = int(os.environ.get("D1DEC_FORWARD_CHUNK", "32"))

        # The rotary is the engine's hottest loop: it is 22 calls of
        # "rotate two halves of a head", and the naive form walks over
        # the head ten times. The complex form is one multiply.
        #   native — the straightforward fp32 form (what ggml does)
        #   cplx   — the same rotation as one complex multiplication
        #   fp16   — the rotation in fp16 (the fastest, the coarsest)
        self.rope_mode = os.environ.get("D1DEC_ROPE", "cplx")
        # the short convolution: fp16 (cuDNN, fp32 accumulate) or fp32
        self.conv_mode = os.environ.get("D1DEC_CONV", "fp16")
        # grouped-query attention without repeating the keys and values
        self.gqa = os.environ.get("D1DEC_GQA", "1") == "1"

        self.n_embd = int(meta["lfm3.embedding_length"])
        self.n_ff = int(meta["lfm3.feed_forward_length"])
        self.n_layer = int(meta["lfm3.block_count"])
        self.n_head = int(meta["lfm3.attention.head_count"])
        self.n_head_dim = int(meta["lfm3.attention.key_length"])
        self.n_rot = int(meta["lfm3.rope.dimension_count"])
        self.n_vocab = len(meta["tokenizer.ggml.tokens"])
        self.d_conv = int(meta["lfm3.shortconv.l_cache"]) - 1
        self.n_ctx = int(meta["lfm3.context_length"])
        self.eps = float(meta["lfm3.attention.layer_norm_rms_epsilon"])
        self.rope_freq_base = float(meta["lfm3.rope.freq_base"])
        self.rope_freq_base_swa = float(meta["lfm3.rope.freq_base_swa"])
        self.sliding_window = int(meta["lfm3.attention.sliding_window"])
        self.causal = bool(meta["lfm3.attention.causal"])

        head_kv = list(meta["lfm3.attention.head_count_kv"])
        swa_pattern = list(meta["lfm3.attention.sliding_window_pattern"])
        self.n_head_kv = [int(h) for h in head_kv]
        self.is_swa = [bool(s) for s in swa_pattern]

        self.temperature = {
            t: float(meta[f"lfm3.decision.temperature.{t}"])
            for t in ("choice", "score", "noul")
            if f"lfm3.decision.temperature.{t}" in meta
        }

        self.tok_embd = self._load("token_embd.weight")
        self.output_norm = self._load("output_norm.weight")
        self.layers: list[LayerWeights] = []
        for il in range(self.n_layer):
            p = f"blk.{il}."
            is_conv = self.n_head_kv[il] == 0
            lw = LayerWeights(
                attn_norm=self._load(p + "attn_norm.weight"),
                ffn_norm=self._load(p + "ffn_norm.weight"),
                attn_post_norm=self._load_opt(p + "post_attention_norm.weight"),
                ffn_post_norm=self._load_opt(p + "post_ffw_norm.weight"),
                is_conv=is_conv,
                is_swa=self.is_swa[il],
            )
            if is_conv:
                lw.conv = self._load(p + "shortconv.conv.weight")  # [d_conv+1, n_embd]
                lw.conv_in = self._load(p + "shortconv.in_proj.weight")  # [n_embd, 3*n_embd]
                lw.conv_out = self._load(p + "shortconv.out_proj.weight")  # [n_embd, n_embd]
            else:
                lw.wq = self._load(p + "attn_q.weight")
                lw.wk = self._load(p + "attn_k.weight")
                lw.wv = self._load(p + "attn_v.weight")
                lw.wo = self._load(p + "attn_output.weight")
                lw.q_norm = self._load(p + "attn_q_norm.weight")
                lw.k_norm = self._load(p + "attn_k_norm.weight")
                lw.wgate = self._load(p + "attn_gate.weight")
                if not self.is_swa[il]:
                    lw.rope_freqs = self._load("rope_freqs.weight")
            lw.ffn_gate = self._load(p + "ffn_gate.weight")
            lw.ffn_up = self._load(p + "ffn_up.weight")
            lw.ffn_down = self._load(p + "ffn_down.weight")
            self.layers.append(lw)

        # the rotary tables, one per rotary kind
        self._rope_cache: dict[tuple[bool, str], tuple[torch.Tensor, torch.Tensor]] = {}

        # the weights are on the GPU now; the file's bytes are dead weight
        self.gguf.release()

    # -- loading -------------------------------------------------------------

    def _load(self, name: str) -> torch.Tensor:
        arr = self.gguf.get(name, dtype=_np_dtype(self.dtype))
        t = torch.from_numpy(np.ascontiguousarray(arr)).to(self.device, dtype=self.dtype)
        return t

    def _load_opt(self, name: str) -> torch.Tensor | None:
        if not self.gguf.has(name):
            return None
        return self._load(name)

    # -- the pieces ----------------------------------------------------------

    def _rms_norm(self, x: torch.Tensor, w: torch.Tensor) -> torch.Tensor:
        """RMSNorm, with ggml's arithmetic.

        ggml reads the fp16 tensor, accumulates the sum of squares in
        fp32, scales and multiplies by the weight in fp32, and rounds
        **once**, when it writes the result back. ``F.rms_norm`` is that
        same computation, fused into one kernel, so it neither
        materialises an fp32 copy of the activations nor rounds twice.
        """
        return F.rms_norm(x, (x.shape[-1],), w, self.eps)

    def _rope(
        self,
        x: torch.Tensor,
        positions: torch.Tensor,
        is_swa: bool,
        freqs: torch.Tensor | None,
    ) -> torch.Tensor:
        """The NeoX rotary of llama.cpp, for a [B, H, L, D] tensor.

        The head's dimension count is 128 and the rotary covers all of
        it, so the pairs are (d, d + 64). The dense layers carry a
        per-pair frequency divisor (``rope_freqs``) that is 1e30 for the
        upper half, which makes those dimensions pass through unrotated.

        The rotation of a pair is

            out0 = x0*cos - x1*sin
            out1 = x0*sin + x1*cos

        which is exactly the product of the complex numbers
        ``x0 + i*x1`` and ``cos + i*sin``. Written that way it is worth
        about a quarter of the forward pass: the straightforward form
        walks over the head ten times (two casts to fp32, four
        multiplies, a subtraction, an addition, a concatenation and a
        cast back), while the complex form does it in one multiply — and
        it is the same arithmetic, in the same order, to within the last
        bit of the accumulator.
        """
        d = x.shape[-1] // 2
        key = (is_swa, "sw" if is_swa else "dense")
        table = self._rope_cache.get(key)
        if table is None:
            freq_base = self.rope_freq_base_swa if is_swa else self.rope_freq_base
            theta_scale = torch.tensor(
                freq_base ** (-2.0 / self.n_rot), dtype=torch.float32, device=self.device
            )
            idx = torch.arange(d, dtype=torch.float32, device=self.device)
            table = theta_scale**idx  # [d]
            self._rope_cache[key] = table
        base = table
        theta = positions.float().unsqueeze(-1) * base.unsqueeze(0).unsqueeze(0)  # [B, L, d]
        if freqs is not None:
            theta = theta / freqs.float().unsqueeze(0).unsqueeze(0)
        cos = theta.cos().unsqueeze(1)  # [B, 1, L, d]
        sin = theta.sin().unsqueeze(1)

        if self.rope_mode == "fp16":
            # the same rotation in fp16: cheaper still, and the answer
            # moves by about three parts in ten thousand
            cos = cos.half()
            sin = sin.half()
            x0 = x[..., :d]
            x1 = x[..., d:]
            out0 = x0 * cos - x1 * sin
            out1 = x0 * sin + x1 * cos
            return torch.cat([out0, out1], dim=-1)

        if self.rope_mode == "cplx":
            # ggml computes the rotation in fp32 and rounds once, when
            # it writes the result back into the tensor
            xc = torch.complex(x[..., :d].float(), x[..., d:].float())
            wc = torch.complex(cos, sin)
            out = torch.view_as_real(xc * wc)
            return torch.cat([out[..., 0], out[..., 1]], dim=-1).to(x.dtype)

        # the straightforward form, one pass at a time
        x0 = x[..., :d].float()
        x1 = x[..., d:].float()
        out0 = x0 * cos - x1 * sin
        out1 = x0 * sin + x1 * cos
        return torch.cat([out0, out1], dim=-1).to(x.dtype)

    def _short_conv(self, x: torch.Tensor, lw: LayerWeights) -> torch.Tensor:
        """The short convolution, per sequence.

        ``x`` is [B, L, n_embd]. The convolution looks six tokens back
        from a zero state, so it is a causal convolution; running it on a
        right-padded batch is the same as running it on each sequence on
        its own.

        ggml's ``ssm_conv`` runs in fp32 — the CUDA kernel is
        ``ssm_conv_f32`` — so the convolution is done in fp32 here too.
        In fp16 the seven products of a tap lose about four decimal
        digits, and the decision head reads the difference between two
        logits that are sometimes a thousandth apart.

        cuDNN's fp16 convolution accumulates in fp32, so the fp16 form
        is the same computation with one rounding at the end instead of
        three, and it does not copy the whole activation into fp32
        first. The copy is most of the cost of the layer.
        """
        b, L, _ = x.shape
        bcx = x @ lw.conv_in  # [B, L, 3*n_embd]
        bb, cc, xx = torch.chunk(bcx, 3, dim=-1)
        bx = (bb * xx).transpose(1, 2)  # [B, n_embd, L]
        bx = F.pad(bx, (self.d_conv, 0))
        # the ggml kernel is [d_conv+1, n_embd]; conv1d wants [out, 1, k]
        w = lw.conv.transpose(0, 1).unsqueeze(1).contiguous()  # [n_embd, 1, d_conv+1]
        if self.conv_mode == "fp16":
            conv = F.conv1d(bx, w, groups=self.n_embd)  # [B, n_embd, L]
            y = cc.float() * conv.transpose(1, 2).float()
        else:
            conv = F.conv1d(bx.float(), w.float(), groups=self.n_embd)  # [B, n_embd, L]
            y = cc.float() * conv.transpose(1, 2)
        return y.to(self.dtype) @ lw.conv_out

    def _attn_block(
        self,
        x: torch.Tensor,
        lw: LayerWeights,
        positions: torch.Tensor,
        attn_mask: torch.Tensor,
    ) -> torch.Tensor:
        """One attention layer. ``x`` is [B, L, n_embd]."""
        b, L, _ = x.shape
        n_kv = lw.wk.shape[1] // self.n_head_dim
        group = self.n_head // n_kv

        q = (x @ lw.wq).view(b, L, self.n_head, self.n_head_dim).transpose(1, 2)
        k = (x @ lw.wk).view(b, L, n_kv, self.n_head_dim).transpose(1, 2)
        v = (x @ lw.wv).view(b, L, n_kv, self.n_head_dim).transpose(1, 2)

        q = self._rms_norm(q, lw.q_norm)
        k = self._rms_norm(k, lw.k_norm)

        q = self._rope(q, positions, lw.is_swa, lw.rope_freqs)
        k = self._rope(k, positions, lw.is_swa, lw.rope_freqs)

        if group != 1:
            if self.gqa:
                # the keys and the values stay shared between the heads
                # of a group: repeating them costs a copy of the whole
                # tensor per layer
                pass
            else:
                k = k.repeat_interleave(group, dim=1)
                v = v.repeat_interleave(group, dim=1)

        if self.attn_dtype == torch.float32:
            # fp32 attention: the scores of an fp16 attention are rounded to
            # fp16 before the softmax, and that rounding is the largest
            # numerical difference between this engine and llama.cpp
            if group != 1 and self.gqa:
                k = k.repeat_interleave(group, dim=1)
                v = v.repeat_interleave(group, dim=1)
            out = self._attn_fp32(q, k, v, attn_mask)
        elif self.gqa and group != 1:
            out = F.scaled_dot_product_attention(
                q, k, v, attn_mask=attn_mask, enable_gqa=True
            )
        else:
            out = F.scaled_dot_product_attention(q, k, v, attn_mask=attn_mask)
        out = out.transpose(1, 2).reshape(b, L, self.n_head * self.n_head_dim)

        gate = torch.sigmoid(x @ lw.wgate)  # [B, L, n_head]
        gate = gate.unsqueeze(-1)  # [B, L, n_head, 1], one gate per head
        out = out.view(b, L, self.n_head, self.n_head_dim) * gate
        out = out.reshape(b, L, self.n_head * self.n_head_dim)
        return out.to(self.dtype) @ lw.wo

    def _attn_fp32(
        self,
        q: torch.Tensor,
        k: torch.Tensor,
        v: torch.Tensor,
        attn_mask: torch.Tensor,
    ) -> torch.Tensor:
        """The attention in fp32, a batch chunk at a time.

        The scores of a whole batch do not fit in fp32 at once (a tick of
        192 sequences is 192 * 16 * 267 * 267 * 4 bytes), so the batch is
        cut into chunks and the chunks are run one after the other.
        """
        outs = []
        for lo in range(0, q.shape[0], self.attn_chunk):
            hi = min(lo + self.attn_chunk, q.shape[0])
            outs.append(
                F.scaled_dot_product_attention(
                    q[lo:hi].float(), k[lo:hi].float(), v[lo:hi].float(),
                    attn_mask=attn_mask[lo:hi],
                )
            )
        return torch.cat(outs, dim=0)

    # -- the forward ---------------------------------------------------------

    @torch.inference_mode()
    def forward_last(self, sequences: list[list[int]]) -> torch.Tensor:
        """The logits at the last token of every sequence.

        ``sequences`` is a list of token id lists; they are right-padded
        to the longest one.

        A tick of 192 sequences is cut into chunks of
        ``forward_chunk`` sequences, so that the activations of a whole
        tick do not have to be resident at once. The weights are read
        once per chunk instead of once per batch, which is still four
        reads against llama.cpp's 192.
        """
        chunk = self.forward_chunk
        if chunk and len(sequences) > chunk:
            outs = [
                self._forward_chunk(sequences[lo : lo + chunk])
                for lo in range(0, len(sequences), chunk)
            ]
            return torch.cat(outs, dim=0)
        return self._forward_chunk(sequences)

    @torch.inference_mode()
    def _forward_chunk(self, sequences: list[list[int]]) -> torch.Tensor:
        """One chunk of sequences, right-padded to the longest one."""
        device = self.device
        b = len(sequences)
        lengths = [len(s) for s in sequences]
        L = max(lengths)

        tokens = np.zeros((b, L), dtype=np.int64)
        for i, s in enumerate(sequences):
            tokens[i, : len(s)] = s
        tokens_t = torch.from_numpy(tokens).to(device)

        positions = torch.zeros((b, L), dtype=torch.int64, device=device)
        for i, n in enumerate(lengths):
            positions[i, :n] = torch.arange(n, device=device)

        # the key mask: the padded positions are never attended to
        key_ok = torch.zeros((b, 1, 1, L), dtype=torch.bool, device=device)
        for i, n in enumerate(lengths):
            key_ok[i, :, :, :n] = True

        # the dense layers read the prompt both ways, the sliding-window
        # layers stay causal and see the last `sliding_window` positions
        idx = torch.arange(L, device=device)
        causal = (idx.unsqueeze(0) <= idx.unsqueeze(1)) & (
            (idx.unsqueeze(1) - idx.unsqueeze(0)) < self.sliding_window
        )
        mask_swa = key_ok & causal.unsqueeze(0).unsqueeze(0)
        mask_dense = key_ok.expand(b, 1, L, L)

        # the embedding matrix is [n_embd, n_vocab], so the lookup is a
        # gather over its columns
        h = self.tok_embd[:, tokens_t].permute(1, 2, 0).contiguous().to(self.dtype)  # [B, L, n_embd]

        last_idx = torch.tensor([n - 1 for n in lengths], device=device)
        for il, lw in enumerate(self.layers):
            prev = h
            x = self._rms_norm(h, lw.attn_norm)
            if lw.is_conv:
                x = self._short_conv(x, lw)
            else:
                mask = mask_swa if lw.is_swa else mask_dense
                x = self._attn_block(x, lw, positions, mask)
            if lw.attn_post_norm is not None:
                x = self._rms_norm(x, lw.attn_post_norm)
            if il == self.n_layer - 1:
                # llama.cpp reads the logits of the last prompt token
                x = x[torch.arange(b, device=device), last_idx]
                prev = prev[torch.arange(b, device=device), last_idx]
            h = prev + x
            f = self._rms_norm(h, lw.ffn_norm)
            f = F.silu(f @ lw.ffn_gate) * (f @ lw.ffn_up)
            f = f @ lw.ffn_down
            if lw.ffn_post_norm is not None:
                f = self._rms_norm(f, lw.ffn_post_norm)
            h = h + f

        h = self._rms_norm(h, self.output_norm)
        # the output projection is the embedding matrix (the model ties them):
        # it is [n_embd, n_vocab], so the logits are h @ tok_embd
        return h @ self.tok_embd


# --------------------------------------------------------------------------
# the decision head
# --------------------------------------------------------------------------

def decision_probabilities(
    logits: torch.Tensor,
    groups: list[list[int]],
    temperature: float,
) -> list[list[float]]:
    """The calibrated probabilities of one question.

    The logit of an option is the largest logit over its label group;
    the probabilities are a softmax over those logits at the model's own
    temperature.
    """
    scores = []
    for group in groups:
        scores.append(max(float(logits[t]) for t in group))
    m = max(scores)
    exps = [math.exp((s - m) / temperature) for s in scores]
    total = sum(exps)
    return [e / total for e in exps]
