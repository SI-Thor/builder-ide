#!/usr/bin/env python3
"""What one llama-server holds of the Thor's GPU, under the night's own load.

`measure_llama_gpu.sh` (same directory) measured the servers **at rest** —
after /health answered, before any request — and found almost no difference
between the flag sets (3.33 GB vs 3.00 GB). That is not the number the
heavy phase lives with: llama.cpp sizes its **compute buffer** when the
first batch of a given shape arrives, so the number that matters is the
one under a real request. This script measures that.

Each configuration is started under its own thor-admit lease (practice
tier, 20 GB peak), asked the night's own request shapes, and measured with
nvidia-smi's per-process query (the same source the guard reads) plus the
server's own /proc status. The server's log is kept beside the results,
because llama-server prints its KV and compute-buffer sizes at startup.

The request shapes are the night's, not stand-ins:

  judge     POST /v1/systemone, a state the length of a recorder state and
            one noul question — the shape of the night's 245 decisions
            (asked twice, because the compute buffer arrives with the
            first batch and the second call shows the steady state)
  delegate  POST /v1/systemone, the night's own crate picture with the six
            fixed class questions — the shape of the d1-2B's work

There is no /completion on this build of llama-server (501 Not
Implemented): it is a System One decision-model server, so the night's
request shapes are the only shapes it has.

Run on the Thor (stdlib only, no venv needed):

  python3 docs/lab/night-v5-scripts/measure_llama_gpu_under_load.py

It takes about four minutes and prints one block per configuration.
"""
from __future__ import annotations

import base64
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HOME = Path.home()
SERVER = HOME / "llama.cpp-upstream" / "build-up" / "bin" / "llama-server"
ADMIT = HOME / "lm-tools" / "thor-admit"
OUT = Path(__file__).resolve().parent / "results"
PORT = 8297
CRATE = HOME / "lm-wt" / "trellis" / "out" / "genbatch" / "crate_s102_00003_.png"

#: The six fixed class questions, in the words the night asks them.
CLASS_QUESTIONS = {
    "holes": "Does the image show holes or missing material in the main object?",
    "missing_object": "Is the main object missing or absent from the image?",
    "texture_swap": "Does the object's texture look swapped or mismatched?",
    "noise_fireflies": "Is there visible noise or fireflies in the image?",
    "black_frame": "Is the image a black or nearly black frame?",
    "floating_object": "Does an object float impossibly in the image?",
}

#: A recorder-state-length state for the judge request (about 250 tokens).
STATE = (
    "The harbour at first light. The sea state is the question: calm, "
    "swell, choppy or rough. The recorder names a truth and a decoy, once "
    "each, and the order is the caller's. The state here carries the wind "
    "(north-west, fourteen knots), the tide (rising, two hours to high), "
    "the fetch (eighty miles) and the observed whitecaps (a few, on the "
    "far side). The question is which sea state the model reads in the "
    "presentation, not the truth: on the steps where the decoy was named "
    "first, the 2B's answer tracked the presentation rather than the "
    "truth, and the 3B's did not. This state is the same shape as the "
    "fixed recorder's two hundred and forty states, long enough to fill a "
    "prefill batch and no longer."
)

LONG_PROMPT = "The night measures what it keeps and writes down what it measures. " * 480  # ~4700 tokens


def per_process_gpu() -> dict[int, int]:
    out = subprocess.run(
        ["nvidia-smi", "--query-compute-apps=pid,used_memory",
         "--format=csv,noheader,nounits"],
        capture_output=True, text=True).stdout.strip()
    result: dict[int, int] = {}
    for line in out.splitlines():
        pid, mib = [x.strip() for x in line.split(",")]
        result[int(pid)] = int(mib)
    return result


def server_pid(port: int) -> int | None:
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            if (entry / "comm").read_text().strip() != "llama-server":
                continue
            argv = (entry / "cmdline").read_bytes().decode(errors="replace").split("\0")
            if str(port) in argv:
                return int(entry.name)
        except OSError:
            continue
    return None


def post(path: str, body: dict, timeout: float = 180.0) -> dict:
    request = urllib.request.Request(
        f"http://127.0.0.1:{PORT}{path}",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read())


def wait_healthy(runner: subprocess.Popen, seconds: int = 180) -> bool:
    for _ in range(seconds):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{PORT}/health", timeout=1)
            return True
        except Exception:
            if runner.poll() is not None:
                return False
            time.sleep(1)
    return False


def proc_status(pid: int) -> str:
    try:
        text = Path(f"/proc/{pid}/status").read_text()
        rss = text.split("VmRSS:")[1].split("kB")[0].strip()
        hwm = text.split("VmHWM:")[1].split("kB")[0].strip()
        return f"RSS {int(rss)/1024:.0f} MB, peak RSS {int(hwm)/1024:.0f} MB"
    except OSError:
        return "gone"


