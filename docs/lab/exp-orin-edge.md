# orin-edge: the Orin as an edge node for the agent-world community

Date: 2026-11-02 (Orin local time). Question (BRIEF.md): what can the Orin do as an
EDGE NODE for the agent-world community so the Thor carries less and a second device
carries the reflex?

## 1. llama.cpp with CUDA on the Orin, serving d1-2B on :8091

**Build.** `~/lm-orin/llama.cpp` — source synced from the Thor's
`~/llama.cpp-upstream` (commit `2e0d86b`, the same build the Thor's d1 baseline uses),
built with CUDA 13.2 for **sm_87**: `cmake -DCMAKE_BUILD_TYPE=Release -DGGML_CUDA=ON
-DCMAKE_CUDA_ARCHITECTURES=87`, GNU 13.3.0, `llama-server` + `llama-bench` in
`build-cuda/bin`. (The pre-existing `~/model-farm/src-llama` tree was checked first:
commit 63b4b30 predates the `lfm3` architecture and its CUDA build never produced the
tools — unusable.)

**Model.** `d1-2B-Q8_0.gguf` (1,846,240,576 bytes, md5
`0b45b01d3db04dbea658b8c67ace3667`, identical on both boxes) copied from the Thor's
`~/models/d1-2B/` to `~/lm-orin/models/`.

**Server.** `llama-server -m … -ngl 99 -fa on -c 8192 --parallel 8 -ub 512 -t 4 -tb 4
--cache-ram 0` on `0.0.0.0:8091` (LAN). The server recognises it as
`decision model type: lfm3-d1`; tegrastats shows GR3D at 90–96 % during serving, so
the weights run on the GPU. **The server is still running on :8091.**

**Measurement.** Request shape is the Thor's `tools/d1dec` client's:
`POST /v1/systemone` with `{"state", "questions"}`; packs from the Thor's
`workload/packs.jsonl` (256 packs, 3 typed questions each, ~219-token prompts,
distinct states — nothing cacheable). 2 warmup + 8 rounds at each concurrency
(1/4/8); power from tegrastats (`VDD_IN` = whole board, `GR3D_FREQ` = GPU):

| concurrency | decisions/s (questions) | pack p50 ms | pack p95 ms | board power (mean / p95) | GPU util |
|---|---|---|---|---|---|
| 1 | 7.80 | 384 | 385 | 18.9 W / 19.6 W | 90 % |
| 4 | 7.87 | 1144 | 1529 | 19.7 W / 19.9 W | 92 % |
| 8 | 7.81 | 1921 | 3060 | 20.1 W / 20.3 W | 96 % |

Raw results: `results/bench_c{1,4,8}.json`, power samples `logs/power_c{1,4,8}.txt`.

**What the flat throughput means.** One decision ≈ 130 ms on the Orin GPU (one
219-token prompt, single 2B Q8_0 prefill). Throughput does **not** scale with
concurrency because llama.cpp runs lfm3-d1 with `task.decision.no_batching` —
decisions are one flat prompt each and are served one at a time. That is the exact
limitation the Thor's `tools/d1dec` batched server exists to beat (it gets 42.2
decisions/s on the Thor; this llama.cpp box gets 7.8 even idle on the Orin).

**Memory.** RAM peak during the c8 run: 5.7 GB used of 7.5 GB shared → ~1.8 GB
MemAvailable at the peak, above the 1.5 GB floor (it held; the box is otherwise idle).
Power: ~20 W board total under full load.

## 2. One agent-world reflex pointed at the Orin

Done **without touching the live world** (the world's tmux session, its reflex on
:8110, its shared d1 on :8094 and its ledger were never modified):

- Copy of the reflex source on the Thor at `~/lm-wt/orin-edge/reflex-copy`
  (live copy at `~/lm-wt/agent-world/reflex` untouched; only two small env-gated
  patches: `AW_D1_URL` accepted by `DecisionModel` so the backend is
  `D1Backend(url=…)` instead of the loopback port discovery, and the ledger/skills
  dirs moved under a scratch runtime).
- Isolated state: own skill library (22 seed skills admitted) and own SQLite ledger
  under `~/lm-wt/orin-edge/aw-scratch/`; served on loopback :8120 with
  `AW_D1_URL=http://192.168.0.50:8091`.
- Verification: 35 bot-shaped `POST /decide` requests (the exact `bots/src/reflex.js`
  payload: `{bot, role, context, state}`, one distinct state per call so nothing
  cache-hits) — **35 d1 calls, 0 failures**, all answered through the Wi-Fi link to
  the Orin (`port_source: url http://192.168.0.50:8091` in `/stats`).

