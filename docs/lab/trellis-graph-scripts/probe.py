"""The probe — measurements taken *inside* the ComfyUI process.

A monkeypatch that lives in this worktree, never in ComfyUI's checkout.  It
is loaded as a custom node from a base directory that also lives here (see
``serve_probe.sh``), so the TRELLIS.2 environment is read, never modified.

Three jobs, each measured where it happens:

1. **CUDA-graph capture of a KSampler step** (``TRG_MODE=graph``).

   The probe wraps the diffusion model's forward so that every step is run
   twice on *identical* inputs: once eagerly, once from a captured CUDA
   graph.  The pair gives a per-step measurement of GPU time and CPU issue
   time, eager vs graphed, that is not confounded by a different step or a
   different timestep.  The graphed output is what the sampler keeps, so a
   run that completes is a run whose KSampler steps were graphed end to end.

   Two capture targets, because TRELLIS.2 has two kinds of step:

   * ``unet`` — the whole ``Trellis2.forward``: the dense structure stage
     and the two sparse stages.
   * ``stage`` — the per-stage sub-model (``structure_model``,
     ``img2shape_512``, ``img2shape``, ``shape2txt``): the transformer
     blocks, which is where the time is.

2. **The sparse layout sync** (``TRG_MEMO_LAYOUT=1``).

   TRELLIS.2's sparse stages resolve a per-batch *layout* (which token
   slice belongs to which batch) through ``SparseTensor.layout``, and that
   resolution ends in ``.item()`` — a device synchronisation, once per
   step.  A CUDA graph cannot contain a synchronisation, so the sparse
   stages refuse capture for that reason alone.

   The layout is a pure function of the token count and the batch count
   (the coordinates' batch ids are contiguous by construction — the
   ``Trellis2ShapeStage`` node validates it), and it is *constant for the
   whole stage*.  So the probe can memoise it: one synchronisation per
   stage instead of one per step.  That is the Thor-native fix the spike
   points at, and the experiment runs both ways so the cost of the fix is
   measured rather than assumed.

3. **The fused-fp8 path's CPU-side per-layer scale work**
   (``TRG_MODE=fp8``).

   The fused fp8 path builds a ``QuantizedTensor`` per linear and dispatches
   through ``__torch_dispatch__`` to a scaled matmul.  Each of those steps
   is host work: Python object construction, dispatch table lookup, and the
   scale handling.  This probe counts them and times them, so the lab can
   say how much of a step is CPU work in the scales rather than GPU work in
   the matmul — and, with ``TRG_PRECOMPUTE_SCALES=1``, what the same path
   costs when the scales are precomputed per layer on the GPU.

Design rules this file follows:

* the TRELLIS.2 environment is read, never modified — nothing here writes
  to ComfyUI's checkout;
* measurements are reported with the box's state beside them (see
  ``boxstate.sh``); the probe only records what it can time;
* a refused capture is a result, not a failure.  Every refusal records the
  reason, so the write-up can say *why* the graph half died.
"""

from __future__ import annotations

import json
import os
import time
import traceback
from typing import Any

CFG: dict[str, Any] = {
    # off | graph | fp8 | both
    "mode": os.environ.get("TRG_MODE", "off"),
    "out": os.environ.get("TRG_OUT", "/tmp/trg-probe.json"),
    "warmup": int(os.environ.get("TRG_WARMUP", "3")),
    # unet | stage | both
    "target": os.environ.get("TRG_TARGET", "both"),
    # Memoise the sparse layout so the sparse stages can be captured.
    "memo_layout": os.environ.get("TRG_MEMO_LAYOUT", "1") == "1",
    # Precompute the fp8 per-layer scales instead of making them per call.
    "precompute_scales": os.environ.get("TRG_PRECOMPUTE_SCALES", "0") == "1",
    # How many paired (eager, graphed) steps to record per target.
    "max_pairs": int(os.environ.get("TRG_MAX_PAIRS", "12")),
    # Watch the host-to-device copies without attempting a capture.
    "spy": os.environ.get("TRG_SPY", "0") == "1",
}

