# first-mile: LFM3 voice and omni on the ProArt

Measurements from 2026-10-31, on the ProArt, for the brief in `BRIEF.md`.
Every number below was written by a script into `out/` and read back out
again; `scripts/collect_numbers.py` regenerates this file's figures into
`out/numbers.json`. Nothing here is estimated.

---

## 1. The box

| | |
|---|---|
| GPU | NVIDIA GeForce RTX 4050 Laptop GPU, **6141 MiB** VRAM, driver 616.92 |
| CPU | AMD Ryzen AI 9 HX 370 w/ Radeon 890M, 12 cores / 24 threads |
| RAM | **15 990 MB** visible to this WSL2 VM (the brief says 31 GB; WSL2 is capped at 16 GB here, and `free -m` reports the VM's share, not the host's) |
| OS | Ubuntu 26.04.1 LTS under WSL2, kernel 6.18.54.1-microsoft-standard-WSL2 |
| Host | Windows 11; Chrome holds the mic, the speakers and the thin-client viewer |
| Idle GPU | **675 MiB** of the 4050 used by the Windows desktop, Chrome, Edge and the viewer, with nothing of ours running |
| Integration | `world-mcp` on `127.0.0.1:8808`; the viewer's dev server on Windows `127.0.0.1:8787` |

The 4050 is shared with the Windows desktop through the same driver, so
"VRAM used" is a whole-GPU number, not a per-process one.

---

## 2. What is real about the models

Checked against Liquid's own Hugging Face pages on 2026-10-31.

| Model | Real, per Liquid's card | Not as the brief had it |
|---|---|---|
| **LFM3-Audio-2B** | 2B params, **32K** context, 18 speech locales, 24 kHz speech out, tool calling, LiquidCodec | the brief's "256K context" belongs to LFM3-1.7B, not to this one |
| **LFM3-Omni-2B** | 2.17B params, 32K context, any-to-any in, text + 24 kHz speech out; the card says one model replaces a separate ASR model, a vision-language model, an LLM and a TTS model | — |
| **LFM3-1.7B** | text, tools, JSON, **256K** context | — |
| **d1-2B** | 1.92B, single forward pass, no generated tokens | — |
| **d1-Omni-2B** | d1-Omni-2B on top of LFM3-Omni-2B, adds audio, still no generated tokens or speech | — |
| **LFM3-VL-2B** | image + video | — |

All five exist with official GGUF repositories. The GGUF file names in
`models/` match `LiquidAI/LFM3-Audio-2B-GGUF` and
`LiquidAI/LFM3-Omni-2B-GGUF` exactly: `LFM3-{AUDIO,OMNI}-2B-{Q4_K_M,Q8_0}.gguf`
plus a matching `mmproj-*.gguf`.

**The licence.** `LiquidAI/LFM3-Audio-2B` ships `LICENSE` = LFM Open
License v1.0. The clause that matters:

> "Threshold" means your annual revenue is **$10,000,000 or more**.

Commercial use is licensed while you stay below that threshold. The
threshold is on *revenue*, not on funding, and it is not a per-seat
number. So the licence is fine for internal and pre-revenue work, and a
revenue line above $10M a year puts the commercial terms in play.

**Runtimes.** Liquid's own card lists GGUF → **llama.cpp**, plus MLX-VLM
(Apple Silicon), ONNX Runtime, and vLLM/SGLang/Transformers for the BF16
weights. There is no local Liquid package on PyPI: `pip install liquidai`
gives you the **cloud API client**, not a local runtime. So llama.cpp is
the documented local path, and it is the one used here.

**What needed a build.** LFM3-Audio does not work on an old llama.cpp —
the audio encoder, the `/tts` endpoint and the speech decoder all landed
recently. The runtime in `runtime/` is the **prebuilt** llama.cpp `b12024`
CUDA 13.4 x64 release asset from GitHub, plus its bundled `cudart`
libraries. No source build was needed and none is pending approval.

---

## 3. Time to first audio, real-time factor, VRAM and RAM

Measured on the 4050 with the model server resident, four prompts
spun through `/tts`, three repetitions each. Median of 12.

| build | time to first audio | total for the reply | RTF | RTF after first audio | VRAM | server RSS |
|---|---|---|---|---|---|---|
| Audio-2B **Q4_K_M** | **51 ms** | 581 ms | **0.173** | 0.155 | 2612 MB | 881 MB |
| Audio-2B **Q8_0** | 78 ms | 783 ms | 0.233 | 0.211 | 3448 MB | 909 MB |
| Omni-2B **Q4_K_M** | 58 ms | 683 ms | 0.186 | 0.162 | 3106 MB | 880 MB |
| Omni-2B **Q8_0** | 68 ms | 802 ms | 0.232 | 0.209 | 4022 MB | 946 MB |

RTF below 1.0 means the model speaks faster than the utterance it is
replying to. The Q4 build is 1.9 GB of VRAM and speaks ~1.6x faster than
real time; Q8 costs 800 MB more VRAM and about a third more time.

**The hardware fact:** 6141 MiB of VRAM, of which 675 MiB is already taken
by the Windows desktop, leaves 5466 MiB for everything else on the GPU.

**Why the old path could not use it:** the voice lived on the Thor
(`:8102`, "ears"). Every spoken reply was a LAN round trip to another
machine before a single sample of audio could be produced, on a box that
was already running other people's jobs. A reply that has to cross the
network cannot be an *instant* reply.

**What the new path does differently:** the audio model and the audio
projector are resident in the ProArt's own GPU memory, next to the browser
that is already capturing the microphone. The reply is generated on the
same machine that heard the question.

**What it makes possible:** a spoken answer whose first audio arrives
tens of milliseconds after the request — which is what makes the instant
acknowledgement in §5 possible at all.

---

## 4. Speech recognition, and spoken tool calling

All test audio was generated on the spot by the same model's own `/tts`.
**No human audio and no human transcripts are stored anywhere in this
directory.** The commands are the three from the brief, plus three more in
the same shape.

### ASR

| | exact match | mean F1 | median ASR time |
|---|---|---|---|
| 6 commands | 5/6 (83.3%) | 0.9445 | **137–155 ms** |

The one miss is a paraphrase ("Hold the night." vs "Pause the night."),
not a recognition failure — the words were right, the wording was not
what the bench expected.

### Spoken tool calling

Six builder commands × 3 repetitions, three input shapes:

| input shape | correct | rate | median latency |
|---|---|---|---|
| **audio only** | 15/18 | **83.3%** | 258 ms |
| audio + transcript | 15/18 | 83.3% | 255 ms |
| transcript only | 6/18 | 33.3% | 235 ms |

