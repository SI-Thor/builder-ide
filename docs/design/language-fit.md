# Language fit: pick what is best, not what is easiest to write (Casey, 2026-11-01)

> "For the CPU especially [Rust]… the GPU side, we can be whatever is highest performance when we are remaking: C++ CUDA, PTX, Triton, Vulkan, HLSL; every case is different there… and for the quilt side, those where they fit, and Gleam, Elixir/Erlang might be optimal as networks grow larger… it's the agentic era, so pick what's best, not what's easiest to write."

Agents write the code. So the cost that used to decide the language (how quickly a person writes it) no longer dominates. What remains is what the **runtime** guarantees and what the **type system** catches before a run.

## The map, by layer
| Layer | Default | Why that fits | Our prior work |
|---|---|---|---|
| CPU services, daemons, kernels of logic | **Rust** | Exact memory on a 122 GB unified box, no GC pauses, determinism, and the same code compiled to WASM for the viewer | thor-admit; mission B's std-only stream; SolidCraft |
| GPU kernels | **per kernel, by measurement:** CUDA C++/CUTLASS, inline PTX, Triton, Vulkan/HLSL/WGSL compute | Tensor-core GEMMs want CUTLASS or PTX; fused elementwise iterates fastest in Triton; anything that must also run on the ProArt's Radeon or in Chrome wants Vulkan/WGSL | thor-fp4 (CUTLASS sm_110a), Warp |
| **The quilt: large agent networks** (the canon, the mediator's fleet, bots, cells) | **BEAM: Elixir or Gleam on Erlang/OTP** | See below | `SuperInstance/tit_quilt_elixir`, `SuperInstance/quilt-i2i` |
| Capacity planning for any of the above | **queueing models, in Rust** | Size before building: M/M/c, Erlang C, Jackson networks, priority queues | `SuperInstance/queueing-theory` (MIT OR Apache-2.0, 72 tests) |

## Why BEAM for the quilt as networks grow
`tit_quilt_elixir` (2026-08-29; 16/16 tests) makes the point concretely. The fabric's doctrine *is* the runtime's semantics, so it is not code bolted on:

| Quilt doctrine | BEAM primitive |
|---|---|
| a cell's only world-touch is an effect | `send/2` (messages; no shared state) |
| receipted read | `GenServer.call` |
| a cell's failure propagates to who depends on it | `Process.link/1` |
| **let it crash**, restart as a kernel feature | supervision trees |
| the storm brake | supervisor restart intensity (3 in 5 s) |
| crash-safe journal, witnesses | immutable state, hash-chained journal |
| harness changes land between ticks | **hot code reload** |

**What this buys at scale.** Hundreds or thousands of agents, each a lightweight process (about 2 KB each, preemptively scheduled, with no thread per agent). A bad agent crashes alone and its supervisor restarts it. Distribution across the Thor, the ProArt and the Orin is built into the runtime: nodes, monitors, and location-transparent messages.

That is the canon's and the mediator's half of `three-minds.md`. The reflex half stays tensors on the GPU.

**Gleam or Elixir.** Gleam is statically typed on the same VM. In the agentic era, types matter more, not less: they catch an agent's mistakes before a run, and our classifier rules favour artefacts we can check before executing. Prefer **Gleam for new cells**, Elixir where its libraries (Phoenix for the spectator channel, Nx) earn their place, and raw Erlang/OTP where `quilt-i2i` showed the actor form is the clearest.

## Where we apply it first
1. **agent-world's fleet** (the Minecraft bots, the coach, the spectator channels): a BEAM supervisor tree over the bots, one process per bot and one per coach. The bot client stays mineflayer (Node) or moves to a Rust client, whichever measures better. Measure bots per box, restart time after a bot crash, and the cue latency.
2. **The canon and the event log** for the room graph: the emitter as a supervised BEAM service; the sparse room matrix stays a GPU kernel the BEAM node calls.
3. **thor-admit's presence queue and the night scheduler:** use `queueing-theory` to model the tiers (a priority M/M/c) before tuning, and compare the model's predicted wait with the ledger's measured one. **Seed 162.**

**Install note:** no machine has OTP yet. The first job that needs it installs a rootless OTP + Elixir/Gleam in its worktree (the fleet's old `beams.env` pattern), and logs it with its undo.
