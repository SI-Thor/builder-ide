#!/usr/bin/env python3
"""Box-state capture for every measurement in lab round 3.

CLAUDE.md: "Measure, with the box's state beside every number." This module is
the single place that answers "what was the box doing when you measured that?".

Two things live here:
  * box_state()  -- a snapshot: load average, NV power mode, GPU utilisation,
                    tegrastats power rails, and the *contenders* (other seats'
                    processes on the GPU) that would invalidate a number.
  * PowerSampler -- a background tegrastats reader that integrates the power
                    rails over a window so a measurement can report joules
                    instead of just seconds.

The rails come from `tegrastats`, whose power fields are
`NAME <current>mW/<avg>mW/<max>mW`. We use the *avg* field for sustained
power and the *max* field to report the worst sample inside a window.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field, asdict

# ---------------------------------------------------------------- tegrastats

# "VDD_GPU 20065mW/20065mW/20065mW" -> rail name + (current, avg, max) in mW
_RAIL_RE = re.compile(r"\b(VDD_[A-Z0-9_]+|VIN(?:_SYS_[0-9]V[0-9])?)\s+(\d+)mW/(\d+)mW/(\d+)mW")

# "RAM 49414/125749MB" / "CPU [5%@972, ...]" / "tj@41.156C"
_RAM_RE = re.compile(r"RAM (\d+)/(\d+)MB")
_GPU_TEMP_RE = re.compile(r"gpu@([\d.]+)C")


def parse_tegrastats_line(line: str) -> dict:
    """Parse one tegrastats output line into a dict of fields."""
    out: dict = {"rails_mw": {}}
    for m in _RAIL_RE.finditer(line):  # every rail on the line, not just the first
        name, cur, avg, mx = m.group(1), int(m.group(2)), int(m.group(3)), int(m.group(4))
        out["rails_mw"][name] = {"current": cur, "avg": avg, "max": mx}
    m = _RAM_RE.search(line)
    if m:
        out["ram_used_mb"] = int(m.group(1))
        out["ram_total_mb"] = int(m.group(2))
    m = _GPU_TEMP_RE.search(line)
    if m:
        out["gpu_temp_c"] = float(m.group(1))
    out["raw"] = line.strip()
    return out


class PowerSampler:
    """Sample tegrastats in the background and integrate joules over a window.

    Usage:
        with PowerSampler() as ps:
            ... the measured work ...
        print(ps.report())
    """

    def __init__(self, interval_ms: int = 200):
        self.interval_ms = interval_ms
        self.samples: list[dict] = []
        self._proc: subprocess.Popen | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._t0 = 0.0
        self._t1 = 0.0
        self._err: str | None = None

    # -- lifecycle ---------------------------------------------------------
    def __enter__(self):
        self._t0 = time.perf_counter()
        cmd = ["tegrastats", "--interval", str(self.interval_ms)]
        try:
            self._proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1
            )
        except FileNotFoundError:
            self._err = "tegrastats not found"
            self._t1 = time.perf_counter()
            return self
        self._thread = threading.Thread(target=self._reader, daemon=True)
        self._thread.start()
        return self

    def _reader(self):
        assert self._proc and self._proc.stdout
        for line in self._proc.stdout:
            if self._stop.is_set():
                break
            line = line.strip()
            if not line:
                continue
            rec = parse_tegrastats_line(line)
            rec["t"] = time.perf_counter() - self._t0
            self.samples.append(rec)
        self._proc.stdout.close()

    def __exit__(self, *exc):
        self._stop.set()
        if self._proc:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=5)
            except Exception:
                self._proc.kill()
        if self._thread:
            self._thread.join(timeout=5)
        self._t1 = time.perf_counter()
        return False

    # -- results -----------------------------------------------------------
    @property
    def elapsed_s(self) -> float:
        return max(self._t1 - self._t0, 1e-9)

    def _rail_series(self, rail: str, field: str = "avg") -> list[tuple[float, float]]:
        """(t_seconds, value_mW) series for one rail."""
        series = []
        for s in self.samples:
            r = s.get("rails_mw", {}).get(rail)
            if r:
                series.append((s["t"], float(r[field])))
        return series

    def integrated_joules(self, rail: str, field: str = "avg") -> float:
        """Trapezoidal integral of a rail's power over the sampled window."""
        series = self._rail_series(rail, field)
        if len(series) < 2:
            return float("nan")
        joules = 0.0
        for (t0, p0), (t1, p1) in zip(series, series[1:]):
            joules += 0.5 * (p0 + p1) * (t1 - t0) / 1000.0  # mW*s -> J
        return joules

    def mean_watts(self, rail: str, field: str = "avg") -> float:
        series = self._rail_series(rail, field)
        if not series:
            return float("nan")
        return sum(v for _, v in series) / len(series) / 1000.0

    def peak_watts(self, rail: str) -> float:
        vals = [
            s["rails_mw"][rail]["max"]
            for s in self.samples
            if rail in s.get("rails_mw", {})
        ]
        return max(vals) / 1000.0 if vals else float("nan")

    def report(self, rails=("VDD_GPU", "VDD_CPU_SOC_MSS", "VIN")) -> dict:
        rep = {
            "window_s": round(self.elapsed_s, 4),
            "n_samples": len(self.samples),
            "interval_ms": self.interval_ms,
            "rails": {},
        }
        for rail in rails:
            rep["rails"][rail] = {
                "mean_w": round(self.mean_watts(rail), 3) if self.samples else None,
                "peak_w": round(self.peak_watts(rail), 3) if self.samples else None,
                "joules": round(self.integrated_joules(rail), 4) if self.samples else None,
            }
        if self._err:
            rep["error"] = self._err
        return rep


