# `rolling-perception` read as a stream platform, and the harmony map for `rolling-harmony`

*2026-11-01, read-only study. Clone: `third_party/rolling-perception` (gitignored, private
SI-Thor/rolling-perception --depth 1 — never copied here, never moved to a public repo,
never written to). The other agent of Casey's is actively building in that repo right now
(the 48 h camera soak runs to 2026-11-03); nothing in it was touched, no service of theirs
was approached (`confluence-watch`, `~/confluence-play`).*

**What this document is for.** (1) What `rolling-perception` is, with its own measured
numbers cited, and (2) one row per seam between it and our lanes, each with a concrete
interface proposal (who emits what, in which format, at what rate), then (3) the three
smallest joint builds, and (4) the questions to forward to the other agent.

**What we did.** Read `docs/READING-GUIDE.md`, `docs/RESULTS.md`,
`docs/SPEC-STREAM-PLATFORM.md` (+ Amendments 1–2), `DESIGN.md`, `slice3/synth/README.md`
and the crate/slice READMEs. We ran nothing (no model, no GPU, no `thor-admit` lease) and
measured nothing: **every number in §1 is theirs**, quoted from the file named beside it.
The box state for this study is "Thor idle, no leases held" — a clone, reads and greps.

---

## 1. What it is

### 1.1 One paragraph

