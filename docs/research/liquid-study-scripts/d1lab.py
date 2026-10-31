"""Shared helpers for the liquid-study experiments.

Two rules from builder-ide's docs/lab/IDEAS.md are enforced here rather than
remembered per script:

  rule 3  warm the GPU clock before timing anything (315 -> 1575 MHz, ~1.4 s;
          a cold reading is 2.6x slow);
  rule 4  on a shared box, absolute times drift 2-3.4x with other seats'
          load -- so every number is recorded beside the box state it was
          taken under, and comparisons are interleaved, not sequential;
  rule 6  joules come from the attributable VDD_GPU rail, not the whole-box rail.

Nothing here touches another seat's service. The servers are ours, on our own
ports (8290-8299), and are stopped when the script exits. Only the d1 decision
models are ever served -- no other LLM is hosted on this box.
"""

from __future__ import annotations

import json
import os
import re
import signal
import socket
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

LAB = Path(__file__).resolve().parent.parent
LOGS = LAB / "logs"
RESULTS = LAB / "results"
LOGS.mkdir(exist_ok=True)
RESULTS.mkdir(exist_ok=True)

LLAMA_SERVER = Path(os.environ.get(
    "LLAMA_SERVER", "/home/caseydigennaro/llama.cpp-upstream/build-up/bin/llama-server"))
MODELS_DIR = Path(os.environ.get("MODELS_DIR", "/home/caseydigennaro/models"))

#: The d1 family as it actually is on this box. The decision type is read out
#: of the GGUF metadata by llama.cpp (`<arch>.decision.type`), which is why
#: "d1" needs no server flag.
#:   d1-3B        -> lfm2-d1        (LFM2, 32k ctx)
#:   d1-2B        -> lfm3-d1        (LFM3, 128k ctx, no_batching)
#:   d1-omni-600M -> lfm2-d1-omni   (LFM2 + vision projector, 128k ctx)
MODELS: dict[str, dict[str, tuple[str, str, str | None]]] = {
    "d1-3B": {
        "Q8": ("d1-3B", "d1-3B-Q8_0.gguf", None),
        "Q4": ("d1-3B", "d1-3B-Q4_K_M.gguf", None),
        "BF16": ("d1-3B", "d1-3B-BF16.gguf", None),
    },
    "d1-2B": {
        "Q8": ("d1-2B", "d1-2B-Q8_0.gguf", None),
        "Q4": ("d1-2B", "d1-2B-Q4_K_M.gguf", None),
        "BF16": ("d1-2B", "d1-2B-BF16.gguf", None),
    },
    "d1-omni-600M": {
        "Q8": ("d1-omni-600M", "d1-omni-600M-Q8_0.gguf", "mmproj-d1-omni-600M-Q8_0.gguf"),
        "Q4": ("d1-omni-600M", "d1-omni-600M-Q4_K_M.gguf", "mmproj-d1-omni-600M-Q4_K_M.gguf"),
        "BF16": ("d1-omni-600M", "d1-omni-600M-BF16.gguf", "mmproj-d1-omni-600M-BF16.gguf"),
    },
}


# --------------------------------------------------------------------------
# box state
# --------------------------------------------------------------------------

_TG_RE = {
    "ram_used_mb": re.compile(r"RAM (\d+)/(\d+)MB"),
    "cpu": re.compile(r"CPU \[([^\]]*)\]"),
    "gpu_temp_c": re.compile(r"gpu@([\d.]+)C"),
    "vdd_gpu_w": re.compile(r"VDD_GPU (\d+)mW"),
    "vin_w": re.compile(r"VIN (\d+)mW/(\d+)mW"),
}


