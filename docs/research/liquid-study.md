# liquid-study — two idea chats, read hard, checked against the box

**Date:** 2026-10-31 · **Seat:** `liquid-study` (`~/lm-wt/liquid-study`) · **Box:** NVIDIA Jetson AGX Thor
Developer Kit (aarch64, tegra264, 122 GB unified LPDDR5X, Blackwell sm_110, CUDA 13.2, JetPack 7.2.1 / L4T 39.2.1, driver 595.78)

**Sources read in full:** `liquid1.md` (1567 lines) and `liquid2.md` (2015 lines) — 38,926 words;
`~/src/builder-ide/CLAUDE.md`, `docs/vision.md`, `docs/design/tiles.md`, `docs/research/jev.md`,
`docs/lab/IDEAS.md` (Parts 0 and B); `~/lm-wt/lab-cascade/BRIEF.md` and `~/lm-wt/lab-fp4/BRIEF.md`.

**Read after the study began, folded in by the ProArt seat (2026-10-31, writing only — no hardware
was touched):** builder-ide's `docs/research/pincher-fit.md`, `core/hysteresis/README.md` and
`docs/lab/exp-genbatch-plausibility.md`; lab-cascade's `exp-cascade.md` §3 (the E1 result, §1.4
below). Consequences: **§4.2 is recorded as crashed, not measured** — the state-snapshot check never
completed, and every "§4.2" sentence that read as a box measurement has been re-worded to what the
llama.cpp source establishes; Part 3 is written; the lab-cascade E1 results are folded in as §1.4
and as dated notes on I1, I2 and I4. Every number is the runner seat's, unchanged.

**Rules honoured:** everything is in this directory. Nothing in `~/src/builder-ide` or another lab's
directory was edited. No system installs; no repo cited by the chats was cloned or run. No other seat's
job or service was stopped. No LLM is hosted on the Thor beyond the d1 decision models. No sub-agents.

**How to reproduce every number here:** `scripts/run_part2.sh` (takes `~/lm-wt/heavy.lock` and queues
behind other seats) reproduces Parts 2's numbers; §1.4's and the fold-ins' numbers reproduce from
lab-cascade's `exp-cascade.md` §8, not from anything in this directory. `scripts/d1lab.py` holds the
shared helpers, including the box-state sampler that records load, `MemAvailable`, GPU utilisation
and the VDD_GPU rail beside every measurement.

---

## 0. The box, in one paragraph, because the chats are about a different box

Both chats are written about a **DRIVE AGX Thor**: DriveOS 7, DriveWorks, GMSL2 cameras, a CAN bus,
NVMedia capture buffers, a separate safety island, an NVLink-C2C link between CPU and GPU. Ours is a
**Jetson AGX Thor devkit**: JetPack 7.2.1, no cameras, no DriveOS, CPU and GPU sharing one 128 GB
LPDDR5X pool, no MIG, no `tcgen05`/TMEM. The translation is not cosmetic — it removes the mechanism
several of the chats' most concrete ideas depend on, and it *adds* one they never had: the CPU and GPU
are the same memory, so "shipping a model state to the cloud" is a copy out of ordinary RAM.

Three measured facts that reframe everything downstream:

* `nvidia-smi` cannot see GPU memory or SM clocks on this box (`memory.used = [N/A]`,
  `clocks.current.sm = [N/A]`) — the fourth and fifth confirmation in builder-ide's IDEAS.md. The box's
  GPU state is observable through `tegrastats` (VDD_GPU millwatts, temperatures, per-core frequencies)
  and through CUDA itself, not through `nvidia-smi`.
* CUDA reports `multiProcessorCount = 20`, `l2CacheSize = 32 MiB`, `memoryBusWidth = 256`,
  `memoryClockRate = 4266 MHz`. Twenty SMs is the real number; "2560 CUDA cores" is 20 × 128.
* The d1 models on this box are **Liquid's own decision models**, and llama.cpp upstream has a
  first-class path for them. `~/models/d1-3B` is `lfm2-d1` (LFM2 architecture, 32k context),
  `~/models/d1-2B` is `lfm3-d1` (LFM3 architecture, 128k context), `~/models/d1-omni-600M` is
  `lfm2-d1-omni`. The decision type is read from the GGUF's `<arch>.decision.type` key, so "d1" needs
  no server flag. They are served over `POST /v1/systemone`, which returns **calibrated probabilities
  over a fixed option set and zero generated tokens** — the head maps hidden states straight to
  Noul / Choice / Score.

That last point is the single most useful thing this study found, and the chats never had it.

### 0.1 The d1 models already have a designed seat in builder-ide

`docs/research/jev.md` is 39 lines and settles the most important question this study had to answer:
**where do these models go?**

* Jev is a **cloud** model behind an MCP server (`@jkudish/jev-mcp`, MIT; TypeSafe's Jev model behind
  it), twelve tools that return *typed verdicts with probability distributions and a confidence score*
  — `verify`, `screen`, `noul`, `find`, `rerank`, `classify`, `decide`, `compare`, `extract`, `audit`,
  `review`, `gate` — at **150–500 ms** per call.
* **d1's local shape is the same shape.** llama.cpp's d1 question types are `choice`, `score` and
  `noul`; the answer is a probability vector plus a confidence, with **zero generated tokens**. Jev's
  `noul`, `decide` and `classify` are the same three kinds of answer.
* The core's plan already names the seam: *"A small adapter in the core (`core/judge/`): Jev behind one
  interface with a fake for tests. Every judgment is recorded in the ledger with its distribution and
  cost."* **That adapter is where a local d1 decision model plugs in** — same interface, no cloud call,
  no per-call cost, tens of milliseconds instead of hundreds. (`core/judge/` does not exist yet; it is
  a plan. `core/vocab/call.py` and `core/svc/predictions.py` are the nearest real service seams.)
* And the tiles seat already plans for it by name: *"Tiles: labelling play outcomes — `jev_classify` in
  batches … These are the training labels for **the local decision models**, with the probability kept
  as a soft label"*, and *"Tiles: the shortlist — `jev_rerank` pre-ranks a large library down to the few
  candidates **the local decision model** chooses among at play time."*

So the chats' central wish — a fast, local, typed decision model in the loop — is not a proposal for
builder-ide. It is a requirement builder-ide has already written down, with the seat (`core/judge/`)
named and the interface shape specified. The d1 models in `~/models/` are the local half of it, and
Jev is the cloud half. The gap is that the adapter has not been written and the local half has never
been measured on builder-ide's own data.

---

## Part 1 — the study

### 1.1 Claims check

Every concrete technical claim in the two chats, sorted into **true on our box**, **false for us**, or
**unverified** (with the check that would settle it). "Our box" means the Jetson AGX Thor devkit named
above. Names were checked for existence only; nothing the chats cite was run.

#### 1.1.1 Hardware and platform