It is a **stream platform for a Thor ("Confluence") standing on a working rolling-perception
engine**: every stream in the house (library files, cameras, live sources, audio, feeds,
screens) ingested as *items*, perceived **rolling** rather than frame-batched, kept as
structured text in per-stream ledgers, and served back as one shelf, one player, and one
change feed that is silent unless a published verdict says otherwise ("Watch this for me,
tell me what changed — otherwise silence", `docs/SPEC-STREAM-PLATFORM.md`). The engine's
claim under it is the one our brief names: **a maintained world state beats held samples for
a late reader, 8–18×** (`slice3/synth/README.md`).

### 1.2 Rolling stages vs frames — the engine's numbers

The pipeline is a five-stage cascade (**perceive → decide → direct → refine → publish**)
running through real rings, with per-lane phase offsets, publishing at *stage completion*,
never on a clock tick. Verdicts are claims about *this* tick; stale scores never re-fire.

| what | measured (theirs) | source |
|---|---|---|
| first output, rolling vs batched, identical work (400 µs stagger, CPU) | **243.5 µs vs 2,528.6 µs — 10.39×**, checksum Δ = 0 | `docs/RESULTS.md`, `crates/rolling-perception` |
| first output on GPU | 5.74 ms vs 21.41 ms — **3.7×**, total completion unchanged | `SPEC-STREAM-PLATFORM.md` §2.2 |
| cross-arch determinism | checksum 345101.1999 identical on x86_64 and aarch64 | `README.md` |
| adaptive stagger vs fixed under drift | prediction p95 **1,669 µs vs 854,285 µs**; exact tie at zero jitter | `crates/rolling-adaptive` |
| cascade gating | **71.9 % of perceive ops skipped**; sheaf energy 132.75 → 95.97 | `crates/rolling-pipeline` |
| NVRTC hot-swap from Rust at launch boundary | **1,000/1,000 bit-exact**; sm_100 CUBIN refused (error 209), sm_100 PTX runs | `crates/cuda-thor` |
| persistent kernel for slice work | loses 9–27× (resident-grid starvation); two-stream shadow is the default (big slices 3.6→3.0 ms, small 4.2→2.7 ms) | `crates/cuda-thor`, `SPEC` §2.5 |

So: rolling buys *continuity* honestly (10.4× / 3.7× earlier first output, same total work) —
not throughput. The stagger, not a frame clock, is the scheduling doctrine.

### 1.3 The unified-memory ring

Per lane, one **SPSC ring** of 64-byte-aligned `SlotHeader`s with separately allocated
64-byte-aligned payloads, and a per-slot generation protocol (free-for-n → ready-n →
free-for-(n+cap)) where **one atomic word** does all the synchronisation (`Release` on
publish, `Acquire` on acquire). Loss is always accounted: `produced == consumed +
dropped_newest + dropped_oldest + in_flight`, asserted at shutdown (`DESIGN.md` §3). Their
seed's `FluidSubstrateBuffer` protocol is kept in the design record as an autopsy — four
named defects (a finaliser that publishes the wrong generation, a livelock on wrap, no
consumer-side protocol at all, a raw `*mut f32` handed out with no generation check):
"the protocol as a whole was never stated, so no line could be checked against it."
On the GPU side the same discipline is **unified memory by role**: control/flag slots in
host-pinned *mapped* memory (doorbells), bulk tensors in managed memory
(`directManagedMemAccessFromHost=0` on this part), kernel variants swapped only at launch
boundaries with epoch retirement. Hardware: AGX Thor sm_110, 20 SMs, 122 GiB unified
LPDDR5X, driver 595.78, CUDA 13.2 (`docs/FEASIBILITY.md`).

### 1.4 Laplacian consistency (the sheaf refine)

Refine = one **Laplacian step over the tile grid** ($s \leftarrow s - \alpha D^{T}(Ds)$,
energy accumulated in f64, no allocation in the step, NaN refusal as a hard error). Measured
effect: fixture **precision 0.60 → 1.00 at recall 1.00** on the sheaf ablation, and the
cascade's energy 132.75 → 95.97. On real scenes, gated vs ungated frame verdicts agree
**1.0000** on the cuts sequence. Local agreement between tiles is a stronger signal than any
single judge — which is how it is used.

### 1.5 Lineage

`present: u64` bitmask + `counts: [u16; 64]` saturating visit counts + `overflowed` flag,
≈ **144 B per slot**, riding with the payload (`DESIGN.md` §5). Order is *not* in the slot —
it is in the replay log, opt-in and priced. "**Verdicts without lineage are not published**"
(`SPEC` §2.3). The seed's prime-product lineage ("did p ever divide S?") is fenced in
`pir.rs` as an experiment with failure-demonstrating tests and excluded from all non-test
code by a CI grep.

### 1.6 Viewport gating

`rolling-substrate-core/gating.rs` ("FluidAttn, Pillar 3"): ROI/viewport gating where the
skip is *demonstrable* — gated output inside the ROI is bit-identical to ungated, tiles
outside are never touched (sentinel-tested), and ops are counted so the saving is a number
(71.9 % of perceive ops skipped). The `direct` stage sets the viewport with a **deadband**
(band + yaw, Casey's two named parameters): the gate moves at most 2 cells toward the target,
only after the challenger wins for `yaw_ticks`, and gate churn is a first-class metric.

### 1.7 Confluence cells, presence, the shelf

- **Confluence cells** (Amendment 2): "anything is a cell in a graph — a stream, a terminal,
  a model, a camera, a voice — and the connections between cells are second-class citizens
  next to the function each cell achieves with whatever power and IO is attached." The
  substrate's rings are one rendering of cell-to-cell flow; **the ledger is the graph
  written as text**. Amendment 1 makes the wiring model the service model (one way to wire
  anything) and the **converter** the platform's job: "a translation becomes a conversion" —
  a mapping understood once compiles into working machinery. Thin devices are first class
  (the phone-as-camera is the reference IO node; installability has an acceptance test).
- **Presence** (Amendment 2): a browser lends its senses to the Thor; the Thor remains the
  only mind. Presence is *a session a person opened*, with a live indicator — Panel 1's
  refusal stands: **no always-on ambient microphone**. Measured: resident Piper vs spawn
  **1,974 → 287 ms**, full voice loop **2,891 → 1,284 ms**; presence brain
  Qwen3-Coder-30B-A3B at 65 tok/s (already on the disk); battery 7/7 with zero invented
  numbers; v3 claim checker 23/23 unit traps, 8/8 stub-fed traps replaced before TTS,
  battery 6/7 twice — failures upstream in STT garbling, and **no third run taken to fish
  for 7/7** (`slice2/presence/README.md`).
- **The shelf**: one shelf across stream types (a film, a camera event and a radio stream are
  all items with one spine: id, type, source, perception state, artefact pointers).
  Backfill pass 1+2 shelved **234 real items** (232 images, 2 videos; thumbs 232/232,
  posters 2/2, zero NVENC draw) and counted the house's whole video holding at **65.9 s**
  (`slice3/BACKFILL-PASS1.md`). Perception state is *visible* on the item — an unperceived
  item is honestly unperceived.
- **Budgets**: perception is metered in **embed-seconds** (one I-JEPA embed ≈ 0.173 s) with
  plain-language knobs ("spend freely / normal / sip / reflex only") that compile to numbers
  shown next to the words; a yield ladder L1–L4 makes the platform a *tenant* of Casey's
  bench (2026-10-28 ruling).
- The serving wall was measured, not assumed: NVENC **64/64 sessions opened, no per-session
  cap**; the cap is aggregate **~580–640 fps** of 1080p; realtime transcodes hold through 16
  and break at 24 → promise 8, engineer 12, hard cap 16; the player is remux-first with an
  encode-fps budget (141/141 frames and 1800/1800 through it, 429 refusal at cap while remux
  still serves, a frame-counter watchdog that kills a stalled source and marks it failed)
  (`slice2/NVENC-BENCH.md`, `slice2/player/RESULTS.md`).

### 1.8 "Maintained world state beats held samples 8–18× for late readers"

`slice3/synth/` prices the engine-as-synthesiser claim against a held-sample reader at lags
0–10 s (synthetic ground truth + one real-data echo; 17/17 labelling rules tested).

| lag (s) | reader age (s) | sampler mean err | engine mean err | ratio |
|---|---|---|---|---|
| 0 | 0.27 | 0.935 | 0.087 | **11×** |
| 1 | 1.27 | 4.347 | 0.236 | **18×** |
| 2 | 2.27 | 7.717 | 0.442 | 17.5× |
| 5 | 5.26 | 17.545 | 1.380 | 12.7× |
| 10 | 10.26 | 33.083 | 4.065 | **8×** (5× on p95) |

Their own qualifications, which matter more than the headline:

- **"Latest sample" is already a stale serve** — an undelayed reader holds a read averaging
  0.27 s old, costing the sampler 0.94 units of mean error on moving objects.
- Every serve carries an evidence kit: `basis`, `extrapolation_age`, a stated `tolerance`,
  the lens's `stale_threshold` — age 0 → `corrected`, age ≤ period + 3σ → `extrapolated`,
  above → `stale`, **never "now"**. Past ~1 s almost every serve is stale-labelled in their
  rig — and the stale-labelled extrapolation still beats the held sample 8×; the label
  governs how a consumer may *act*, not which estimate is best.
- **The synthesiser lies at turns.** For ~2 s after a velocity flip the engine is worse than
  the stale sample (peak error 60× baseline in the [1, 2) s window; full recovery by ~4.4 s),
  and under sustained acceleration it *bleeds* (~6–7× baseline for the whole 30 s, no alarm
  moment). **Snap rule v2** (3× trigger + decontaminated band) cuts reversal recovery
  **6.0 s → 2.0 s** with 2 corrections and **zero false snaps**, controls/speeder
  bit-identical.
- Their real-data echo: a naive sampler's scene-label accuracy oscillates 1.000/0.000 by
  frame parity; the rhythm-learning engine reads **0.000 error at all lags**.

### 1.9 What they publish as deficits (their own list, condensed)

The diff gate is **a ranker, not a separator** (skipped-tile drift 0.20 vs embedded 0.48);
every brain tested was blind to a stale heartbeat presented as raw data (the fix lives in
the digest, not in the model); panel round 2's cache design failed honestly ($0.034 / $0.054
runs); the Thor's ffmpeg 8.0.1 has no scale filter; **slice 1's precision number does not
exist yet** (the soak's silence is machine-verifiable, precision needs a human, verdict
2026-11-03); presence has never been used by a human; and Casey's decision-model servers
(:8295/:8296) are down — **reaped by the Thor's `thor-admit` guard because their leases were
absent**. Their house rule is ours: no claim without a test or a bench number, deficits at
the same prominence as wins, the repo private until Casey calls the graduation.

---

## 2. The harmony map

One row per seam. "Interface" is a proposal written from their spec, **not agreed** — the
questions in §5 are how it gets agreed.

### Row 1 — the vibe-sandbox playtester and an H.264/viewport stream as Confluence cells; NitroGen as a rolling-stage reflex

*Ours:* `~/lm-wt/vibe-sandbox` (prompt JSON → watcher → generator → headless Blender → the
critic incl. self-intersection → GLB outbox + ledger event → three.js viewer → a Playwright
capsule walk reporting collision traps / unreachable areas / floating objects / frame time →
`qa_report.json` → gate). Its v2 plan already names "H.264 viewport stream + VLM tester".
*Theirs:* the §3.6 screen/game-capture ingest class (tile-verdict unit per nominated frame,
perception sampling gate-paced, the *served* stream a separate passthrough that never shares
the perception queue) and the measured encode wall (§1.7).

**Interface.**
- **vibe-sandbox → Confluence, per run:** one item record in their shared ingest contract
  `{stream_id: "build/<lane>", arrival_stamp, content_ref (GLB sha256), class: qa_report}`
  plus per-stage receipts (ms, verdict) — the Radio Room discipline their spec adopts. One
  item per prompt drop (seconds), receipts per stage; nothing else. Each GLB outbox artefact
  is a shelf item with perception state `unperceived → perceived`, exactly like a library file.
- **The viewport → Confluence, live:** the three.js canvas captured at **30 fps H.264 via
  NVENC** as a serve-plane passthrough (their player can hold it; one more session on top of
  a measured 64/64), with perception sampling at **1 fps nominated frames** as 4×4
  tile-verdict units (µs-class diffs, embeds only where nominated, ~173 ms each). Perception
  and the passthrough never share a queue (their §3.6 rule) so a playtest can never stutter a
  human's spectating.
- **NitroGen as the rolling-stage reflex:** NitroGen is a 500M DiT that maps the last frame
  to a 25-dim gamepad action chunk (horizon 16) — a pure system-1 executor
  (`docs/research/nitrogen.md` §3.1). In the playtest lane it is the **reflex tier** *of
  motion*: one action chunk per tick in the ring vocabulary (a slice per tick, drop-and-
  receipt rather than queue — frames are worthless old), with the QA/critic verdicts staying
  system-2 above it. Serve shape: ZMQ REP on Linux (their `serve.py` pattern), one
  `thor-admit --tier live --peak 4G --label nitrogen.serve` lease, reply
  `{action_chunk[16×25], inference_ms}` per request at ~10 Hz (vendor latency 60–100 ms,
  **not measured by us**).
- **Must not break:** NitroGen's licence is NVIDIA non-commercial research only — nothing
  from its checkpoint ships in a product. The watched screen is an *agent's* view of a game
  build (our privacy rule allows that); frames stay in memory, only the QA report is stored.

### Row 2 — screen-watcher, `core/drift`, seat-watch-live: rolling outputs into the rate gate (time-first)

*Ours:* `docs/design/screen-watcher.md` (a reflex gate over a *change stream*, inputs are
rates with Δt, silence is a scored action), `core/drift` (six signals, one-sided rate gate
with band+dwell over 5-minute windows of the world ledger; rate gate **6/6 holdout episodes
at 1.63 alarms/hour of world** vs the level gate's 4/6 at 0.71; pause ladder soft/tier/hard),
and `seat-watch-live` (one line then exit: `DONE/QUOTA/STALL/BOX`; the measured gate behind
it is the 2026-11-01 replay: rate gate **8/13 interventions caught, 71 speeches, 50.3 min
mean lead, 385 min of stall saved** vs level gate 4/13, 184 speeches, 32.6 min lead).
*Theirs:* the attention plane's uniform entry grammar (*source, what changed, when, evidence
attached*), verdicts-not-raw-events, silence by default, "stream down" as its own feed entry,
and the design target **≤ 1 false change event per stream per day** maintained from a
published precision estimate.

**Interface.** (a) **Us → them:** seat-watch-live's one-line events and `core/drift`'s alarms
are already a sensor/text feed (their §3.7 class) — emit one `attention/feed.jsonl` entry per
event `{source: "seat:<job>" | "world:drift", what: "<reason token>", when, evidence: {signal,
badness, delta}}`, at our measured ~0.8 events/hour. (b) **Them → us:** their published
verdicts and `stream down`/stale decls import into seat-watch-live as extra `BOX` reasons
(`telemetry_dark` already exists) and as inputs to the rate gate's badness series — never as
frames. (c) **The number exchange:** their ≤1 false/day per stream is the same metric as our
3.69 FA/h (rate) vs 10.54 (level); the two should be reported against each other on our
13 labelled episodes.
- **Must not break:** our gates stay **time-first** (one-sided rise, band+dwell, hysteresis
  reset across gaps) — feed them rates, not levels, not pixels; the watch keeps its
  one-line-and-exit contract; derived events only are stored.

### Row 3 — design for absence: the returning human is a late reader

*Ours:* `docs/design/vibecode-in-world.md` §4 — the Biographer letter (≤ 150 words + one open
question, *a view over the ledger, not a summary of a summary*), the five-beat return
(threshold, recognition, digest, thread, quiet moment), the Director's cut, the scrubber over
`seq`. The ledger: **82,952 events / 22.07 h** (3,760/h, ≈5.1 MB/h). Keyframes measured
(`exp-syzygy-keyframes.md`): a cached keyframe + delta read is **11.7× faster** (1.712 s →
0.146 s on a 14,012-token prefix), but under motion the delta is the expensive thing
(50,004 tokens/frame vs the full frame's 6,523; best delta policy 27,539 = 4.2×), idle-scene
refresh is 230–388 tokens/frame, and a motion channel is 228 B/frame vs 35,828 B (**157×**),
lifting "which way is this moving" accuracy 0.431 → 0.889.
*Theirs:* §1.8 — the synthesiser and its evidence kit, the reversal window, snap rule v2.

**Interface.** (a) **Four fields on every answer the return serves:** their
`basis` (corrected | extrapolated | stale), `extrapolation_age`, stated `tolerance`,
`stale_threshold` — attached at serve time to each of the five beats' answers (5 per
return page; negligible rate). Our folded world state is the *engine*, the raw ledger is the
held sample; these labels say which one the reader is looking at. (b) **The reversal lesson
transfers:** after a rewind or auto-pause (a world "flip"), the first span of digest lines is
labelled `post-flip, replay-backed` and served from the ledger replay, not the extrapolated
snapshot — our analogue of "for ~2 s the stale sample is more honest than the synthesiser".
What the span is must be **measured on our ledger**, not imported (their 2 s is their toy).
(c) **Keyframes on the human's own stops** (their snap rule v2 shape: trigger at 3× plus a
decontaminated band, zero false snaps on their rig) instead of a fixed interval — §2.3 of the
design already concluded the same from the other direction.
- **Must not break:** no invented history. Stale is published as stale and labelled; their
  rule "a verdict is a claim about this moment" matches our "gaps are recorded, never
  backfilled with invention."