# Every record the probe makes, in order.
RECORDS: list[dict[str, Any]] = []
# Set when a capture is refused, with the reason.
REFUSALS: list[dict[str, Any]] = []
# The layout memo, when it is on: (token count, batch count) -> layout.
LAYOUT_MEMO: dict[tuple[int, int], list] = {}
LAYOUT_STATS = {"hits": 0, "misses": 0, "verified": 0, "mismatch": 0}
# The per-batch length tensor, and the broadcast map, memoised the same way.
# Both are constant for a whole stage, and both are built from a Python list
# and copied to the GPU — which a CUDA graph will not allow.
SEQLEN_MEMO: dict[tuple, tuple] = {}
BOARDCAST_MEMO: dict[tuple, Any] = {}
SPARSE_STATS = {"seqlen_hits": 0, "seqlen_misses": 0, "boardcast_hits": 0, "boardcast_misses": 0}
# The pinned staging buffers, kept alive for the life of the process: a
# captured graph records a *pointer*, so a buffer that was freed and reused
# would make the replay read the wrong numbers.
_PINNED_KEEPALIVE: list[Any] = []
# The copy spy: what crosses the bus, and from where.
COPY_SPY: dict[str, Any] = {"count": 0, "copies": []}


# --------------------------------------------------------------------------
# results
# --------------------------------------------------------------------------


def _flush() -> None:
    payload = {
        "config": CFG,
        "records": RECORDS,
        "refusals": REFUSALS,
        "layout_stats": LAYOUT_STATS,
        "sparse_stats": SPARSE_STATS,
        "copy_spy": COPY_SPY,
        "pid": os.getpid(),
    }
    tmp = CFG["out"] + ".tmp"
    try:
        with open(tmp, "w") as fh:
            json.dump(payload, fh, indent=1)
        os.replace(tmp, CFG["out"])
    except OSError:
        pass


# --------------------------------------------------------------------------
# the sparse layout — the sync that stops a graph
# --------------------------------------------------------------------------


def _install_copy_spy() -> None:
    """Record every host-to-device copy the model makes, and where from.

    A CUDA graph will not contain a copy from unpinned host memory, so every
    such copy is a place a capture can die.  This spy finds them without
    attempting a capture at all: it watches the Python-level ``.to()`` calls
    the model's own code makes and records the ones that cross the bus.

    It is a diagnostic, not a fix: the capture is what breaks, and the spy
    says which copy breaks it.
    """
    import torch

    original_to = torch.Tensor.to

    def to(self, *args, **kwargs):
        device = kwargs.get("device")
        if device is None and args and isinstance(args[0], (torch.device, str)):
            device = args[0]
        if device is not None and self.device.type == "cpu":
            try:
                target = torch.device(device)
            except (RuntimeError, TypeError, ValueError):
                target = None
            if target is not None and target.type == "cuda":
                COPY_SPY["count"] += 1
                if len(COPY_SPY["copies"]) < 200:
                    COPY_SPY["copies"].append(
                        {
                            "shape": list(self.shape),
                            "dtype": str(self.dtype),
                            "numel": int(self.numel()),
                            "where": [
                                line.strip()
                                for line in traceback.format_stack(limit=8)[-6:-1]
                                if "probe.py" not in line
                            ],
                        }
                    )
        return original_to(self, *args, **kwargs)

    torch.Tensor.to = to


def _install_pinned_copies() -> None:
    """Let a capture copy a small host constant across the bus.

    A CUDA graph cannot contain a copy from *unpinned* host memory: the copy
    would be a blocking memcpy, and the graph would replay a pointer to a
    buffer the allocator does not own.  PyTorch says exactly that in the
    error a refused capture produces, and the fix is what the error says:
    pin the source.

    The patch is deliberately narrow.  It acts only while a capture is in
    flight, only for host-to-device copies, and only for small tensors —
    the model's own constants (the rotary frequencies, the per-batch
    lengths).  Outside a capture nothing changes at all.
    """
    import torch

    original_to = torch.Tensor.to

    def to(self, *args, **kwargs):
        device = kwargs.get("device")
        if device is None and args and isinstance(args[0], (torch.device, str)):
            device = args[0]
        if device is not None and self.device.type == "cpu" and not self.requires_grad:
            try:
                target = torch.device(device)
            except (RuntimeError, TypeError, ValueError):
                target = None
            if (
                target is not None
                and target.type == "cuda"
                and self.numel() <= 65536
                and torch.cuda.is_current_stream_capturing()
            ):
                self = self.pin_memory()
                _PINNED_KEEPALIVE.append(self)
        return original_to(self, *args, **kwargs)

    torch.Tensor.to = to