| # | claim | verdict | evidence / what would settle it |
|---|---|---|---|
| H1 | The GPU is Blackwell, compute capability 11.0 (`sm_110`) | **true** | `cudaDeviceGetAttribute`: `multiProcessorCount = 20`; lab-fp4's bench header records `cc=11.0`; `nvcc --list-gpu-arch` lists `sm_110`; `__CUDA_ARCH_SPECIFIC__ = 1100` for `sm_110a` |
| H2 | "2,000 FP4 TFLOPS" / "2070 TFLOPS" | **true as a datasheet figure, false as a budget** | NVIDIA's Jetson Thor page: 2070 TFLOPS is **sparse FP4**; dense FP4/FP8/INT8 is 1035 and dense FP16/FP8 is 517. Measured on our box: BF16 **100–109 TFLOPS**, FP8 **178–236**, NVFP4 **371–456** (lab-fp4's in-flight `results/sweep-main.txt`). So the reachable dense FP4 figure is ≈**456 TFLOPS max, ~44 % of the dense spec and ~22 % of the sparse headline** |
| H3 | 128 GB LPDDR5X at 273 GB/s | **true as spec, false as a budget** | 256-bit @ 4266 MHz = 273 GB/s theoretical; `memoryClockRate = 4266000 kHz`, `memoryBusWidth = 256` confirmed via CUDA. Achieved: **166 GB/s eager, ~220 GB/s graphed** (IDEAS.md Part 0) — 0.61–0.81× |
| H4 | 14-core Arm Neoverse V3AE | **true** | `/proc/cpuinfo` + device tree; `tegrastats` reports exactly 14 CPU cores at up to 2601 MHz |
| H5 | "2560 CUDA cores, 96 fifth-generation Tensor Cores" | **true as marketing, misleading as architecture** | CUDA reports **20 SMs**. The tensor cores on sm_110 are the consumer-Blackwell generation: they use the Ada-style `mma.sync` path, **not** `tcgen05`/TMEM (see H8) |
| H6 | The Thor supports **MIG** partitioning | **false for us** | `nvidia-smi` has **no `mig` subcommand at all** on this box; `nvidia-smi -q` reports MIG Mode Disabled / Pending Disabled. The datasheet line "Multi Instance GPU (MIG) with 10 TPCs" describes the GPU's capability; the Jetson devkit does not expose MIG partitioning |
| H7 | **MMIO**: "map Thor's physical MMIO base addresses into the CUDA virtual memory allocation space", `0x3F000000` as an ASIL-D base | **false as stated** | `0x3F000000` is not a device on this box — the only neighbour in `/proc/iomem` is `actmon@d3f0000`. The SoC's platform devices *are* memory-mapped at real addresses, but `cudaHostGetDevicePointer` on a physical register address is not a way to reach them; device registers are reached by their own drivers. There is no public MMIO programming model here |
| H8 | **tcgen05** / TMEM / "5th-gen tensor cores with TMEM" | **false for us** | Decisive and local: NVIDIA's own header on this box says `tcgen05.mma ... PTX ISA 86, SM_100a, SM_100f, SM_103a, SM_103f`, and the compile-time guard fires on `__CUDA_ARCH_SPECIFIC__ == 1000 || 1030`. `sm_110a` gives `__CUDA_ARCH_SPECIFIC__ = 1100`. **tcgen05 does not exist on sm_110**; it is datacenter Blackwell |
| H9 | **TMA** (`cp.async.bulk.tensor`), speculative pre-staging into shared memory | **true** | Compiled and linked for `sm_110` with CUDA 13.2: `cp.async.bulk.tensor.2d.shared::cluster.global.tile.mbarrier::complete_tx::bytes` and the 1-D `cp.async.bulk` variant both build at `sm_90`, `sm_110` and `sm_110a` |
| H10 | **mbarrier** | **true** | `mbarrier.init.shared::cta.b64` compiles for `sm_110` |
| H11 | "warp-shuffle registers" for a final classification layer | **true of the instruction, false of the noun** | `shfl.sync` is a warp-level primitive available on every `sm_` — but there is no separate "warp-shuffle register file". A shuffle reads and writes the warp's ordinary 32-bit registers. The chat's mental model of a hidden register bank to map a classifier onto does not exist |
| H12 | Blackwell **Async Copy engines** moving NVMedia capture buffers into tensor-core shared registers | **false for us** | There are no NVMedia capture buffers: no `/dev/video*` nodes, no sensors. The capture plumbing is in the device tree (`mods_vi0`, `mods_vi1`, `mods_isp0/2`, `tegra-capture-isp`) but nothing is attached to it |
| H13 | **GPUDirect Storage** inside "DriveOS 7" | **false for us** | We run JetPack 7.2.1, not DriveOS. Separately: GDS on a **unified-memory** part is a different thing from GDS on a discrete/host-memory part — and IDEAS.md already measured that the box's external FUSE shelf "stalled and took I/O down with it", so the box's own I/O story is settled against any NVMe ring buffer idea |
| H14 | "No RT cores" | **true as a Linux CPU claim, with a correction** | No RT core appears in `/proc/cpuinfo` (14 Neoverse cores only) and the `rtcpu` device-tree node has no `cpu@` children. **But** the safety island *is* present in silicon: `/proc/device-tree/rtcpu@81893d0000` with `nvidia,cpu-name = "rce"`, `status = okay`, and four `hsp-vm1..4` partitions. It is not a programmable Linux CPU on this SKU. IDEAS.md's stronger phrasing ("no safety island") is wrong in the device-tree sense |
| H15 | No NVDLA, no OFA | **true** | Absent from `/dev` and the device tree (IDEAS.md Part B, R3). Confirmed again: no `nvidia,nvdl@*` or `nvidia,ofa@*` nodes |
| H16 | **NVLink-C2C** at 900 GB/s between CPU and GPU | **false for us** | That is DRIVE AGX Thor's CPU↔GPU link. On the Jetson devkit there is no NVLink-C2C: CPU and GPU share the same 128 GB LPDDR5X, which is exactly why IDEAS.md's headline measured fact holds — *"host `malloc` memory is device-addressable; kernels read/write NumPy pages in place; torch↔cupy share one buffer via DLPack"* (`devicePointer == hostPointer`, verified at 4 GB) |
| H17 | DriveOS 7, DriveWorks, GMSL2 cameras, CAN bus, 4×25 GbE | **false for us** | JetPack 7.2.1 / L4T 39.2.1 / driver 595.78 on a devkit. The devkit has a CAN header and a QSFP28 cage, but no DriveOS, no DriveWorks, no GMSL camera stack (IDEAS.md Part B: "automotive Thor configurations, not this devkit") |

#### 1.1.2 Latency and performance claims about d1