### Row 4 — Confluence as the UX shell for agent-world and the vibecode loop

*Ours:* agent-world's human surfaces (Java `:25565`, Bedrock `:19132` through Geyser +
Floodgate, watchers at `http://192.168.0.78:8080/`, `/ascii`, `/voices`) and the vibecode
loop (intent → proposal → pre-flight → commit → live world, rewind as a fork).
*Theirs:* browser-first clients and thin devices first class (Amendment 1), a terminal that
lends senses (Amendment 2), one shelf / one player / one change feed, the bridge console, and
an install + service model with an acceptance test.

**Interface.** (a) Each agent-world **view** (world stream, `/ascii`, `/voices`) and each
vibe-sandbox outbox item becomes a **Confluence cell**; their state is our ledger's text and
every human surface we own becomes a projection of it (their world-is-text rule: the ledger is
right, the rendering is replaceable). (b) The vibecode loop's *read* side — "what changed
while I was out" — is their cross-stream change feed: our rows convert into its uniform entry
grammar; the *write* side (proposals, pre-flight, commits) stays ours, each landing as one
feed entry. (c) **Rate discipline:** our ledger records ≈ **1.04 events/s** live; that must
fold to *verdicts* (drift alarms, branch moves, auto-pauses, gap notes) — one entry per
verdict or per 5-minute window, never one per event. (d) Delivery is their browser-first
client (the web viewer and the Bedrock tablets keep their own protocols and read the same
projections). (e) **Presence is the voice face of the return:** their voice loop is measured
(1,284 ms full loop with resident Piper) and their acceptance gap ("presence has never been
used by a human") is the same gap as our from-the-chair five-beat test — one joint test
answers both.
- **Must not break:** presence stays *a session a person opened*, with a live indicator, no
  ambient mic (their Panel 1 refusal); a guest profile must not see the children's views
  (their §1.4 profiles are a viewing boundary, ours is a privacy rule).

### Row 5 — the lock-free ring vs our persistent-queue doorbell, and `thor-admit` leases

*Ours* (`docs/lab/xp-batch/`): a resident kernel polling a ring in pinned memory beats
per-job CUDA Graph replay by **12× at p50 (3.01 µs vs 34.9 µs) and 860× at p99 (5.41 µs vs
4,657 µs)** at 314k jobs/s (rel err 2.4e-08 over 100k jobs); mapped pinned memory is coherent
both ways for polite single-thread polling (the doorbell design works), while a 20k-thread
grid spinning on one mapped word never sees host writes and a non-volatile empty spin is
compiled away (**atomic acquire is mandatory**); driver-API CUDA Graphs hang; stream
priorities are structurally useless under a persistent background loop (1/1,200 launches
served); green contexts isolate (6+14 SM split, 1,195/1,200 launches at a 10 ms cadence,
overlap 1.00) but cost 6× idle p50; L2 persistence is accepted but inert. `thor-admit`:
admission before spend, leases (`--tier/--peak/--label`), lease-before-lock, a guard that
sees GPU bytes per process (r13) and reaps unleased multi-GB loads — which is exactly how
their :8295/:8296 servers died (their own deficits list).
*Theirs:* §1.3 — the SPSC slot protocol, the accounting invariant, the mapped-pinned
doorbell pattern (4.8 µs mean request→ack on their tiny ack path), two-stream shadow as the
default arrangement, and gpu-queue successor discipline as their placement doctrine.

**Interface.** (a) **One descriptor-ring contract, two implementations:** 64-byte slot
header + one atomic sequence word (their layout), doorbell on a mapped pinned word with
atomic release, ack ring back (our persistent kernel), and **both** sides assert
`produced == consumed + dropped + in_flight` (theirs) / every shed receipted (ours). First
joint measurement: run our persistent-queue job shape through their `rolling-substrate-core`
ring and report both p50/p99 tables in one document — CPU bookkeeping theirs, GPU residency
ours; no models, no licence questions. (b) **Lane families hold `thor-admit` leases:** one
lease per family (`thor-admit run --tier live --peak <GiB> --label confluence.<family>`) and
their yield ladder L1–L4 becomes the *lease* order — backfill at `--tier study` (first to
die), embed lanes `--tier live` with peaks measured around the rack's 173 ms/embed class,
reflex-only mode = a lease held with no model resident. Their "gpu-queue successor
discipline" is a good doctrine with the wrong controller for this box; `thor-admit` is
already the enforcement point and already greps the plane their deficit list trips over.
- **Must not break:** never start anything that preallocates GPU memory without
  `XLA_PYTHON_CLIENT_PREALLOCATE=false` on the Thor (GPU memory is system memory); nothing
  multi-GB runs unleased — the guard is not a negotiation.

### Row 6 — lineage vs our ledger provenance

*Ours:* the world ledger's three things (events with a gapless per-project `seq` that is the
resume cursor, 4 KiB payload cap with hash spill, seeds), actors named (Kite 24,375 · Sprout
8,509 · Pebble 7,270 · Timber 2,413), and the fold rule — "every projection row derives from
audit events, in seq order, and nothing else." *Theirs:* §1.5 — bitmask + saturating counts
per slot, order only in the replay log, verdicts without lineage unpublished.

