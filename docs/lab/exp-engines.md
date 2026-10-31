# EXP 1 — What accelerators does this Thor actually expose to user software? (the engine fact check)

**Date:** 2026-10-31 00:45 local (Alaska Daylight Time)
**Verdict: HALF THE ROSTER IS REAL, HALF IS POETRY** — the box has **PVA v3 (9
contexts), NVENC, NVDEC and a full INA current-sensor set**, and it has **no
NVDLA at all** (no `/dev` node, no device-tree node, no string in the DTB). It also
has **no OFA device node** despite the driver exposing an OFA counter. The
"power rails for a joules metric" question has a clean answer: **two independent
sources that agree to within 2 %** — `tegrastats` VDD_* fields and the INA3221 /
INA238 I²C current sensors — and the INA238 gives a whole-box input power that
makes "joules per fixed point" directly measurable.

---

## 1. The idea

Round 3's brief asks for a fact check of the engine roster in Kimi's notes before
any of it is built on:

> "Hardware engines repurposed: NVDLA as a critic farm (does Thor even have NVDLA?
> Orin does), PVA as scheduler, NVENC/NVDEC to compress world-state latents between
> frames (warm start), CUDA Graphs to kill launch overhead in a hot loop."

and for the other half of the physics:

> "the **power rails** readable for a joules metric (INA sensors / tegrastats VDD_* fields)."

An idea that names an engine that does not exist costs a day to discover. This
experiment is the day that discovers it, for all of them at once.

## 2. Hypothesis

1. **NVDLA is absent.** Thor replaced the Orin-era NVDLA with the Blackwell GPU's
   own tensor cores. Kimi's own parenthetical suspects this.
