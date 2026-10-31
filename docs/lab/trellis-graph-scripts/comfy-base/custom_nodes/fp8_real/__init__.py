"""``fp8_real`` — make the weights fp8 when the fused fp8 path is asked for.

This node is a **patch**, and it lives in this worktree on purpose: the
TRELLIS.2 environment is read, never modified.

**The bug it fixes.**  ComfyUI's fused fp8 linear (``comfy.ops.fp8_linear``)
only runs when the module's weight is *already* fp8 — it reads
``self.weight.dtype`` and returns ``None`` for anything else, which drops the
call through to the ordinary matmul.  The weight arrives bf16, because
ComfyUI's dynamic VRAM loader **assigns** the checkpoint's tensors over the
model's parameters:

    comfy/model_base.py   load_model_weights -> load_state_dict(..., assign=True)
    comfy/ops.py          disable_weight_init.Linear._lazy_load_from_state_dict
                             module.weight = torch.nn.Parameter(v)   # v: the checkpoint's bf16

The model was *built* for fp8: ``set_inference_dtype`` put
``torch.float8_e4m3fn`` into ``unet_config['dtype']``, so every linear
records ``weight_comfy_model_dtype = torch.float8_e4m3fn``.  The assignment
throws that away.  Without the dynamic VRAM path the same checkpoint would be
*copied into* the fp8 parameter (torch's ``copy_`` casts), and the fused path
would run.  The dynamic loader replaced a cast with an assignment — and the
cast was what made the fp8 request mean anything.

So the fused path was never *broken*: it was never *reached*.  The probe in
this directory counted 43,697 ``cast_bias_weight`` calls and zero fused
matmuls, which is the signature of the fallback path, not of fp8.

**The fix.**  At the point where the weight is assigned, cast the
checkpoint's tensor to the dtype the module was built for, so the weight the
model ends up holding is the fp8 one it asked for.  The cast is paid once, at
load, and it is cheap: about 6 GB/s on this box, so ~1.5 s for the whole
9.7 GB UNet.

The fix also removes work rather than adding it.  The dynamic loader's
staging geometry is already fp8 (``setup_param`` sets
``weight._model_dtype`` from ``weight_comfy_model_dtype``), so with a bf16
parameter the loader had to *re-quantise* every weight on its way to the
device, and the manual-cast path had to *up-cast* it again on every use.  With
the weight already fp8 the geometry and the data agree, the load-time cast
disappears, and the fused path consumes the staged fp8 bytes directly.

**What it does not touch.**  A module is cast only when it is a
``comfy.ops.fp8_ops.Linear`` *and* its ``weight_comfy_model_dtype`` is
``torch.float8_e4m3fn``.  A bf16 model is untouched, byte for byte, and so is
a model loaded with ``--fast fp8_matrix_mult`` alone (which selects the fused
*ops* but never asked for fp8 *weights*).

**The switch.**  ``FP8_REAL_FIX=0`` turns the patch off, which is how the
control arm of the experiment reproduces today's behaviour; the default is on.
``FP8_REAL_STATS`` names the file the patch's counters are written to.

    FP8_REAL_FIX=0  -- today's behaviour: the fused path declines
    FP8_REAL_FIX=1  -- the fix: the weights are fp8 and the path fuses
"""

from __future__ import annotations

import atexit
import json
import os
from typing import Any

#: The patch is installed unless it is explicitly turned off.
ENABLED = os.environ.get("FP8_REAL_FIX", "1") == "1"

#: Where the counters go.  Defaults to the probe's own output directory.
STATS_PATH = os.environ.get(
    "FP8_REAL_STATS", "/tmp/fp8-real-stats.json"
)

STATS: dict[str, Any] = {
    "enabled": ENABLED,
    "installed": False,
    "modules_seen": 0,
    "weights_cast": 0,
    "elements_cast": 0,
    "weights_already_fp8": 0,
    "cast_seconds": 0.0,
}

NODE_CLASS_MAPPINGS: dict[str, Any] = {}
NODE_DISPLAY_NAME_MAPPINGS: dict[str, Any] = {}


def _flush() -> None:
    """Write the counters, so the lab can say what the patch actually did."""
    try:
        tmp = STATS_PATH + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(STATS, fh, indent=1)
        os.replace(tmp, STATS_PATH)
    except OSError:
        pass


def _cast_to_fp8(module: Any, state_dict: dict, prefix: str) -> None:
    """Cast one module's weight to fp8, if that module asked for fp8.

    The gate is deliberately narrow:

    * the module must be one of the fused path's own layers
      (``comfy.ops.fp8_ops.Linear``) — the fused matmul is a linear's, and
      a convolution has no fp8 kernel here;
    * the module must have been *built* for fp8
      (``weight_comfy_model_dtype == torch.float8_e4m3fn``) — that is the
      request the loader made, and it is what tells the cast apart from a
      plain bf16 model that happens to run under ``--fast fp8_matrix_mult``.
    """
    import torch

    import comfy.ops as ops

    if not isinstance(module, ops.fp8_ops.Linear):
        return
    if getattr(module, "weight_comfy_model_dtype", None) != torch.float8_e4m3fn:
        return

    STATS["modules_seen"] += 1
    key = prefix + "weight"
    value = state_dict.get(key)
    if not isinstance(value, torch.Tensor) or not value.is_floating_point():
        return
    if value.dtype == torch.float8_e4m3fn:
        STATS["weights_already_fp8"] += 1
        return

    import time

    started = time.perf_counter()
    state_dict[key] = value.to(torch.float8_e4m3fn)
    STATS["cast_seconds"] += time.perf_counter() - started
    STATS["weights_cast"] += 1
    STATS["elements_cast"] += value.numel()
    # The counters are flushed every so often rather than on every cast: a
    # model has thousands of layers, and the file only has to be right if the
    # process dies before it writes its last one.
    if STATS["weights_cast"] % 64 == 0:
        _flush()


def _install() -> None:
    """Patch ComfyUI's lazy state-dict loader, in this process only."""
    import comfy.ops as ops

    original = ops.disable_weight_init._lazy_load_from_state_dict

    def patched(
        module,
        state_dict,
        prefix,
        local_metadata,
        missing_keys,
        unexpected_keys,
        weight_shape,
        bias_shape=None,
    ):
        try:
            _cast_to_fp8(module, state_dict, prefix)
        except Exception:  # noqa: BLE001 - a failed cast must not break the load
            pass
        return original(
            module,
            state_dict,
            prefix,
            local_metadata,
            missing_keys,
            unexpected_keys,
            weight_shape,
            bias_shape,
        )

    ops.disable_weight_init._lazy_load_from_state_dict = staticmethod(patched)
    STATS["installed"] = True
    _flush()


if ENABLED:
    try:
        _install()
    except Exception as exc:  # noqa: BLE001 - the node must never break the server
        STATS["error"] = f"{type(exc).__name__}: {exc}"


def _flush_on_signal(_signum=None, _frame=None) -> None:
    """Write the counters when the server is stopped.

    ``serve_probe.sh stop`` sends SIGTERM and then SIGKILL, so the atexit
    hook is not always reached: a patch whose counters were lost with the
    process would look like a patch that did nothing.
    """
    _flush()


try:
    import signal

    signal.signal(signal.SIGTERM, _flush_on_signal)
except (ImportError, ValueError):  # pragma: no cover - not a POSIX main thread
    pass

atexit.register(_flush)
