# 04 — The QUF cell, FP4 weights, Hebbian learning and the hardware-RNG mutation engine

**Source:** `googleidea3.md` lines 305–341 (cell structs, op codes), lines
404–442 (`execute_hebbian_update`, FP4 pack/unpack), lines 552–576 (cell
initialisation), lines 920–1034 (Stage 35: `entropy.s`,
`entropy_engine.c`, "quantum stochastic mutation").

**Relation to the corpus:** repeats googl1's part 09 (the QUF cell, FP4)
with a *quieter* geometry, and adds the RNG-mutation engine, which is new
in googleidea3. The "NUMA_LOCAL_ID_MASK" in the path hash repeats
googleidea2's "NUMA Socket 0" language — the Thor is a single-socket UMA
machine (`exp-ct-thor.md`: one 122.8 GB pool, one triad number); no NUMA
exists to be local to.

## What it says

A packed, 16-byte-aligned cell: id, activation, threshold (0x7FFF), edge
count, four "dials", 16 links, and a 4-byte "FP4_Weight_Block" (eight
4-bit weights). Learning: `execute_hebbian_update` — a fixed-point
reinforcement `(activation × signal) >> 16`, shifted, saturating at 15,
packed back into a nibble. Stage 35: read the Arm **RNDR** register
(`s3_3_c2_c4_0`) with its carry-flag validity check, and use the bits for
`inject_quantum_stochastic_mutation` — ±1 random walks on edge weights,
"channeling atomic-scale noise directly into the cellular link matrix".

## What it means

Three separable mechanisms: (a) a fixed-width cell record — settled
territory (googl1 part 09: yes, at a 128-byte stride); (b) a quantised
Hebbian update — ordinary fixed-point arithmetic; (c) seeding random
search from a *hardware* entropy source instead of a PRNG — the only new
hardware claim in this part, and the only one that can be checked on the
live machine, which we did.

## Is it true on the Thor?

| Claim | Verdict | Evidence |
|---|---|---|
| The cell record geometry is the 128-byte-stride record googl1 settled | **contradicted (silently different)** | The fields total 100 B; `packed, aligned(16)` makes `sizeof` = **112 B** — not 128, and not a multiple of the 128 B cache line, so cells straddle lines exactly like googl1's 144 B did (googl1 part 09's argument applies unchanged) |
| The cell can hold MAX_EDGES=16 edges with weights | **contradicted by its own struct** | `FP4_Weight_Block` holds **eight** nibbles; `unpack_fp4_weight`'s switch handles edges 0–7 only (edges 8–15 read 0 and `pack_fp4_weight` writes nothing). Half the declared edges have no weight storage |
| "FP4" here is the Thor's NVFP4 tensor format | **name collision, not the same thing** | These weights are unsigned 4-bit *integers* 0–15 (clamped ++/−−). NVFP4 is E2M1 floating point with UE4M3 per-16 block scales (`thor-fp4/BENCHMARKS.md`, googl1 part 09). Two different formats sharing a name across documents |
| The Hebbian update is implementable as written | **plausible but sloppy** | `(activation_state * signal_intensity) >> 16` is a 16.16-style fixed-point multiply in `u32` — the product needs a 64-bit intermediate (`umull`) or it wraps; safe only if both operands stay ≤ 16 bits, which nothing enforces. Also one-sided: the shown code can only increase a weight (decay lives in the never-shown Stage 18 tick). In-place FP4 accumulation remains lossy (googl1 part 09: keep a higher-precision shadow) |
| RNDR (`s3_3_c2_c4_0`) with the carry-validity check is real Arm | **confirmed (architecture)** | FEAT_RNG (Armv8.5-A+): RNDR is `S3_3_C2_C4_0`, and the C-flag-after-read validity idiom (`cset cs`) matches the Arm ARM. Correctly written assembly |
| The Thor's Neoverse V3 AE implements FEAT_RNG | **contradicted (checked live)** | `/proc/cpuinfo` Features on the box (kernel 6.8.12-1021-tegra, which knows HWCAP_RNG) contains **no `rng`** → `ID_AA64ISAR0_EL1.RNDR` reads 0 → the `mrs` would take an UNDEFINED-instruction exception. Arm leaves FEAT_RNG optional per core; no public V3 AE TRM promises it, and the box says no |
| Hardware entropy from a TRNG is reachable in our software | **confirmed, differently** | User space gets the box's entropy via `getrandom(2)`/`/dev/urandom` (backed by the SoC's RNG through the kernel) — same source, supported path, no EL3 |
| Random ±1 walks on weights let a network "discover alternative connection shapes" | **plausible but unverified; not a hardware claim** | This is random local search (cf. simulated annealing without a temperature). Nothing about the Thor bears on it; it is a toy learning rule whose value would have to be shown on a workload, not asserted |

**The honest summary.** The one checkable new claim — that this machine
has architectural RNDR to read — is false where it matters: the register
sequence is real Arm, the CPU does not implement it, and the code as
written would fault on the first `mrs`. The cell geometry drifted from
googl1's 144 B to 112 B without noticing either number fails the same
alignment argument, and the "FP4" weights are integers, not the tensor
format. The mutation idea itself is just random search and needs no
hardware at all — `getrandom` already delivers the same entropy to user
space.

## Judgement

Stock JetPack, today: use `getrandom()` if the runtime ever wants
stochastic exploration; keep the 128-byte cell record decision (googl1
part 09 / part 13, unchanged); keep FP4 meaning NVFP4 and keep accumulation
in higher precision.

Needs Casey: nothing. Even the entropy is available without privilege.

**What we would measure** if random edge-walk exploration ever mattered to
builder-ide: convergence of Hebbian-plus-mutation vs Hebbian-only on a
real workload, both seeded from `getrandom` — a user-space experiment with
no Thor-specific claim, which is precisely why it is not a paper candidate
for this library (no mechanism tied to this machine, no hardware claim to
test).

**Cost:** zero for the decisions; days for a throwaway learning-rule
experiment nobody has asked for.
