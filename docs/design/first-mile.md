# The first mile: design

How the first mile turns a person talking into a world that answers, on the
ProArt, in the time it takes to say "on it".

Measurements are in [`../exp-first-mile.md`](../exp-first-mile.md); this
document is the design they justify.

---

## 1. The rule

**The first mile owns turn-taking and the instant reply. Everything else is
a slow path, and the first mile never waits for one.**

There are two clocks in a spoken interface. The first is the human's
attention: while they are still speaking, they are still deciding what to
say next, and the right thing to do is not answer but acknowledge, so they
know the machine heard them and can keep going. The second is the
machine's work: recognising the words, resolving what they mean, asking
the world, compiling an answer, generating an asset. That work can take
seconds, minutes, or a human's afternoon.

The first mile is the thing that runs on the human's clock. It decides
when the human has finished talking, it says something immediately, and
then it finds the slow path that can actually answer the question.

Concretely, the first mile:

- listens, and decides when speech has ended;
- **acknowledges inside 300 ms** — measured at 0.3 ms (worst 0.8 ms of 18) (§5 of the
  experiment notes);
- routes the turn to whatever can answer it;
- speaks the result when it lands, briefly.

And it never blocks. Not on the model, not on the world, not on the cloud.
If a slow path is late, the human has already heard "on it".

---

## 2. The shape

```
   ┌─────────────────────────── Chrome on Windows ───────────────────────────┐
   │                                                                         │
   │   microphone ──20 ms frames──▶ WebSocket ──┐        ┌──▶ speakers ◀──┐ │
   │                                          │        │                 │ │
   │   (the same browser hosts the thor-world viewer)                    │ │
   └──────────────────────────────────────────┼────────┼─────────────────┼─┘
                                              │        │                 │
                                    ┌─────────▼────────▼─────────────────▼───┐
                                    │          the first mile (WSL2)           │
                                    │                                         │
                                    │  VAD ──▶ turn ──┬──▶ reflex layer ──┐  │
                                    │   │             │   (quilt-pincher) │  │
                                    │   │             ├──▶ LFM3-Audio-2B  │  │
                                    │   │             │   (ears + mouth)  │  │
                                    │   │             └──▶ world-mcp ◀─────┼─┤
                                    │   │                                   │ │
                                    │   └──▶ cached acknowledgement ──────┘ │
                                    │         (cached, 0.3 ms from memory)      │
                                    └─────────────────────────────────────────┘
                                              │
                                    slow paths, off the critical path
                                    cloud LLMs · d1 / Clef / Jev · the Thor's
                                    generators · the engineers
```

Four processes, each with one job:

| process | port | job |
|---|---|---|
| `llama-server` | 8811 | LFM3-Audio-2B: the ears (ASR) and the mouth (TTS), one resident model |
| `reflex_service.ts` | 8791 | quilt-pincher: matches known commands in ~0.1 ms, compiles misses in the background |
| `first_mile.py` | 8790 | the WebSocket front door, the VAD, the turn loop, the routing |
| `world-mcp` | 8808 | the core: the context packet, referent resolution, work orders |

---

## 3. Turn-taking

The browser's `AudioWorklet` sends 20 ms frames of 16 kHz PCM to the
first mile. A simple energy VAD watches them:

- **onset** — six consecutive frames above −42 dBFS. This is the moment
  the human has started speaking, and it is the moment the clock for the
  acknowledgement starts.
- **end** — 650 ms below the threshold. The turn is over.

The acknowledgement fires on the onset, not at the end. That is the whole
point: the reply arrives while the human is still talking, so they are not
left waiting through their own sentence.

**The acknowledgement does not use the model.** The set of
acknowledgements is small and fixed ("On it.", "Got it.", "Right.",
"Okay.", plus the clarifying variants), so they are synthesised once at
startup and kept as raw PCM in memory. On an onset the server copies bytes
out of memory and streams them. Measured **0.3 ms (worst 0.8 ms of 18)** from onset to
first playable sample, against 219–364 ms for synthesising it on the spot.

This is the design decision that makes the instant reply possible. A
forward pass per acknowledgement would put a model queue in front of every
human turn; a memcpy does not. It also means the acknowledgements sound
the same every time, which the model's own speech does not — llama.cpp
warns on every request that no speaker reference was provided and the
model may behave randomly.

**When the first mile needs to ask rather than acknowledge**, it says so
in one line: "Which ones, the east span or the north?" — the
clarification set is cached the same way.

---

## 4. The three tiers

The reflex layer is `SuperInstance/quilt-pincher` (Apache-2.0), vendored
under `vendor-quilt-pincher`. It is not a wrapper: the service runs the
real `PincherEngine` with the `HDCEmbedder` — a deterministic,
model-free hypervector embedder, so matching costs no model and no
network — a memory reflex store, and a veto.

The tier decision is the engine's, at two thresholds:

| score | tier | what happens |
|---|---|---|
| ≥ 0.80 | **hit** | run it now |
| 0.55 – 0.80 | **confirm** | say what we think it was, in one line, then run it |
| < 0.55 | **miss** | compile a new reflex in the background, and answer from the slow path now |

Measured: known commands **30/30 hits, 0.146 ms** at the median,
0.365 ms at the worst of fifty. Well inside the 50 ms Casey specified.

The store grows as it is used: a miss is compiled in the background and
the compiled reflex joins the store, so the next time that phrasing is
spoken it hits. The store grew from 29 seeded reflexes to 36 during the
benches.

### The miss does not block

The engine's own compile path is synchronous: on a miss it calls the
compiler and waits. That is right for a reflex engine that has to return
an answer, and wrong for a first mile, where the human is waiting.

So the service makes the tier decision itself — the same embed, the same
store, the same thresholds — and hands a hit or a confirm to the engine,
while a miss returns immediately and the compile runs in the background:

```
[reflex] miss (score 0.227) -> background compile, no blocking
[reflex] background compile stored "make these arches stronger" -> world_action in 377 ms (cloud $0.00003)
```

The human's answer comes from the slow path, which was going to run
anyway. The reflex is ready next time. Groq is called once, for
$0.00003, and the whole reflex bench cost $0.00006.

The action of a compiled reflex is never the model's text: the compiler
names an intent from a closed list, and the service builds the action from
its own template (§8). The prompt also gives the cue for each intent,
because a list of names alone is not enough: given only the names, a 20B
model will answer `decision` for "make these arches stronger". A compile
that names no known intent is refused and nothing is stored.

### Normalisation

The HDC embedder binds tokens by position, so "pause everything tonight"
and "pause the night" are not close in its space — the extra words dilute
the similarity below the confirm band. The service strips filler words
before embedding, which lifts a spoken paraphrase back into range. This is
what separates the near commands that land in the confirm band from the
ones that used to miss.

---

## 5. Routing

The world core has eleven doors. The first mile uses five of them, and
picks between them by what the human said:

| the human says | the door | what comes back |
|---|---|---|
| a world action ("make these sturdier") | **`file_work_order`**, with the context packet attached | the core's one-line confirmation, and a work order waiting for the owner's word |
| the owner's word ("go") | **`confirm_work_order`** | "Queued. It is in tonight's plan." |
| a question the core asked ("the east span") | **`answer_question`** | the confirmation of the unblocked work order |
| a recall ("what did the Architect do last night") | **`read_night_plan`** | the slate and the price, in one sentence |
| an asset ("make some crates") | **`queue_genbatch`** | "Queued that with the generators as job task_…" |
| a quick judgement ("should we reinforce the north pier") | **a decision model** — d1 locally if it fits, otherwise Clef or Jev in the cloud | the decision, in one line |
| a hard ask ("redesign the whole harbour") | **a work order** for a cloud LLM or for an engineer | nothing yet; a spoken update when it lands |

The reflex layer sits **in front of** all of them. A known command does
not consult the world, the model or the cloud at all: it matches in
0.146 ms and runs.

### The owner's one word

`file_work_order` files a **draft**. It does not queue it. The queueing is
the owner's decision, and `confirm_work_order` takes one word — go, no, or
edit.

So after filing a work order the first mile holds the draft and says
nothing more. When the human says "go", the first mile calls
`confirm_work_order` and the order moves from draft to queued. Measured:
**19 ms** from the word to the routed answer — faster than the reflex
match, because it is a state transition and not a lookup.

The same holds for a question. When the core finds two plausible referent
sets it asks, and the question is parked; the human's answer goes to
`answer_question` and the work order unblocks.

This is checked **before** the reflex layer and before the model. The
owner's word is the fastest thing in the system and it must never be
routed around.

---

## 6. The context packet, and never guessing

builder-ide's design says that *"ambiguity is resolved by asking, never by
guessing"*, and that the core keeps a **context packet** — the selection's
resolved referents, the region, the params — which it attaches to every
call.

The measurement in the experiment notes makes the shape of this clear:

- the 2B model, given only audio, **refuses to resolve "these"** and
  answers in speech;