2. **PVA is present and real** (the Thor's PVA v3), and `/dev/nvhost-ctrl-pva0`
   exists — but it is a *vision* accelerator with a fixed-program model, so
   "PVA as scheduler" is the wrong use of a real part.
3. **NVENC/NVDEC are present and reachable** (`/dev/v4l2-nvenc`, `/dev/v4l2-nvdec`,
   live utilisation counters in `nvidia-smi`).
4. **OFA is not reachable** from user software on this SKU even though the driver
   carries an OFA counter and NVIDIA lists an optical flow accelerator on Thor.
5. **There are real power rails**, and two independent ways to read them.

## 3. Setup

Everything here is a *read*. No services touched, no system installs, nothing
written outside `results/`.

- Script: `scripts/exp1_engines.py`; raw JSON: `results/exp1_engines.json`
  (rerun: `.venv/bin/python scripts/exp1_engines.py`)
- Sources of truth, in order of authority:
  1. `/proc/device-tree` (the live, kernel-filtered device tree)
  2. `/boot/dtb/kernel_tegra264-p4071-0000+p3834-0008-nv.dtb` (the compiled DTB
     on disk — the live tree hides some nodes, the DTB does not)
  3. `ls /dev`
  4. `nvidia-smi -q`
  5. `tegrastats` + `/sys/class/hwmon/*` (the INA sensors)
  6. NVIDIA's published Thor platform specs, for the SoC-vs-SKU comparison

- Power measurement: `scripts/boxstate.py` runs `tegrastats --interval` in the
  background and polls the INA sensors every 25 ms, then integrates the rails
  (trapezoid) into joules. Box state is captured in the same window.

### The box this ran on

| | |
|---|---|
| Board | `tegra264-p4071-0000+p3834-0008-nv.dtb` (Jetson AGX Thor devkit, T5000 module) |
| GPU | NVIDIA Thor, Blackwell (`GPU Part Number 2B00--A1`) |
| Driver / CUDA | 595.78 / CUDA 13.2 |
| JetPack | **R39 (release) REVISION 2.1**, Ubuntu 24.04.5, kernel `6.8.12-1021-tegra` |
| CPU | 14 × Neoverse-V3AE |
| Memory | 125 748 MiB unified (LPDDR5X) |
| Power mode | `MAXN` (nvpmodel mode 0) |
| **Load during these runs** | **loadavg 10.9 – 13.4 on 14 cores**, GPU util 87 – 98 % |
| **Contender** | pid 1982714 — the Infinigen spike's own Cycles render: `.venv/bin/python -m infinigen_examples.generate_indoors --seed 0 --task render …` (running since 00:27) |

> The contender matters for every *timing* number in this round. It does **not**
> affect this experiment, which is all device enumeration — but it is the reason
> the throughput experiments are re-run on a quiet box before they are published.

## 4. Numbers

### 4.1 The engine roster, from `/dev`

| engine | `/dev` node | verdict |
|---|---|---|
| **NVDLA** | **none** | **does not exist on this box** |
| **PVA** | `/dev/nvhost-ctrl-pva0` (rw) | present |
| NVENC | `/dev/v4l2-nvenc` (rw) | present |
| NVDEC | `/dev/v4l2-nvdec` (rw) | present |
| **OFA** | **none** | not reachable |
| ISP | `/dev/nvhost-ctrl-isp`, `-isp1` | present (no cameras attached) |
| camera capture | **no `/dev/video*`** | none |
| JTAG | **none** | not reachable |

`ls /dev` also confirms round 2's finding rather than contradicting it: **no OFA
node.**

### 4.2 The device tree

| node | what it is |
|---|---|
| `bus@0/host1x@8181200000/pva0@818c000000` | **PVA v3**, with **9 contexts** (`pva0_niso1_ctx0` … `ctx8`) |
| `reserved-memory/pva-carveout` | PVA has its own reserved memory |
| `bus@0/aocluster@c000000/aon@c040000` | the **always-on subsystem** (`nvidia,adsp_mem`, `nvidia,adsp_os_secload`) — an ADSP cluster, **no `cpu@N` children** |
| `cpus/cpu@0` … `cpu@13` | the 14 Neoverse-V3AE cores — all of the app CPUs |
| `etf_soc@10040000/coresight-default-sink` | the **GPU's** trace sink — one node, inside the ETF trace path |
| `safetyservices_epl_client@110000` | a *services client endpoint* — not a safety island CPU |
| `rtcpu@81893d0000` | the camera RTCPU (RISC-V), already used by the ISP path |
| **NVDLA** | **absent — no node anywhere in the tree** |

In the compiled DTB the only matches for Kimi's engines are `pva0*` (9 contexts
plus `nafll_pva0_core` / `nafll_pva0_vps`, the PVA AFL libraries), `jtag_reg` and
`jtag_reg_ungated` (**register-block definitions, not an accessible port**), and
the six `arm,coresight-*` funnel/replicator/pmu/stm/tmc nodes that form the
**GPU performance-counter trace path**. `nvdla` and `ofa` produce **zero** matches.

### 4.3 `nvidia-smi -q`

```
Product Name    : NVIDIA Thor          Product Architecture : Blackwell
Driver 595.78   CUDA 13.2             GPU Part Number       : 2B00--A1

Utilization      GPU 97 %   Memory 0 %   Encoder 0 %   Decoder 0 %   JPEG 0 %   OFA 0 %
Encoder Stats    Active Sessions 0
Memory           total / used / free = N/A
ECC Object N/A   ECC Mode N/A   Single Bit ECC N/A   Double Bit ECC N/A
```

Two things to keep: the driver **does** carry live Encoder / Decoder / JPEG / OFA
utilisation counters (so those engines exist in the GPU), and **`nvidia-smi` still
cannot see memory or ECC on this box** — round 2's trap 6 is confirmed a third
time, and it is the reason the joules metric has to come from the rails.

### 4.4 The power rails — two sources, and they agree

`tegrastats` exposes four rails: `VDD_GPU`, `VDD_CPU_SOC_MSS`, `VIN_SYS_5V0`,
`VIN` (each as `current/avg/max` mW).

Underneath it, the board has **real I²C current sensors**, readable from user
space with no root:

