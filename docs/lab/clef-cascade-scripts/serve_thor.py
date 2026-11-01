"""Serve the d1 decision models ourselves, on ports we pick, and stop them.

We use the same llama.cpp build that already serves last-mile's d1
models (~/llama.cpp-upstream/build-up/bin/llama-server), which speaks
POST /v1/systemone -- the protocol last-mile's agents and the TypeSafe
Jev provider both speak.

We do not touch the box's other services. These servers are ours, they
live for the duration of a sweep, and they are stopped at the end.
"""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

LAB = Path(__file__).resolve().parent.parent
LOGS = LAB / "logs"
LOGS.mkdir(exist_ok=True)

LLAMA_SERVER = Path(os.environ.get(
    "LLAMA_SERVER", "/home/caseydigennaro/llama.cpp-upstream/build-up/bin/llama-server"))

#: The nine (model, precision) cells of the precision ladder.
#: model key -> (directory, weights filename, mmproj filename or None)
MODEL_FILES: dict[str, dict[str, tuple[str, str, str | None]]] = {
    "d1-omni-600M": {
        "Q4": ("d1-omni-600M", "d1-omni-600M-Q4_K_M.gguf", "mmproj-d1-omni-600M-Q4_K_M.gguf"),
        "Q8": ("d1-omni-600M", "d1-omni-600M-Q8_0.gguf", "mmproj-d1-omni-600M-Q8_0.gguf"),
        "BF16": ("d1-omni-600M", "d1-omni-600M-BF16.gguf", "mmproj-d1-omni-600M-BF16.gguf"),
    },
    "d1-2B": {
        "Q4": ("d1-2B", "d1-2B-Q4_K_M.gguf", "mmproj-d1-2B-Q4_K_M.gguf"),
        "Q8": ("d1-2B", "d1-2B-Q8_0.gguf", "mmproj-d1-2B-Q8_0.gguf"),
        "BF16": ("d1-2B", "d1-2B-BF16.gguf", "mmproj-d1-2B-BF16.gguf"),
    },
    "d1-3B": {
        "Q4": ("d1-3B", "d1-3B-Q4_K_M.gguf", "mmproj-d1-3B-Q4_K_M.gguf"),
        "Q8": ("d1-3B", "d1-3B-Q8_0.gguf", "mmproj-d1-3B-Q8_0.gguf"),
        "BF16": ("d1-3B", "d1-3B-BF16.gguf", "mmproj-d1-3B-BF16.gguf"),
    },
}

MODELS_DIR = Path(os.environ.get("MODELS_DIR", "/home/caseydigennaro/models"))


def port_free(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) != 0


@dataclass
class Server:
    """One llama-server we own."""

    model: str
    precision: str
    port: int
    alias: str
    proc: subprocess.Popen | None = None
    log: Path | None = None

    def start(self, ctx_size: int = 4096, n_gpu_layers: int = 99,
              parallel: int = 1, host: str = "127.0.0.1",
              timeout_s: float = 420.0,
              cache_reuse: int = 0, slot_prompt_similarity: float = 0.0,
              cache_ram: int = 0, seed: int | None = None,
              temp: float | None = None, top_p: float | None = None,
              retries: int = 2) -> "Server":
        spec = MODEL_FILES[self.model][self.precision]
        subdir, weights, mmproj = spec
        mpath = MODELS_DIR / subdir / weights
        if not mpath.exists():
            raise FileNotFoundError(f"weights missing: {mpath}")
        ppath = MODELS_DIR / subdir / mmproj if mmproj else None
        if ppath is not None and not ppath.exists():
            ppath = None

        if not port_free(self.port, host):
            raise RuntimeError(f"port {self.port} is already in use")

        cmd = [str(LLAMA_SERVER), "-m", str(mpath), "--host", host,
               "--port", str(self.port), "-ngl", str(n_gpu_layers),
               "--flash-attn", "on", "--ctx-size", str(ctx_size),
               "-ub", "4096", "--alias", self.alias]
        # The vision projector: all three lab tasks are text-only, so by
        # default we do not load it -- one less variable and less memory.
        # It is loaded when a task needs images.
        if ppath is not None and os.environ.get("LAB_USE_MMPROJ") == "1":
            cmd += ["--mmproj", str(ppath)]
        if parallel > 1:
            cmd += ["--parallel", str(parallel), "--cont-batching"]
        # The runtime's own prompt/state cache. The server logs say
        # "decision model: prompt cache disabled by default, use
        # --cache-ram N to enable it" -- this is the Liquid internal-state
        # lever E3 asks about: a cached prefix state per task.
        if cache_ram:
            cmd += ["--cache-ram", str(cache_ram)]
        if cache_reuse:
            cmd += ["--cache-reuse", str(cache_reuse)]
        if slot_prompt_similarity:
            cmd += ["--slot-prompt-similarity", str(slot_prompt_similarity)]
        if seed is not None:
            cmd += ["--seed", str(seed)]
        if temp is not None:
            cmd += ["--temp", str(temp)]
        if top_p is not None:
            cmd += ["--top-p", str(top_p)]

        self.log = LOGS / f"server-{self.alias}.log"
        fh = self.log.open("w")
        self.proc = subprocess.Popen(cmd, stdout=fh, stderr=subprocess.STDOUT,
                                     start_new_session=True)

        deadline = time.time() + timeout_s
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(f"server {self.alias} died; see {self.log}")
            try:
                import urllib.request
                urllib.request.urlopen(f"http://{host}:{self.port}/health", timeout=2).read()
                return self
            except Exception:
                time.sleep(0.5)
        self.stop()
        raise TimeoutError(f"server {self.alias} not ready in {timeout_s}s; see {self.log}")

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
            self.proc.wait(timeout=20)
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


def alias_for(model: str, precision: str) -> str:
    return f"{model}-{precision}"


def main() -> int:
    """CLI: serve one cell, wait, and stop. `python serve.py <model> <precision> [port]`"""
    model, precision = sys.argv[1], sys.argv[2]
    port = int(sys.argv[3]) if len(sys.argv) > 3 else 8099
    s = Server(model, precision, port, alias_for(model, precision))
    s.start()
    print(f"serving {s.alias} on :{port} (pid {s.proc.pid}); ctrl-c to stop")
    try:
        while True:
            time.sleep(1)
            if s.proc.poll() is not None:
                print("server exited")
                return 1
    except KeyboardInterrupt:
        s.stop()
        print("stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