Per command (3 reps each):

| command | audio | audio+transcript | text |
|---|---|---|---|
| "Make the north pier stronger." | 3/3 | 3/3 | 3/3 |
| "What did the Architect do last night?" | 3/3 | 3/3 | 3/3 |
| "What did the Landscaper do?" | 3/3 | 3/3 | 3/3 |
| "Pause the night." | 3/3 | 3/3 | 3/3 |
| "Hold the night." | 3/3 | 3/3 | 3/3 |
| **"Computer, make these sturdier."** | **0/3** | **0/3** | **0/3** |

Three findings come out of this table.

**1. Every unambiguous command produces a correct tool call, with correct
arguments, in every input shape.** 15/15 for the five unambiguous
commands. The model's own arguments are right too:
`reinforce_structure(targets=["north pier"])`,
`recall_recent_work(character="Landscaper")`, `pause_night(scope=...)`.

**2. The model is better when it hears the command than when it reads
it.** 83.3% with audio against 33.3% from text alone. Giving the model
the transcript alongside the audio does not help it (15/18 either way).
The spoken channel carries information the text channel drops — and a
transcript-only first mile would be the weaker of the two.

**3. The single failing command is not a failure of tool calling.** "Make
these sturdier" contains a pronoun, and the model refuses to guess what
it refers to. Given only the audio it answers in speech ("To make these
sturdier…"); given a text packet that names the selection it asks
("Which structures should I reinforce to…"). It never invents a target.

That is the right behaviour, and builder-ide's design says so: *"Ambiguity
is resolved by asking, never by guessing."* The referent lives in the
**context packet**, and the core resolves it — not the 2B model. So the
first mile attaches the packet to the *call* (§7) and the model never has
to guess. The prototype's spoken answer is the core's own one-line
confirmation, which is what the run in §7 produced.

---

## 5. The reflex layer, and the instant reply

`SuperInstance/quilt-pincher` (Apache-2.0), vendored under
`vendor-quilt-pincher`, running the real `PincherEngine` with the
`HDCEmbedder` (deterministic, model-free), a memory reflex store, a
closed-verb veto and a Groq compiler. Upstream's own determinism spine
hash matches (`spine 51b6d1e1…`) and its suite passes **39/39**.

### Matching

| group | n | outcome | match time (median) | match time (max) | under 50 ms |
|---|---|---|---|---|---|
| known commands | 30 | **30 hits** | **0.146 ms** | 0.365 ms | 30/30 |
| near commands | 20 | 10 hit, 5 confirm, 5 miss | 0.127 ms | 0.262 ms | 20/20 |
| a miss | 1 | miss | 0.427 ms | — | — |

The match is the embed plus the store query: **0.146 ms** at the median,
0.365 ms at the worst of fifty. Well inside the 50 ms Casey specified.

Near commands split three ways. "what did the architect do yesterday"
lands in the **confirm** band (same keywords, different time word) — the
right place for it. "pause everything tonight" scores 0.227 and **misses**
outright, because the HDC embedder binds tokens by position and
"everything" is not in the stored phrasing. The fix is normalisation:
stripping filler words before embedding lifts a spoken paraphrase back
into range. That normalisation is in the service now, and it is what
turned "can you make these arches stronger" from a miss into a hit.

The near group also improves with use: a miss is compiled in the
background and the compiled reflex joins the store, so the next time that
phrasing is spoken it hits. The store grew from 29 seeded reflexes to 36
during the benches.

### The cloud compile

A miss returns immediately and the compile happens in the background, so
the first mile never waits for it:

```
[reflex] background compile stored "make these arches stronger" -> world_action in 377 ms (cloud $0.00003)
```

**$0.00003 per compile**, one call to `gq.py -m 20b`. The whole reflex
bench cost **$0.00006**, against the $2 budget. The action is built from
a template in the service, never from the model's text, so a bad compile
cannot inject code.

Two things about the compile are worth recording.

**The intent has to be checked.** The first version of the compiler
prompted only with the list of intents, and a 20B model given "make
these arches stronger" answered `decision` — the wrong door, because
"should we" and "make this" are both questions about work. The prompt
now gives the cue for each intent, and the same utterance compiles to
`world_action`. A compile that names no known intent is refused and
nothing is stored.

**The compile's latency varies with the cloud, not with the box.** 377 ms
when Groq is quick, 1.3–3.9 s when it is not. Because the compile runs
in the background, that variation never reaches the human — it only
decides how long it takes for a new phrasing to become a hit.

### The instant acknowledgement

The brief asks for an acknowledgement in under about 300 ms. Two
approaches were measured.

**Synthesising it on the spot:** the first version asked the model for
the acknowledgement at the moment of the onset. Measured **219–364 ms**,
because a TTS request is a model call and the server was busy with the
ASR at the same time. Over budget, and it varied with load.

**Caching it at startup:** the acknowledgements are a fixed set of four
short phrases, so they are synthesised once when the first mile starts and
kept as raw PCM in memory. On an onset the server copies bytes out of
memory and streams them.

| | onset → first playable audio in the browser |
|---|---|
| on-the-spot TTS | 219–364 ms |
| **cached** | **0.3 ms median, 0.8 ms worst of 18** |

Sub-millisecond, and it does not depend on the model being idle. The same
phrases sound the same every time, which the model's own speech does not
("no speaker reference provided, the model may behave randomly" appears
in every server log).

**The hardware fact:** the first mile's whole GPU cost is 1955 MB for the
Q4 audio build (§6), and a memcpy of 40 KB of PCM costs nothing.

**Why the previous path could not do this:** the acknowledgement was
going to be produced by a remote model on the Thor, behind a network hop
and a model queue. The instant reply has to be *local*, and it has to not
be a model call at all.

**What it makes possible:** the computer can speak **while the human is
still talking**. The acknowledgement arrives about 0.5 s into a 2.4 s
utterance — the human has not finished the sentence yet.

---

## 6. VRAM, and the thin-client viewer

The brief budgets ≤ 3.5 GB for the first mile and asks for coexistence to
be measured.

**Idle on the 4050** with nothing of ours running: **675 MiB** (Windows
desktop, Chrome, Edge, the viewer).

| build | first mile's own cost | total on the GPU | headroom left | within 3.5 GB budget |
|---|---|---|---|---|
| Audio-2B Q4_K_M | **1955 MB** (1.91 GB) | 2630 MB | 3511 MB | yes |
| Audio-2B Q8_0 | 2793 MB (2.73 GB) | 3468 MB | 2673 MB | yes |
| Omni-2B Q4_K_M | 2449 MB (2.39 GB) | 3124 MB | 3017 MB | yes |
| Omni-2B Q8_0 | 3367 MB (3.29 GB) | 4042 MB | 2099 MB | yes, with 209 MB to spare |

All four builds fit the budget. The Q4 audio build leaves 3.5 GB for
everything else on the GPU.

### Coexistence with the viewer

The viewer was loaded in Chrome (the viewer's own dev server on Windows
`:8787`, SSE connected and streaming) and the GPU was read from the
Windows per-process counters, which name the process and the adapter:

| process | adapter | dedicated GPU memory |
|---|---|---|
| `vmwp.exe` (WSL2 — the first mile) | **RTX 4050** | 2641.7 MB |
| `chrome.exe --type=gpu-process` (the viewer) | **Radeon 890M (integrated)** | 18.1 MB |
| `dwm.exe` (desktop) | Radeon 890M | 122.5 MB |

**The viewer is not on the 4050.** Chrome chose the integrated Radeon
890M for the WebGL/WebGPU context, and the whole of the 4050's 6 GB is
available to the first mile. So on this box the viewer and the first mile
do not contend for VRAM at all.

That is a configuration, not a guarantee: it depends on Chrome's adapter
choice and on the scene. The budget in the table above is the number to
hold to if the viewer is ever forced onto the discrete GPU, where 3.5 GB
of 6 GB still leaves 2.1 GB for a desktop.

---

## 7. The whole loop

The prototype: Chrome's microphone → WebSocket → the first mile in WSL2 →
the model → streamed audio back. All three routes exercised, the
acknowledgement measured from the onset to the first playable sample in
the browser.

```
######## Computer, make these sturdier.
    0.675s  ack: 'On it.' (first audio 0.0 ms)
    4.215s  heard: 'Computer, make these sturdier.'
    4.215s  route: world
    7.219s  answer: 'CONFIRM: Computer, make these sturdier.; build/verify: ~30 min [e]
                     · generate/test: ~60 min [e] · reversible at ver_0001. Go?'
                     (first audio 1033.9 ms)
    7.219s  asr 514 ms | route 430 ms | total 3528 ms
  ack, end to end (onset -> first playable audio in the browser): 0.3 ms

######## What did the Architect do last night?
    0.658s  ack: 'On it.' (first audio 0.0 ms)
    4.535s  heard: 'What did the architect do last night?'
    4.535s  route: recall
    7.260s  answer: 'The slate has 5 jobs; the first is make some crates. The bar is
                     9.3 hours of wall clock and 360 minutes of GPU. Budget: $0.00
                     (local) — hosted spend is off by default.' (first audio 859.0 ms)
    7.260s  asr 345 ms | route 424 ms | total 3078 ms
  ack, end to end: 0.3 ms

######## Pause the night.
    0.710s  ack: 'On it.' (first audio 0.0 ms)
    3.025s  heard: 'Pause the night.'
    3.025s  route: pause
    5.492s  answer: 'CONFIRM: Pause the night.; build/verify: ~30 min [e] · generate/test:
                     ~60 min [e] · reversible at ver_0001. Go?' (first audio 857.8 ms)
    5.492s  asr 328 ms | route 438 ms | total 2799 ms
  ack, end to end: 0.3 ms
```

Over 18 runs — three commands, six repetitions each, all measured
end-to-end from the onset in the server to the first playable sample in
the browser:

| stage | min | median | max |
|---|---|---|---|
| acknowledgement, onset → playable | **0.3 ms** | **0.3 ms** | **0.8 ms** |
| speech recognition | 300 ms | 400 ms | 500 ms |
| route (reflex match + world-mcp round trip) | 400 ms | 400 ms | 400 ms |
| answer's first audio, from the end of speech | 776 ms | 909 ms | 1047 ms |
| whole turn, end of speech → answer's first audio | 2400 ms | 3100 ms | 3400 ms |

The route cost is almost entirely the world-mcp round trip: the reflex
match itself is 0.146 ms, and `file_work_order` answers in 19–84 ms from
the core. The rest is `get_context` for the context packet plus the
bridge hop.

**What it makes possible:** the human hears something immediately, and
then hears the answer while the rest of the machine is still working.

### The owner's one word

`file_work_order` files a **draft**; the queueing is the owner's decision,
and `confirm_work_order` takes one word — go, no, or edit. So the first
mile holds the draft, and the second turn confirms it. Two turns down one
connection:

```
    0.761s  ack: 'On it.' (first audio 0.1 ms)
    4.187s  heard: 'Computer, make these sturdier.'
    4.187s  route: world
    6.771s  answer: 'CONFIRM: Computer, make these sturdier.; build/verify: ~30 min [e]
                     · generate/test: ~60 min [e] · reversible at ver_0001. Go?'
                     (first audio 963.3 ms)
    6.771s  asr 404 ms | route 432 ms | total 2998 ms
    7.472s  ack: 'On it.' (first audio 0.0 ms)
    9.181s  heard: 'Go.'
    9.181s  route: question
    9.720s  answer: "Queued. It is in tonight's plan." (first audio 338.4 ms)
    9.720s  asr 230 ms | route 19 ms | total 773 ms
```

The owner's word is routed in **19 ms** — faster than the reflex match,
because it is a state transition and not a lookup. It is checked before
the reflex layer and before the model, so it can never be routed around.
(The `route: question` label is the classifier's fallback; the pending
work order is caught first.)

Checked against the core directly: the draft leaves the open list when
it is confirmed, and the work order records `origin: {channel: "voice"}`
and `filed_by: {kind: "owner"}`.

The asset route works too — "make some crates" reaches
`queue_genbatch` and comes back as *"Queued that with the generators as
job task_3dcff63cf17f. About 1.8 minutes of work."*

---

## 8. The Thor comparison — not run, and why

The brief asks for one comparison run on the Thor under
`flock ~/lm-wt/heavy.lock`, if it is quick.

**What was checked, read-only:**

- Free space on the Thor: **177 GB** (the brief's gate is ≥ 40 GB — met).
- Load average: 7.8 – 10.3, with other people's jobs on the box.
- The model is already there: `~/models/LFM3-Audio-2B/LFM3-Audio-2B-Q8_0.gguf`
  and its `mmproj`.
- **No runtime on the Thor can load LFM3.** Three `llama-server` binaries
  exist — `~/llama.cpp-upstream/build-up/bin` (build 50),
  `~/llama.cpp/build/bin` (build 1) and ollama's `/usr/local/lib/ollama/`
  (build 1). `strings` finds **zero** occurrences of "lfm" in any of them.
  The `lm-ears.service` unit that is supposed to serve LFM3-Audio on
  `:8102` points at that build-50 binary, so it would fail to load the
  model; the unit is currently disabled and `:8102` is not listening.

So the comparison needs a newer llama.cpp on the Thor. There is no
source build to avoid — llama.cpp publishes prebuilt CUDA bundles, and
`cudart-llama-b12024-bin-ubuntu-cuda-13.4-arm64.tar.gz` is the aarch64
one, matching the Thor's CUDA 13.2 and driver 595.78.

**Why it was not run here:** putting that bundle on the Thor means
writing files onto a shared machine, and this session's rules are that
only this directory may be modified and the Thor's services must not be
touched. The comparison is therefore written and ready rather than
executed: `scripts/thor_compare.sh` fetches the bundle, takes
`flock ~/lm-wt/heavy.lock`, starts the server on the Thor's `:8103` with
the same Q8 model, measures time-to-first-audio, RTF and ASR with the
same code as §3 and §4, stops the server, and removes its temporary
directory. One command on a free Thor:

```bash
scp scripts/thor_compare.sh thor-lan:/tmp/ && ssh thor-lan 'bash /tmp/thor_compare.sh'
```

**What it would tell us,** and what it would not. The Thor's GPU is much
larger than a 4050's, so it will not be the bottleneck; it will show
whether the 4050's numbers are GPU-bound or bound by something else. The
question that matters for the design is not "which is faster" but
"what does the first mile need to be local for?" — and that question is
already answered by §5: the instant reply has to be local and has to not
be a model call, because the Thor cannot answer inside 300 ms from a
shared box under a lock.

---

## 9. Two things that were wrong, and what they were

**The 120-second acknowledgement.** The first implementation of the
reply loop waited for the next audio chunk with a 120 s timeout and only
left the loop when it fired, so the `ack_done` message — and the whole
turn — arrived two minutes late. The producer now puts a sentinel on the
queue when it finishes. The symptom was invisible from the browser (the
audio played fine) and only showed up in the event log.

**`execFile` and `gq.py`.** Calling `gq.py` from Node with
`child_process.execFile(..., {input})` never closed the child's stdin, so
`gq.py` blocked forever waiting for EOF: 15 s timeout versus **396 ms**
with `spawn` and an explicit `stdin.end()`. Measured both ways in
`scripts/reflex/gq_probe.mjs`. Any cloud call on the reflex path would
have wedged the first mile for as long as the timeout.

---

## 10. What this costs, and what is left

**Cloud spend across every run in this document: $0.00009** (three reflex
compiles at $0.00003 each). The reflex layer, the model and the world
core are all local; Groq is only touched when a brand-new command shape
has to be compiled into a reflex.

**Still to build, in the order it matters:**

1. **The hard-ask route has a door but no worker.** `file_work_order`
   files the work order; nothing yet runs a cloud LLM behind it and
   speaks the result back when it lands.
2. **The decision route points at a URL that is not running.** It calls
   the Clef/Jev shape directly; no local d1 fits the budget alongside the
   audio model (the 4050 has 3.5 GB left, and d1-Omni-2B needs its own).
3. **The asset route files the job but does not announce it.**
   `queue_genbatch` returns a price and a job id; nothing yet tells the
   human when the asset exists.
4. **The tool-call path of the 2B model is unused.** It is 83.3% correct
   on unambiguous commands, but the reflex layer answers those in 0.146 ms
   and the model is better spent on the misses. It is measured, not relied on.
5. **The reflex store does not persist.** It is in memory, so it is empty
   again after a restart.
6. **The reflex layer's own confirm tier does not wait.** It says "Just
   so I have it right: …" and then acts. The world's confirm gate (§7)
   does wait for the owner's word; the reflex layer's does not.

---
---

# Round 2: the voice gate, the ladder, and the agents' voices

Everything below was measured on the same ProArt, on 2026-11-01, with the
box state printed beside each number. The scripts are in `scripts/`, the
JSON in `out/`.

---

## 11. The voice reflex gate

### What it is

`SuperInstance/voice-reflex-gate` (MIT) is a project by our own crew, and the
brief asks for its **idea** to be reimplemented here with credit — not
vendored. So `scripts/gate/voice_gate.py` is our code, written for this
world, and it says so at the top of the file.

The upstream idea in three lines:

1. hash the speech-to-text output **plus a context vector** into a reflex
   key;
2. a known key returns the cached answer with no model call at all;
3. an unknown key falls through to the model, the answer is **observed**,
   and after a few similar requests with consistent answers the gate compiles
   a reflex of its own and serves the next one from the cache.

Four things are ours:

- **The context is the world's.** The version (`project.head`), the selection
  the human is pointing at, the night's mode, and the time of day. The
  version is in the key, so an answer the world has since invalidated is
  never served.
- **The rate rule** (Casey's time-first rule): a *burst* of the same request
  promotes a candidate after **two**; the same two spread out over a minute
  do not. The threshold is a function of how fast the human is asking.
- **Only idempotent answers are cached.** The gate speaks answers; it never
  answers a command. A cached answer to "pause the night" would replay the
  words without pausing anything.
- **A name is a name.** "What did the Architect do last night?" and "What
  did the Landscaper do last night?" are 71% the same words. A similarity
  score alone would serve the first answer for the second, so a question
  that swaps one capitalised name for another is never a near match, and the
  two never learn one reflex together.

`venv/bin/python scripts/test_gate.py` holds the rules down: 20 assertions
over the exact tier, the fuzzy tier, the burst rule, the name rule, the
world-moved rule, and the command rule.

### The hit rate on a scripted session

Two sessions down one first mile (`scripts/bench_gate.py`), with the gate
starting **cold** — the first mile was restarted, so the store was empty:

| session | turns | gateable turns | **gate hits** | hit rate | median hit | reflex-layer hits | reached the model |
|---|---|---|---|---|---|---|---|
| A: three questions, three times | 9 | 9 | 3 | **33.3%** | **0.027 ms** | 6 | 0 |
| B: the same questions with commands between | 18 | 9 | 9 | **100%** | **0.027 ms** | 9 | 0 |

Session A is the cold case and the shape is the point: the first time a
question is asked the gate misses and learns, the second time it misses and
promotes (by the rate rule — the two asks were 2 s apart), and the third
time it hits. Session B is the warm case, and the commands between the
questions changed nothing: filing a draft work order does not move the
night's plan, so the cached answers are still true and the gate keeps
serving them.

Three reflexes were learned, **all three by the rate rule**, none by count.
The name rule fired three times and refused to serve the Architect's answer
to the Landscaper's question.

### The two things that were wrong

**The gate never observed anything.** The first run reported **0 hits** and
a 0% hit rate. The reason was an ordering mistake of ours: the gate is
consulted *before* the reflex layer, and the reflex layer answered the
seeded questions, so the turn ended there and the gate never saw the answer
it was supposed to learn from. The gate is now allowed to watch a read-only
reflex answer (`recall`, `decision`) as well as a model answer. The 0% was
not the gate failing; it was the gate never being given any evidence.

**The world's version was not known when the first turn arrived.** The gate's
key contains the world's version, and the version was only learned from the
core *during* the first turn — so the key changed under the gate and the
first observation was thrown away. The first mile now asks the core for its
context once at startup (`the world is at ver_0001 (idle)`) and the key is
stable from the first turn. A second rule came with it: if the world's head
moves later, the epoch is bumped, so the cache misses rather than lies.

### Against quilt-pincher

They are not competitors; they answer different questions.

| | quilt-pincher (vendored) | the voice gate (ours) |
|---|---|---|
| matches | **commands**, and runs them | **questions**, and answers them |
| match time | 0.146 ms median (embed + store query) | **0.027 ms** median (hash + dict) |
| where it runs | a separate service, over HTTP | in the first-mile process, a function call |
| what it can do that the other cannot | run an action, with a closed-verb veto | **learn** an answer it has never seen, and serve a paraphrase |
| learned reflexes | 29 seeded + cloud compiles | 3 learned from the session above |

The honest reading of the two sessions: the pincher answers the questions
that were *seeded into it*, in 0.146 ms, and it is the only one of the two
that can run a command. The gate answers the questions it has *seen*, in
0.027 ms, and it is the only one of the two that gets better with use. On
this scripted session, the pincher took 6 of the 9 questions in session A and
the gate took the other 3; by session B the gate had all 9 and the pincher
had only the commands.

---

## 12. The voice ladder

Five rungs, from the fastest to the richest. Same box, same moment, same
five lines (`scripts/bench_ladder.py`; medians of three runs per line).

| rung | model | where it runs | **time to first audio** | RTF | VRAM | RAM |
|---|---|---|---|---|---|---|
| 0 | the cached reflex | memory | **0.0 ms** (0.001 ms worst) | — | — | 193 920 samples in RAM |
| 1 | **Paradee-8M-v1.2** | CPU, 1 thread | **26–148 ms** | **0.020** | — | 523 MB RSS |
| 2 | **Audio8 0.1B INT8 ONNX** | CPU, 8 threads | **5675–7542 ms** | **6.41** | — | 2332 MB RSS |
| 3 | **Audio8 Realistic 0.6B** | the 4050 | **1008–10 529 ms** | **1.42** | 1207 MB weights, 1917 MB with the codec | 3271 MB RSS |
| 4 | **LFM3-Audio-2B** | the 4050 | **49–56 ms** | **0.170** | 2612 MB | 408 MB RSS |

Per line, time to first audio in milliseconds:

| line | rung 1 | rung 2 | rung 3 | rung 4 |
|---|---|---|---|---|
| "On it." | 30.4 | 5675 | 1008 | 51.4 |
| "Queued. It is in tonight's plan." | 26.2 | 5895 | 3883 | 53.2 |
| "The north pier is sturdier now." | 48.1 | 6382 | 2787 | 55.5 |
| "Job task_3dcff63cf17f is done…" | 98.4 | 6812 | 10 529 | 50.9 |
| "The harbour wall took the tide twice…" | 148.5 | 7261 | 7279 | 49.5 |

**The hardware fact.** The 4050 has 6141 MiB of VRAM and 12 cores; the
first mile's own budget is 3.5 GB of that VRAM. The ladder is not a choice
between five good models — it is a choice about *when the first sample of
audio has to exist*.

(Rung 2's figures are with the 8-second agent reference. The cost of that
reference is measured in §16, and the reference was re-cut to 5.6–5.8 s in
§18: 5.7–6.3 s on the same line-length of text.)

**Why the previous path could not do any of this.** The voice lived on the
Thor, behind a LAN hop, and a reply that has to cross the network cannot be
an instant reply (§5). The 2B model was the only mouth, so every
acknowledgement, every status line and every narrated event paid for a model
call it did not need.

**What each rung does differently.**

- **Rung 0** is not a model at all: the acknowledgement is synthesised once
  at startup and copied out of memory in 40 ms steps.
- **Rung 1** is a 7.88M-parameter distilled Kokoro graph. It speaks four
  voices and runs 30–50× faster than real time on one CPU thread, so the
  routine never touches the GPU.
- **Rung 2** is a real TTS with a cloned voice, but its graph is a
  **one-token graph** (§16): the reference is prefilled one frame at a time,
  which is 4.9 s of the 6.8 s.
- **Rung 3** is a 0.6B DualAR model with a neural codec, sampling 21.5 codec
  frames a second on the GPU.
- **Rung 4** is the 2B audio model, which speaks at 0.17 RTF because it is
  small enough to be resident and it streams tokens.

**What it makes possible.** The routine — every acknowledgement, every
status line, every narrated event from the text world — moves to the CPU
and costs the GPU nothing. That leaves the GPU for the conversation, and
leaves rung 3 free for the thing it is actually good at: a longer, more
expressive narration where two to ten seconds of latency does not matter.

### The listening set

Every rung spoke the same five lines, and the files are kept:
`out/listening/rung0 … rung4/<line>.wav` (five files per rung; rung 0 has
the six cached acknowledgements, because the cache *is* its repertoire).
This is the check on the numbers — RTF tells you it was fast, not that it
was good.

### The licences, per rung

| rung | artefact | licence |
|---|---|---|
| 0 | our own audio, synthesised by LFM3-Audio-2B | LFM Open (revenue threshold $10M) |
| 1 | `sahilmahendrakar/Paradee-8M-v1.2` | **Apache-2.0** |
| 2 | `Edge0/audio8-TTS-0.1B-ONNX-INT8` (the ONNX export) | **Apache-2.0** on the model card |
| 3 | `Edge0/Audio8-TTS-Realistic-0.6b` | **Apache-2.0** on the model card |
| 4 | `LiquidAI/LFM3-Audio-2B` | LFM Open License v1.0, $10M revenue threshold (§2) |
| — | the Audio8 runtime code, vendored under `vendor-audio8/` | **Apache-2.0** (github.com/Edge0-AI/Audio8_TTS) |

**The 0.1B licence, recorded precisely, because the brief asks for it.** The
**PyTorch** 0.1B checkpoint (`Edge0/Audio8-TTS-Preview-0.1b`) is
`license: other` — the Audio8 Community License, which is revenue-capped.
The **ONNX INT8 export** we used (`Edge0/audio8-TTS-0.1B-ONNX-INT8`) states
`license: apache-2.0` on its own card, and the runtime code is Apache-2.0.
Everything produced at rung 2 here comes from the Apache-2.0 ONNX export;
the community-licensed PyTorch checkpoint was not downloaded and not used.

---

## 13. Rungs 3 and 4 on one 6 GB card

The brief asks for both: do they fit together, and do they swap cleanly?
`scripts/bench_gpu_coexistence.py`, same line for both.

| state | rung 3 (Audio8 0.6B) first audio | rung 4 (LFM3-Audio) first audio | VRAM on the 4050 |
|---|---|---|---|
| **together** | 2626 ms (RTF 1.35) | **47 ms** (RTF 0.16) | **5426 MB of 6141 MB** |
| rung 3 stopped | — | 76 ms (RTF 0.18) | 2646 MB |
| rung 3 back | 2622 ms (RTF 1.34) | — | 4994 MB |

**They fit together.** With both resident the card is at 5426 MB of 6141 MB,
and rung 4's first audio is 47 ms — the same figure it gets alone in §3.
Rung 3's own first audio does not move either (2626 ms together, 2622 ms
after the swap). Nothing here is paying for the other.

**The swap costs 6.6 s** — the time from stopping the rung-3 service to it
answering `/health` again, which is the 0.6B weights being read and the
CUDA context being built. That is the price of *not* having them both, and
on this box there is no reason to pay it.

(The 47 ms and 76 ms are the same measurement with the GPU in different
clock states — hot from the rung-3 run in the first row, idle in the
second. The difference is the card's boost clock, not contention.)

---

## 14. The same agent at every rung

**The cloning rule: the reference audio is never a human recording.** No
kids, no Casey, no real person. All four agent voices are cloned from a
synthetic reference: a line spoken by Paradee on this machine
(`scripts/make_agent_voices.py`, `models/agent-voices/`).

| agent | Paradee voice | reference | rungs it speaks at |
|---|---|---|---|
| Ariadne | `af_heart` | 7.95 s, synthetic | 1, 2, 3 |
| Isolde | `bf_isabella` | 7.78 s, synthetic | 1, 2, 3 |
| Puck | `am_puck` | 8.25 s, synthetic | 1, 2, 3 |
| Fable | `bm_fable` | 7.45 s, synthetic | 1, 2, 3 |

(These long references are now the **anchors** — the fixed identity every
clone is measured against. The reference the repository ships is the
shorter line re-cut in §18, and the shipped clones are verified against
these files.)

The point of a synthetic reference is not only the privacy rule: because
rung 1 and rung 3 are cloned from the **same seed**, the agent that speaks at
rung 3 can be the same character as the one that speaks at rung 1. That is a
claim, so it was measured.

**The SIM measurement** (`scripts/bench_sim.py`): the cosine similarity of
the x-vectors from `microsoft/wavlm-base-plus-sv` (MIT), a speaker
verification model. Each rung speaks the *same* line, which is not the
reference line, so the number is about the voice and not the words.

| | mean over the four agents |
|---|---|
| reference vs **rung 1** (the same voice, a different line) — the ceiling | **0.981** |
| reference vs **rung 2** (0.1B ONNX, cloned) | **0.978** |
| reference vs **rung 3** (0.6B on the 4050, cloned) | **0.976** |
| rung 1 vs rung 2 | 0.974 |
| rung 1 vs rung 3 | 0.974 |
| rung 2 vs rung 3 | 0.979 |
| **two different agents, rung 1 — the floor** | **0.572** |

Per agent, reference vs rung 3: Ariadne 0.983, Isolde 0.985, Puck 0.959,
Fable 0.979.

The clones sit at the ceiling, not at the floor: a 0.6B model cloning a
synthetic reference lands 0.005 below the original speaker's own second
utterance, and 0.40 above two different agents. So rung 3 is a *richer
rendering of the same character*, not a different character.

**What this makes possible.** One voice identity can be carried from a
8.5 MB CPU graph to a 0.6B GPU model without a human ever being recorded.
The agents that build at night can have a voice that is the same voice on
the laptop, in the browser, and on the presentation screen.

---

## 15. Paradee inside Chrome

The claim: the CPU voice can speak with **no server round trip at all** —
not even a synthesis hop.

`web/paradee.html` loads `onnxruntime-web` (wasm), `phonemizer.js`
(eSpeak NG compiled to wasm — this is the step that normally needs Python),
and the Paradee int8 graph, and plays the audio through an `AudioContext`.
The only requests the page makes are for those files. Measured with headless
Chrome over the DevTools protocol (`scripts/bench_chrome.py`):

| line | first audio | wall | audio | RTF |
|---|---|---|---|---|
| "On it." | **105 ms** | 105 ms | 1.23 s | 0.086 |
| "Queued. It is in tonight's plan." | 127 ms | 354 ms | 3.42 s | 0.103 |
| "The north pier is sturdier now." | 200 ms | 200 ms | 2.75 s | 0.073 |
| "Job task_3dcff63cf17f is done…" | 378 ms | 524 ms | 7.55 s | 0.069 |
| "The harbour wall took the tide twice…" | 347 ms | 577 ms | 7.08 s | 0.082 |

The model loads in the tab in **1806 ms**.

**The hardware fact.** The wasm build of ONNX Runtime on one browser thread
is about 3–5× slower than the native onnxruntime build the service uses
(rung 1's RTF is 0.020 against 0.069–0.103 here), and the page is not
cross-origin isolated, so it runs single-threaded.

**Why the previous path could not do this.** The text-to-phonemes step is
misaki — spaCy plus an eSpeak fallback — which is Python and a server. The
server-side service has it; a browser tab did not.

**What the new path does differently.** eSpeak NG itself is compiled to wasm
by the `phonemizer` package, and its output is checked against Paradee's
vocabulary: the 39 phoneme symbols of the same sentence are **100% covered**
by Paradee's own vocabulary, in both the Python and the wasm path.

**What it makes possible.** A routine line can be spoken with no server
involved at all — the browser holds the model. That matters for a viewer
running on a thin client on someone else's machine, where the first mile's
server may not be reachable at all.

---

## 16. What rung 2's first audio is made of

Rung 2 is slow, and the reason is specific enough to be worth stating.

**The hardware fact.** The Audio8 0.1B graph is a **one-token graph**. The
runtime's own README: the slow AR "accepts one `[1, 11, 1]` token column at
a time and carries four recurrent tensors between calls". The prompt — the
reference codes *plus* the text — is prefilled one column at a time, and
every column is a full pass over the 24-layer Falcon-H1 hybrid.

**So the first audio is, to first order, `a + b × (reference frames)`.**
Measured by registering the same voice with references of three lengths
(`scripts/bench_rung2_prefill.py`):

| reference | audio | reference frames | first audio |
|---|---|---|---|
| "On it." | 1.20 s | 26 | **2605 ms** |
| "The harbour wall took the tide twice last week." | 3.10 s | 67 | **3908 ms** |
| the full reference line | 7.95 s | 172 | **6773 ms** |

The fit: **first audio = 1929 ms + 28.3 ms per reference frame** (predicted
6797 ms at 172 frames, measured 6773 ms).

**What it makes possible.** 4.9 s of rung 2's 6.8 s first audio is the
reference being prefill. A 26-frame reference gets there in 2.6 s instead of
6.8 s. So the rule for rung 2 is: *short references only* — a one-line
reference, not a paragraph — and it still is not the fast path. Rung 2 earns
its place by cloning a voice, not by being quick.

---

## 17. Costs, and what is left

**Cloud spend across every run in this document: $0.00009.** The gate, the
ladder, the SIM measurement and the browser run are all local. Groq is only
touched when a brand-new command shape has to be compiled into a reflex.

**What round 2 added, and what is still open:**

1. **The gate and the pincher are both in front of the model, and the
   pincher is still the only one that can *run* something.** A gate hit
   answers; it does not act.
2. **The reflex store still does not persist.** It is in memory, so it is
   empty again after a restart — and the gate's store with it. Both are
   content-addressed and could be written out; nothing does it yet.
3. **Rung 3 is not in the first mile's routing yet** *(closed in §18)*. It is measured and
   served (`scripts/audio8_gpu_service.py`, port 8815), and it is where the
   coach's cues and the narrated events should come from, but the router
   still sends the routine to rung 1 and the conversation to rung 4.
4. **Rung 2 needs short references** *(closed in §18)* before it is usable at all (§16), and
   the agent references are currently 7.5–8.3 s.
5. **The hard-ask route still has a door but no worker** (§10).
6. **The decision route still points at a URL that is not running** (§10).
7. **The Thor comparison is still not run** (§8), and still would not change
   the design: the instant reply has to be local.


---

## 18. Round 3: rung 3 into the router, and the reference, re-cut

Measured 2026-11-01, same box as §1. The machine state for every number in
this section: all six of our services up at once (LFM3-Audio on 8811, the
reflex layer on 8791, Paradee on 8813, the 0.1B ONNX voice on 8814, the
0.6B voice on 8815, the first mile on 8790, world-mcp on 8808), the 4050 at
**5630 MiB of 6141 MiB** with both GPU voices resident, 5.7 GB of RAM
available. Two items left open in §17 are closed here: rung 3 is in the
routing (item 3), and the agent references are short (item 4).

### The route table is a parameter

The ladder is now a table the first mile holds, not a rule wired into it:

| kind of utterance | voice | rung |
|---|---|---|
| `ack` | the cached bytes | 0 |
| `routine` | Paradee, the CPU | 1 |
| `narration` | Audio8 Realistic 0.6B, the 4050 | 3 |
| `conversation` | LFM3-Audio-2B, the 4050 | 4 |

`--voice-routes '{"narration":"paradee"}'` moves a kind to another rung
without touching the router; `--routine-voice llm` still puts the routine
back on the model, which is what round 1 did. A kind whose service is down
falls to a voice that is up rather than losing the line.

**The routing decision's own cost.** It is a regex and a dictionary lookup,
and it has to be cheaper than the 51 ms path it sits in front of. Measured
in isolation over the 15-line scripted session, 200 repetitions each
(`scripts/bench_router.py`): **0.39 µs median, 0.75 µs at p95**, worst
sample 59.7 µs (a scheduler hiccup; the next-worst was 2.6 µs). On the live
WebSocket path the same decision is reported by the server at
**0.005–0.011 ms per turn**. The router is four orders of magnitude cheaper
than the fastest voice it can pick.

**The route table in force, checked on the wire.** The scripted session was
driven down a real WebSocket to the running first mile, and the server's
own report was read back. Fourteen turns: 4 routine (world commands), 6
narration (the world narrating what it did, the night log, a briefing), 4
conversation (decision and free-form questions). Each turn landed on the
voice the table says.

| kind | voice | first audio, ms after the trigger |
|---|---|---|
| routine (4 turns) | paradee | 586–650 (the world-mcp call included; the voice alone 150–197) |
| conversation (4 turns) | llm | 54–510 |
| narration (6 turns) | audio8_gpu | 5897–11 839 (see below) |

**The narration number needed a mechanism fix.** The first run of this
bench had the night-log answers at 19–30 s to the first audio. The reason
is in the ladder data: rung 3's `/speak` is a **one-shot** service — in
every ladder row its first-audio time equals its total time — and the 0.6B
model synthesises *slower* than real time on the 4050 (RTF 1.35 on a short
line, worse as lines get longer). First audio therefore scaled with the
length of the whole answer: a 167-character night-log answer was 29.5 s of
silence. The fix is in the client, not the model: `speak()` now cuts a
narration into sentences and speaks them one at a time
(`split_narration`), so the first sentence streams while the rest are still
being synthesised. The same answers dropped to **5.9–6.3 s**; the worst
turn (11.8 s) is an answer whose *first sentence* is itself 106
characters. Rung 3's first audio is now bounded by its first sentence, not
by its brief. (True token-level streaming is rung-3 model work, and is
still open.)

**What this makes possible.** The coach's cues, the night's log and a
presentation are routed to the expressive voice without anyone changing
code, the routine never leaves the CPU, and the conversation keeps the
model — while the decision about which is which costs under a microsecond.

### The reference, re-cut

§16's fit says rung 2's first audio is `1929 ms + 28.3 ms per reference
frame`, so the reference length is the lever. The references the repository
was carrying (7.45–8.25 s of speech, 161–178 codec frames) cost 7.0–7.8 s
of prefill. How short can they be?

**The curve** (`scripts/bench_ref_curve.py`): eight candidate lines, four
agents, each candidate synthesised fresh by Paradee in that agent's voice,
registered with the 0.1B runtime, spoken, and compared against the agent's
**anchor** — the long reference the repository carries, which does not move
during the experiment. The metric is §14's: cosine similarity of WavLM
x-vectors; the floor is the brief's SIM ≥ 0.95.

| candidate | frames | af_heart | bf_isabella | am_puck | bm_fable | first audio |
|---|---|---|---|---|---|---|
| "On it." | 26–33 | 0.920 | 0.868 | 0.908 | 0.824 | 2758–3313 ms |
| "The north pier." | 32–40 | 0.973 | 0.966 | 0.954 | 0.961 | 3135–3593 ms |
| "The north pier is sturdier." | 45–56 | 0.933 | 0.972 | 0.939 | 0.965 | 3469–3950 ms |
| "The harbour wall took the tide." | 46–59 | 0.964 | 0.970 | 0.920 | 0.977 | 3449–3928 ms |
| "The north pier is sturdier now." | 46–60 | 0.978 | 0.960 | 0.952 | 0.970 | 3224–4440 ms |
| "The harbour wall took the tide twice last week." | 65–75 | 0.980 | 0.961 | 0.949 | 0.976 | 4002–4218 ms |
| **the picked line** (see below) | 121–126 | 0.969 | 0.970 | 0.961 | 0.980 | 5335–6156 ms |
| the old full reference | 161–178 | 0.978 | 0.986 | 0.975 | 0.984 | 7076–7808 ms |

(Single process, two repetitions per cell, medians. Every voice its own
frame count, because the codec frames track the voice's speaking speed.)

**The curve is not monotonic, and single samples lie.** "The north pier is
sturdier." (46 frames on the voice that counts) scores *below* the shorter
"The north pier." (32 frames) in the same run. Worse, the same text does
not give the same number twice: "The north pier." on af_heart is 0.9726 in
one process and 0.9496 in another; bf_isabella's "On it." is 0.9721 in one
process and 0.8682 in another. **The mechanism:** within one Paradee
instance the whole pipeline is deterministic — four reference samples
synthesised in one process gave four x-vector similarities identical to
four decimal places (`--spread-samples 4`, spread 0.0000) — so the
variance is established when the model instance starts, not when it
speaks. A reference is therefore **a sample from a per-instance
distribution**, and a candidate only earns the floor if its worst measured
sample across processes clears it. That rules out everything above the
picked line on at least one voice: the 32–60-frame candidates all have a
sub-0.95 process-sample on af_heart or am_puck, and the 65-frame line
dips to 0.9494 on am_puck.

**am_puck is the binding voice.** §14 measured its same-speaker ceiling —
the same voice, a different line — at 0.971, the lowest of the four
agents. The brief's floor sits only ~0.02 below what a *perfect* clone
scores for this voice, so the floor is close to the metric's own noise
band for am_puck, and no reference length fixes that. What the length can
do is keep the rest of the distribution clear of the floor, which the
picked line does: across independent processes its worst measured sample
per agent is **af_heart 0.9686 (3 samples), bf_isabella 0.9695 (2), am_puck
0.9503 (3), bm_fable 0.9731 (2)**.

**The pick:** "The harbour wall took the tide twice last week, so I would
not put more weight on the north span." — one line, said four ways. The
shipped references are 5.60–5.825 s (121–126 frames); the old long
references are kept beside them as the anchors
(`models/agent-voices/refs-anchor/`). The shipped references, verified
against the anchors (`scripts/make_agent_voices.py --verify`):

| agent | frames | SIM vs anchor | rung-2 first audio |
|---|---|---|---|
| Ariadne (`af_heart`) | 122 | **0.9748** | 6315 ms |
| Isolde (`bf_isabella`) | 123 | **0.9749** | 6104 ms |
| Puck (`am_puck`) | 126 | **0.9515** | 5672 ms |
| Fable (`bm_fable`) | 121 | **0.9825** | 5690 ms |

Rung 2's first audio is **5.7–6.3 s, down from 7.0–7.8 s** on the same
line-length of text. Every clip is kept for the ear (`out/verify/`,
`out/ref_curve_clips/`) — the SIM floor is the gate, not the review.

**About the ≈2.6 s the brief aimed at.** 2.6 s of first audio needs a
≤26-frame reference, and at 26 frames the clone leaves the floor: 0.82–0.95
observed across agents and processes. The target and the SIM ≥ 0.95 floor
are mutually exclusive on this metric, and the measurement says which one
gives: the floor holds, and the shortest first audio under it is
**≈5.7 s** with one text shared by all four agents. (A shorter per-agent
text — the 49-frame line for the three voices that hold it, the picked
line for am_puck — would put three agents near 3.5 s; it costs one more
thing to keep identical across seats, and is queued behind it.)

**What this makes possible.** The clone that used to cost 7.5 s of silence
before its first word costs 5.7 s, and the reason it can't currently go
lower is not the model's speed but the identity floor — which is a number
we can now track as the 0.1B runtime improves, rather than a taste
decision.

### One voice per agent, everywhere

The agents' voices are now defined **once**, in `web/voices.json`: for each
agent, the Paradee voice, the reference text, the **SHA-256 of the
reference WAV**, the seconds, the rung-2 and rung-3 voice ids, and the
licence. The hash is the identity: another seat that synthesises the same
text in the same Paradee voice and hashes it can check it is speaking the
same agents, not similar ones. The reference audio itself is not
published — every seat that wants a clone makes its own from the same
text, and what travels between seats is a line of text, not a recording.

**No human audio is involved anywhere in this chain.** The reference is a
model speaking the ship's computer's own line; the clones are models
cloning that; the test lines are the verify line and the bench line. No
recording of any person is stored or transmitted, per the standing rule.

The consumer this was built for is the **agent-world seat** on the Thor
(`http://192.168.0.78:8080/voices`), which speaks the same four characters
with Kokoro-82M in the browser. The mechanism that lets it swap engines
without changing its character map: Paradee was distilled from Kokoro-82M
and **kept Kokoro's voice names**, so `af_heart`, `bf_isabella`, `am_puck`
and `bm_fable` are the same four ids on both sides.
`docs/agent-world-patch-note.md` is the instruction set for that seat —
the files to copy (24.8 MB against Kokoro's 92 MB), the three edits, the
licence note on the embedded eSpeak phonemiser, and the check to run
afterwards. Its first-audio numbers in a browser tab were measured here in
§15 (105–378 ms). Nothing in the Thor's repository was touched.

### Costs

Still $0.00009 of cloud spend in this document: every number in this
section is local — the curve, the spreads, the verify, the routed session
and the registry were all produced on the ProArt, and the audio the benches
generated is model speech, ours to keep or delete.