- given a text packet that names the selection, it **asks** ("Which
  structures should I reinforce to…");
- it never invents a target.

That is correct behaviour from a 2B model, and it means the referent
resolution belongs **in the core, not in the prompt**. The first mile
therefore attaches the context packet to the *call* — it asks
`get_context` and hands the packet to `file_work_order` — and the model
is freed from having to guess.

This is also why the spoken answer in the prototype is the core's own
confirmation line ("CONFIRM: …; build/verify: ~30 min [e] · generate/test:
~60 min [e] · reversible at ver_0001. Go?"). The computer's voice is the
world's language, not a paraphrase of it.

---

## 7. The voice

One voice, always the same. The model is asked for a flat, plain reading
with no affect and no performance; there is no music, no sound effects and
no TTS artefacts. Replies are one sentence, or the one line the world
core wrote.

This matters for a system that is always talking to the same person: a
voice that shifts is tiring, and a voice that performs is a voice that
interrupts.

---

## 8. Safety

quilt-pincher's own documentation is honest that `execute()` is an
unsandboxed `new Function(...)` evaluation. That is a real capability gap
in the engine, and the first mile does not rely on the engine's veto
alone:

1. **The reflex store is ours.** Reflexes are seeded in one file, and a
   miss may only add a reflex whose action is one of four templates.
2. **The veto checks the action's shape, not its safety hints.** The
   engine's `DefaultVeto` compares safety metadata, which is not a
   capability check. The service's `ClosedVerbVeto` rejects any action
   that is not exactly one of the templates, and any op that is not in
   the closed op list.
3. **The reflex never runs world code.** An action calls back through
   `POST /internal/op` on the first mile, which accepts only
   `world_action`, `recall`, `pause_night` and `decision`. The effect
   happens behind the first mile's own vocabulary, not inside the
   reflex engine.
4. **A compiled reflex is not the model's text.** The cloud compiler
   names an intent from a closed list; the service builds the action.

The same reasoning applies to the voice: no human audio and no human
transcripts are stored in this directory. Every piece of test audio was
generated on the spot by the model itself.

---

## 9. Why this is on the ProArt at all

**The hardware fact.** The RTX 4050 has 6141 MiB of VRAM, of which 675 MiB
belongs to the Windows desktop. The audio model needs 1955 MiB of that as
Q4, leaving 3.5 GB — the brief's budget, met with room to spare.

**Why the previous path could not use it.** The voice lived on the Thor
(`:8102`, "ears"), on a shared box under a lock, running other people's
jobs. Every reply was a LAN round trip before a single sample of audio
could exist. A reply that crosses a network cannot be an instant reply,
and a reply that shares a GPU with a build queue cannot be a *reliable*
one.

**What the new path does differently.** The model and its projector sit in
the ProArt's own memory, next to the browser that is already holding the
microphone. The acknowledgement is a memcpy from a cache rather than a
forward pass, so it does not care whether the GPU is busy.

**What it makes possible.** The computer can talk over the human, and it
can talk while the rest of the machine works — the reflex layer answers
known commands in 0.146 ms, the world core files a work order in 19–84 ms,
and anything harder goes to the background while the human carries on
talking.

---

## 10. What the numbers were, and what they allow

| | measured |
|---|---|
| acknowledgement, onset → playable | 0.3 ms median, 0.8 ms worst of 18 |
| speech recognition | 300–500 ms |
| reflex match | 0.146 ms median, 0.365 ms worst |
| answer's first audio from the end of speech | 776–1047 ms |
| whole turn | 2400–3400 ms |
| the owner's word, routed | 19 ms |
| first mile's VRAM | 1955 MB (Q4) – 3367 MB (Omni Q8) |
| cloud spend for every run | $0.00009 |

These are the numbers the design rests on. Full detail, the machine state
beside them, and the things that went wrong are in
[`../exp-first-mile.md`](../exp-first-mile.md).

---

## 11. Where it goes next

The gaps, in the order they matter:

1. **The hard-ask route needs its background job and its spoken
   callback.** A work order for a cloud LLM, and an update that speaks
   itself when the result lands. The door (`file_work_order`) works; the
   background worker and the callback do not exist yet.
2. **The decision route needs a destination.** d1 locally does not fit
   beside the audio model on a 6 GB card, so Clef or Jev in the cloud
   until the Thor is free.
3. **The asset route needs its callback.** `queue_genbatch` files the job
   with the Thor's generators and returns a price; nothing yet tells the
   human when the asset lands.
4. **The reflex store should persist**, so the first mile gets faster
   across restarts instead of starting empty.
5. **The tool-call path of the 2B model is measured but unused.** It is
   83.3% correct on unambiguous commands, but the reflex layer answers
   those in 0.146 ms. It is worth keeping measured, and worth using for
   the shapes the reflex layer has not learned.
6. **The confirm tier of the reflex layer says and then acts.** It says
   "Just so I have it right: …" and then runs the command, rather than
   waiting for a yes. The world's own confirm gate (§5) does wait; the
   reflex layer's does not.

---

## 12. Running it

```bash
scripts/start_proto.sh            # model server, reflex layer, first mile
open http://127.0.0.1:8790/       # the browser page: mic, transcript, route, audio
scripts/stop_proto.sh
```

The model server, the reflex layer and the first mile each log into `out/`.
`scripts/proto_run.py` drives the whole loop from a synthesised command
and prints the timings; `scripts/bench_*.py` are the benches, each
writing its JSON into `out/`.