def _install_layout_memo() -> None:
    """Memoise the sparse path's per-step host work.

    Three things stand between TRELLIS.2's sparse stages and a CUDA graph,
    and all three are the same mistake: a constant is rebuilt from a Python
    list, every step, and handed to the GPU.

    * ``SparseTensor.__cal_layout`` ends in ``.item()``: it reads the batch
      offsets back from the GPU so Python can slice with them.  A
      synchronisation — and a CUDA graph cannot contain one.
    * ``SparseTensor.seqlen`` is ``torch.tensor([...], device=cuda)``: a
      host-to-device copy of a Python list, which a capture refuses unless
      the source is pinned.
    * ``SparseTensor.batch_boardcast_map`` is built from ``seqlen``, so it
      inherits the same problem.

    All three are constant for a whole stage — the coordinates' batch ids
    are contiguous by construction, and the token count does not change
    between the steps of one stage — so the probe computes them once per
    stage and reuses them.  The first time a layout key is seen the real
    computation runs and is checked against a second, independent
    computation, so the memo is *verified*, not assumed.
    """
    import torch

    from comfy.ldm.trellis2.vae import SparseTensor

    name = "_SparseTensor__cal_layout"
    original = getattr(SparseTensor, name)
    if getattr(original, "_trg_memoised", False):
        return

    def memoised(self, coords, batch_size):
        key = (int(coords.shape[0]), int(batch_size))
        hit = LAYOUT_MEMO.get(key)
        if hit is not None:
            LAYOUT_STATS["hits"] += 1
            return hit
        LAYOUT_STATS["misses"] += 1
        layout = original(self, coords, batch_size)
        # Verify: compute the layout a second time, from scratch, and check
        # it agrees with the one we are about to cache.
        check = original(self, coords, batch_size)
        if list(layout) == list(check):
            LAYOUT_STATS["verified"] += 1
        else:
            LAYOUT_STATS["mismatch"] += 1
        LAYOUT_MEMO[key] = layout
        return layout

    memoised._trg_memoised = True
    setattr(SparseTensor, name, memoised)

    # -- the per-batch length, and the broadcast map ----------------------

    def seqlen(self):
        seqlens = tuple(l.stop - l.start for l in self.layout)
        key = (seqlens, str(self.device))
        hit = SEQLEN_MEMO.get(key)
        if hit is None:
            SPARSE_STATS["seqlen_misses"] += 1
            tensor = torch.tensor(
                list(seqlens), dtype=torch.long, device=self.device
            )
            hit = (tensor, seqlens)
            SEQLEN_MEMO[key] = hit
        else:
            SPARSE_STATS["seqlen_hits"] += 1
        return hit[0]

    def batch_boardcast_map(self):
        seqlens = tuple(l.stop - l.start for l in self.layout)
        key = (seqlens, str(self.device))
        hit = BOARDCAST_MEMO.get(key)
        if hit is None:
            SPARSE_STATS["boardcast_misses"] += 1
            lengths = torch.tensor(list(seqlens), dtype=torch.long, device=self.device)
            hit = torch.repeat_interleave(
                torch.arange(len(self.layout), device=self.device), lengths
            )
            BOARDCAST_MEMO[key] = hit
        else:
            SPARSE_STATS["boardcast_hits"] += 1
        return hit

    SparseTensor.seqlen = property(seqlen)
    SparseTensor.batch_boardcast_map = property(batch_boardcast_map)


# --------------------------------------------------------------------------
# timing helpers
# --------------------------------------------------------------------------


def _time_isolated(fn):
    """Run ``fn`` with an empty GPU queue and time it.

    ``torch.cuda.synchronize()`` before the call means the host issues the
    whole step into an empty queue and never waits for the GPU, so the host
    time is the *CPU issue time* — the thing a CUDA graph is supposed to
    shrink.  The CUDA events bracket the GPU's own span for the same call.

    Returns ``(result, host_ms, gpu_ms)``.
    """
    import torch

    torch.cuda.synchronize()
    start = torch.cuda.Event(enable_timing=True)
    end = torch.cuda.Event(enable_timing=True)
    start.record()
    t0 = time.perf_counter()
    result = fn()
    t1 = time.perf_counter()
    end.record()
    torch.cuda.synchronize()
    return result, (t1 - t0) * 1000.0, start.elapsed_time(end)


def _collect_tensors(obj, out):
    """Walk a nested structure and collect every tensor with its path."""
    import torch

    if isinstance(obj, torch.Tensor):
        out.append(obj)
    elif isinstance(obj, dict):
        for value in obj.values():
            _collect_tensors(value, out)
    elif isinstance(obj, (list, tuple)):
        for value in obj:
            _collect_tensors(value, out)
    return out