# ---------------------------------------------------------------- box state


# ---------------------------------------------------------------- INA rails
# The Thor exposes real current sensors on I2C:
#   hwmon4 = ina238  -> label "VIN": whole-box input power (power1_input, uW)
#   hwmon6 = ina3221 -> per-rail V (inN_input, mV) x I (currN_input, mA)
#                       with in1_label=VDD_GPU, in2_label=VDD_CPU_SOC_MSS,
#                            in3_label=VIN_SYS_5V0
# tegrastats reports the same rails as computed power; the two agree to <1%.

INA238_DIR = "/sys/class/hwmon/hwmon4"
INA3221_DIR = "/sys/class/hwmon/hwmon6"


def _read(path: str) -> float | None:
    try:
        with open(path) as f:
            return float(f.read().strip())
    except Exception:
        return None


def _read_text(path: str) -> str | None:
    try:
        with open(path) as f:
            return f.read().strip()
    except Exception:
        return None


def ina_layout() -> dict:
    """Which INA channels exist and what they are called."""
    out: dict = {"ina238": {}, "ina3221": {}}
    for i in range(1, 9):
        label = _read_text(f"{INA3221_DIR}/in{i}_label")
        v = _read(f"{INA3221_DIR}/in{i}_input")
        i_ma = _read(f"{INA3221_DIR}/curr{i}_input")
        if label or (v is not None and i_ma is not None):
            out["ina3221"][f"ch{i}"] = {
                "label": label,
                "volts": (v / 1000.0) if v is not None else None,
                "amps": (i_ma / 1000.0) if i_ma is not None else None,
                "watts": (v * i_ma / 1e6) if (v is not None and i_ma is not None) else None,
            }
    lbl = _read_text(f"{INA238_DIR}/label")
    pw = _read(f"{INA238_DIR}/power1_input")
    out["ina238"] = {
        "label": lbl,
        "input_volts": (_read(f"{INA238_DIR}/in1_input") or 0) / 1000.0,
        "amps": (_read(f"{INA238_DIR}/curr1_input") or 0) / 1000.0,
        "watts": (pw / 1e6) if pw is not None else None,
        "temp_c": (_read(f"{INA238_DIR}/temp1_input") or 0) / 1000.0,
    }
    return out


