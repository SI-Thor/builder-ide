# 00 — Overview: googleidea3 digested

**Source:** `docs/googleidea3/01…13`, each digesting one part of
`googleidea3.md` (Casey's "third part of that": a ~15,000-word continuation
of the googl1 brainstorm — a "Cellular POSIX Simulator" shell, the Stages
31–40 code, and a closing self-review) against our measurements, NVIDIA's
public documentation, the Arm architecture references, and other primary
sources. Method and verdict vocabulary follow the googl1 digest
(`docs/00-overview.md`); the director's judgement there stands, and
nothing here revises it.

## What googleidea3 is, relative to the corpus

- **It extends googl1** literally: the stage numbering continues (31–40),
  the same QUF cells, miter, GIC, doorbell and warm-boot motifs recur, and
  Stage 40 calls back to googl1's Stages 16/18/23/24/25/27/29 by number.
  It is the cascade's final act — the completeness performance googl1
  part 12 diagnosed, carried ten stages further.
- **It repeats googleidea2's** invented-hardware DNA: MMIO doorbell
  registers, NVLink performance counters, per-blade telemetry — new
  addresses each time (0x5000F000 here vs 0x50004000 there vs
  0x40001000 in googl1), which is the tell that no register was ever
  read. It also repeats the "NUMA" language on a single-socket UMA
  machine.
- **It contradicts googleidea1**, the corpus's one practical document: a
  TensorRT-LLM / vLLM / Holoscan / ROS 2 / Docker pipeline is a *Linux*
  pipeline. Removing the OS removes googleidea1's entire material; the
  POSIX simulator that replaces it cannot list a directory or parse the
  command you typed (part 01). The corpus is not a plan converging on a
  machine; it is one plan (idea1) and one fantasy (googl1→idea2→idea3)
  sharing a brand.

## The map of the parts

| Part | What it is about | Verdict in one line |
|---|---|---|
| [01](01-the-posix-simulator-layer.md) | The Cellular POSIX Simulator (Stage 31) | The shell-as-compiler shape is right and already measured (the 3 µs ring); the Linux costume does not close — paths collide at ~300 names, `ls` cannot list, and "exploit immunity" inverts the truth |
| [02](02-the-monolithic-image.md) | linker.ld, boot.s, the build pipeline | Real Arm boot mechanics (canonical values, correct vectors) on an invented, self-contradictory map behind the signed-boot wall; the "monolith" does not assemble |
| [03](03-the-invented-register-map.md) | The register map and GPU command path | The head/tail ring discipline is exactly paper 61's measured ring; every address is invented, the GIC programming is wrong in law and in banks, and the interrupt handler **does not compile** (probe: 5 lvalue errors + a missing typedef) |
| [04](04-cells-fp4-weights-hebbian-and-rng.md) | Cells, "FP4" weights, Hebbian, RNDR mutation | Cell quietly drifted to 112 B (fails the same alignment rule googl1's 144 failed); "FP4" here is 4-bit ints, not NVFP4; the RNDR sequence is real Arm **but the box's V3 AE does not implement FEAT_RNG** (checked live) — the `mrs` would fault; `getrandom()` already gives the same entropy |
| [05](05-the-jtag-deployment-route.md) | Stage 32 JTAG flashing | Textbook TAP traversal on a Raspberry Pi GPIO map, writing boot flash that the signed chain rejects; the supported flash route (USB recovery) already exists |
| [06](06-crash-dump-and-watchdog.md) | Crash dump and watchdog (Stage 33) | The crash-only pattern is right (pstore/ramoops is its supported form); verify pstore once + keep the agent's hash-chained journal — the one operational habit worth adopting |
| [07](07-cache-maintenance-and-coherence.md) | `dc ivac`/`dc cvac` (Stage 34) | Real instructions, correct idiom, wrong premise: the CPU↔GPU path is coherent and every measured run (170 k bit-exact jobs/frames) needed zero cache maintenance |
| [08](08-the-hardware-timer.md) | The generic timer (Stage 36) | The most nearly correct stage — right registers, right PPI — still carries an EL2/EL3 naming error, a GICv3 bank error and a never-defined symbol; user space paces fine via clock_gettime/vDSO |
| [09](09-the-pcie-completion-barrier.md) | Stage 37 completion barrier | The payload-before-doorbell hazard is real; the fix is wrong (Transactions-Pending is not your writes' arrival) and unnecessary (posted-write ordering + release/acquire — proven by paper 61's bit-exact runs) |
| [10](10-nvlink-telemetry-and-multi-blade.md) | NVLink telemetry (Stage 38) | Third appearance of the NVLink fiction; no NVLink on Thor (4×25 GbE); the telemetry pattern is fine against real ethtool counters |
| [11](11-the-hardware-context-swapper.md) | Stage 39 context swapper | Invented registers on top of its own command ring; a CPU register file pasted onto a GPU; the real answers are measured (ring: no context to swap; Green Context floor: 1195/1200) |
| [12](12-the-stage-40-loop.md) | The Stage 40 integration loop | Right skeleton (ingest→dispatch→audit→heal), organs invented; the file does not assemble against the document's own parts and is not in its own build |
| [13](13-the-expert-review.md) | The closing self-review | Two real mechanisms (TMA, mbarrier — assembler-verified on sm_110a) beside picosecond claims, Apple-ecosystem API names, and invented registers; its one fully-true assertion (zero-copy on one coherent pool) is now measured |

## The overall verdict

**googleidea3 adds no mechanism that the googl1 digest did not already
adjudicate, and its new specifics fail their first contact with the
machine.** The pattern, part after part: the *shape* is inherited from
googl1 (rings, doorbells, cells, audits) and lands where googl1's
verdicts landed; the *new* specifics — register maps, GIC banks, cell
geometry, the RNG, the JTAG route, the context registers — are invented,
and this digest could check several of them hard enough to falsify: the
interrupt handler does not compile under any C compiler, the CPU lacks the
FEAT_RNG the mutation engine reads, the device tree says `arm,gic-v3`
where the document says GICv4 at a different base, and the "monolith"
contradicts itself from linker script to final file. What remains standing
is exactly what stood after googl1: Thesis B (a compiled, immutable,
hardware-scheduled artifact *over* the driver), the resident ring, the
service floor, the differential discipline — plus one operational addition
this document earns honestly: crash-first evidence handling (part 06).

Where googl1 was a multi-year programme with a week's measurable yield,
googleidea3 is a continuation with, essentially, none of its own: the
measurable yield of the whole corpus already sits in paper 61 — and as of
this seat, that paper's final pre-registered measurement (the zero-copy
ingress arm) has **run and passed**: 3.21/4.84 µs p50 vs 29.3/44.4 µs
naive (9.1×/9.2×), mismatch 0, zero >1 ms events, over 70,000 frames
co-tenant (commit `2d0ccb6` on `googl1-papers`).

