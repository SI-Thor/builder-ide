# idea4: optimisations, continued (2026-10-31)

`idea4.md` continues `idea3`. Unlike the earlier chats, **it has read our public repos**: it builds on our measured results (the splice at 2.3–2.5×, the Warp mesher at 3.9×, 629-byte deltas over SSE, manifold3d repair with an IoU gate, recipes as the source of truth). Its hardware section is the most accurate of the four documents. The DeepSeek library extracted it ($0.02).

## Already ours (it is building on our work)

These confirm the direction; nothing new to do:
- partial scene splice;
- the content-addressed stage cache;
- the Warp SDF mesher;
- glTF quantization + meshopt deltas over SSE;
- manifold3d repair with an IoU gate;
- recipes, not meshes, as the source of truth.

## New seeds worth testing

| Idea | Verdict | Where it lands |
|---|---|---|
| **The Anticipatory Horizon Compiler:** predict the zone the camera or avatar heads to next, and pre-generate it while the human is idle | Plausible; a hit rate to measure | **B3, the always-on daytime world:** Casey's purpose for it is "rendering precalculated assets so that when the human joins, it's better". Prediction makes that targeted rather than blind |
| **CUDA stream priorities:** the UX stream at the highest priority, background work lower, with an event fence | True (a standard CUDA feature); whether it preempts on sm_110 is to be measured | The resident scene server and the viewer: a builder's preview stays responsive while a night render runs. Complements thor-admit (memory) and Green Contexts (SMs) |
| **Pinned ARM core affinity** for background daemons (e.g. cores 10–13) | True | thor-admit, the core service, the sweep: keep the 14 cores' interactive work off the cores the daemons use |
| **A static block allocator** (4 MB blocks, no malloc at run time) | True | Generators; a finer-grained version of idea3's static pool, inside thor-admit's leases |
| **A double-buffered scene state with an atomic pointer flip** | True within one process | The resident scene server: readers (the stream compiler, the critic) read A while the builder writes B |

**Metaphor only:** "living crystal", "the system dreams your system's future", "synthetic soil where the agent's math is forced to sweat", "the engine has grown its own reflex".

## Experiments, under a day each

1. **Anticipatory hit rate** on a 10-minute scripted camera path. Pass: ≥ 60 % top-1 and ≥ 80 % top-3 for the next zone. Below 40 % top-1, gate pre-generation on a cheaper signal.
2. **Stream priority actually preempts on the Thor.** A long background kernel at low priority, and a short UX kernel at high priority. Pass: UX p99 under load ≤ 1.2× its idle baseline.
3. **The splice, re-measured** across several parameter deltas of different sizes (answering Q1 below with a distribution, not one run).

## Its questions, and which ones we can already answer

1. *"Is the 2.5× splice measured on the same scene with the same delta?"* **Answered:** the same scene and the same one-parameter change, two runs (2.33× and 2.46×), canonical-equal (`docs/research/engine-round3.md`). The open part is the spread across delta sizes, which is experiment 3.
2. *"Does manifold3d clear the 0.9999 IoU bar on real TRELLIS outputs?"* **Answered: yes.** 9/9 props at 0.99992–1.00000, 3.1–3.8 s each (`docs/lab/mini-night-2.md`).
3. *"What is the idle threshold, and how much of a session is idle?"* **Open, and a good question.** The first mile and the daytime world both need that number.