**Interface.** Two granularities of one claim, cheap to join:
- **Names:** their `NodeRegistry` names map **1:1** to our ledger `actor` values (one mapping
  table in the docs, no code). Their node IDs are registry-assigned; ours are strings; the
  table is the whole translation.
- **Carry their micro-lineage in our verdict rows:** add a `lineage` field to
  `judge.verdict`/`critic.verdict` rows carrying their `{present, counts, overflowed}` triple
  (or the resolved node-name list). Cost measured against our baseline: +144 B on ≈1,356 B
  per event ≈ **+10 %** of ≈5.1 MB/h. What it buys us: a verdict row that says exactly which
  stages ran and how many times — today `tile.played` rows name the actor but not the path.
- **Order is free in our direction:** our `seq` is their replay log's tick; any exchange
  carries `seq` as the replay key and their ordering claim becomes checkable on our data too.
- **Accounting invariant shared:** adopt their `produced == consumed + dropped + in_flight`
  as the assert behind our ingestion sheds (the vibe-sandbox inbox and camera-style drops) —
  our current rule ("every shed receipted") is the same claim without the assert.

---

## 3. The three smallest joint builds

1. **The ring contract cross-bench.** A short spec (64-byte slot, one atomic word, accounted
   drop, mapped-pinned doorbell with atomic acquire) plus a bench that runs the
   persistent-queue job shape through their `rolling-substrate-core` ring and reports both
   p50/p99 tables and the accounting assert in one document. CPU, ≤ 1 h of the Thor, and the
   known anomalies get a second rig to sit in (their two-stream shadow vs our plain-launch
   mapped-write stall after job 1).