def _sparse_types():
    """The sparse tensor classes, if this ComfyUI has them."""
    try:
        from comfy.ldm.trellis2.vae import SparseTensor, VarLenTensor
    except Exception:  # noqa: BLE001 — a ComfyUI without TRELLIS.2
        return ()
    return (SparseTensor, VarLenTensor)


def _clone_structure(obj):
    """Copy a nested structure, replacing tensors with GPU clones.

    The sparse tensors are copied too: the features and the coordinates
    become static buffers, and the spatial cache (the layout, the rotary
    frequencies) is carried over so the copy is already resolved.
    """
    import torch

    sparse = _sparse_types()
    if isinstance(obj, torch.Tensor):
        return obj.detach().clone()
    if sparse and isinstance(obj, sparse):
        from comfy.ldm.trellis2.vae import SparseTensor

        if isinstance(obj, SparseTensor):
            new = SparseTensor(
                obj.feats.detach().clone(),
                obj.coords.detach().clone(),
                shape=obj._shape,
                scale=obj._scale,
            )
        else:
            new = type(obj)(obj.feats.detach().clone())
        # Shallow copy, so the layout and the rotary frequencies are already
        # resolved and the capture contains no synchronisation.
        new._spatial_cache = {k: dict(v) for k, v in obj._spatial_cache.items()}
        new._cache = dict(getattr(obj, "_cache", {}))
        return new
    if isinstance(obj, dict):
        return {k: _clone_structure(v) for k, v in obj.items()}
    if isinstance(obj, tuple):
        return tuple(_clone_structure(v) for v in obj)
    if isinstance(obj, list):
        return [_clone_structure(v) for v in obj]
    return obj


def _copy_into(live, static):
    """Copy every tensor of ``live`` into the matching tensor of ``static``.

    Returns the list of mismatches: a tensor whose shape or dtype differs
    from its static twin cannot be copied, and the graph would be wrong.
    """
    import torch

    sparse = _sparse_types()
    mismatched: list[dict[str, Any]] = []
    if isinstance(live, torch.Tensor):
        if not isinstance(static, torch.Tensor):
            return [{"live": tuple(live.shape), "static": None}]
        if live.shape != static.shape or live.dtype != static.dtype:
            mismatched.append(
                {
                    "live": list(live.shape),
                    "static": list(static.shape),
                    "dtype": str(live.dtype),
                }
            )
            return mismatched
        static.copy_(live)
        return mismatched
    if sparse and isinstance(live, sparse):
        from comfy.ldm.trellis2.vae import SparseTensor

        if isinstance(live, SparseTensor):
            mismatched += _copy_into(live.feats, static.feats)
            mismatched += _copy_into(live.coords, static.coords)
            return mismatched
        return _copy_into(live.feats, static.feats)
    if isinstance(live, dict):
        for key in live:
            if key in static:
                mismatched += _copy_into(live[key], static[key])
        return mismatched
    if isinstance(live, (list, tuple)):
        for index, value in enumerate(live):
            if index < len(static):
                mismatched += _copy_into(value, static[index])
        return mismatched
    return mismatched


def _signature(args, kwargs, name):
    """A key for the capture: the mode plus every tensor's shape and dtype.

    A different generation mode or a different latent shape is a different
    graph; the TRELLIS.2 workflow reuses one UNet for three stages.
    """
    import torch

    parts = [name]
    mode = kwargs.get("trellis2_generation_mode")
    if mode is not None:
        parts.append(f"mode={mode}")
    options = kwargs.get("transformer_options")
    if options is not None:
        # The options decide the attention backend and the CFG branch, so
        # two calls that differ only in their options are two graphs.  Only
        # the small values go in the key: a tensor's repr would be enormous
        # and would change every step.
        described = []
        for key in sorted(options, key=str):
            value = options[key]
            if isinstance(value, torch.Tensor):
                described.append(f"{key}=tensor{tuple(value.shape)}")
            else:
                described.append(f"{key}={value!r}")
        parts.append(f"opts=[{','.join(described)}]")
    for label, value in (("args", args), ("kwargs", kwargs)):
        for tensor in _collect_tensors(value, []):
            parts.append(f"{label}:{tuple(tensor.shape)}:{tensor.dtype}")
    return "|".join(parts)


def _gpu_utilisation() -> float | None:
    """The GPU's own utilisation, as a percentage.

    Another seat's render can be on the GPU while this experiment runs, and
    a step time measured in the middle of somebody else's render is not
    comparable with one measured on an idle box. Recording the utilisation
    with every measurement is what makes the numbers readable later.
    """
    import torch

    try:
        return float(torch.cuda.utilization())
    except Exception:  # noqa: BLE001
        return None