def kill_server(pid: int | None) -> None:
    """Stop the server by pid, and only by pid: the box has other seats'
    llama-servers, and a pattern kill would take one of theirs."""
    import os
    import signal
    if pid is None:
        return
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.kill(pid, sig)
        except (OSError, ProcessLookupError):
            return
        for _ in range(50):
            if not Path(f"/proc/{pid}").exists():
                return
            time.sleep(0.2)


def measure(label: str, model: Path, mmproj: Path | None, extra: list[str],
            requests: list[tuple[str, dict]]) -> None:
    log = OUT / f"llama-load-{label}.log"
    if server_pid(PORT) is not None:
        print(f"=== {label}: SKIPPED — something already holds :{PORT} ===")
        return
    argv = [str(ADMIT), "run", "--tier", "practice", "--peak", "20G",
            "--label", f"night-v5.llama-load.{label}", "--",
            str(SERVER), "-m", str(model), "--host", "127.0.0.1",
            "--port", str(PORT), "-ngl", "99", "--flash-attn", "on",
            "--alias", "probe", *extra]
    if mmproj is not None:
        argv += ["--mmproj", str(mmproj)]
    peak: dict[str, int] = {}

    def sampler(pid_holder: dict) -> None:
        import threading
        def run() -> None:
            while pid_holder.get("stop") is False:
                gpu = per_process_gpu()
                pid = pid_holder.get("pid")
                if pid in gpu:
                    peak["gpu"] = max(peak.get("gpu", 0), gpu[pid])
                time.sleep(0.2)
        threading.Thread(target=run, daemon=True).start()

    with open(log, "w") as fh:
        runner = subprocess.Popen(argv, stdout=fh, stderr=subprocess.STDOUT,
                                  stdin=subprocess.DEVNULL,
                                  start_new_session=True)
    pid = None
    holder: dict = {"pid": None, "stop": False}
    try:
        if not wait_healthy(runner):
            print(f"=== {label}: NOT READY (see {log}) ===")
            return
        pid = server_pid(PORT)
        if pid is None:
            print(f"=== {label}: no llama-server found on :{PORT} ===")
            return
        holder["pid"] = pid
        sampler(holder)
        print(f"=== {label} ===  pid {pid}; flags: {' '.join(extra)}")
        print(f"  at rest : GPU {per_process_gpu().get(pid)} MiB; {proc_status(pid)}")
        for name, body in requests:
            peak["gpu"] = per_process_gpu().get(pid, 0)
            started = time.perf_counter()
            try:
                post("/v1/systemone", body)
                verdict = f"{time.perf_counter() - started:.2f} s"
            except Exception as exc:  # noqa: BLE001 - the row records the failure
                verdict = f"FAILED: {exc}"
            gpu = per_process_gpu().get(pid)
            print(f"  {name:<9}: GPU {gpu} MiB (peak {peak.get('gpu')} MiB); "
                  f"{proc_status(pid)}; {verdict}")
        for line in log.read_text(errors="replace").splitlines():
            if any(key in line for key in ("KV self size", "compute buffer",
                                           "CUDA0 model buffer size",
                                           "total ctx size")):
                print(f"  server says: {line.strip()}")
    finally:
        holder["stop"] = True
        kill_server(pid)
        runner.terminate()
        try:
            runner.wait(timeout=10)
        except subprocess.TimeoutExpired:
            runner.kill()
        time.sleep(3)


def main() -> None:
    OUT.mkdir(exist_ok=True)
    d3 = HOME / "models" / "d1-3B" / "d1-3B-Q8_0.gguf"
    d2 = HOME / "models" / "d1-2B" / "d1-2B-Q8_0.gguf"
    mm = HOME / "models" / "d1-2B" / "mmproj-d1-2B-Q8_0.gguf"
    judge_body = {"state": STATE, "questions": {
        "sea_state": {"type": "noul",
                      "instructions": "Is the sea state rough rather than calm?"}}}
    long_body = {"prompt": LONG_PROMPT, "n_predict": 8}
    image_body = {
        "state": None,
        "images": ["data:image/png;base64,"
                   + base64.b64encode(CRATE.read_bytes()).decode()],
        "questions": {qid: {"type": "noul", "instructions": text}
                      for qid, text in CLASS_QUESTIONS.items()},
    }
    night = ["--ctx-size", "8192", "-ub", "4096"]
    shrunk = ["--ctx-size", "4096", "-ub", "1024"]
    measure("d1-3B-night", d3, None, night,
            [("judge", judge_body), ("judge2", judge_body)])
    measure("d1-3B-shrunk", d3, None, shrunk,
            [("judge", judge_body), ("judge2", judge_body)])
    measure("d1-2B-night", d2, mm, night,
            [("judge", judge_body), ("delegate", image_body)])
    measure("d1-2B-shrunk", d2, mm, shrunk,
            [("judge", judge_body), ("delegate", image_body)])
    print("=== the box after ===")
    print(per_process_gpu())


if __name__ == "__main__":
    sys.exit(main())