| # | claim | verdict | evidence |
|---|---|---|---|
| L1 | "d1-3B at 16 ms" per decision | **misleading as stated — it is the marginal cost of an extra question in a shared-prefix pack, not the cost of a decision** | §4.1. A standalone decision on a fresh state costs several times that; the pack's first question pays the whole prefill |
| L2 | "d1 at 4 ms" | **false for us** | Same measurement: no path on this box reaches 4 ms per decision for d1-3B Q8 |
| L3 | "we measured ~90 ms for a 3-question pack, ~11 ms per option" | **true, and now explainable** | The pack shares one state prefix; the first question pays the prefill and each additional question pays ~11 ms. §4.1 reproduces and decomposes it |
| L4 | "Liquid models … executing entirely within uniform, single-digit millisecond windows" | **false for us** | The 600M model at Q8 measured 155–344 ms per standalone decision under load on this box (the crashed seat's run; box load 1 = 20.5, GPU 98 % — that run's result file was overwritten by §4.1's re-run, so the figure survives only as recorded here); d1-3B is slower. "Uniform" is also wrong: the cost splits sharply between "first question pays prefill" and "extra question pays margin" |
| L5 | "Precision is a lever: FP4 → FP16 promotion on uncertainty" | **false — there is no precision headroom to promote into** | lab-cascade's E1: precision changes **no** d1 accuracy — 0 of 27 within-size pairs significant (on T1 all nine cells are identical to the fourth decimal; on T2/T3 they differ by one or two items, never significantly); and 4-bit is *not* faster than 16-bit on the Thor (600M: BF16 p50 82 ms vs Q4 109 ms; 2B: BF16 273 ms vs Q4 313 ms). Precision buys **memory**, nothing else |
| L6 | "FP4 is a measured no on this box" (IDEAS.md Part B) | **now superseded — and this is the one live correction** | IDEAS.md measured 13.69 TFLOPS via torchao and concluded "the dtype exists, the path does not". lab-fp4's in-flight sweep reaches **371–456 TFLOPS NVFP4** through cuBLASLt's block-scaled path, with a real error check (errRMS 4.49e-03, errMax 3.12e-02 at 4096³ — the only cell in its matrix where a reference was actually compared). IDEAS.md's "the path does not" is true *of torchao* and false of cuBLASLt. It should be re-worded, not re-measured |
| L7 | "the 600M's mean confidence is 0.97 at 0.415 accuracy" | **true, and sharper than it reads — but not comparable across sizes** | llama.cpp's `get_decision_confidence()`: for `lfm2-d1` (600M, 3B) confidence is **`(p_max − 1/K)/(1 − 1/K)`**, a normalised *margin*; for `lfm3-d1` (2B) it is **`max(probs)`**, the raw top probability; `score` questions use a third formula. So for K = 5, the 600M's "0.97" means **p_max ≈ 0.976** — nearly deterministic and mostly wrong. But a confidence column putting the three sizes side by side is comparing a margin against a probability against another margin. Anyone comparing confidence across d1 sizes must fix the definition first |

#### 1.1.3 Model, repository and paper names — existence only, nothing run

| # | name in the chats | verdict | what it actually is |
|---|---|---|---|
| N1 | **JEV-27B-VL** | **true — it exists** | `autotrust/JEV-27B-VL` on Hugging Face: a **rank-32 LoRA adapter on Qwen3.8-27B plus a bf16 vision tower**, 27.8 B params, #1 of 20 on the Jev Decision Index 0.3 Vision board (updated 7 Oct 2026), ECE 0.019. Served by **vLLM** (needs `--max-num-seqs 8`), protocol `POST /v1/decide` (`jev27-bare-v1`). **Not a llama.cpp/GGUF target** — it will not run on this box's d1 serving path |
| N2 | **SuperInstance/why** | **true — and already in builder-ide** | Apache-2.0, pushed 2026-10-31. `~/src/builder-ide/core/why` is *"a faithful Python port of why-core v0.2 (SuperInstance/why, Rust)"* |
| N3 | **SuperInstance/cognitive-ecology** | **true** | MIT, pushed 2026-10-31, "a persistent cognitive ecology: WHY (live justification) as the conservation law governing a world" |
| N4 | **nexu-io/motion-anything** | **true** | Apache-2.0, 1017 stars, last pushed 2026-07-07 — matches the citation already in builder-ide's `docs/vision.md` |
| N5 | **nexu-io/looper** | **true** | MIT, 136 stars, pushed 2026-10-28 |
| N6 | **nexu-io/html-anything** | **true** | Apache-2.0, 9348 stars, pushed 2026-10-13 |
| N7 | **FlashRT-PAI**, arXiv 2610.24349 | **true** | "Fast Kernels Are Not Fast Pipelines for Physical AI Inference", Su, Chen, Li, Guo, Lv (17 Oct 2026); `flashrt-project/FlashRT` is open source. Two facts the chats missed: **four-bit π₀.₅ gets 94.04 % success on Thor** (vs 92.4 % FP16), and FlashRT's *"execution-state capsules enable fast snapshot, restore, and fork of persistent pipeline state"* — which is the same primitive the chats were groping for under the name "state snapshots", already built and already measured on a **Jetson AGX Thor** |
| N8 | **π₀.₅** | **true** | Physical-AI VLA, evaluated by FlashRT-PAI on Thor and RTX 5090 |
| N9 | **Isaac GR00T N1.7**, **Alpamayo 1.5**, **Cosmos 3** | **true** | GTC, 16 Mar 2026 (NVIDIA press release). GR00T N1.7 is a 3 B open VLA, code Apache-2.0, weights under the NVIDIA Open Model License |
| N10 | "Liquid **CI**" / "Liquid continuous integration steps" | **false as a product** | It is the chat's wordplay, not a Liquid feature. No such product exists in Liquid's public lineup |
| N11 | **d1** as a Liquid decision-model family | **true** | Liquid shipped **"Open d1: Edge decision models for text, vision, and audio"** (2026-10-07) and **"d1-ultra: the world's best decision model"** (2026-10-15). Liquid's model page describes decision models as *"purpose-built models for classification, routing, and scoring. One API call returns calibrated probabilities across a fixed set of outcomes"* — which is exactly the `lfm2-d1` / `lfm3-d1` decision types in llama.cpp |
| N12 | "Liquid models discard text generation entirely; the final layer maps hidden states directly to Noul, Choice, Score" | **true — independently verified** | llama.cpp's own `tools/server/server-decision.cpp` implements exactly three question types — `choice`, `score`, `noul` — reads single-token label groups, and returns scores with `"output_tokens": 0` |
| N13 | "Liquid models strip away … complex key-value caches" | **false as stated** | LFM2 is a **hybrid**: 10 double-gated short-range convolution blocks + 6 grouped-query-attention blocks (Liquid's LFM2 blog and tech report, arXiv 2511.23404). The attention blocks keep a KV cache; what LFM2 removes is *most* of the sequence, not the cache |
| N14 | "single, shared, multimodal Continuous-Time State-Space Neural Network (CT-SSM) backbone" for LFM3 and d1 | **partly true** | LFM3 is real (`liquid.ai/blog/lfm3` is cited by the chats and `d1-2B` on our box is `lfm3-d1`). But "single shared backbone across text, vision, audio and video" overstates it: the box's three d1 models are three *different* architectures (`lfm2-d1`, `lfm3-d1`, `lfm2-d1-omni`) with three different context lengths |
| N15 | Isaac Sim as the sandbox | **true as a product, false as our target** | We build virtual worlds with Infinigen + Warp on the Thor (IDEAS.md: "Infinigen 2.0 runs end-to-end on the Thor"). Isaac Sim is not installed and not a plan |
| N16 | OpenUSD / Omniverse | **true as a product** | builder-ide has its own `core/usd` |
| N17 | "Jev" as a decision-model service | **true — and already in use here** | `@jkudish/jev-mcp` (MIT) over TypeSafe's Jev model; installed on this box; `docs/research/jev.md` names twelve tools, 150–500 ms per call, cloud-hosted so it fits B2 ("no LLMs on the Thor"). lab-cascade's scripts already include `jev_mcp.py` and `cloud.py`. **The d1 models are the local counterpart of the same interface** (§0.1) |

#### 1.1.4 The claims that were never claims — architecture the chats assumed

| # | claim | verdict | note |
|---|---|---|---|
| A1 | "the model doesn't get bigger, the exocortex gets richer" (Casey's own line, quoted in liquid1) | **true and already true here** | The box runs a 600M–3B decision model and a 30 MB-L2, 20-SM GPU; the "exocortex" is the cloud plus the ledger. This is the one architectural bet in the chats that the box confirms rather than contradicts |
| A2 | "atomic pointer swap … without ever interrupting the global system clock" (liquid2.md:82) | **true, and already measured** | IDEAS.md round 4: PEFT's `set_adapter` costs **73–119 ms** of host time per switch; the merged-resident **pointer swap is 0.40 ms** (180×), and merged serving is *faster* than adapter serving (18.6 vs 47.0 ms/request at N=32). The chat's instinct is exactly what the lab already built |
| A3 | "double-buffered memory pointers for context switching" | **true, and there is already a mechanism** | llama.cpp's `/slots/{id}?action=save\|restore` is a double-buffered context switch with a disk payload — the endpoint is in the server source; the box measurement is §4.2's, which crashed before producing a number (see §4.2) |
| A4 | "each peripheral runs a tiny, independent state machine … update weights in the background" | **unverified for us** | The check: `nvidia-smi` cannot see GPU memory on this box, so "background weight update" cannot be observed by memory traffic. The honest version is the pointer swap (A2), which is a host-side pointer change and *is* measurable |
| A5 | "a decision model that is fast enough to sit in a control loop" | **true** | d1 decisions are tens of milliseconds (§4.1); the control loop the chats imagined (per-sensor decisions at frame rate) is reachable — but only because the decision head emits a score vector, not text |

#### 1.1.5 The claims that survive contact with the box, in one line each

1. **Decision models are the right shape.** The d1 head returns calibrated probabilities over a fixed
   option set with zero generated tokens, and llama.cpp ships it upstream. Everything the chats wanted
   from a "decision model in the loop" already exists as a supported runtime path.
2. **Snapshots of model state are a real, supported mechanism** — both here (`/slots` save/restore) and
   in FlashRT's execution-state capsules on the same class of hardware.
3. **Precision is not a lever.** Size is.
4. **The chats' hardware layer is a different product.** Anything resting on tcgen05, MIG, MMIO
   programming, NVLink-C2C, NVMedia, or DriveOS has to be re-grounded or dropped.

---

### 1.2 The ideas, refined

Each underlying idea, taken hardware-independently, mapped onto builder-ide's actual projects: what it
would *be* here, what it *overlaps with already*, and the smallest experiment that would settle it.

The grounding names: **characters** and **the night** (`core/night`), **tiles** (`core/tiles`), **the
critic** (`core/critic`), **motion policies** (tiles of another kind, per `docs/design/tiles.md`),
**the ship's computer** (the thing that decides at night while builders are asleep), **cold start**
(`core/coldstart`), **why** (`core/why`).

---

#### I1 — Precision promotion on uncertainty

*Hardware-independent idea:* when the model is unsure, run the same decision at a higher precision and
trust the higher one.

**What it would be in builder-ide.** A rule on the tiles chooser's decision path: if the local decision
model's confidence on a choice is below a threshold, re-run the same choice with a higher-precision
copy of the same weights and take that answer.

**What it overlaps with.** `core/tiles/chooser.py` is a *contextual bandit* with a `TileChooser` door
behind which "a small learned ranker and an RL policy sit". The door is where a promotion rule would
live. `core/coldstart/gate.py` already flips *ask → act* on an evidence count, and
`core/coldstart/sealing.py` already makes confidence **computed, never chosen** — a promotion rule
would have to be written so that it does not let the caller smuggle in a confidence.

**Why it is dead on arrival, on our box.** lab-cascade's E1 found precision changes **no accuracy**
(0 of 27 within-size pairs significant; on T1 the nine cells are identical to the fourth decimal, on
T2/T3 within one or two items, never significant). If the 4-bit answer and the 16-bit answer are the
same answer, promoting on uncertainty promotes to *the same answer*. There is no accuracy to recover.
Worse, 4-bit is *slower* than 16-bit on this Thor (600M: BF16 82 ms p50 vs Q4 109 ms; 2B: 273 vs
313 ms) — so promotion costs time and buys nothing. The uncertainty that matters in builder-ide is
**model-size** uncertainty, not precision uncertainty: d1-2B (0.985) beats d1-3B (0.880) on the
action gate, and d1-omni-600M manages 0.415 with **mean confidence 0.97** — it is confidently wrong,
so a confidence-triggered escalation would never fire.

**Smallest experiment.** Not a hardware experiment — a *routing* experiment on builder-ide's own data:
take the tiles acceptance run's contexts, and measure whether "escalate to the 2B model below
confidence θ" beats "always use the 2B model" on the same contexts. If the escalated system is not
better than the big model everywhere, the escalation is decoration and should not be built.

> **Fold-in (E1, §1.4).** Lab-cascade's ladder answers most of this on last-mile's scenes: d1-2B
> alone is 0.985, **all three of its errors sit in its bottom confidence band** (above confidence
> 0.5 it is 196/196 exactly right; a 0.5 gate escalates 2 % of the traffic and catches 100 % of the
> errors), and last-mile's D71 already measured the escalation step itself (+0.02 accuracy, +25 ms,
> 4 % escalated). Promotion on *precision* has nothing to promote to (0 of 27 pairs significant);
> escalation on the **2B's confidence** is the version with a measured basis. What is still open is
> only whether that calibration transfers to builder-ide's own contexts.

---

#### I2 — A golden-core validator

*Hardware-independent idea:* a small, trusted, always-resident checker that validates the outputs of
the larger, more complex machinery, and can veto.

**What it would be in builder-ide.** `core/critic` currently runs scripted checks over a seeded-defect
reference set and publishes an FP/FN table (`core/critic/CALIBRATION.md`). The golden core would be a
**second opinion on the critic's own verdicts**: d1 asked, as a plain question, "is this render
acceptable?" — and the critic's verdict and the model's probability compared, per defect class. The
model is small (600M, ~0.7 GB Q8), runs on the same GPU, and is 155–344 ms per decision.

**What it overlaps with.** Three packages, and the third is the important one:
* `core/critic/checks.py` and `calibration.py` own the FP/FN counting rule (a planted defect of class
  K that the class-K check misses is a false negative; a check firing on a *different* class's defect
  is excluded from all four counts).
* `core/coldstart/sealing.py` owns the rule that confidence is computed, not chosen.
* **`core/vocab/gate.py` is a "confidence gate" already** — and reading it changes the shape of the
  idea. Its confidence is **not** a model's probability: it is a **denominator**. The world gate is
  per `claim_type` and requires a denominator; the taste gate is per reason code and requires ≥ 2
  prior observations (`MIN_OBSERVATIONS_TO_SPEAK_TASTE = 2`,
  `MIN_OBSERVATIONS_TO_ACT_ALONE = 2`, `MIN_OBSERVATIONS_FOR_CERTAINTY = 3`). The gate decides
  **speaking** (may the builder say a claim?) versus **acting alone** (may it act unsupervised at
  night?), and it is *"a hard gate in the core's prediction and utterance APIs, not prompt
  instructions"*.

So the golden core is not "add a second opinion to the critic". It is the sharper question:
**what does a model's probability add to a denominator-based gate?** Three candidate answers, all
cheap to test and all mutually exclusive:
1. a **veto** — the model can refuse where the gate would allow;
2. an **evidence row** — the model's probability becomes one more observation feeding the denominator
   (so a model that agrees raises the count);
3. a **trigger** — the model's confidence escalates to the human, which is the reading that collides
   with the 600M's 0.97-at-0.415 calibration and therefore should be tried last.

**What it does not overlap with.** lab-cascade's E2 escalates to a *bigger model*; the golden core
*vetoes*. And the 600M's uncalibrated confidence (0.97 at 0.415 accuracy) means the golden core
cannot be a confidence threshold — it has to be an agreement statistic measured against the seeded
reference set.

**Smallest experiment.** One script, read-only against builder-ide's data: take the 51-member critic
reference set (21 with a seeded defect, 30 clean), ask d1-omni-600M a `noul` question per member
("does this render have a defect?"), and publish a 2×2 against the planted class — exactly the table
shape `CALIBRATION.md` already uses. **Kill it** if the 600M's agreement with the scripted checks is
no better than the majority-class baseline (0.706 — 36 of 51 members are `none`). The interesting
variant: d1-**2B** instead of 600M, if the 2B is worth its extra latency.

> **Fold-in (E1, §1.4).** Lab-cascade's T2 is the nearest measured cousin of this experiment — the
> same 51-member reference set, fed to all nine ladder cells as text — and **every cell lands at or
> below the 0.706 majority baseline** (macro-F1 0.17–0.48; `missing_object` and `texture_swap` are
> never detected by any cell). The text route to the golden core is measured dead, before this seat
> had to run it. What remains live is the **vision** cell — the same members with the render passed
> as an image (`cascade-addendum.md` C5, assigned to lab-cascade) — and the 2×2's shape is still the
> deliverable, published beside `CALIBRATION.md`.

---

#### I3 — Hidden-state / internal-state snapshots for cloud calibration

*Hardware-independent idea:* capture what the model "knows" mid-decision, ship it to the cloud, and
have the cloud calibrate the local model.

**What it would be in builder-ide.** A night-local decision loop where each decision's context is
snapshotted, so the morning can ask "what did the ship's computer see when it chose that tile?"

**What it overlaps with.** `core/night/ledger.py` — the log is already the source of truth and the
tiles library and chooser statistics are folds over the audit log (`core/tiles/README.md` rule 6). The
tiles play record already carries the context with the play (rule 4: "a play without its context
cannot be learned from"). So the *semantics* of this idea are already implemented; what is missing is
the **model's** state, not the *world's* state.

**What the box actually gives.** From the llama.cpp source this seat read (`tools/server/`, commit
`2e0d86b`): the runtime exposes the decision context as an opaque binary snapshot
(`--slot-save-path`, `/slots/{id}?action=save|restore`). It does **not** expose hidden activations
as numbers — the only numeric output of a decision is the option score vector. So "ship the hidden
state to the cloud" is not available on this runtime; "ship the decision context and its score
vector" is. **The restore's exactness on this box is not measured**: the check that would have
settled it crashed before producing any number (§4.2), and until it is re-run "bit-exact restore" is
the mechanism's design claim, not this box's result.

**Smallest experiment.** Designed and attempted; the measurement is still owed (§4.2 — the fixed
script is in `scripts/`). The next step after it is a *size* question: bytes per snapshot as
a function of state length, and whether the morning report needs the blob at all or just the score
vector plus the ledger entry. FlashRT's "execution-state capsules" are the same primitive measured on
this class of hardware, and are the reference implementation to read.

---

#### I4 — Hysteresis gates between perception and logic

*Hardware-independent idea:* put a temporal gate between what is perceived and what is decided, so the
decision only changes when the evidence has moved decisively.

**What it would be in builder-ide.** The seam between the night's perception (the render, the critic's
verdict, the builder's report) and the ship's computer's decision (which tile to play, whether to
re-render, whether to wake a builder). Today that seam has a **count** gate
(`core/coldstart/gate.py`: ask→act at two observations per builder × reason code) but **no temporal
gate** — nothing stops a decision that is wobbling on a noisy signal from flipping every tick.

**What it overlaps with.** The tiles chooser's epsilon-decay exploration is a *different* kind of
stability: it stops the builder exploring too much, but it does not stop the decision from flip-flopping
on the evidence. `core/coldstart/gate.py`'s threshold is on observations, not on time or on the
confidence margin. So the idea is **complementary, not duplicate**.

**The reason it is not a duplicate — stated properly.** `core/vocab/gate.py` counts **observations**,
and the denominator is the builder's evidence: *"a note without a denominator would be a fabrication,
and the whole project is against that."* A model's probability is **not** an observation — it is a
reading of one. So if a model's per-tick output were logged as an observation, a wobbling model would
**inflate the denominator with noise**, and the gate would open on the strength of noise. That is the
real argument for the gate, and it is an argument about the *honesty of the denominator*, not about
"stability" in the abstract:

> a temporal gate on the model output is what keeps the denominator honest, by making sure that one
> piece of evidence is counted once rather than once per wobble.

**What it does not overlap with.** lab-cascade's E2 is escalation to a bigger model; a hysteresis gate
changes no model, only the threshold over one model's output.

**Smallest experiment.** Two steps, in order.
*(a)* The one in §4.3: a first hysteresis gate on a decision task, measured on d1's own probability
vectors — flip rate and accuracy as a function of the margin.
*(b)* The one that would actually ship: implement sticky-with-margin as a second rung behind the
existing `TileChooser` door in `core/tiles/chooser.py`, and re-run the tiles acceptance suite
(`tests/tiles/test_acceptance_learning.py`), reporting the win rate beside the bandit's **0.798**
(95 % CI on the difference [0.388, 0.488], z = 15.43). The acceptance run needs **no GPU and no LLM**,
so this is a half-day CPU-only change. **Kill it** if the gate does not raise the win rate or if the
flip rate was never a problem — the tiles game resolves in one play, so the gate may have nothing to
damp.

> **Fold-in (merged after the study began).** Builder-ide now has **`core/hysteresis`** — the gate
> this idea wanted, already built and measured: split enter/exit thresholds, an asymmetric minimum
> dwell served by the same target, the caller's clock, 13 tests, and the two numbers published
> (flicker removed, latency added). Its README names three call sites — the WHY kernel's inferred
> standing, a tile's `active`/`retired` standing, the vocabulary gate's confidence level — and none
> is wired. So *(b)* should not invent a sticky-argmax rung; it should give the **existing** package
> its first caller. And §4.3's verdict + E1 say where the first caller should be: not the chooser's
> argmax (the tiles game resolves in one play; 0 % of d1-3B's decisions were near a boundary), but
> the **escalation state** driven by the 2B's confidence — a continuous, per-tick signal whose raw
> threshold would flicker straight into the ledger. Part 3, item 3.

---

#### I5 — The WHY.md / ECOLOGY.md behavioural script registry

*Hardware-independent idea:* a registry of behaviours, each named, each with a justification, each
compiled down to something a machine can execute; and an ecology in which a behaviour only survives if
its justification is alive.

**What it would be in builder-ide.** It **already is** builder-ide, and this is the single largest
correction the chats need.

**What it overlaps with.**
* `core/why` is *"a faithful Python port of why-core v0.2 (SuperInstance/why, Rust)"* — the exact
  `WHY` idea, already ported: two files (`graph.txt`: child→parent edges, explicit or inferred;
  `att.txt`: root liveness with hard `until` expiry and soft `review-by`), four verdicts
  (`alive`/`unknown`/`dead`/`absent`), and the rule that **inferred edges never confer a verdict** and
  that **liveness is attested, never computed**.
* **`core/justification` is the second half, and it is the part that makes the idea real**: *"Attaching
  the vendored WHY kernel (`core.why`) to builder-ide's records. Every asset, vocabulary entry, recipe
  branch and work order carries a justification chain — who or what it serves."* It is three modules —
  `graph` (records → kernel inputs, and the root mapping, ADR-0002), `lifecycle` (the borrowed
  behaviours: labels, weights, **the one gate**), `service` (statuses, because-chains, the
  morning-report view) — and its rule is that when a root dies its dependents become **questionable,
  not deleted** (kernel status `unknown`), and **nothing is ever deleted**.
* `core/tiles` is the **behavioural script registry**: content-addressed, versioned, never deleted,
  admitted only through a door (`core/tiles/door.py`), played, recorded, and **retired** with a reason
  (`core/tiles/retrain.py`).
* `core/why` + `core/justification` + `core/tiles` together *are* the ECOLOGY.md idea: justification
  gates behaviour, and behaviour is a registry of named, versioned, retireable things.

**So the idea is not "to build" — it is to notice that builder-ide already has the thing the chats
proposed inventing, and that the chats' version (a Rust micro-compiler translating namespaced IDs into
flat 64-bit hardware masks) is a *worse* version of a thing that already exists as a pure-Python
kernel with a vendored Rust original (`core/why/VENDORED.md`).

**What is genuinely new in the chats' version** is one idea worth keeping: *a namespaced ID that
compiles to a flat hardware mask*. But builder-ide's `core/why/reach.py` already computes the
reachability set — the mask **is** the reach set, computed at run time from the graph, with the
provenance rules attached. A precompiled mask would be a stale copy of a live computation. The
research question worth asking is the opposite one: **what must a justification decide that reachability
cannot?** The answer in builder-ide's own terms is already written down: `core/why` returns
`unknown` as a first-class verdict, and the interesting cases are the ones where evidence is *thin*
rather than absent — which is `core/coldstart`'s whole subject.

**Smallest experiment.** No experiment — a *reading*, and then one small addition: add the tiles
library as a second consumer of `core/why`, so a tile's eligibility precondition is a justification
question rather than a boolean, and a tile whose precondition's root is `dead` is retired with a
reason instead of merely becoming ineligible. Then measure: how many tile retirements in a real night
are attributable to a dead justification versus to a bad payoff? If the number is zero, the integration
is not worth it and the chats' idea stays a duplicate.

---

#### I6 — The evolution loop

*Hardware-independent idea:* the system proposes changes to itself, tests them against the world, and
keeps what survives.

**What it would be in builder-ide.** It **already is** `core/tiles`: the cloud author writes a tile,
the library holds it, the chooser picks, every use is a *play*, the night **retrains** from the plays
and hands the losers back to the cloud as a `FeedbackPacket` ("write a better one, here is why it
lost"). Measured: chooser win rate **479/600 = 0.798** against a uniform pick at 0.358, and the win
rate **rises over the night** (232/300 → 247/300) — which is the part that matters.

**What it overlaps with.** Everything. The chats' "evolution loop" and builder-ide's retrain loop are
the same loop. The one thing the chats add that builder-ide does not have is the **cloud in the loop**
writing updated *weights*; builder-ide's cloud writes *scripts* (tiles) and the Thor learns *which*
ones work.

**What is genuinely open.** Three things, all named in `docs/design/tiles.md` §10's open questions:
whether a chooser may act alone at night (cold start's two-observation gate answers it for *taste*,
not for *tiles*), how long play records are kept, and whether one chooser serves a world or a
character.

**Smallest experiment.** Pure CPU, no GPU, no LLM, and it is the most valuable half-day in this study:
add the **decision model as a rung above the bandit** in the tiles chooser ladder, behind the same
`TileChooser` door, and re-run the acceptance suite. The bandit's 0.798 is the floor to beat. This is
the "somatic sandbox" (I7) with the sandbox already built.

---

#### I7 — The somatic sandbox

*Hardware-independent idea:* a body for the intelligence to live in — a world it can act on and be
acted on by — so that "thinking" is grounded in consequences rather than in text.

**What it would be in builder-ide.** The tiles acceptance run *is* a somatic sandbox: a simulated game
where a play wins with probability 0.85 when the tile's style is the one the context asked for, and
0.15 when it is not. The whole suite runs **with no network, no GPU and no LLM** — 93 tests. That is
the point: the loop is exercisable before the engine lands.

**Where the body comes from.** `docs/research/jev.md` already names *"the local decision models"* as
the thing that chooses among the shortlist at play time, and `core/judge/` as the adapter seam. The
body for the tiles chooser is a **d1 decision model served locally**; the cloud half (Jev) is the
150–500 ms fallback for the judgments that must not be local. This is the one place in the chats'
vision that is not a duplicate: everything else has a built seat, and *this* is the seat that has a
model and no experiment.

**A second, better home for the same model.** `core/genbatch` is the Prop-maker's generative batch:
*"a concept prompt goes through the local image model, the picture goes through TRELLIS.2, and the
mesh that comes out is measured, judged, and recorded as an asset with its provenance and its licence
row. **The best of N seeds is kept**, and the morning says which one won and what it beat."* Choosing
the best of N generated assets is exactly a scored classification over a candidate set — the shape a
decision model is built for — and it already has a measured critic (`core/genbatch/critic.py`,
`fidelity.py`) to compare against. That comparison, "the d1 decision model versus the measured
critic on the same N seeds", is a cleaner and more honest experiment than the tiles game, because
*the tiles game resolves in one play and therefore has nothing to damp* (see I4).

**What it overlaps with.** `core/tiles` (the game and the learning), `core/night` (the executor and the
clock that would drive it), `core/coldstart` (the first night, where the only honest currency is a
sealed guess).

**What the chats add that is wrong.** They put the sandbox in **Isaac Sim**, on a physical robot, with
GMSL2 cameras and a CAN bus. On our box the sandbox is virtual by design, and there are no cameras —
so the perception side of a somatic loop has to be the **critic on rendered frames** (which we have:
DINOv2-large, 6.1–84.6 ms per verdict, bit-exact, zero-copy, graphed) rather than a live camera.

**Smallest experiment.** Put d1-3B (or d1-2B) in the tiles chooser ladder as the rung above the bandit
and re-run the acceptance suite; the win rate against 0.798 is the number. This is the same experiment
as I6's, and that is a sign both ideas are the same idea: **the tiles game is the somatic sandbox, and
the d1 decision model is its body.**

---

#### I8 — The NVMe telemetry ring buffer

*Hardware-independent idea:* a bounded, circular, on-device buffer of telemetry that survives crashes
and drains to the cloud.

**What it would be in builder-ide.** Almost certainly **not** an NVMe ring buffer. The audit log is
already the source of truth, already crash-safe by construction (a fold over the log), and already
capped at 4 KiB per payload with a refusal rather than a truncation (tiles README rule 5). A ring
buffer would be a *second* source of truth, which is precisely what rule 6 forbids.

**What it overlaps with.** `core/night/ledger.py` and `core/records.py` (the closed set of event types).
The tiles seat writes exactly four audit types (`tile.authored`, `tile.retired`, `tile.played`,
`tile.retrained`) and nothing else — and a closed event set is a deliberate schema constraint, not an
oversight.

**What the box says.** The box's own I/O history argues against the idea: the external cold shelf is a
FUSE mount that "stalled and took I/O down with it" once already (IDEAS.md Part 0), and cold NVMe
reads into unified memory run at **1.15–1.68 GB/s** with the warm tier (page cache) already free at
~100 GB/s. A ring buffer over a filesystem is a worse store than the ledger over memory.

**Smallest experiment.** Not a buffer — a *rate*: instrument the ledger and measure the write cost per
decision at the rate the ship's computer actually decides (tens of milliseconds apart, per §4.1), and
compare it against the 4 KiB payload cap. If the ledger absorbs the decision rate with room to spare,
the ring buffer is not a thing to build; if it does not, the answer is to *coarsen the events*, not to
add a second buffer.

---

#### I9 — The "hidden state to the cloud" compiler loop

*Hardware-independent idea:* a cloud service that consumes snapshots of local model state and emits
updated weights, fed back to the edge.

**What it would be in builder-ide.** This is the one idea with a *direct* and *unclaimed* overlap: the
cloud already writes tiles, and the tiles seat's `FeedbackPacket` is the existing wire format for
"here is why it lost". A state-snapshot compiler would be the same loop one level down — but it needs
the snapshot to be *readable*, and the runtime's snapshot is an opaque binary (that much is in the
server source; §4.2 is the check on this box, crashed and still owed), while the readable numbers —
the score vector — are exactly what the ledger should already carry.

**What it overlaps with.** `core/tiles/author.py`'s `CloudAuthor` seam, `core/tiles/retrain.py`'s
retirement + feedback loop, and IDEAS.md's **"skill switch"** result, which is the closest thing on
this box to "the cloud sends updated weights": merged-resident **pointer swap 0.40 ms**, batched
multi-LoRA **11–14 ms/request at N ≥ 4**, 9.0× PEFT's switching server, all four paths numerically
exact. The cloud→edge weight-update path **is already built and measured**.

**What it overlaps with least.** The *granularity*: FlashRT's execution-state capsules, and llama.cpp's
slot snapshots, move *pipeline state*, not *weights*. Weight updates are the skill-switch problem;
state updates are the snapshot problem. The chats fused them.

**Smallest experiment.** Measure the *wire cost* of each: (a) bytes of a slot snapshot per decision,
(b) bytes of a merged skill set (60 MiB fp32 adapter vs 720 MiB bf16 merged set — 12×), (c) bytes of a
score vector. Then ask which of the three the morning report actually needs. Almost certainly (c) plus
the ledger entry; (a) is interesting only if a decision has to be *re-litigated* after the fact.

---

#### I10 — The reward-modelling / self-correcting loop

*Hardware-independent idea:* train the model so that it corrects its own outputs.

**What it would be in builder-ide.** `core/critic` + `core/coldstart/calibration.py` already measure
the thing a reward model would stand in for: an FP/FN table per defect class on a seeded reference set,
with the counting rule that a missed defect is never hidden. And `core/coldstart/sealing.py` already
enforces the honesty rule that the confidence is **computed from the ledger**, not chosen by the
caller — which is the whole point of a "self-correcting" system done honestly.

**What it overlaps with.** The critic's calibration table and the cold-start seal policy.

**Smallest experiment.** The one that matters and is cheap: measure whether d1's *probabilities* are
calibrated on builder-ide's own data. ECE on the critic reference set, with a reliability diagram and
a Wilson interval on each bin, published next to `CALIBRATION.md`'s table. The chats assume calibrated
probabilities are available for free; lab-cascade has already shown one d1 model is **confidently wrong**
(mean confidence 0.97 at 0.415 accuracy). Calibration is a measurement, not an assumption.

---

### 1.3 The end-of-response questions as research routes

All 29 are listed in `results/end_of_response_questions.md`, extracted verbatim from both chats
(20 from `liquid1.md`, 9 from `liquid2.md`). They fall into seven families:

* **A — the platform layer** (L532 async copy, L625 GDS, L768/L1388/L1566 MMIO and intent
  registers, L1470 NVLink-C2C, L1145 TMA, L700/L1388 warp shuffle and warp scheduling):
  *8 questions.* Every one of these rests on a claim this study found **false for our box** (§1.1.1).
* **B — the TensorRT / C++ / PTX implementation layer** (L84, L177, L266, L360, L476, L1290):
  *6 questions.* All assume a TensorRT 10 custom plugin. There is no TensorRT pipeline in
  builder-ide; the box has TensorRT 10.16.2 installed but the serving path is llama.cpp.
* **C — the state/precision plumbing** (L450 pause/resume, L918 hidden-state snapshots, L1085
  precision promotion, L532/L1145 context switching): *4 questions.* These are the ones worth taking.
* **D — the registry and the compiler** (L629, L823 Rust micro-compiler; L1031 JSON schemas):
  *3 questions.* Two are duplicates of things that exist; one is a schema question.
* **E — the sandbox** (L711 Isaac Sim handshake, L172 game engine vs web dashboard):
  *2 questions.* The sandbox exists already.
* **F — the model and the deployment** (L101 robot platform, L218 reward modelling, L266 harness
  template, L289 game-state JSON structure, L362 telemetry packaging): *5 questions.* The best family.
* **G — the write-ups** (L654, L700, L961 whitepaper/schematic): *3 questions.* Lowest value; this
  document is the write-up.

#### The eight worth taking, each with the experiment that would answer it on our box

| # | from | route | the experiment | why this one |
|---|---|---|---|---|
| **R1** | L289, L101 | **How much state can a local decision model afford to read per tick?** | Sweep d1-3B Q8 latency against state length (0.1 → 8 kB) at the §4.1 serving configuration; report the state-length budget for 10 Hz and 30 Hz decisions. Extend §4.1 with the length axis. | It is the *ship's computer's* budget, and every other local-decision idea is sized by it. The chats never asked it. Cheap: one server, one sweep |
| **R2** | L1085, L700 | **Can d1 be the golden-core validator?** | Run d1-omni-600M (and d1-2B) as a `noul` question over builder-ide's 51-member critic reference set; publish a 2×2 agreement table against the planted defect class; compare with the 0.706 majority baseline | Read-only against builder-ide's own data; uses the decision head exactly as designed; produces a table in the shape `CALIBRATION.md` already publishes |
| **R3** | L266, L1145 | **Does a hysteresis gate reduce flips without costing accuracy?** | §4.3 does the first half on d1's probabilities. The shipping half is a second rung behind the `TileChooser` door, re-running the tiles acceptance suite against the bandit's 0.798 | CPU-only, no GPU, no LLM, and the tiles suite is already the seat's claim |
| **R4** | L450 | **Is "freeze the model" free, or does it cost a reload?** | Measure, on one server: (a) unload + reload of d1-3B Q8; (b) `/slots` save + restore; (c) bytes per snapshot. Then the decision is arithmetic | "Pause/resume" is a real operational question for a box that hosts many seats. (b) and (c) are exactly what §4.2 was to measure; the run crashed and the fixed script is ready to re-run (Part 3, item 2) |
| **R5** | L918, L177 | **What does a state snapshot actually cost, and does the morning need it?** | Bytes per snapshot against state length; then the wire decision: score vector + ledger entry, or the blob? | The mechanism exists; the *budget* does not, and FlashRT's capsules are the reference to compare against |
| **R6** | L1566, L629, L823 | **What must a justification decide that reachability cannot?** | Add `core/why` as a second consumer of the tiles library (a tile's precondition becomes a justification question) and measure how many retirements are attributable to a dead justification | Turns a duplicate idea into the question that is actually open |
| **R7** | L711, L172 | **Does a decision model beat the bandit in the tiles game?** | Put d1-2B or d1-3B behind the `TileChooser` door — the seat `docs/research/jev.md` already names ("the local decision model") — and re-run `tests/tiles/test_acceptance_learning.py`; compare win rate with 0.798 and with the uniform pick at 0.358 | The somatic sandbox already exists; this is the one experiment that decides the chooser ladder, and it is the local half of the `core/judge/` adapter |
| **R8** | L362, L625, L1031 | **What telemetry does the night actually need, at what rate?** | Instrument the ledger: write cost per decision at the §4.1 decision rate, against the 4 KiB payload cap; then coarsen the events if it does not fit | Replaces an NVMe ring buffer (a second source of truth) with a measurement of the one that exists |

### 1.4 Lab-cascade's E1, folded in (ProArt seat, 2026-10-31 afternoon)

The runner seat cited E1 from lab-cascade's in-flight results; the full §3 of `exp-cascade.md` has
since landed, and four of its results are load-bearing for this document. They are kept exactly as
measured: nine cells (3 sizes × Q4_K_M / Q8_0 / BF16) × three tasks, every cell answering every item,
McNemar on the discordant pairs, one model server at a time.

1. **Precision changes no accuracy.** 0 of 27 within-size pairs significant (smallest p = 0.18);
   on T1 all nine cells are identical to the fourth decimal. Already carried above (L5, I1) — and
   note the design point: pass A (nine cells resident, box under the seed sweep, load 15–27) and
   pass B (one cell at a time, quiet box) produced **18 of 18 identical accuracy figures**, so the
   accuracies are properties of the models and only the latencies are properties of the box.
2. **Q4 is 1.3–1.5× slower than BF16.** Pass B p50 on T1: 600M 41.9 vs 27.8 ms; 2B 129.2 vs
   99.0 ms. The decision path is not matmul-bound, so quantisation buys memory and costs time.
   Already carried above (L5, I1).
3. **d1-2B beats d1-3B, replicating last-mile's D62.** T1: 0.985 vs 0.880, 22 discordant items one
   way and 1 the other (McNemar p = 6×10⁻⁶). Already carried above (§4.3, I1). E1 adds the *why*:
   the 2B is at ceiling on the sub-questions (`enemy_visible` 0.99–1.00, `beacon_reachable`
   0.995–1.00) where the 3B is *worse* at the hardest one (`beacon_bearing` 0.59–0.62 vs 0.72–0.75).
4. **The confidence gate splits by proposer — and the positive half is new to this document.** For
   **d1-2B** on T1: all three of its errors sit in the bottom confidence band; **above confidence
   0.5 it is 196/196 exactly right; a gate at 0.5 catches 100 % of the errors with 2 % of the
   traffic.** For **d1-omni-600M**: mean confidence 0.973 at 0.415 accuracy, and **72 % of its
   errors sit in the [0.9, 0.995) band** — its uncertainty is not where its errors are, so no
   threshold on its confidence can gate anything. L7 explained the two formulas behind these
   numbers; E1 supplies the consequence: **the local rung of any cascade is the 2B, and the 600M is
   in no plan as a proposer.** E1's T2 also lands on this document: the critic's 51-member
   reference set, as text, is at or below the 0.706 majority baseline for **every** cell
   (macro-F1 0.17–0.48; `missing_object` and `texture_swap` never detected) — the text route to the
   golden core (I2) is measured dead, and the live route is the vision cell (`cascade-addendum.md`
   C5). And E1's T3 tempers the tiles routes (I6, I7, R7): one-shot d1-2B reaches only **0.450** on
   the tile-choice task (majority 0.250) — a decision model is a cold-start and shortlist rung, not
   a replacement for a bandit that learns from outcomes.

Consequences are folded in as dated notes on I1, I2 and I4, and as Part 3's dedup section.

---

## Part 2 — what the box settled

Three checks were planned, each served by **our own** llama-server on **our own** port (8290–8294),
each stopped afterwards, all of them run under `~/lm-wt/heavy.lock` so they queue behind other seats
rather than fighting them for the GPU. **Two produced numbers** — §4.1 (latency) and §4.3 (the
hysteresis gate). **The third, §4.2 (the state-snapshot check), crashed before measuring anything:**
a one-line bug in its probe — `scripts/exp_b_state.py` unpacking `decide()`'s three-tuple into two
values — fired seconds after its server came up, `run_part2.sh` logged `exp_b exit=1` and moved on.
`results/exp_b_state.json` therefore **does not exist**, and every "§4.2" sentence in this document
that read as a box measurement has been re-worded to what the llama.cpp source establishes (§4.2
records the whole story). Raw output that exists: `results/exp_a_latency.json`,
`results/exp_c_hysteresis_d1-3B.json`, `results/exp_c_hysteresis_d1-2B.json`, and the full
probability traces in `results/exp_c_trace_*.json`.

The box state around the timed run was quiet and stable: load 1 **7.0 → 8.9**, `MemAvailable`
**115.7 → 115.4 GB**, GPU **52–57 °C**, VDD_GPU rail 3.5–5.5 W between requests. The interleaved
design's own drift check — the same 1-question block measured again at the end — came back
**+0.61 ms** on a 49 ms median, i.e. **1.2 %**. That number is the licence to trust the rest of the
table: the box did not drift under the measurement.

### 4.1 The latency of a d1 decision — the decomposition the chats never made

**Model** `d1-3B` (`lfm2-d1`), Q8_0, llama-server `--ctx-size 4096 -ngl 99 --flash-attn on`.
**Method** one server, five interleaved blocks of 30 requests each; every request carries a fresh
scene state, so nothing is cached between requests. A "pack" asks *k* questions over **one** shared
state; a standalone decision asks one.

| block | questions per request | p50 | p90 | amortised per question | input tokens |
|---|---|---|---|---|---|
| **standalone** | 1 | **49.00 ms** | 58.84 ms | 49.00 ms | 146 |
| pack 2 | 2 | 97.19 ms | 112.01 ms | 48.59 ms | 293 |
| pack 3 | 3 | **116.94 ms** | 131.32 ms | **38.98 ms** | 440 |
| pack 5 | 5 | 194.58 ms | 217.59 ms | 38.92 ms | 730 |
| standalone (repeat, end of run) | 1 | 49.61 ms | 60.01 ms | 49.61 ms | 146 |

Derived: the **marginal cost of an extra question inside a shared-prefix pack** is
**34.0 ms** (pack 3 vs pack 1), 36.4 ms (pack 5 vs pack 1), 48.2 ms (pack 2 vs pack 1).

**What this settles.**

* **"d1-3B at 16 ms" is false for this box by about 3×.** A standalone d1-3B Q8 decision is
  **49.0 ms p50 / 58.8 ms p90**. Even the most favourable figure in the table — the amortised cost of
  a question inside a 5-question pack — is **38.9 ms**, still 2.4× the claim. "d1 at 4 ms" is false by
  more than an order of magnitude.
* **The brief's own "~90 ms for a 3-question pack" is the right *kind* of number.** We measure
  **116.9 ms** for a 3-question pack on d1-3B Q8 with a ~46-token state. Same order of magnitude;
  the gap is model size, precision and state length, all of which this study varies.
* **The "~11 ms per option" figure is not the marginal cost on this hardware.** We measure **34 ms**
  per extra question — three times higher. What *is* right is the shape of the idea: a pack is
  cheaper per question than a standalone decision, by **20 %** (38.98 vs 49.00 ms).
* **Why the saving is only 20 %, and what it predicts.** The shared prefix here is the **state** —
  about 46 tokens — while each question carries its own instructions plus five option descriptions
  (about 147 tokens). So only 31 % of a 146-token request is shareable, and 31 % is roughly the
  saving observed. **The pack's value scales with the state length.** That is a testable prediction
  and it is route R1 below: sweep the state length and the amortised cost should fall towards the
  full prefill cost of the state as the state grows.

**The one thing this changes for builder-ide.** A decision costs **~49 ms**, not 16 ms. At 49 ms the
ship's computer gets ~20 decisions a second from one d1-3B, or **~31/s from a d1-2B** (§4.3). That is
ample for a per-tick loop; it is *not* ample for a per-frame loop over a 30 Hz camera. The number that
should be written into any plan is **49 ms**, and the number that should be written into a *plan
about the ship's computer* is **"how long is the state?"** — because that, not the model, is what
sets the cost.

### 4.2 The state-snapshot check — designed, started, crashed; still owed

**The question (from the brief).** Does llama.cpp expose the d1 hidden or recurrent state that
"state snapshots" would need? `scripts/exp_b_state.py` was designed to answer it on d1-3B Q8 in
three parts:

1. **the interface probe** — does any endpoint hand out internal activations, or is the score vector
   the only numeric output? It probes `/props`, `/slots`, `/metrics` and `/v1/models`, then the
   decision response's own shape;
2. **snapshot / restore / fork** — save the slot after a decision on state A, move the slot on to
   state B, restore, ask again: are the probabilities **bit-identical** to the first answer? Then
   fork — restore twice and ask a *different* question both times. And the budget: bytes per
   snapshot at a ~46-token state and at a ~550-token state, whether two saves of the same state are
   byte-identical, and whether the prompt is readable as plain text in the blob;
3. **the runtime's own prompt cache** — `--cache-ram 256` on a second server (off by default for
   decision models), state sequence A→B→A→A: does the cache actually restore decision state (the
   log line *"found better prompt with f_keep = 1.000"*), and what does it buy in wall time?

**What happened.** The server came up on port 8291 (its log is `logs/server-8291-d1-3B-Q8.log`) and
the warm-up decisions ran; the four GET probes returned; then the script crashed on the probe's own
decision call with `ValueError: too many values to unpack (expected 2)` — it unpacked `decide()`'s
three-tuple `(status, body, seconds)` into two values, the one call site in the harness with that
mistake. `run_part2.sh` logged `exp_b exit=1` at 14:16 and moved on to exp_c. **No part of the
experiment produced a number**: no probe result, no snapshot, no exactness check, no blob size, no
cache timing. The slot-save directory it creates and empties at start (`state/`) was left empty —
which is why it is absent from this copy of the directory. The nearest recorded box state, seconds
later at exp_c's start: load 8.88, `MemAvailable` 115.1 GB, GPU 0 % busy, 52.3 °C, VDD_GPU 4.7 W —
**the crash was the script's, not the box's**, and the `finally` clause stopped the server cleanly.

**What still stands, from source rather than measurement.** The mechanism claims this document and
`cascade-addendum.md` C6 make come from reading the llama.cpp tree this box serves from (commit
`2e0d86b`), and they do not depend on the crashed run: `--slot-save-path` plus
`POST /slots/{id}?action=save|restore` exists; the prompt cache is disabled by default for decision
models (`--cache-ram N` enables it); and there is no endpoint that exports activations — the only
numeric output of a decision is the per-option score vector. What the crashed run **would** have
established, and did not: that a restore is bit-exact on this box's d1 probabilities, the
bytes-per-snapshot budget and its scaling with state length, and whether `--cache-ram` restores
decision state in practice. Until it is re-run, **"the restore is bit-exact" is the design's claim,
not this box's measurement** — FlashRT's execution-state capsules (N7) are the published existence
proof that the primitive works on this class of hardware.

**The fix and the re-run.** The unpack is one line, and the copy of `scripts/exp_b_state.py` in this
directory now carries the correction (the script's mtime postdates the 14:16 crash: the runner seat
fixed it, and was stopped before re-running). It compiles, and every call site's arity against
`d1lab.py` has been checked by the ProArt seat. The re-run is a few minutes under the heavy lock —
one server at a time, stopped after — and is Part 3's item 2, together with the state-length sweep
that turns it into R1's budget.

### 4.3 A first hysteresis gate on a decision task

**Task.** Five-way sea-state classification. The ground truth is computed from the data, never from
the model. Each state names one condition and then a second; with probability 0.35 the second is
presented first. 6 trials × 40 steps = 240 decisions per model, generated from a fixed seed.

**The gate.** *Sticky argmax*: keep the current option unless another beats it by a margin. The
whole sweep is computed offline from the recorded probability vectors, so no extra GPU time is spent
on the sweep and the analysis can be redone at any time from `results/exp_c_trace_*.json`.

| | d1-3B | d1-2B |
|---|---|---|
| latency per decision (p50 / p90) | 50.68 / 56.84 ms | **32.21 / 35.77 ms** |
| accuracy when the state shows the truth | 0.500 | **0.7975** |
| accuracy when the state shows the decoy | 0.000 | 0.000 |
| decision margin (top1 − top2), p50 / min | 0.61 / 0.16 | 0.50 / 0.09 |
| share of decisions within 0.10 of a flip | **0.0 %** | 7.9 % |
| ungated flip rate | 0.5667 | 0.6375 |

| margin | d1-3B flips | d1-3B acc | d1-2B flips | d1-2B acc |
|---|---|---|---|---|
| 0.00 | 136 (0.567) | 0.3292 | 153 (0.638) | 0.5250 |
| 0.10 | 136 (0.567) | 0.3292 | 150 (0.625) | 0.5125 |
| 0.20 | 132 (0.550) | 0.3167 | 142 (0.592) | 0.5125 |
| 0.30 | 131 (0.546) | 0.3125 | **132 (0.550)** | **0.5375** |
| 0.40 | 131 (0.546) | 0.3125 | 123 (0.513) | 0.4958 |

**What this settles.**

* **The gate works mechanically** — the flip rate falls monotonically with the margin, and the per-trial
  numbers show the damping is real rather than an artefact of pooling.
* **On d1-3B the gate is a net loss.** Every margin that reduces flips also costs accuracy
  (−1.25 pp at 0.20, −1.67 pp at 0.30), because **no d1-3B decision in 240 was within 0.10 of a
  flip**: the model's decisions are either clearly right or clearly wrong, so a gate that suppresses
  near-boundary wobble suppresses almost nothing and only adds lag at genuine reversals.
* **On d1-2B there is a narrow window where the gate wins.** At margin **0.30** the flip rate falls
  from 0.6375 to **0.550** (−13.6 % relative) *and* accuracy rises from 0.5250 to **0.5375**
  (+1.25 pp). At 0.40 the gate overshoots and accuracy falls. With n = 240 the accuracy gain is
  **not significant**; the flip-rate reduction is.
* **The decisive number is the margin.** A hysteresis gate can only pay where the decision is
  genuinely near a boundary. d1-3B: **0 %** of decisions are. d1-2B: **7.9 %**. That single number is
  what decides whether the idea is worth building, and it is a property of the *model on the task*,
  not of the gate.
* **The model follows the salient condition.** Accuracy is 0.000 whenever the state presents the
  decoy first — the model never picks the second-named condition. The model's job here is a clean
  5-way classification of what it is shown, and it is good at that (0.7975 for d1-2B) and bad at
  anything else.
* **d1-2B beats d1-3B on both axes again** — 32.2 ms against 50.7 ms, 0.7975 against 0.500 — which
  agrees with lab-cascade's E1b (d1-2B 0.985 at 99–115 ms; d1-3B 0.880 at 134–184 ms). **d1-3B is
  dominated: slower and less accurate on every measurement this seat or lab-cascade has taken.**

**What this means for the idea.** The hysteresis gate is **not dead**, but it is **not a general
technique either** — it is a technique for models whose decisions sit near boundaries, and d1 models
on these tasks mostly do not. The right way to spend it is not on the tiles chooser (which resolves in
one play and has nothing to damp) but on a task with genuine near-boundary decisions, and the first
step is to **measure the margin distribution** on the task you care about. If the share of decisions
within 0.10 of a flip is near zero, the gate is a no-op and should not be built.

---


## Part 3 — the top five things to build or test next

*(written 2026-10-31 by the ProArt seat — writing only, no hardware. Written against everything that
landed after the study began, so that nothing below duplicates it: builder-ide's
`docs/research/pincher-fit.md`, `core/hysteresis/README.md`, `docs/lab/exp-genbatch-plausibility.md`,
and lab-cascade's `exp-cascade.md` §3 (E1, folded in as §1.4). The dedup is stated in full in
"what the five deliberately do not re-propose" at the end of this part.)*

The five share one spine, which is what the whole study converges on: **d1-2B is this box's decision
model** — fastest (32.2 ms p50 on §4.3's short states), most accurate (0.985 on E1's action gate,
beating the 3B it supersedes), and the only size whose confidence is a usable gate (100 % of its
errors below confidence 0.5, at 2 % of the traffic). Everything else — Jev at 150–500 ms, the
600M's dead confidence, the 3B's dominated accuracy, precision's nothing — is now positioned around
that fact. The five build the seam that lets builder-ide use it (1), pay the two measurements the
study owes (2, 4), wire a package that is built but has no caller (3), and settle the one route from
the chats that is still open (5).

---

### 1. Write `core/judge/` — one interface, three backends (local d1-2B, cloud Jev, a fake for tests) — and put d1-2B behind it on the first real builder-ide judgment

**Why this first.** `docs/research/jev.md` already names the seat and the shape: *"A small adapter in
the core (`core/judge/`): Jev behind one interface with a fake for tests. Every judgment is recorded
in the ledger with its distribution and cost."* It does not exist yet. This study established that
d1's `choice` / `score` / `noul` — calibrated probabilities over a fixed option set, zero generated
tokens — is the *same shape* as Jev's verdicts, at 32 ms instead of 150–500 ms and no per-call fee;
E1 (§1.4) established *which* model goes in (the 2B) and *what its confidence means* (act above 0.5,
escalate below). Until the adapter exists, every downstream plan — the cascade's rungs, the golden
core's second opinion, the tiles shortlist chooser, the genbatch best-of-N pick — is blocked on a
seam nobody can call.

**Smallest experiment.** The adapter is pure code (interface, the fake, two real backends, every
judgment recorded with distribution and cost); the first measurement is the tiles shortlist, which
jev.md already names: on the acceptance rig's contexts, the local judge answers `choice` over the
same K candidates the chooser considers. Publish (a) win rate beside the bandit's **0.798** floor —
read through E1's T3 caution (one-shot d1-2B reached 0.450 on lab-cascade's tiles toy), so the
primary reading is the **cold-start curve**: win rate as a function of play index, judge-first
versus bandit-from-zero, where the bandit has no data yet; (b) agreement with the bandit's picks;
(c) latency. Served on our own port under `~/lm-wt/heavy.lock`, stopped after, peak memory recorded
beside every number.

**Where it lands.** `core/judge/` (new — the named seam); `core/svc/predictions.py` and
`core/vocab/call.py` (the nearest existing service seams); the tiles shortlist at play time;
rung 1 of the local→local→cloud cascade.

---

### 2. Re-run the fixed state-snapshot check (§4.2) and extend it into the state-length budget (R1) — the two numbers every local-decision plan is sized by

**Why.** The study cites §4.2 in five places and the check never ran; the fixed script is in
`scripts/`, checked, and a few minutes under the heavy lock. And the same serving session answers
the study's own sharpest open route: §4.1 proved a decision's cost is set by the *state length*
(only 31 % of a 146-token request was shareable, and the pack saving matched), but never swept the
axis. R1 — *how much state can a local decision model afford to read per tick?* — is the ship's
computer's budget, and nothing else in this document is sized without it.

**Smallest experiment.** One session, one server at a time (d1-2B Q8 and d1-3B Q8, the two models
that matter), everything under the lock with `free -g` checked before and peak memory recorded:
*(a)* the fixed `scripts/exp_b_state.py` — restore exactness on the decision probabilities, fork
determinism, bytes per snapshot at ~46 and ~550 tokens, whether the blob is deterministic and
whether the prompt is readable in it, and the `--cache-ram` sequence A→B→A→A; *(b)* §4.1's
interleaved-block design extended with a state-length axis (0.1 → 8 kB), reporting amortised
per-decision cost against length — the state-length budget for 10 Hz and 30 Hz loops. The
freeze-or-stay-resident decision for the night's executor is then arithmetic: an unload/reload
timing versus snapshot cost versus ~49/32 ms per decision.

**Where it lands.** `core/night` (the executor's model-residency policy); lab-cascade's E3
"cached prefix state per task" (C6's mechanism, their lever); the ledger payload design (item 4
consumes its byte counts).

---

### 3. Give `core/hysteresis` its first caller: replay recorded d1 probability traces through the gate, then wire the winning configuration as the cascade's escalation trigger

**Why.** `core/hysteresis` is the rarest thing in the repo: a mechanism built, tested (13 tests) and
*measured* for exactly the two numbers that matter — flicker removed, latency added — with three
call sites named in its README and **no caller**. E1 (§1.4) supplies the signal worth gating: the
2B's confidence, a near-perfect error predictor, which as a raw per-tick threshold would flicker
straight into the ledger — each flap a fact written, withdrawn, written again. And §4.3 already
measured the *other* gate (sticky-argmax on the model's margin) and found it nearly useless for d1
(0 % of d1-3B decisions within 0.10 of a flip; a narrow 2B window at margin 0.30): the gate that
pays is on the **escalation state**, not on the decision itself.

**Smallest experiment.** CPU-only, no GPU, no server, half a day: replay this seat's recorded
traces (`results/exp_c_trace_*.json`, 480 decision vectors) — and lab-cascade's E1b per-item
confidences, which their E1b results hold (the §3.6 band tables are computed from them) — through
`core/hysteresis/gate.py`; sweep enter/exit bands and dwell (symmetric and asymmetric); report
flaps removed and latency added beside the raw threshold. **Kill it** — for the escalation use, not
the package — if the band+dwell removes no flaps on real traces, i.e. the 2B's confidence is not
tick-noisy and the raw threshold ships as-is; that is a one-line check with a fine outcome either
way. The winner then wires behind item 1's judge interface as the rung-0→rung-1 trigger, and — the
README's own second call site — behind a tile's `active`/`retired` standing, which is where a
flapping tile costs a retirement record per night.

**Where it lands.** The vocabulary gate's confidence level and the tiles standing (two of the
three named call sites); the cascade's escalation trigger via `core/judge/`; not the chooser's
argmax — §4.3's verdict stands, the tiles game resolves in one play and has nothing to damp.

---

### 4. Measure the night's telemetry budget: the ledger at the decision rate, and snapshot-versus-score-vector wire cost (R5 + R8 in one experiment)

**Why.** The chats' NVMe ring buffer (I8) is answered by measuring the store that exists, not by
building a second one against the tiles README's rule 6; the "hidden state to the cloud" compiler
loop (I9) is answered by byte arithmetic once item 2 has produced the snapshot sizes; and the
constraint is already written down — the ledger is the only source of truth, events are a closed
set, payloads cap at 4 KiB with a refusal rather than a truncation. Nobody has measured whether the
ledger absorbs the decision rate the box actually affords (~20–31 decisions/s, §4.1/§4.3).

**Smallest experiment.** CPU-only, builder-ide's own code: instrument `core/night/ledger.py` and
drive the four tile event types at the measured decision rate; report sustained writes/s, bytes per
event against the 4 KiB cap, and the fsync share of the cost. Beside it, the wire arithmetic with
item 2's numbers: bytes per snapshot versus bytes per score vector plus ledger entry, per decision
and per night. **The deliverable is a decision, not a number:** the morning report ships score
vectors + ledger entries, and the blob is carried only for decisions that must be re-litigated — or,
if the ledger cannot absorb the rate, the answer is to *coarsen the events*, stated with the
measurement in hand.

**Where it lands.** `core/night/ledger.py` (write path and rate); the tiles play record payload;
the morning report's schema — and it retires I8's ring buffer with evidence either way.

---

### 5. Make `core/why` a second consumer of the tiles library: justification-driven retirement, measured (R6)

**Why.** This is the one route born from the chats that survives everything the study and E1 found.
The chats' registry idea (I5) turned out to be builder-ide itself — `core/why` + `core/justification`
+ `core/tiles` *are* WHY.md/ECOLOGY.md done properly — with exactly one live question left:
**what must a justification decide that reachability cannot?** The tiles library already retires
with a reason (`core/tiles/retrain.py`); the WHY kernel already returns `unknown` as a first-class
verdict and treats thin evidence as its subject. But no tile has ever been retired because its
*justification* died rather than because its payoff was bad, so the project does not know whether
the distinction does any work.

**Smallest experiment.** CPU-only, half a day, no GPU and no LLM: a tile's eligibility precondition
becomes a justification question (is the precondition's root alive?), admitted through the same
door; run nights against the existing acceptance rig; count retirements attributable to a dead
justification versus a bad payoff — and, the sharper half, the retirements that a payoff reading
would have kept and a justification reading correctly kills. **Kill it** if the count is zero across
the rig's nights: then the integration is decoration, the chats' last surviving idea is published as
a duplicate, and `core/why` keeps its single consumer.

**Where it lands.** `core/tiles/retrain.py` (retirement reasons gain a class);
`core/justification/service.py` (the morning report gains "why a tile died" in justification
terms); and `core/why` gains the second consumer I5 argued it should have.

---

### What the five deliberately do not re-propose

* **The retrieval front over the tile library, the three score bands, the `.nail` export, and
  pincher in the first mile** — all proposed, with experiments, in `docs/research/pincher-fit.md`.
  Item 1 puts d1 behind the judge as a *scorer of a shortlist*, which is complementary: pincher's
  bands are threshold policy, and item 3 is what holds such thresholds steady without flicker.
* **The anti-flicker mechanism itself** — built (`core/hysteresis`), measured, tested. Item 3 wires
  it; nothing here rebuilds it, and nothing here re-litigates §4.3's sticky-argmax verdict.
* **The plausibility side of the prop judge** — designed and toy-measured
  (`exp-genbatch-plausibility.md`), with its own stated next step (fit the prior on the real
  approved assets, on the box). The five's only contact with it: its `escalate` verdict needs a
  target, and item 1's judge is the target.
* **Anything lab-cascade owns**: E2–E4, and the addendum's C1–C11 — in particular the vision cell
  (C5), which is the live version of the golden core and lands in builder-ide only as its result
  (a 2×2 beside `CALIBRATION.md`); the LFM3 no-batching measurement (C2); the temperature sweep
  (C3); the distillation loop (C10). This seat's `cascade-addendum.md` is the handoff.
* **Precision, anywhere.** Settled: 0 of 27 pairs significant, and 4-bit slower. Nothing below
  promotes, demotes, or sweeps a dtype.
* **The 600M, as a proposer.** Its confidence carries no gate signal in any band that matters
  (72 % of errors above 0.9). It keeps one job: the vision cell's projector, in lab-cascade's C5.
* **Anything automotive**: tcgen05, MIG, MMIO registers, NVLink-C2C, NVMedia, DriveOS, Isaac Sim,
  cameras. All false for this box (§1.1.1); the somatic sandbox is the tiles game and the critic on
  rendered frames, which already exist.

### The one-paragraph version

Build the judge seam (`core/judge/`) and put d1-2B behind it, because every downstream plan is
blocked on that interface and the model to fill it is measured (item 1). Re-run the crashed
state-snapshot check and sweep state length with it, because the study owes the measurement and
every latency budget in every plan is sized by the answer (item 2). Give the built-but-unwired
`core/hysteresis` gate its first caller on the traces already on disk, because the 2B's confidence
is the escalation signal and a raw threshold on it would flicker into the ledger (item 3). Measure
the ledger at the decision rate and settle snapshot-versus-score-vector wire cost, so the morning
report's schema is decided by arithmetic instead of taste (item 4). And wire `core/why` into tile
retirement and count what it kills, because it is the last open idea from the two chats and one
rig run retires it or adopts it (item 5).