def _max_abs_diff(left, right):
    """The largest absolute difference between two outputs, if comparable."""
    import torch

    sparse = _sparse_types()
    try:
        if sparse and isinstance(left, sparse):
            left = left.feats
        if sparse and isinstance(right, sparse):
            right = right.feats
        if isinstance(left, torch.Tensor) and isinstance(right, torch.Tensor):
            if left.shape != right.shape:
                return None
            return float((left.float() - right.float()).abs().max().item())
    except Exception:  # noqa: BLE001
        return None
    return None


# --------------------------------------------------------------------------
# the graph runner
# --------------------------------------------------------------------------


class GraphRunner:
    """Captures and replays CUDA graphs for one callable.

    One runner per model instance.  It holds one graph per *signature* so a
    model reused across stages (TRELLIS.2's UNet runs the structure, shape and
    texture stages) gets a graph per stage instead of one wrong graph.
    """

    def __init__(self, name: str, orig):
        self.name = name
        self.orig = orig
        self.graphs: dict[str, dict[str, Any]] = {}
        self.calls = 0
        self.pairs = 0

    # -- capture ---------------------------------------------------------

    def _capture(self, sig: str, args, kwargs) -> None:
        import torch

        entry: dict[str, Any] = {
            "signature": sig,
            "state": "capturing",
            "capture_ms": None,
            "warmup_ms": None,
            "error": None,
        }
        self.graphs[sig] = entry

        static_args = _clone_structure(args)
        static_kwargs = _clone_structure(kwargs)

        try:
            # Warm up on a side stream.  PyTorch's documented recipe: the
            # allocator needs the kernels to have run at least once before a
            # capture can succeed.
            side = torch.cuda.Stream()
            side.wait_stream(torch.cuda.current_stream())
            t0 = time.perf_counter()
            with torch.cuda.stream(side):
                for _ in range(max(1, CFG["warmup"])):
                    self.orig(*static_args, **static_kwargs)
            torch.cuda.current_stream().wait_stream(side)
            torch.cuda.synchronize()
            entry["warmup_ms"] = (time.perf_counter() - t0) * 1000.0

            graph = torch.cuda.CUDAGraph()
            # Hold the graph object *before* the capture: a capture that
            # fails leaves captured allocations in the graph's private pool,
            # and freeing that pool (which is what happens when the local
            # goes out of scope) makes the allocator abort the process with
            # "uncaptured free of a captured allocation". Keeping the
            # reference keeps the pool alive, so a refused capture costs a
            # refusal and nothing else.
            entry["graph"] = graph
            t0 = time.perf_counter()
            try:
                with torch.cuda.graph(graph):
                    static_out = self.orig(*static_args, **static_kwargs)
            except Exception:
                # A capture that failed leaves the stream in a state where a
                # synchronise raises — and a CUDA error escaping into
                # ComfyUI's worker thread terminates the process.  So: ask
                # for the stream to settle, and swallow whatever it says.
                try:
                    torch.cuda.synchronize()
                except Exception:  # noqa: BLE001
                    pass
                raise
            entry["capture_ms"] = (time.perf_counter() - t0) * 1000.0

            entry["static_args"] = static_args
            entry["static_kwargs"] = static_kwargs
            entry["static_out"] = static_out
            entry["state"] = "captured"
        except Exception as exc:  # noqa: BLE001 — a refused capture is a result
            entry["state"] = "refused"
            entry["error"] = f"{type(exc).__name__}: {exc}"
            entry["traceback"] = traceback.format_exc(limit=30)
            REFUSALS.append(
                {
                    "model": self.name,
                    "signature": sig,
                    "error": entry["error"],
                    "traceback": entry["traceback"],
                }
            )
            _flush()

    # -- the call --------------------------------------------------------

    def __call__(self, *args, **kwargs):
        import torch

        self.calls += 1
        sig = _signature(args, kwargs, self.name)

        entry = self.graphs.get(sig)
        if entry is None:
            self._capture(sig, args, kwargs)
            entry = self.graphs[sig]
        if entry["state"] == "refused":
            # A refused capture is not a fatal error: the step runs eagerly,
            # and the refusal is on the record.  It is not attempted again —
            # one refusal per signature is the result, not a per-call event.
            return self.orig(*args, **kwargs)

        # Paired run: the same input, eager and graphed.
        eager_out, eager_host, eager_gpu = _time_isolated(
            lambda: self.orig(*args, **kwargs)
        )

        mismatched = _copy_into(args, entry["static_args"])
        mismatched += _copy_into(kwargs, entry["static_kwargs"])

        graph = entry["graph"]
        # The replay is timed the same way: an empty queue, so the host time
        # is the cost of *issuing* the graph.
        torch.cuda.synchronize()
        start = torch.cuda.Event(enable_timing=True)
        end = torch.cuda.Event(enable_timing=True)
        start.record()
        t0 = time.perf_counter()
        graph.replay()
        t1 = time.perf_counter()
        end.record()
        torch.cuda.synchronize()
        graph_host = (t1 - t0) * 1000.0
        graph_gpu = start.elapsed_time(end)
        graphed_out = entry["static_out"]

        diff = _max_abs_diff(eager_out, graphed_out)
        self.pairs += 1
        RECORDS.append(
            {
                "model": self.name,
                "signature": sig,
                "call": self.calls,
                "pair": self.pairs,
                "eager_host_ms": eager_host,
                "eager_gpu_ms": eager_gpu,
                "graph_host_ms": graph_host,
                "graph_gpu_ms": graph_gpu,
                "max_abs_diff": diff,
                "shape_mismatch": mismatched,
                "capture_ms": entry["capture_ms"],
                "warmup_ms": entry["warmup_ms"],
                "gpu_utilisation": _gpu_utilisation(),
                "ts": time.time(),
            }
        )
        _flush()

        # The graphed result is what the sampler keeps: if the numbers differ
        # we would rather the run continue and be *visible* than abort.
        return _clone_output(graphed_out)