2. **The event converter ("a translation becomes a conversion").** One small tool that maps
   `world-ledger.sqlite3` rows and seat-watch-live's one-line events into Confluence
   `attention/feed.jsonl` entries (uniform grammar) and back, folding 1.04 events/s into
   verdicts. Acceptance: our 13 labelled episodes (seat-watcher ground truth) come through
   with the same catch counts, and their ≤1 false/day target is reportable on our data.
3. **The late-reader kit for the return.** Their serve evidence kit (`basis`,
   `extrapolation_age`, `tolerance`, `stale_threshold`) plus snap-rule keyframes-on-stops,
   attached to the five-beat return's answers in `vibecode-in-world.md` §4. Acceptance: replay
   one real absence (the 22 h window of §2.2) and report our own lag table.

Kept out of the three because they are not small: the NitroGen reflex under the playtest lane
(checkpoint download, 4 GB lease, Windows client or Linux stand-in — `docs/research/nitrogen.md`
§4), and the presence voice loop as the return's face (needs their rack/model servers; their
own :8295/:8296 are down and the launch recipe is Casey's).

---

## 4. What we did not verify

- **We measured nothing.** Every `rolling-perception` number in this file is theirs,
  un-re-run by us; their tests (55 workspace tests, 52/52 native on the Thor per `SPEC` §1.1)
  were not run. Our own numbers are cited from the documents beside them, measured earlier by
  other seats, on their stated box states.
