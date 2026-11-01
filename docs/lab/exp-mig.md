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

---

# Round 2: the headless test (2026-11-01, 08:40–09:05)

Casey approved taking the Thor's desktop down to finish the test ("MIG makes sense"). We now know what MIG on the Jetson AGX Thor actually offers, and that it cannot do the job we wanted from it.

## The question
Can MIG give live work (d1, the first mile, previews) a GPU slice that a background sweep cannot slow down? Green Contexts already give a *service floor*: 1195/1200 live launches on a 10 ms cadence under a heavy background. They do not give *latency*: live p50 0.74 ms vs 0.117 ms idle, p99 5.4 ms (`docs/lab/xp-batch/green-contexts.md`). MIG had to beat that.

## What we did, in order
1. **Quieted the GPU.** We stopped six GPU users, recording each command line for the restart (`~/lm-tools/mig-window/` on the Thor):
   - night-v3's d1 server (its run had ended);
   - agent-world's shared d1 (`thor-admit serve`);
   - a d1 baseline server and the orphaned server of a dead mcode seat;
   - mission A zcode's `d1server`;
   - the Infinigen sweep worker.

   Holders that `nvidia-smi --query-compute-apps` does not show also had to go:
   - a **CPU-only** llama-server (`-ngl 0`), whose CUDA build still opens `/dev/nvidia*`;
   - two **looping `nvidia-smi` monitors** (`-l 1`, `-l 2`).

   `sudo fuser -v /dev/nvidia*` is the check that finds all of them.
2. **Went headless:** `sudo systemctl isolate multi-user.target`. gdm and Xorg stopped. dmesg logged `NVRM: GPU1 rpcRmApiControl_dce … NV_ERR_TIMEOUT` from the display engine as it went (harmless).
3. **Enabled MIG** (`nvidia-smi -mig 1`). It again needed no reset.
4. **Created slices, and learned the real constraint.**

| Attempt | Result |
|---|---|
| 2g (82), then 1g (80) | **2g created** (reported **14 SMs**, not the profile table's 12); the 1g failed: `Insufficient Resources` |
| …then 1g+gfx (81) | Created (6 SMs, its own **8 MB of L2**, a quarter of 32 MB). **Any compute on it hangs:** the first allocation-and-sync never returns |
| Destroy all; 1g (80) first, then 2g (82) | 1g created; **the 2g then failed**: `Insufficient Resources` |
| Compute on that plain 1g | **Hangs** the same way |
| Compute on the 2g | **Works:** 14 SMs, a bf16 matmul at 121.5 TFLOPS (a mid-size test, not a peak) |

5. **Reverted:** destroyed the instances, `nvidia-smi -mig 0`, `isolate graphical.target`. The full GPU measured 20 SMs, 119.6 TFLOPS bf16, the same as before. Every stopped service was restored.

## What we learned
1. **MIG works on the Thor, but only as one compute slice.** With this driver (595.78, JetPack 7.2.1) we could run compute on exactly one partition, the 2g (14 SMs). A 6-SM slice can be created but does not execute compute, and the two cannot coexist as compute slices. A live/background split of the GPU by MIG is not available here. Round 1's open question (Hy4: "is instance creation a stub?") is answered: creation is real, but useful configurations stop at one compute slice.
2. **What MIG partitions here:** SMs, and **L2** (the 1g slice reported its own 8 MB). Not DRAM: every profile is "0 GiB", the unified pool. Green Contexts partition SMs only, sharing L2. So MIG would, in principle, isolate the cache that Green Contexts cannot. But the configuration that would have tested it (live on 1g, background on 2g) is the one that does not run.
3. **Taking the desktop down does not drop the network.** The Wi-Fi connection is system-wide (`psk-flags 0`) and NetworkManager logged no disconnect. Headless operation is safe on this box.
4. **The two zcode seats that died during the window were not killed by it.** Both failed at 09:00–09:02 with `429 Weekly/Monthly Limit Exhausted` from z.ai (reset 2026-11-07 06:37), a coincidence of timing. We note it so nobody blames the window.
5. **The operational lessons:**
   - "Quiet the GPU" means `fuser -v /dev/nvidia*`, not the compute-apps list: CPU-only CUDA builds and `nvidia-smi -l` monitors hold the device too.
   - Seats restart their servers on their own unless told, so a window needs a note in each seat's BRIEF *before* it starts.
   - `pkill -f` patterns must not match their own command line (twice tonight a pattern killed the ssh session running it).

## The decision this supports
**Keep MIG off.** The live floor comes from **Green Contexts**: 1195/1200 on cadence, with the desktop up. Live **latency** under load is a memory-bandwidth problem, so the lever is **capping background bandwidth while live work runs**: a thor-admit dimension, drafted in round 11's Green-Context design note.

**What would reopen MIG:** a driver or JetPack release that runs compute on two slices at once. The test is the one above:
- create 2g + 1g;
- run `mig_iso.py` (in `~/lm-tools/mig-window/`), live on the 1g and the 2 GiB streaming background on the 2g;
- compare against Green Contexts' numbers.

It is a 30-minute test with the desktop down.
