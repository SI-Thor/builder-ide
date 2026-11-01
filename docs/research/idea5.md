# idea5: orchestrating many models on one box (2026-10-31)

`idea5.md` is another optimisation chat, mostly about **running a swarm of models together**: pre-rendering, agents and decision models sharing the Thor, with the ProArt as the stage. The DeepSeek library extracted it ($0.02). This is the director's sorting.

## A correction to our own facts: MIG may exist on this Thor

We had recorded "no MIG on the Thor". The chat cites a **MIG preview in JetPack 7.2** for Jetson Thor. On our box:

```
$ nvidia-smi --query-gpu=mig.mode.current,mig.mode.pending --format=csv,noheader
Disabled, Disabled
$ dpkg -l nvidia-jetpack   →   7.2.1-b49
```

A GPU without MIG support reports `[N/A]` there; ours reports **Disabled**, on the JetPack release the chat names. **MIG (Multi-Instance GPU) partitions both the SMs *and* the memory into isolated instances, each with its own guaranteed capacity.** If it works here, it is the hardware answer to today's OOM crash: a render, the critic and the decision models each get a fenced slice that cannot starve the others. That is stronger than Green Contexts (SMs only) or thor-admit (admission only).

**Enabling MIG changes the GPU's mode and needs the GPU idle and a reset** (`sudo nvidia-smi -mig 1`), so it is Casey's call and a planned window, not a seat's.

## The ideas worth keeping

| Idea | Verdict | Where it lands |
|---|---|---|
| **"Never wait": substitution with supersede.** A deadline per request; when it passes, a fallback answers; a late real answer is recorded as *superseding* the fallback, and committed history is never rewritten | True, and the most important: it is a **correctness** property, not a speed claim | **The first mile:** it never blocks on a slow path. **The ledger:** append-only already; a supersede event is the missing piece. **Characters:** a reflex now, a better answer later |
| **A central conductor**, not peer-to-peer: one scheduler owns the plan | True | It is our core (single writer, the night runner). It contradicts `fromgoogle4`'s peer-to-peer utility trees, and we side with the conductor |
| **A two-phase commit against canon:** propose, check, commit | True | Our predict → render → keep-or-undo, and the tiles' veto; a confirmation of the design |
| **Partition by bandwidth sensitivity, not FLOPs** | True | On a memory-bandwidth-bound box, isolate the latency-critical, bandwidth-hungry work (decision models, the critic) from bulk renders: MIG if it works, Green Contexts or stream priorities if not |
| **Pre-rendering as speculative asset baking:** the Thor bakes ahead, the ProArt composites cached chunks | True | B3 (the daytime world) plus idea4's anticipatory pre-generation |
| **An explicit quality-of-service contract for each fallback tier** | True | Each first-mile fallback states what it guarantees (latency, quality) |
| **Cosmos 3 Edge** (a 4B world-and-action model, 15 Hz, 32 actions per inference) as a reflex layer | **Unverified:** does it exist and run here? The MiniMax agent named it too | **Motion as virtual robotics (B2)**, if real: a short-horizon world model choosing actions. lab-motion should check it |
| Sparse hub attention across agents; routing committed history as conditioning | Papers, not built | Seeds for later |

**Metaphor only:** "the mob becomes an ensemble", "the Thor proposes, the ProArt disposes", "the swarm contract".

## Experiments, under a day each

1. **"Never wait" holds.** A conductor with a 50 ms deadline and a 200 ms worker, 1,000 requests. Pass: none blocks past 50 ms, every fallback is recorded, and every late answer is marked superseded and never overwrites committed history.
2. **MIG on the Thor** (needs Casey's window). Enable MIG, list the profiles, create two instances, and run a render in one and d1 in the other. Pass: the d1 p99 under the render's load stays ≤ 1.2× idle, and neither instance can exhaust the other's memory.
3. **Cosmos 3 Edge viability:** does it exist, what licence, does it run on sm_110 at ≥ 10 Hz.

## Three checkable questions for the author

1. **The JetPack 7.2 MIG preview:** which profiles exist on Jetson AGX Thor, and is memory partitioned as on datacenter GPUs, or SMs only? (Our box reports MIG "Disabled", not N/A, on 7.2.1.)
2. **Cosmos 3 Edge at 15 Hz:** measured on a Thor, or extrapolated from a datacenter GPU? At what resolution and precision?
3. The doc assigns OptiX-dependent paths to "the ProArt side". Our ProArt is a 6 GB RTX 4050 under WSL2. **Does the split still hold at 6 GB, and without a native Linux display?**