| hwmon | chip | channel | label | V | I | P |
|---|---|---|---|---|---|---|
| hwmon4 | **ina238** | 1 | `VIN` | 27.98 V | 1.70 A | **47.5 W** (whole-box input) |
| hwmon6 | **ina3221** | 1 | `VDD_GPU` | 19.672 V | 1.06 A | **20.85 W** |
| hwmon6 | ina3221 | 2 | `VDD_CPU_SOC_MSS` | 19.68 V | 0.42 A | 8.27 W |
| hwmon6 | ina3221 | 3 | `VIN_SYS_5V0` | 5.112 V | 1.70 A | 8.69 W |

**Agreement, same instant:**

| rail | INA3221 (V × I) | `tegrastats` | Δ |
|---|---|---|---|
| VDD_GPU | 20.07 W | 20.07 W | **< 0.1 %** |
| VDD_CPU_SOC_MSS | 7.87 W | 7.87 W | **< 0.1 %**| VIN_SYS_5V0 | 8.49 W | 8.47 W | 0.2 % |

**This is the answer to "the power rails readable for a joules metric": both, and
they are the same rails seen twice.** `tegrastats` is the convenient one (it is
already parsed by the lab's tooling and gives a `max` since start); the INA
sensors are the *finer* one (25 ms sampling, per-rail current, and the INA238's
whole-box `VIN` number). Round 3 uses the INA sensors as the primary joules
source and `tegrastats` as the cross-check.

There is also a **`gpu-nvd-0` devfreq node** — the video encode/decode engine has
its *own clock domain*, separate from `gpu-gpc-0`. That is the hardware fact
behind Kimi's "NVENC runs in parallel with the GPU's tensor work" claim, and
`exp-cuda-graphs-nvenc.md` measures it.

### 4.5 The 273 GB/s in Kimi's formula

NVIDIA's published specs for this module: **Jetson AGX Thor, T5000, 128 GB,
256-bit LPDDR5X, 273 GB/s, PVA v3.0, up to 6x4Kp60 encode, up to 4x8Kp30 decode,
up to 2070 TFLOPS sparse FP4, 40-130 W.** So **273 GB/s is the *datasheet*
bandwidth, and it is correct as a datasheet number** — it is the spec, not a
measurement. Round 1 measured **~100 GB/s achievable** on this box
(`exp-unified-memory.md`: 100.87 GB/s zero-copy read, 100.93 GB/s device-resident).
The gap between 273 and 100 is the whole story behind "FP4 as an iteration
multiplier", and `exp-batched-shared-model.md` re-derives the real multiplier
against the *measured* bandwidth rather than the spec.

NVIDIA's own Orin-vs-Thor comparison confirms the NVDLA point:

| | DRIVE AGX Orin | DRIVE AGX Thor |
|---|---|---|
| GPU | CUDA Tensor Core GPU **+ Deep Learning Accelerator** (254 INT8 TOPS) | Blackwell GPU with generative AI Engine — FP32/16/8/4-bit, 2 000 FP4 TFLOPS, **no DL accelerator** |
| Memory bandwidth | 205 GB/s LPDDR5 | 273 GB/s LPDDR5X |

Orin has the NVDLA. Thor deleted it and moved that work into the GPU's FP4/FP8
tensor cores.

## 5. Killed by fact (Kimi's poetic claims)

These are the ones the brief says to list with a reason and not spend time on.

| claim | killed by | reason |
|---|---|---|
| **NVDLA as a critic farm** | **no NVDLA on this SoC** | absent from `/dev`, from the device tree, and from the compiled DTB. NVIDIA replaced it with the Blackwell GPU's FP4/FP8 tensor cores. The "critic farm" has to be *the GPU* (shared with the generator — which is precisely the contention question round 3 measures) or **PVA**, whose 9 contexts are real but whose input never arrives. |
| **PVA as the scheduler** | wrong capability + no input | PVA v3 is a *vision* accelerator (VPU cores, fixed-program model, driven through the camera stack, `nafll` libs). It is not a control-plane CPU and cannot run a scheduler. And there are **no `/dev/video*` capture nodes** on this box, so there is nothing to perceive. The *surviving* idea is the narrower one already in `IDEAS.md` #10: PVA as cheap always-on perception — still parked for want of a camera. |
| **OFA as a real-time mesh deformer** | no device node | confirmed again: `nvidia-smi` carries an **OFA utilisation counter** and NVIDIA lists an optical-flow accelerator on Thor, but there is **no `/dev` node and no device-tree node** on this SKU. Not reachable from user software. (Round 2 already recorded this; it holds.) |
| **Die heat as attention** | thermal zones are read-only scalars, and they are *outputs* | there are exactly **5** thermal zones (`tj`, `gpu`, `cpu`, `soc012`, `soc345`), each a single millidegree read-only file. Attention is a per-token distribution over a vocabulary; the die temperature is one number per zone that is a *consequence* of the work, not an input to it. Nothing on this box can make temperature modulate an attention distribution, and a scheme that did would be non-deterministic — which breaks the project's own "recipes, not meshes" premise (a recipe must replay identically). |
| **ECC bit-flips as entropy** | no observable ECC on this box, and the mechanism is backwards | `nvidia-smi -q` reports **ECC Object / ECC Mode / Single Bit ECC / Double Bit ECC all `N/A`** — there is no error counter to read. On LPDDR5X the memory is ECC-protected *and actively scrubbed*, so a flip is corrected before it is observable; a flip that *did* escape would be a silent numerical error in a weight, not an entropy source. Harvesting it would make generation non-reproducible — again fatal for a recipe-based system. |
| **JTAG / Coresight as a puppeteer window** | no port is exposed | there is **no `/dev/jtag*`** and no JTAG node in the device tree. The DTB's `jtag_reg` / `jtag_reg_ungated` are *register-block definitions*, not a usable port. The `arm,coresight-*` nodes are the **GPU's internal perf-counter trace funnel** (`coresight-default-sink` is the ETF sink), i.e. profiling instrumentation — they read counters, they do not write state into a running system. The devkit's "Debug" USB-C is a serial/power debug port, not a SoC debug port. Nothing here can puppeteer a running process. |
| **The safety island as constitution** | there is no safety-island CPU to be one | the closest real thing is `aocluster/aon@c040000` — the **always-on ADSP cluster** (audio/sensor DSP, `nvidia,adsp_os_secload`), which has **no `cpu@N` children** and is not user-programmable; and `safetyservices_epl_client@110000`, which is a *client endpoint* for the SoC's own power/wake/thermal services. All 14 app cores are in the single `cpus` node. There is no island to constitutionalise anything. |

## 6. Reproduce

```bash
cd /home/caseydigennaro/lm-wt/lab3
.venv/bin/python scripts/exp1_engines.py            # -> results/exp1_engines.json

# the three facts that decide the roster, by hand:
ls /dev | grep -iE 'nvdla|pva|nvenc|nvdec|ofa|video'   # -> pva, nvenc, nvdec only
find /proc/device-tree -iname '*nvdla*' -o -iname '*ofa*' # -> nothing
strings /boot/dtb/*.dtb | grep -icE 'nvdla'             # -> 0

# the rails
.venv/bin/python -c "
import sys,time; sys.path.insert(0,'scripts')
from boxstate import PowerMeter
with PowerMeter() as m: time.sleep(3)
print(m.report()['ina']['rails'])"
```

## 7. What this unlocks (and what it costs)

- **The joules metric is real and has two independent readings.** Every remaining
  experiment in this round reports joules from the INA238 whole-box `VIN` and from
  the `VDD_GPU` rail, with `tegrastats` as the cross-check.
- **The engine roster for round 3 is now: Blackwell GPU (FP8/FP4 tensor cores),
  PVA v3 (9 contexts, no input), NVENC + NVDEC (separate clock domain), 14
  Neoverse cores.** There is no third accelerator to repurpose. Any plan that
  assumes "a spare engine to farm work on" has exactly **one** candidate — the
  video engines — and that is what experiment 5 measures.
- **Critic farm, re-stated honestly:** the critic cannot have its own accelerator
  on this box. It either shares the GPU with the generator (and the interesting
  question becomes *how much does the critic cost the generator?* — measured in
  `exp-batched-shared-model.md`) or it runs on the CPU (worth ~4.4x, per
  `IDEAS.md` #11) or it waits for a camera so PVA can do it.
