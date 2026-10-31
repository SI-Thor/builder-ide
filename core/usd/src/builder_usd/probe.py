"""The zero-GPU probe — evidence, not an assertion.

rev-tech spike 3's pass/fail says build123d must use **zero** GPU memory. On
this box that claim is easy to make and easy to fake, so this module measures
it instead:

* ``/proc/self/maps`` — every shared library the process has mapped. If any
  CUDA or NVIDIA driver library is mapped, the process has a path to the GPU.
* ``/proc/self/fd`` — every file descriptor open. A CUDA context shows up as
  an open ``/dev/nvidia*`` handle.
* ``/proc/self/status`` — the peak resident set size, so the cost is on the
  record next to the zero.

On this machine ``nvidia-smi`` reports GPU memory as ``[N/A]`` because the
memory is unified with the CPU's (rev-tech R3), so a GPU number cannot be
read from here at all — which is exactly why the claim is checked structurally,
in the process, rather than through a number that the box cannot produce.
"""

from __future__ import annotations

import os
import resource
from dataclasses import dataclass, field
from pathlib import Path

__all__ = ["GpuProbe", "probe"]

#: Anything in the process's mappings that would give it a path to the GPU.
_GPU_MARKERS = ("nvidia", "libcuda", "libnv", "libGLX_nvidia", "cuda")


@dataclass(frozen=True)
class GpuProbe:
    """What the probe found."""

    gpu_mappings: tuple[str, ...] = ()
    gpu_fds: tuple[str, ...] = ()
    modules: tuple[str, ...] = ()
    peak_rss_kb: int = 0
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def gpu_free(self) -> bool:
        return not self.gpu_mappings and not self.gpu_fds

    def to_dict(self) -> dict:
        return {
            "gpu_free": self.gpu_free,
            "gpu_mappings": list(self.gpu_mappings),
            "gpu_fds": list(self.gpu_fds),
            "modules": list(self.modules),
            "peak_rss_kb": self.peak_rss_kb,
            "notes": list(self.notes),
        }


def _read(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def probe() -> GpuProbe:
    """Measure whether this process has any path to the GPU."""
    mappings: list[str] = []
    modules: list[str] = []
    for line in _read("/proc/self/maps").splitlines():
        lowered = line.lower()
        if any(marker in lowered for marker in _GPU_MARKERS):
            mappings.append(line.strip())

    for line in _read("/proc/self/maps").splitlines():
        fields = line.split()
        if len(fields) >= 6 and fields[-1].startswith("/"):
            modules.append(fields[-1])

    fds: list[str] = []
    for entry in sorted(Path("/proc/self/fd").iterdir()) if Path("/proc/self/fd").exists() else []:
        try:
            target = os.readlink(entry)
        except OSError:
            continue
        if "nvidia" in target.lower() or "cuda" in target.lower():
            fds.append(target)

    peak_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss

    notes = [
        "GPU memory is unified with RAM on this box; nvidia-smi reports [N/A], so the "
        "zero claim is checked structurally inside the process.",
        "peak RSS is the whole-process figure at the time of the probe.",
    ]
    return GpuProbe(
        gpu_mappings=tuple(mappings),
        gpu_fds=tuple(fds),
        modules=tuple(sorted(set(modules))),
        peak_rss_kb=peak_kb,
        notes=tuple(notes),
    )