class InaSampler:
    """Poll the INA current sensors at high rate and integrate joules per rail."""

    def __init__(self, interval_ms: int = 25):
        self.interval_ms = interval_ms
        self.samples: list[dict] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._t0 = 0.0
        self._t1 = 0.0

    def _poll_once(self, t: float) -> dict:
        rec = {"t": t, "rails_w": {}}
        for i in range(1, 9):
            label = _read_text(f"{INA3221_DIR}/in{i}_label")
            if not label:
                continue
            v = _read(f"{INA3221_DIR}/in{i}_input")
            c = _read(f"{INA3221_DIR}/curr{i}_input")
            if v is not None and c is not None:
                rec["rails_w"][label] = v * c / 1e6
        pw = _read(f"{INA238_DIR}/power1_input")
        if pw is not None:
            rec["rails_w"]["VIN_total"] = pw / 1e6
        rec["gpu_clk_mhz"] = gpu_clock_mhz()
        return rec

    def _loop(self):
        while not self._stop.is_set():
            self.samples.append(self._poll_once(time.perf_counter() - self._t0))
            self._stop.wait(self.interval_ms / 1000.0)

    def __enter__(self):
        self._t0 = time.perf_counter()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        self._t1 = time.perf_counter()
        return False

    def _series(self, rail: str) -> list[tuple[float, float]]:
        return [(s["t"], s["rails_w"][rail]) for s in self.samples if rail in s["rails_w"]]

    def joules(self, rail: str, t0: float | None = None, t1: float | None = None) -> float:
        """Integrate a rail over the whole window, or over [t0, t1] within it.

        Sub-window integration matters: the sampler starts before the measured
        work does, so a joules figure over the whole window would charge the
        meter its own start-up. Mark the exact region instead.
        """
        ser = self._series(rail)
        if t0 is not None:
            ser = [(t, p) for t, p in ser if t >= t0]
        if t1 is not None:
            ser = [(t, p) for t, p in ser if t <= t1]
        if len(ser) < 2:
            return float("nan")
        j = 0.0
        for (ta, pa), (tb, pb) in zip(ser, ser[1:]):
            j += 0.5 * (pa + pb) * (tb - ta)
        return j

    def mean_w(self, rail: str) -> float:
        ser = self._series(rail)
        return sum(p for _, p in ser) / len(ser) if ser else float("nan")

    def peak_w(self, rail: str) -> float:
        ser = self._series(rail)
        return max(p for _, p in ser) if ser else float("nan")

    def report(self) -> dict:
        rails = sorted({r for s in self.samples for r in s["rails_w"]})
        clks = [s.get("gpu_clk_mhz") for s in self.samples if s.get("gpu_clk_mhz")]
        return {
            "window_s": round(self._t1 - self._t0, 4),
            "n_samples": len(self.samples),
            "interval_ms": self.interval_ms,
            "gpu_clk_mhz_min": (min(clks) if clks else None),
            "gpu_clk_mhz_max": (max(clks) if clks else None),
            "rails": {
                r: {
                    "mean_w": round(self.mean_w(r), 3),
                    "peak_w": round(self.peak_w(r), 3),
                    "joules": round(self.joules(r), 4),
                }
                for r in rails
            },
        }