- Slice 1's **precision does not exist yet** — the 48 h soak is running (started
  2026-11-01 18:18 AKST, verdict due 2026-11-03; at +50 min: 5,431 frames, 0 events, spend
  ratio 0.0002, `silence_meaningful = true`). Anything that needs its precision must wait for
  the human judgement of that window.
- **The interfaces in §2 are proposals written from their spec**, not agreements. Their repo
  is being actively built; names, rates and budgets may move under us.
- NitroGen's serve latency, the ~10 Hz playtest cadence and the H.264 viewport path for
  vibe-sandbox are vendor claims or plan items (`docs/research/nitrogen.md` §1.3, §5; the
  viewport stream exists as a v2 line only).
- The reversal span for a *rewind* (Row 3) is unmeasured on our ledger; their ~2 s is their
  toy's and must not be transplanted.
- Licensing posture: their repo is private until Casey calls the graduation and nothing of it
  is reproduced here but short citations of numbers and of Casey's own framing; NitroGen is
  NVIDIA non-commercial research only. If either changes, the rows above that quote them need
  a re-read.
- Noted for the record: `NOTE-FROM-DIRECTOR.md`'s thor-admit parallel-test flake is already
  fixed on this branch (`fd9d776`, the integration suite serial by default) — nothing to do.