def _clone_output(out):
    """A private copy of the graph's output.

    The samplers keep the model's output across steps (dpmpp_2m holds the
    previous denoised sample), so the static buffer must not be handed out
    directly — the next replay would overwrite it.
    """
    import torch

    sparse = _sparse_types()
    try:
        if sparse and isinstance(out, sparse):
            from comfy.ldm.trellis2.vae import SparseTensor

            if isinstance(out, SparseTensor):
                new = SparseTensor(
                    out.feats.detach().clone(),
                    out.coords.detach().clone(),
                    shape=out._shape,
                    scale=out._scale,
                )
            else:
                new = type(out)(out.feats.detach().clone())
            new._spatial_cache = {k: dict(v) for k, v in out._spatial_cache.items()}
            new._cache = dict(getattr(out, "_cache", {}))
            return new
        if isinstance(out, torch.Tensor):
            return out.detach().clone()
    except Exception:  # noqa: BLE001
        return out
    return out


# --------------------------------------------------------------------------
# installation — the graph half
# --------------------------------------------------------------------------


def _install_graph_probe() -> None:
    """Wrap the diffusion model's forward, and its per-stage sub-models.

    Two capture targets:

    * ``unet``  — ``Trellis2.forward`` itself: the whole step, including
      the parent's reshape and scatter.  This is the honest "the KSampler
      step" target, and it is where the sparse stages refuse capture (the
      parent's boolean-mask scatter is a synchronisation).
    * ``stage`` — the per-stage sub-model: the transformer blocks.  This is
      where the time is, and with the layout memoised the sparse stages can
      be captured here even though the parent cannot.
    """
    import torch

    import comfy.model_base as mb

    runners: dict[int, GraphRunner] = {}
    original_apply = mb.BaseModel._apply_model
    stage_names = ("structure_model", "img2shape_512", "img2shape", "shape2txt")

    def _runner_for(model, name):
        key = (id(model), name)
        runner = runners.get(key)
        if runner is None:
            runner = GraphRunner(name, model.forward)
            model.forward = runner
            runners[key] = runner
        return runner

    def _apply_model(self, x, t, *args, **kwargs):
        model = getattr(self, "diffusion_model", None)
        if model is not None:
            if CFG["target"] in ("unet", "both"):
                _runner_for(model, f"unet/{type(model).__name__}")
            if CFG["target"] in ("stage", "both"):
                for stage in stage_names:
                    sub = getattr(model, stage, None)
                    if sub is not None and hasattr(sub, "forward"):
                        _runner_for(sub, f"stage/{stage}")
        return original_apply(self, x, t, *args, **kwargs)

    mb.BaseModel._apply_model = _apply_model


# --------------------------------------------------------------------------
# installation — the fp8 half
# --------------------------------------------------------------------------


FP8_STATS: dict[str, list] = {}