## The three most valuable takeaways

1. **The ring is the corpus's one true sentence, now measured end to end.
  ** Every document in this family converges on "doorbell a resident
   engine over coherent memory" — and the supported version of exactly
   that is measured twice at the ring level and once at the wire level
   (this seat): dispatch 3 µs, ingress 3.2–4.8 µs, bit-exact. For
   builder-ide this closes the question: the night agent's dispatch path
   is paper 61's runtime, and googleidea3's Stage 31/40 loops are that
   runtime wearing a costume.
2. **Falsifiable beats fluent: this digest killed claims the pretty ones
   survived.** The compile probe (part 03), the live FEAT_RNG check
   (part 04), and the device-tree GIC check (part 03) each took minutes
   and settled paragraphs of confident prose. The method is the takeaway:
   when a document asserts a register, an instruction, or a bank number,
   the machine — not the prose — is the referee; that is how this library
   works, and why its parts name their evidence.
3. **Adopt crash-first evidence, in the supported form (part 06).** The
   one new operational idea worth keeping: verify the box's
   pstore/ramoops once, and keep the agent's own restart journal
   hash-chained. The night agent runs unattended; "what did the box say
   when it died" should never depend on an invented 0x2FFF0000.

## The paper decision (Part 2 of the brief, applied to googleidea3)

**No paper. Nothing in googleidea3 reaches the bar, and the reasons are
specific:**

- **The candidates that look like mechanisms are already subsumed by
  paper 61.** The zero-copy pipeline (part 13's headline) *is* paper 61's
  subject, and its final arm measured PASS this seat; the doorbell
  ordering question (part 09) is answered by paper 61's bit-exact runs
  plus the write-ordering rules; the "shell as a ring client" (part 01) is
  an application note of the same ring — no new claim, no new model, no
  experiment that is not already in the paper's §6 regression.
- **The candidates that are new are not pencilable.** The RNG mutation
  engine rests on a feature the CPU does not implement (part 04); even
  ported to `getrandom`, it is a toy learning rule with no derived model
  and no workload — a user-space experiment, not a paper. The POSIX
  simulator does not close semantically (part 01). The NVLink monitor
  monitors hardware that does not exist (part 10). The context swapper's
  registers are invented (part 11).
- **The one new checkable thing this digest produced — the compile probe,
  the FEAT_RNG absence, the GICv3 device-tree fact — is evidence about a
  document, not a mechanism about a machine**, and belongs in the part
  docs (where it now lives), not in the papers library.

Per the brief, that is a valid outcome and it is recorded here: **no
`googleidea3-papers` branch was created.** The library work this seat did
instead was to finish paper 61's own pre-registered measurement
(`2d0ccb6`, above) — the one action the corpus's ideas actually earned.