def _tegrastats_once() -> dict:
    """One sample of tegrastats. Best-effort: a failure must not kill a run.

    tegrastats is a streaming tool and never exits on its own, so it is run
    under `timeout` and the partial output is read -- `subprocess.run` with a
    timeout alone would block for the whole timeout and return nothing.
    """
    out = {}
    try:
        p = subprocess.run(["timeout", "1", "tegrastats", "--interval", "250"],
                           capture_output=True, text=True, timeout=8)
        line = (p.stdout or "").strip().splitlines()
        line = line[-1] if line else ""
    except Exception:
        return out
    if not line:
        return out
    m = _TG_RE["ram_used_mb"].search(line)
    if m:
        out["ram_used_mb"] = int(m.group(1))
        out["ram_total_mb"] = int(m.group(2))
    m = _TG_RE["gpu_temp_c"].search(line)
    if m:
        out["gpu_temp_c"] = float(m.group(1))
    m = _TG_RE["vdd_gpu_w"].search(line)
    if m:
        out["vdd_gpu_w"] = int(m.group(1)) / 1000.0
    m = _TG_RE["cpu"].search(line)
    if m:
        freqs = [int(x) for x in re.findall(r"@(\d+)", m.group(1))]
        out["cpu_freq_mhz"] = freqs
        out["cpu_busy_cores"] = sum(1 for x in re.findall(r"(\d+)%", m.group(1)) if int(x) > 50)
    return out


