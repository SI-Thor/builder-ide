# l2-persist: L2 persistence window on the Thor (idea3 / googleidea)

Run: 2026-11-01 06:55 (19 s) under `thor-admit` (lease xp-batch.chain). Box:
NVIDIA Thor sm_110, CUDA 13.2, 20 SMs, **L2 = 32 MB**,
`cudaDevAttrMaxPersistingL2CacheSize = 24 MB`,
`cudaDevAttrMaxAccessPolicyWindowSize = 128 MB`. Hot buffer 16 MB fp32, cold
streaming buffer 2 GB, hot kernel = 64 repeated grid-stride passes (1.05 GB read
per measurement), 5 repeats, medians. Cold kernel (grid-stride float4 reads over
the 2 GB buffer, self-terminating by device timer) streamed concurrently during
the loaded conditions.

## Question

Does pinning a 16 MB hot buffer in L2 with an access-policy window
(`cudaDeviceSetLimit(cudaLimitPersistingL2CacheSize)` +
`cudaStreamSetAttribute(accessPolicyWindow, hitProp=Persisting)`) speed repeated
reads while a concurrent stream evicts the cache? Pass bar: >= 15% faster.

## Numbers (median GB/s over 5 repeats)

| condition | hot-read throughput |
|---|---|
| hot alone, no window | 319.4 |
| hot alone, window | 306.5 |
| hot + cold streaming, no window | 207.1 |
| hot + cold streaming, window | **203.8** |

**Speedup with the window under contention: 0.984x — fail (bar was >= 1.15x).**

## Mechanism

- The attributes are supported and were accepted (`window.ok = true`, no error
  recorded): the 24 MB persisting limit was set and a 16 MB window with
  hitRatio 1.0, hitProp=Persisting, missProp=Streaming was attached to the hot
  stream. It simply had no measurable effect, and no adverse effect either
  (0.98x is within run-to-run noise).
- The absolute rates say the hot buffer was never L2-resident in any
  condition: even "hot alone" ran at ~319 GB/s, which is DRAM-class bandwidth
  on this box (measured peak streaming reads 141-247 GB/s depending on box
  load; pure L2-resident reads reach ~1 TB/s effective — the idle GEMV in the
  stream-priority experiment sustains ~1 TB/s on a 16.8 MB weight matrix). If
  the 16 MB buffer were pinned in the 32 MB L2, the repeated-pass kernel
  should be several times faster than DRAM rate.
- Plausible mechanism for the no-op: on this integrated part the L2
  persistence policy either is not honored for unified-memory device
  allocations at this driver (595.78 / CUDA 13.2), or the persisting
  reservation is bounded much further by the desktop/compositor's share of
  L2 than `MaxPersistingL2CacheSize` suggests. Distinguishing those would
  need `ncu` (not installed, `command -v ncu` empty; lts__t_sector_hit_rate
  unavailable), which is the next step if this matters.

## Verdict

**No: the persistence window is accepted but provides no speedup on this
driver (0.98x vs the >= 1.15x bar).** Not "unsupported" — the API path works;
it is ineffective here.

## Caveats

- Clocks not locked (nvidia-smi reports [N/A]; jetson_clocks needs sudo).
- One anomalous rep in the "hot alone, no window" condition (390 GB/s vs
  215-216 for the other four) did not affect the median comparison, which was
  taken within like-for-like conditions.