**Latency the bot would feel** (reflex `/decide`, one d1 question per tick):

| path | mean | p50 | p95 |
|---|---|---|---|
| live reflex → Thor d1 (loopback, measured on the live service) | 55 ms (d1 call) | — | — |
| reflex copy → **Orin** d1 over Wi-Fi, idle | ~200 ms | 215 ms | 227 ms |
| reflex copy → Orin d1 while a c8 bench saturated the Orin | 603 ms | — | — |

A full 3-question pack straight to the server: Orin over Wi-Fi 399 ms mean / 448 ms
p95 vs 119 ms mean on the Thor's loopback d1.

**The Wi-Fi cost, measured** (ping, 2 s interval, 15 min sample, `rtt.txt`):
RTT min/avg/max/mdev = **2.9 / 80 / 444 / 63 ms**. The link is fast when quiet and
spiky when shared — the p95 of a reflex decision rides on that tail. A wired Thor
would remove only one leg of this; the Orin is on Wi-Fi too.

**Why not a real bot yet (the measured plan).** The four builders' names
(Pebble, Timber, Kite, Sprout) are fixed and whitelisted; a second instance of one
of them cannot join the live Paper server without either stopping the live bot's
window or adding a clone name to the live whitelist — both touch the live world.
The cutover when that is wanted is fully de-risked:

1. keep this copy running (it is a known-good, isolated reflex on :8120);
2. when a window is free in the world's tmux session, stop **one** bot's process and
   relaunch it with `AW_REFLEX_PORT=8120` (its only reflex-facing env var) — or, with
   the whole world paused, restart the shared reflex itself with
   `AW_D1_URL=http://192.168.0.50:8091`;
3. watch `http://127.0.0.1:8120/stats` — `model.failures` is the tripwire; the
   bandit-prior fallback already absorbs d1 misses, so a bad link degrades
   gracefully to today's behaviour.

## 3. What moving reflexes to the Orin frees on the Thor

- The Thor's shared d1-2B server (830 MB RSS of the 128 GB pool, one of 8 slots,
  one 219-token prefill per bot per 2 s tick ≈ 0.5 calls/s per bot) sheds one bot's
  questions — a **small** fraction of one shared server. Honest answer: one bot is
  not worth moving on its own.
- The interesting move is a whole lane: the community-loop lane's ticks (64
  characters × 3 questions) are exactly what the Orin's llama.cpp *cannot* carry
  (7.8 decisions/s serialized vs 42.2 needed), but a port of the Thor's `d1dec`
  batched engine (PyTorch, runs from the same Q8_0 file, ~2.3 GB) would make the
  Orin a second reflex node and put the tick's ~10 s of Thor GPU/CPU elsewhere.
  That port is the follow-up; everything this brief needed to judge it is measured.
- Cost side: the Orin sits at ~20 W board power under full serving load, uses
  ~2.5 GB RSS (weights + 8 slots of ctx + CUDA context), 5.7 GB of 7.5 GB box-wide at the c8 peak, and is Wi-Fi-attached.

## Verdict

The Orin is a viable **second reflex node**, not a relieve-the-Thor workhorse:

- ✅ It serves d1-2B (sm_87 CUDA llama.cpp, :8091, LAN) at 130 ms/decision, 7.8
  decisions/s serialized, ~20 W — enough for 2–4 single-character reflexes at 2 s
  ticks, each paying +150–280 ms of Wi-Fi latency over the Thor's loopback.
- ✅ A copied reflex process, unmodified except two env-gated lines, already makes
  real bot decisions through the Orin with 0 failures in 35 calls.
- ❌ It cannot take the full community tick (no decision batching in llama.cpp for
  lfm3-d1); that needs the d1dec engine ported to the Orin, which the numbers above
  now size (~4 GB, same 2.5 GB model, target ≥ 10 decisions/s on sm_87).
- ⚠️ Both boxes on Wi-Fi: p95 decisions ride an 80 ms-average, 444 ms-tail link.
  Wire the Orin when the Thor's wired move happens.

Note on the memory floor: at report time a concurrent third-party build on the
Orin (a gsplat CUDA pip install, ~1.1 GB) pushed MemAvailable to ~1.3 GB; with it
absent the steady state is ~2.6 GB available (the llama-server's own RSS is
2.5 GB: Q8_0 weights + 8×1 K ctx slots + CUDA context).