def box_state() -> dict:
    """The box state every number in this study is recorded beside."""
    st: dict = {"ts": time.time()}
    try:
        st["load"] = [round(x, 2) for x in os.getloadavg()]
    except Exception:
        pass
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    st["mem_available_mb"] = int(line.split()[1]) // 1024
                    break
    except Exception:
        pass
    try:
        p = subprocess.run(["nvidia-smi", "--query-gpu=utilization.gpu,memory.used",
                            "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=6)
        out = p.stdout.strip().splitlines()[0]
        st["gpu_util_pct"], st["gpu_mem_mb"] = [x.strip() for x in out.split(",")]
    except Exception:
        pass
    st.update(_tegrastats_once())
    return st


def summarise_state(states: list[dict]) -> dict:
    """A compact, publishable summary of a block of measurements."""
    if not states:
        return {}
    def col(k):
        vals = [s[k] for s in states if isinstance(s.get(k), (int, float))]
        return (round(min(vals), 1), round(max(vals), 1)) if vals else None
    loads = [s["load"][0] for s in states if s.get("load")]
    return {
        "n_samples": len(states),
        "load1_min_max": (round(min(loads), 2), round(max(loads), 2)) if loads else None,
        "mem_available_mb_min_max": col("mem_available_mb"),
        "gpu_util_pct_min_max": col("gpu_util_pct"),
        "vdd_gpu_w_min_max": col("vdd_gpu_w"),
        "gpu_temp_c_min_max": col("gpu_temp_c"),
        "states": states,
    }


# --------------------------------------------------------------------------
# statistics
# --------------------------------------------------------------------------

def pct(xs: list[float], p: float) -> float:
    if not xs:
        return float("nan")
    s = sorted(xs)
    if len(s) == 1:
        return s[0]
    k = (len(s) - 1) * p / 100.0
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def stats(xs: list[float]) -> dict:
    return {
        "n": len(xs),
        "min": round(min(xs), 2) if xs else None,
        "p50": round(pct(xs, 50), 2) if xs else None,
        "p90": round(pct(xs, 90), 2) if xs else None,
        "max": round(max(xs), 2) if xs else None,
        "mean": round(sum(xs) / len(xs), 2) if xs else None,
    }


# --------------------------------------------------------------------------
# the decision server
# --------------------------------------------------------------------------

def port_free(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) != 0


@dataclass
class Server:
    """One llama-server that we own and will stop."""

    model: str
    precision: str = "Q8"
    port: int = 8290
    alias: str | None = None
    ctx_size: int = 4096
    n_gpu_layers: int = 99
    extra_args: list[str] = field(default_factory=list)
    proc: subprocess.Popen | None = None
    log: Path | None = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def start(self, timeout_s: float = 420.0) -> "Server":
        subdir, weights, mmproj = MODELS[self.model][self.precision]
        mpath = MODELS_DIR / subdir / weights
        if not mpath.exists():
            raise FileNotFoundError(f"weights missing: {mpath}")
        if not port_free(self.port):
            raise RuntimeError(f"port {self.port} is already in use")

        cmd = [str(LLAMA_SERVER), "-m", str(mpath), "--host", "127.0.0.1",
               "--port", str(self.port), "-ngl", str(self.n_gpu_layers),
               "--flash-attn", "on", "--ctx-size", str(self.ctx_size),
               "-ub", "4096", "--alias", self.alias or f"{self.model}-{self.precision}"]
        if mmproj and os.environ.get("LAB_USE_MMPROJ") == "1":
            ppath = MODELS_DIR / subdir / mmproj
            if ppath.exists():
                cmd += ["--mmproj", str(ppath)]
        cmd += list(self.extra_args)

        self.log = LOGS / f"server-{self.port}-{self.model}-{self.precision}.log"
        fh = self.log.open("w")
        self.proc = subprocess.Popen(cmd, stdout=fh, stderr=subprocess.STDOUT,
                                     start_new_session=True)

        deadline = time.time() + timeout_s
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(f"server died; see {self.log}")
            try:
                urllib.request.urlopen(f"{self.url}/health", timeout=2).read()
                return self
            except Exception:
                time.sleep(0.5)
        self.stop()
        raise TimeoutError(f"server not ready in {timeout_s}s; see {self.log}")

    def stop(self) -> None:
        if self.proc is None:
            return
        try:
            os.killpg(os.getpgid(self.proc.pid), signal.SIGTERM)
        except Exception:
            try:
                self.proc.terminate()
            except Exception:
                pass
        try:
            self.proc.wait(timeout=25)
        except Exception:
            try:
                os.killpg(os.getpgid(self.proc.pid), signal.SIGKILL)
            except Exception:
                pass
        self.proc = None

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()


# --------------------------------------------------------------------------
# the /v1/systemone client
# --------------------------------------------------------------------------

def _post(url: str, path: str, payload: dict | None = None, timeout: float = 120.0,
          method: str = "POST") -> tuple[int, dict, float]:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = json.loads(r.read().decode())
            return r.status, body, time.perf_counter() - t0
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="replace")
        try:
            body = json.loads(raw)
        except Exception:
            body = {"raw": raw}
        return e.code, body, time.perf_counter() - t0


def decide(url: str, state, questions: dict, timeout: float = 120.0) -> tuple[int, dict, float]:
    """One /v1/systemone decision round. Returns (status, body, seconds)."""
    return _post(url, "/v1/systemone",
                 {"state": state, "questions": questions}, timeout=timeout)


def get_json(url: str, path: str, timeout: float = 30.0) -> tuple[int, dict]:
    try:
        with urllib.request.urlopen(url + path, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="replace")
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {"raw": raw}
    except Exception as e:
        return 0, {"error": str(e)}


def get_text(url: str, path: str, timeout: float = 30.0) -> tuple[int, str]:
    """Fetch a non-JSON endpoint (llama.cpp's /metrics is Prometheus text)."""
    try:
        with urllib.request.urlopen(url + path, timeout=timeout) as r:
            return r.status, r.read().decode(errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace")
    except Exception as e:
        return 0, str(e)


def warm_gpu(url: str, questions: dict, seconds: float = 3.0) -> dict:
    """Ramp the GPU clocks before timing anything (IDEAS.md rule 3).

    The GPU idles at 315 MHz and takes ~1.4 s to reach 1575 MHz; a cold
    reading is 2.6x slow. We keep a decision loop running for `seconds` and
    report the state at the end of the warm-up.
    """
    t0 = time.time()
    n = 0
    while time.time() - t0 < seconds:
        decide(url, "warmup", questions)
        n += 1
    return {"warmup_requests": n, "seconds": round(time.time() - t0, 2),
            "state_after": box_state()}


def write_result(name: str, payload: dict) -> Path:
    path = RESULTS / name
    path.write_text(json.dumps(payload, indent=2, default=str))
    return path