class PowerMeter:
    """tegrastats rails + INA rails in one window. The joules metric of this lab.

    `joules_total` is the whole-box number (INA238 "VIN"), which is what the
    wall pays; `joules_gpu` is the VDD_GPU rail, which is what the GPU work
    costs. Report both.

    The box is shared, and the whole-box rail carries every other tenant's
    power. So the meter also captures an *idle baseline* -- the power the box
    is already drawing before the measured work starts -- and can report the
    joules *above* that baseline, which is the part the measured work is
    actually responsible for.
    """

    def __init__(self, interval_ms: int = 200, ina_interval_ms: int = 25,
                 baseline_s: float = 0.5):
        self.tegrastats = PowerSampler(interval_ms)
        self.ina = InaSampler(ina_interval_ms)
        self.baseline_s = baseline_s
        self.baseline_w: dict[str, float] = {}
        self.box: dict = {}

    def __enter__(self):
        self.tegrastats.__enter__()
        self.ina.__enter__()
        # let the box settle, then take the idle baseline
        time.sleep(self.baseline_s)
        self.baseline_w = {
            r: self.ina.mean_w(r) for r in self.ina.report()["rails"]
        }
        self.box = box_state()
        return self

    def __exit__(self, *exc):
        self.ina.__exit__(*exc)
        self.tegrastats.__exit__(*exc)
        return False

    def report(self) -> dict:
        rep = {
            "box_state": self.box,
            "baseline_w": {k: round(v, 3) for k, v in self.baseline_w.items()},
            "tegrastats": self.tegrastats.report(),
            "ina": self.ina.report(),
        }
        rep["joules_total"] = self.ina.joules("VIN_total")
        rep["joules_gpu"] = self.ina.joules("VDD_GPU")
        rep["joules_cpu_soc"] = self.ina.joules("VDD_CPU_SOC_MSS")
        rep["mean_w_total"] = self.ina.mean_w("VIN_total")
        rep["mean_w_gpu"] = self.ina.mean_w("VDD_GPU")
        return rep

    def joules(self, rail: str = "VIN_total") -> float:
        return self.ina.joules(rail)

    # -- exact sub-window marking -----------------------------------------
    def mark(self) -> float:
        """Timestamp inside the sampler's own clock, for sub-window joules."""
        return self.ina._poll_once(time.perf_counter() - self.ina._t0)["t"]

    def joules_between(self, rail: str, t0: float, t1: float) -> float:
        return self.ina.joules(rail, t0, t1)

    def watts_between(self, rail: str, t0: float, t1: float) -> float:
        ser = [(t, p) for t, p in self.ina._series(rail) if t0 <= t <= t1]
        return sum(p for _, p in ser) / len(ser) if ser else float("nan")

    def joules_above_baseline(self, rail: str, t0: float, t1: float) -> float:
        """The joules the measured work is actually responsible for.

        The whole-box rail carries whatever the other tenants of this box are
        drawing. Subtracting the idle baseline captured before the work started
        isolates the cost of the work itself. On a quiet box the two numbers
        nearly agree; on a busy box only this one is honest.
        """
        j = self.joules_between(rail, t0, t1)
        if j != j:
            return float("nan")
        base = self.baseline_w.get(rail, 0.0)
        return j - base * (t1 - t0)


def _sh(cmd: list[str], timeout: int = 10) -> str:
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return out.stdout.strip()
    except Exception as e:  # pragma: no cover - diagnostics only
        return f"<error: {e}>"


def gpu_util_pct() -> int | None:
    out = _sh(["nvidia-smi", "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"])
    try:
        return int(out.splitlines()[0].strip())
    except Exception:
        return None


# ---------------------------------------------------------------- GPU clock
# The Thor's GPU sits at 315 MHz when idle and ramps to 1575 MHz under
# sustained load, under the `nvhost_podgov` governor. The ramp takes roughly
# 1-1.5 s of *sustained* work, and the clock decays again after a few idle
# seconds. A measurement taken in the first second after the GPU was idle is
# therefore 2-3x slower than the same measurement taken warm -- which is not a
# property of the code being measured.
#
# Rule for this lab: warm the GPU before timing anything, and record the clock
# beside the number.

GPU_GPC = "/sys/class/devfreq/gpu-gpc-0"
GPU_NVD = "/sys/class/devfreq/gpu-nvd-0"


def gpu_clock_mhz() -> float | None:
    """The GPU's current core clock in MHz (None if unreadable)."""
    v = _read(f"{GPU_GPC}/cur_freq")
    return (v / 1e6) if v is not None else None


def gpu_clock_limits() -> dict:
    out = {}
    for label, path in (("gpc", GPU_GPC), ("nvd", GPU_NVD)):
        lo, hi = _read(f"{path}/min_freq"), _read(f"{path}/max_freq")
        out[label] = {
            "min_mhz": (lo / 1e6) if lo is not None else None,
            "max_mhz": (hi / 1e6) if hi is not None else None,
            "governor": _read_text(f"{path}/governor"),
        }
    return out


