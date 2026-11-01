# Incident, 2026-11-01: the Thor hung after a JAX run preallocated unified memory

**Impact.** The Thor dropped off the network at ~10:45 (no ping, "No route to host") and needed a power cycle (back at 10:59). Running work on the Thor died with it: two zcode seats, agent-world, the sweep and the local coder. ProArt-side seats driving the Thor over ssh survived (their calls failed, then resumed).

**Cause (strong circumstantial evidence; the boot left no journal, which fits a hard hang).**
- At 10:40 the lab-motion seat (pi, Nemotron-Ultra) wrote in NOTES.md: "creating training script for the spike … on MJX (JAX backend)", then started it. Five minutes later the box hung.
- After the reboot, the same seat, still running on the ProArt, relaunched the run (`train_spike.py --backend mjx --nworld 256`) at 11:02. Within 20 seconds it held **94.5 GB of GPU memory**, leaving 15 GB available.
- **The mechanism:** JAX/XLA **preallocates most of the GPU's memory by default** (`XLA_PYTHON_CLIENT_PREALLOCATE` defaults to true; the default fraction is 75–90%). On a discrete GPU that is a private pool. **On the Thor, GPU memory is the system's unified memory**, so one JAX process takes most of the machine's RAM before it computes anything. The seat's notes planned to scale to 1k and 4k worlds next. The first run likely hung the box that way, with unified-memory pressure the kernel's OOM killer did not resolve in time.
- The run was started **outside thor-admit** (no lease), so neither the admission floor nor the watchdog saw it.

**What stopped it the second time.** The director's kill was blocked by the session's safety classifier ("interfere with workloads"), and stopping the seat's ssh session did not stop the detached run. The run ended by itself within minutes. Casey then granted full operational permission for this project, so a runaway can be stopped directly next time.

**What changed.**
1. **A house rule, now in every brief:** never start JAX without `XLA_PYTHON_CLIENT_PREALLOCATE=false`; set `XLA_PYTHON_CLIENT_MEM_FRACTION` (0.15) or the platform allocator; run under `thor-admit run` with an explicit peak (start ≤ 16 GB); scale one step at a time and record peak memory.
2. **Any framework that preallocates** (JAX, TensorFlow, some PyTorch allocator settings) is a hazard on unified memory. The same rule applies.
3. **Open question for thor-admit (round 12):** processes outside any lease are invisible to the watchdog. Options: a box-wide watchdog that acts on the largest *unleased* process near the emergency floor, or a wrapper that refuses to start GPU frameworks without a lease. Weigh the risk of killing unknown work.

**Related:** the 2026-10-31 13:22 OOM crash (seats co-scheduling heavy steps; `feedback-thor-memory-admission`), which led to thor-admit itself.
