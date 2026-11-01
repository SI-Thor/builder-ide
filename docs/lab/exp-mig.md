# MIG on the Jetson AGX Thor: what it offers, and why we cannot use it with the desktop up (2026-10-31)

Casey gave a quiet window for the test. The box was JetPack 7.2.1, MAXN, at 23:25 AKDT, with no compute processes on the GPU (the coldshelf bake-off between GPU steps; the Infinigen sweep in a CPU phase), and 110 GB MemAvailable.

## The hardware fact
`nvidia-smi -q` reports MIG mode **Disabled**, not N/A, so the Thor's GPU can be partitioned. `sudo nvidia-smi -mig 1` enabled it at once, with **no reset and no reboot**.

## What it offers (`nvidia-smi mig -lgip` / `-lgipp`)
| Profile | ID | SMs | Memory | Placement |
|---|---|---:|---|---|
| 1g (also +me, +gfx) | 80 (78, 81) | 6 | 0 GiB | slot {2}, 1 unit |
| 2g (also +gfx) | 82 (83) | 12 | 0 GiB | slot {0}, 2 units |
| 3g (also +gfx) | 0 (32) | 20 (the whole GPU) | 0 GiB | slot {0}, 3 units |

- **Memory is not partitioned** (0 GiB per profile). The GPU uses the unified system memory, so MIG isolates **compute only** (SMs, copy engines, decoders). Memory admission stays thor-admit's job.
- **The useful split is 2g + 1g:** 12 SMs and 6 SMs side by side (18 of 20). For example, live work (the first mile, previews, d1) gets a guaranteed 6-SM slice that the sweep cannot crowd, and presence work gets the 12-SM slice. That is the stream-priority goal, enforced in hardware.

## Why it failed here
- **Creating the instances failed:** "In use by another client". `fuser` on `/dev/nvidia*` showed the holders as **Xorg, gnome-shell, mutter and xdg-desktop-portal**, the Thor's own desktop session.
- **CUDA saw no GPU while MIG was on without instances:** "RuntimeError: No CUDA GPUs are available". Every GPU job would fail in that state.

MIG was reverted (`sudo nvidia-smi -mig 0`) about four minutes later. The baseline was back: **20 SMs, 119.8 TFLOPS dense BF16** (4096³, bf16 matmul, 8 s). No running job logged a CUDA error during the window.

## What it would take
Run the Thor **headless**: stop the display manager (`gdm`), or switch to `multi-user.target`. Then create 2g+1g at boot and point each service at its MIG UUID (`CUDA_VISIBLE_DEVICES=MIG-…`). The costs:
- no local desktop on the Thor;
- 2 SMs unused by the split;
- every CUDA program must be told which slice it uses.

**Casey's call** (it is his desktop). Before deciding, a second window should measure:
- the 6-SM slice's latency for d1 and the first mile while the 12-SM slice runs a full sweep;
- the same pair without MIG, with stream priorities only (xp-batch's `stream-priority` spec).

If priorities already keep live latency flat, MIG is not worth the desktop.

Undo log: `~/last-mile-ops.md` on the Thor.

## The limits of this test (Hy4 adversarial review, 2026-11-01)
- **Partitioning is unproven.** MIG mode enabled and the profiles listed, but **no instance was ever created**. The 2g+1g "guaranteed 6-SM slice" is a proposal, not a measurement, and so is "compute-only isolation".
- **Headless is unproven.** gdm was never stopped and retried. "In use by another client" has other possible causes:
  - clients `fuser /dev/nvidia*` does not show: Xorg as DRM master on `/dev/dri/card0`, `nvargus-daemon`, `nvidia-persistenced`, or a stale context from the earlier jobs;
  - or instance creation may be unsupported on Tegra sm_110 despite the mode toggling. The 0 GiB profiles and a 3g profile equal to the whole GPU hint that it might be a stub.
- **The baseline** is one 8-second matmul, with no clocks or power recorded.

**What to do instead first:**
- the **priority co-run**: live work (d1, the first mile) alone, then beside the sweep with stream priorities only, measuring p50/p95/p99;
- **Green Contexts** (`cuDevSmResourceSplitByCount`, seed 164, `docs/research/googl1.md`): an SM split inside a process that needs no MIG and no headless switch.

Both are specs in xp-batch (`stream-priority`, `green-contexts`). Only if both fail to keep live latency flat is a headless MIG test worth Casey's desktop.
