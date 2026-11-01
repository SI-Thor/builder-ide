#!/usr/bin/env python3
"""exp5b — ct-thor experiment 5: snapkit-v2's judge on the Thor's 14 cores.

The corpus figure "12.3 ms p50 at 4 threads on a Jetson" has no harness in
the snapkit-v2 repo (the README and docs carry no benchmark code), which is
why the corpus flags the ARM figure as unsupported. This script re-measures
the thing the figure refers to — the Harmony Governor judging a fleet of
agents, i.e. the per-tick `record_observation` pass (rolling-window spectral
summary: entropy + Hurst + autocorrelation, in pure Python) — on the Thor's
14 Neoverse cores at 1, 4, and 14 threads.

Fleet: 120 channels (the fleet size in the repo's own architecture doc),
window_size 128 (the repo default), 60 warm cycles, 120 timed cycles,
per-cycle wall time, p50/p10 reported.
"""

import sys
import time
import random
import statistics
import threading

sys.path.insert(0, "snapkit-v2")

from snapkit.governor import HarmonyGovernor  # noqa: E402

FLEET = 120
WARM = 60
TIMED = 120


def build_fleet(n):
    g = HarmonyGovernor()
    for i in range(n):
        # the MIDI bus has 16 channels; rooms are the per-agent abstraction,
        # so agents share channels round-robin (i % 16)
        g.register_channel(f"agent-{i:03d}", channel=i % 16)
    return g


def judge_cycle(g, names, rng, predictions, thread_idx=0, nthreads=1):
    """One judge pass over the fleet: each agent's prediction is recorded and
    the governor computes friction for it (spectral summary on the window)."""
    lo, hi = thread_idx * len(names) // nthreads, (thread_idx + 1) * len(names) // nthreads
    for k in range(lo, hi):
        name = names[k]
        g.record_observation(name, predictions[k], predictions[k] + rng.uniform(-1, 1), 0.3)


def run_threads(g, names, rng, predictions, nthreads):
    """One cycle, split across `nthreads` Python threads."""
    if nthreads == 1:
        judge_cycle(g, names, rng, predictions, 0, 1)
        return
    ths = []
    for t in range(nthreads):
        th = threading.Thread(target=judge_cycle,
                              args=(g, names, rng, predictions, t, nthreads))
        th.start()
        ths.append(th)
    for th in ths:
        th.join()


def main():
    print("=== exp5b: snapkit-v2 Harmony Governor judge on Thor, "
          f"fleet of {FLEET} agents ===")
    g = build_fleet(FLEET)
    names = sorted(g._channels.keys())
    rng = random.Random(42)
    predictions = [rng.uniform(0, 1) for _ in range(FLEET)]

    print("warming (fills the 128-sample windows so the spectral path runs)...")
    for _ in range(WARM):
        run_threads(g, names, rng, predictions, 1)

    print(f"timing {TIMED} judge cycles per thread count...")
    for nthreads in (1, 4, 14):
        cycles = []
        for _ in range(TIMED):
            t0 = time.perf_counter()
            run_threads(g, names, rng, predictions, nthreads)
            cycles.append((time.perf_counter() - t0) * 1e3)
        cycles.sort()
        p10 = cycles[len(cycles) // 10]
        p50 = cycles[len(cycles) // 2]
        p90 = cycles[9 * len(cycles) // 10]
        print(f"  {nthreads:>2} threads: p50 {p50:8.2f} ms/cycle   "
              f"p10 {p10:8.2f}   p90 {p90:8.2f}   "
              f"mean {statistics.mean(cycles):8.2f}   "
              f"({FLEET / p50 * 1e3:,.0f} agent-judgements/s)")


if __name__ == "__main__":
    main()