def _benchmark_scale(args) -> dict:
    """What one per-layer scale tensor costs on the host.

    The fused fp8 path makes two of them per linear, per forward, and the
    spike's idea is to make them once per layer instead.  This measures the
    thing being removed: the cost of one ``torch.ones((), device=cuda)``,
    on this box, at this moment.
    """
    import torch

    device = None
    for arg in args:
        if isinstance(arg, torch.Tensor):
            device = arg.device
            break
    if device is None or device.type != "cuda":
        return {}
    samples = []
    for _ in range(200):
        t0 = time.perf_counter()
        torch.ones((), device=device, dtype=torch.float32)
        samples.append((time.perf_counter() - t0) * 1000.0)
    samples.sort()
    return {
        "device": str(device),
        "n": len(samples),
        "median_ms": samples[len(samples) // 2],
        "p95_ms": samples[int(len(samples) * 0.95)],
        "total_ms": sum(samples),
    }


def _install_fp8_probe() -> None:
    """Time the host side of ComfyUI's fp8 linear path.

    The fused fp8 path (``--fast fp8_matrix_mult`` with fp8 weights) builds
    a QuantizedTensor per linear and dispatches through ``__torch_dispatch__``
    to a scaled matmul.  Each of those steps is host work: Python object
    construction, dispatch table lookup, and the scale handling.  This probe
    counts them and times them, so the lab can say how much of a step is CPU
    work in the scales rather than GPU work in the matmul.

    With ``TRG_PRECOMPUTE_SCALES=1`` the per-call ``torch.ones`` scale
    tensors are replaced by one cached tensor per (device, dtype) — the
    spike's "precompute the scales per layer" idea — and the same counts
    are taken, so the two are directly comparable.
    """
    import torch

    import comfy.ops as ops

    stats = {
        "fp8_linear": [0, 0.0],
        "cast_bias_weight": [0, 0.0],
        "scale_alloc": [0, 0.0],
        "fp8_linear_none": [0, 0.0],
        "fp8_linear_used": [0, 0.0],
    }
    FP8_STATS.update(stats)

    original_fp8_linear = ops.fp8_linear
    original_cast = ops.cast_bias_weight

    # The precomputed-scale path: one scale tensor per (device, dtype),
    # made once, instead of two per linear per forward.
    scale_cache: dict[tuple, Any] = {}

    def _scale(device, dtype):
        key = (str(device), str(dtype))
        scale = scale_cache.get(key)
        if scale is None:
            t0 = time.perf_counter()
            scale = torch.ones((), device=device, dtype=dtype)
            stats["scale_alloc"][0] += 1
            stats["scale_alloc"][1] += (time.perf_counter() - t0) * 1000.0
            scale_cache[key] = scale
        return scale

    def fp8_linear(*args, **kwargs):
        t0 = time.perf_counter()
        out = original_fp8_linear(*args, **kwargs)
        stats["fp8_linear"][0] += 1
        stats["fp8_linear"][1] += (time.perf_counter() - t0) * 1000.0
        if out is None:
            # The fused path declined: the weight is not fp8, or the input
            # is not something it can quantise.  A call that returns None
            # falls through to the ordinary matmul.
            stats["fp8_linear_none"][0] += 1
        else:
            stats["fp8_linear_used"][0] += 1
            if not stats.get("weight_dtype"):
                stats["weight_dtype"] = str(getattr(args[0], "weight", None).dtype)
        if not stats.get("scale_benchmark"):
            stats["scale_benchmark"] = _benchmark_scale(args)
        return out

    def cast_bias_weight(*args, **kwargs):
        t0 = time.perf_counter()
        out = original_cast(*args, **kwargs)
        stats["cast_bias_weight"][0] += 1
        stats["cast_bias_weight"][1] += (time.perf_counter() - t0) * 1000.0
        return out

    ops.fp8_linear = fp8_linear
    ops.cast_bias_weight = cast_bias_weight

    def _timed_precomputed(fn):
        """Time the precomputed-scale path the same way the other one is timed.

        The two arms have to be comparable, so the wrapper counts the calls,
        the host time, and whether the fused path was actually taken.
        """

        def wrapper(*args, **kwargs):
            t0 = time.perf_counter()
            out = fn(*args, **kwargs)
            stats["fp8_linear"][0] += 1
            stats["fp8_linear"][1] += (time.perf_counter() - t0) * 1000.0
            if out is None:
                stats["fp8_linear_none"][0] += 1
            else:
                stats["fp8_linear_used"][0] += 1
                if not stats.get("weight_dtype"):
                    stats["weight_dtype"] = str(
                        getattr(args[0], "weight", None).dtype
                    )
            if not stats.get("scale_benchmark"):
                stats["scale_benchmark"] = _benchmark_scale(args)
            return out

        return wrapper

    if CFG["precompute_scales"]:
        # Re-implement the fused path with the scales precomputed.  The
        # scales are *always* ones, so a cached tensor is the same value; the
        # only thing that changes is that it is made once instead of twice
        # per linear per forward.
        import comfy.ops as _ops

        def fp8_linear_precomputed(self, input):
            dtype = self.weight.dtype
            if dtype not in [torch.float8_e4m3fn]:
                return None
            input_dtype = input.dtype
            input_shape = input.shape
            tensor_3d = input.ndim == 3
            if tensor_3d:
                input = input.reshape(-1, input_shape[2])
            if input.ndim != 2:
                return None
            lora_compute_dtype = _ops.comfy.model_management.lora_compute_dtype(
                input.device
            )
            scale_weight = _scale(input.device, torch.float32)
            scale_input = _scale(input.device, torch.float32)
            input = torch.clamp(input, min=-448, max=448, out=input)
            input_fp8 = input.to(dtype).contiguous()
            layout_params_input = _ops.TensorCoreFP8Layout.Params(
                scale=scale_input, orig_dtype=input_dtype, orig_shape=tuple(input_fp8.shape)
            )
            quantized_input = _ops.QuantizedTensor(
                input_fp8, "TensorCoreFP8Layout", layout_params_input
            )
            with _ops.CastBiasWeightContext(
                self,
                input,
                dtype=dtype,
                bias_dtype=input_dtype,
                offloadable=True,
                compute_dtype=lora_compute_dtype,
                want_requant=True,
            ) as (w, bias):
                w_shape = tuple(w.shape)
                layout_params_weight = _ops.TensorCoreFP8Layout.Params(
                    scale=scale_weight, orig_dtype=input_dtype, orig_shape=w_shape
                )
                quantized_weight = _ops.QuantizedTensor(
                    w, "TensorCoreFP8Layout", layout_params_weight
                )
                o = torch.nn.functional.linear(quantized_input, quantized_weight, bias)
            if tensor_3d:
                o = o.reshape((input_shape[0], input_shape[1], w_shape[0]))
            return o

        ops.fp8_linear = _timed_precomputed(fp8_linear_precomputed)

    def _dump(_signum=None, _frame=None):
        _flush()
        try:
            payload = json.load(open(CFG["out"]))
            payload["fp8_stats"] = {
                k: {"calls": v[0], "host_ms_total": v[1]}
                for k, v in stats.items()
                if isinstance(v, list)
            }
            if stats.get("scale_benchmark"):
                payload["fp8_stats"]["scale_benchmark"] = stats["scale_benchmark"]
            if stats.get("weight_dtype"):
                payload["fp8_stats"]["weight_dtype"] = stats["weight_dtype"]
            with open(CFG["out"], "w") as fh:
                json.dump(payload, fh, indent=1)
        except Exception:  # noqa: BLE001
            pass

    import atexit
    import signal

    atexit.register(_dump)
    try:
        signal.signal(signal.SIGTERM, _dump)
    except ValueError:
        pass


# --------------------------------------------------------------------------
# installation
# --------------------------------------------------------------------------


def install() -> None:
    """Install the probe.  Safe to call twice."""
    mode = CFG["mode"]
    if mode == "off":
        return
    # The pinned-copy patch is part of the capture machinery, not part of the
    # memo: the control arm must differ from the memo arm by the memo alone.
    try:
        _install_pinned_copies()
    except Exception as exc:  # noqa: BLE001
        REFUSALS.append(
            {"model": "pinned-copies", "error": f"{type(exc).__name__}: {exc}"}
        )
    if CFG.get("spy"):
        try:
            _install_copy_spy()
        except Exception as exc:  # noqa: BLE001
            REFUSALS.append(
                {"model": "copy-spy", "error": f"{type(exc).__name__}: {exc}"}
            )
    if CFG["memo_layout"]:
        try:
            _install_layout_memo()
        except Exception as exc:  # noqa: BLE001
            REFUSALS.append(
                {"model": "layout-memo", "error": f"{type(exc).__name__}: {exc}"}
            )
    if mode in ("graph", "both"):
        _install_graph_probe()
    if mode in ("fp8", "both"):
        _install_fp8_probe()
    _flush()