def warm_gpu(seconds: float = 2.0, size: int = 4096) -> dict:
    """Hold the GPU busy long enough for its clock to ramp to max.

    Returns the clock before and after. Without this, the first timed block in
    a process measures the *idle* clock: on this box that is 315 MHz against a
    1575 MHz maximum, a 2.6x error on a GEMM benchmark.
    """
    before = gpu_clock_mhz()
    try:
        import torch
    except Exception:
        return {"clock_before_mhz": before, "clock_after_mhz": before,
                "error": "torch unavailable"}
    a = torch.randn(size, size, device="cuda", dtype=torch.bfloat16)
    b = torch.randn(size, size, device="cuda", dtype=torch.bfloat16)
    t0 = time.perf_counter()
    reps = 0
    while time.perf_counter() - t0 < seconds:
        c = a @ b
        reps += 1
        if reps % 20 == 0:
            torch.cuda.synchronize()
    torch.cuda.synchronize()
    del a, b, c
    torch.cuda.empty_cache()
    return {"clock_before_mhz": before, "clock_after_mhz": gpu_clock_mhz(),
            "warm_seconds": seconds, "reps": reps}


def gpu_processes() -> list[dict]:
    """Other processes holding the GPU. These are the contenders."""
    out = _sh(["nvidia-smi", "--query-compute-apps=pid,process_name,used_memory",
               "--format=csv,noheader,nounits"])
    procs = []
    for line in out.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 2 and parts[0].isdigit():
            pid = int(parts[0])
            try:
                with open(f"/proc/{pid}/cmdline", "rb") as f:
                    cmd = f.read().replace(b"\0", b" ").decode(errors="replace").strip()
            except Exception:
                cmd = parts[1]
            procs.append({"pid": pid, "name": parts[1], "mem_mib": parts[2] if len(parts) > 2 else "", "cmdline": cmd})
    return procs


def load_avg() -> list[float]:
    try:
        return [round(x, 2) for x in os.getloadavg()]
    except Exception:
        return []


def power_mode() -> str:
    out = _sh(["nvpmodel", "-q"])
    for line in out.splitlines():
        if "NV Power Mode" in line:
            return line.strip()
    return out.replace("\n", " ")[:120]


def memory() -> dict:
    info = {}
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                k, _, v = line.partition(":")
                if k in ("MemTotal", "MemAvailable", "MemFree", "Cached"):
                    info[k] = int(v.split()[0]) // 1024  # MiB
    except Exception:
        pass
    return info


def box_state(include_processes: bool = True) -> dict:
    """The snapshot attached to every number in this round."""
    st = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "loadavg": load_avg(),
        "n_cores": os.cpu_count(),
        "power_mode": power_mode(),
        "gpu_util_pct": gpu_util_pct(),
        "gpu_clock_mhz": gpu_clock_mhz(),
        "gpu_clock_limits": gpu_clock_limits(),
        "mem_mib": memory(),
    }
    if include_processes:
        st["gpu_processes"] = gpu_processes()
    return st


def format_box_state(st: dict) -> str:
    """One-line human summary for an exp file."""
    lp = ", ".join(f"{x:.2f}" for x in st.get("loadavg", []))
    parts = [
        f"load {lp}",
        f"{st.get('power_mode', '?')}",
        f"gpu-util {st.get('gpu_util_pct')}%",
    ]
    clk = st.get("gpu_clock_mhz")
    if clk:
        parts.append(f"gpu-clk {clk:.0f} MHz")
    m = st.get("mem_mib", {})
    if m:
        parts.append(f"mem avail {m.get('MemAvailable', '?')} MiB")
    lines = ["| ".join(parts)]
    for p in st.get("gpu_processes", []):
        lines.append(f"  contender pid {p['pid']}: {p['cmdline'][:110]}")
    return "\n".join(lines)


if __name__ == "__main__":
    import json

    st = box_state()
    print(json.dumps(st, indent=2))
    print()
    with PowerSampler(interval_ms=500) as ps:
        time.sleep(2.0)
    print(json.dumps(ps.report(), indent=2))