---

## 5. The questions to put to the other agent

*(Written as a note Casey can forward as-is.)*

> **To the agent behind `SI-Thor/rolling-perception`, from the `rolling-harmony` desk
> (forwarded by Casey).** We read your docs read-only — READING-GUIDE, RESULTS, the
> Confluence spec and both amendments, DESIGN, and the slice 3 synthesiser. Nothing of yours
> was copied; we cite your numbers in our `docs/research/rolling-perception.md` and quoted
> your repo nowhere else. If you would rather we not quote any number before graduation, say
> so and we will strike them. We have some seams we would like to build, and ten questions.
>
> 1. **The soak (verdict due 2026-11-03).** When the hand-labelled precision lands, may we
>    have the corrections ledger? We have 13 labelled intervention episodes from
>    2026-11-01 (seat-watcher ground truth) in the same shape and will trade.
> 2. **Ranker calibration.** Your LensFile refits `ranker_calibration` weekly from
>    (reflex score, true drift) pairs. In what shape and at what rate would you want them?
>    We can emit ours from the world ledger (our rate gate's badness/event pairs) as one
>    more text feed.
> 3. **The ring.** Is a shared descriptor-ring contract worth one experiment: 64-byte slot,
>    one atomic sequence word, accounted drop, mapped-pinned doorbell with atomic acquire,
>    ack ring back? Our persistent-queue bench numbers are p50 3.01 µs / p99 5.41 µs /
>    314k jobs/s with one unexplained anomaly (plain per-job mapped writes stall after job 1);
>    has your two-stream shadow path ever seen that?
> 4. **Admission on this box.** Where do you want lane-family admission to sit? We run
>    `thor-admit` (admission before spend; the guard sees GPU bytes and reaps unleased
>    multi-GB loads — it is what took your :8295/:8296 down). Proposal: one lease per lane
>    family, honest peaks, your yield ladder L1–L4 mapped to lease tiers. We will write the
>    converter if you will take it.
> 5. **Late reader.** Is the serve evidence kit frozen (`basis`, `extrapolation_age`,
>    `tolerance`, `stale_threshold`)? We want those four fields on our returning human's
>    answers (the five-beat return over our ledger). And what does snap rule v2 need from a
>    Minecraft world ledger at 3,760 events/h — events or state? Our keyframes can be taken
>    on the human's own stops.
> 6. **Stale heartbeat.** Your finding is that the fix lives in the digest. Is the v3 claim
>    checker (23/23 unit traps) callable as a library, or do we re-implement the traps for our
>    ledger digests? Our return letter has the same failure mode.
> 7. **Lineage names.** Can `NodeRegistry` names carry our actor names (Kite / Sprout /
>    Pebble / Timber) 1:1, instead of us translating? And would you accept the raw
>    `{present, counts, overflowed}` triple inside foreign-ledger verdict rows, or do you want
>    the resolved node list?
> 8. **The viewport stream.** For a playtest viewport we want one H.264 session plus 1 fps
>    perception sampling off the same canvas. Given your NVENC wall (aggregate ~580–640 fps
>    of 1080p; promise 8, hard 16 transcodes), what per-cell cap do you recommend so a
>    playtest never eats the household's player headroom? And what exactly does the
>    frame-counter watchdog emit at failure — a text line or a feed entry?
> 9. **Presence.** You have measured the voice loop but never had a human use it; our
>    five-beat return is a from-the-chair acceptance too. One joint session would pay both
>    debts. (Our rule is yours: a session a person opened, a live indicator, never ambient.)
> 10. **Where we stop.** If any row of our harmony map is heading somewhere you are not
>     going — or is already obsolete under your build — tell us and we will rewrite the row
>     rather than build against it.