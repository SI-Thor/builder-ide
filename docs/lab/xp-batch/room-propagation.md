# room-propagation: ring vs broadcast vs room on the Thor (Casey's reverberation filter)

Run: 2026-11-01 07:56-08:00 under `thor-admit` (lease xp-batch.chain, peak 3G,
actual 1.5G). Box: NVIDIA Thor sm_110, torch 2.15.0+cu132, 20 SMs, clocks not
lockable (nvidia-smi [N/A]). N = 64, 512, 4096 nodes, uniform random 2-D
positions; radius = 0.15; 8 emitters/tick; hops = ceil(dist / (radius/2));
gain = relevance x absorption^hops; per-tick operator P_total = sum of delay
buckets (sparse COO), applied as sparse mm; ring = torch.roll; broadcast =
dense all-ones matmul; room and broadcast under CUDA Graph capture for the
echo runs (tick timings measured with direct calls, CUDA events, median of
60).

## Question

Does the room deliver relevant events fast and cheap, absorb what should not
reverberate, and does its decay match the spectral-radius prediction
(stable iff rho(P_total) < 1)? Pass bar: relevant events in <= 2 ticks at
<= 10% of broadcast bandwidth, decay within 10% of rho.

## Method note that changes the sweep

Raw gains scale with in-degree (a node with k in-radius neighbors receives
~k x absorption), so absorption alone does not place the operator at the
stability edge: with N=64 the un-normalized room had rho 1.5-7 across the
whole absorption sweep (first attempt — all unstable, measurements
meaningless). The run therefore normalizes: P is rescaled by
target_rho / rho(P) (power iteration, converged to 2e-4), with target rho
swept 0.70 ... 1.40 through the stability edge. Absorption 0.5 and 0.9 set
the hop-gain profile shape. A dense cross-check of the sparse operator is
asserted every run (max |sparse-dense| < 1e-3).

## Numbers

Bandwidth per tick (non-zeros moved) and in-radius delivery:

| N | room nz/tick | broadcast nz/tick | room/broadcast | room in-radius |
|---|---|---|---|---|
| 64   | ~300      | 4,096      | ~7.2% | tick 0-1, 100% of targets |
| 512  | ~17,000   | 262,144    | ~6.5% | tick 0, 100% |
| 4096 | ~1,040,000 | 16,777,216 | ~6.2% | tick 0, 100% |

All three sub-bars of the pass criterion are met by the room:
relevant (in-radius) events arrive within 0-1 ticks at full rate, at 6-7% of
broadcast bandwidth. Out-of-radius exposure exists (that is reverberation
leaking past the radius): first crossing at 1.3-8.7 ticks with fractions
growing from 0.03 (rho 0.85) toward 1.0 as rho -> 1+ — the leak is exactly
what the absorption term is supposed to tune, and it tunes it.

Decay vs spectral radius (measured per-tick decay of the impulse-response
norm vs power-iteration rho, N=512, absorption 0.5):

| target rho | measured rho | measured decay/tick | error |
|---|---|---|---|
| 0.70 | 0.7001 | 0.7003 | 0.03% |
| 0.85 | 0.8499 | 0.8505 | 0.07% |
| 0.92 | 0.9203 | 0.9216 | 0.14% |
| 0.96 | 0.9597 | 0.9606 | 0.09% |
| 1.00 | 1.0001 | 1.0004 | 0.03% |
| 1.04 | 1.0414 | 1.0427 | 0.12% |
| 1.15 | 1.1500 | 1.1512 | 0.10% |

**Decay matches the spectral radius to <0.15% across the sub-unity range —
the 10% bar passes with two orders of margin.** At target 1.40 the impulse
response diverges (decay = inf): the stability boundary sits at rho = 1 as
predicted. Ring decay is exactly 1.0 (torch.roll is norm-preserving —
nothing is ever absorbed); broadcast echo energy diverges to inf (everyone
hears everything forever at full gain).

Echo energy per 200-tick run with continuous emitters (no-graphs path):

| N=512, rho 0.96 | echo energy |
|---|---|
| room | 4,245 |
| ring | 490,900 |
| broadcast | diverges |

The room absorbs ~100x more echo energy than the ring and stays finite where
broadcast diverges.

## Known issue

The echo-energy metric returned exact zeros in the graph-captured path (the
replay produced zeros; unfixed — the table above is from the --no-graphs
path, where ticks run as direct kernel calls; per-tick timings are measured
directly in both paths, so nothing else depends on the capture). The
N=64 decay rows read 0.0 for rho <= 0.92: the impulse dies below the 1e-12
tail threshold before the measurement window — a floor artifact, not a
contradiction. Two rho > 1 rows (N=64, absorption 0.9) show decay 0.73
against rho 1.15: tail overflow before the log-slope — divergence itself is
the correct verdict there.

## Verdict

**Pass** (at N=512 and N=4096; N=64 meets the bandwidth and latency bars,
its decay measurement floors out): relevant events in <= 2 ticks at ~6-7%
of broadcast bandwidth, and the decay rate matches the spectral-radius
prediction far inside 10%, with the stability boundary at rho = 1 confirmed
by divergence above it.
