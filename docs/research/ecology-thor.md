# REPORT — the deferred option, built: ecology-thor as builder-ide's native engine

*2026-11-01. Follow-up to `docs/research/cogeco.md` (2026-10-30), which
studied SuperInstance/cognitive-ecology and recommended option (b):
vendor the WHY kernel, borrow the lifecycle behaviors, do not adopt the
tick loop or the attention economy — *for a two-user daytime world*.
This report is about the thing that changed since: the deferred half now
exists, purpose-built for this box, at
[SI-Thor/ecology-thor] (private — ask Casey). Same owner lineage as the
original study; this time the fit question is not "partnership or
merge" but "when does the daytime world want a 100 Hz money changer
under it, and through which door."*

## 0. What exists now (one paragraph)

ecology-thor is the cognitive ecology rebuilt as a native AGX Thor
service: a zero-dependency Rust kernel (the same WHY conservation law
and re-attestation economics your vendored `core/why` carries, as one
SoA ledger with level-synchronous chain aggregates), an attention
auction that admits work against **rails of GPU-seconds, joules and
cents** — deliberately your unit system — under a veto law (score ≤ 0
never transacts, not even for kernel-class work), a chain-hashed
append-only journal, a 100 Hz framed tick with safe-mode degradation,
and bit-exact CUDA/PTX sweeps for the O(population) columns on the
Blackwell GPU (sm_110, unified-memory zero-copy). It is measured at
**130 µs per auction tick at a realistic 3.2k-purpose population on a
2-vCPU dev box** — roughly 1.6% of its own 8 ms frame budget. Python
bindings (`ecology-py`, abi3) exist for the orchestration edge.

## 1. Re-reading the original study's open door

cogeco.md closed with the condition, quoted here verbatim:

> "if CE's processes ever bid for actual Thor GPU-minutes, BI's rail
> design is the missing currency exchange."

That door is now open from our side: the auction's rails *are* the
exchange. Three of the study's other observations get direct answers:

| cogeco.md observation | ecology-thor's answer |
|---|---|
| "a laptop-class tick loop where budget is an abstraction; nothing in CE has ever had to refuse work because the wallet was empty" | The wallet is real here: gpu_seconds/joules refilled per period, spend-only-what's-held, infeasible bids skipped (never discounted), balances never negative — and every admission is journaled with its cost. |
| "CE has no cost model" | Yours does (`core/night/cost/`, measured p50/p95 on this box). The rails were dimensioned to match it; the auction is the exchange, your ledger stays the accounting truth. |
| "would it even notice a dead routine? …the ecology has no story for asking a process to justify itself in currency it doesn't have" | The re-attestation economics: justification = chain freshness; unserved purposes slide (grace → linear → lapse to UNKNOWN), revived purposes land on parole (capped at half strength until served). A process that wants GPU-seconds must keep its purpose fresh — *use it or lose priority, then lose standing, never lose history*. |

## 2. Where it plugs in (without breaking a single §1.0–§1.8 rule)

The study's hard constraints, checked one by one:

- **Single writer owns the ledger** — the ecology never writes to
  builder-ide's SQLite, never imports `core.*`, never runs in your
  process. It is its own process on the box, publishing a seqlock
  summary (JSON, frozen append-only contract — see
  `docs/INTEGRATION.md` there). If builder-ide wants it, the read
  arrives the way all reads arrive: **a door** (`GET /v1/why/summary`,
  a pure read, no new event type, closed set intact) and a fold on
  your side, or no door at all and thor-world's `world://why` resource
  alone (our draft module is on thor-world's
  `research/ecology-why-stream` branch, purity-law clean).
- **The vendored `core/why` stays the semantics authority for *your*
  world** — and it just gained a native big sibling: the Rust kernel
  ports the same v0.3 semantics (weakest-link freshness, probation,
  lapse) exactly; your golden corpus and its golden corpus can be
  cross-checked. ADR 0001's rule (diverge only via new golden pairs)
  is the shared review discipline; the tree-not-DAG restriction on our
  side is documented and priced (spawning a child under each warrant
  composes richer, not poorer).
- **Admission before spend** — that *is* the auction's law, lifted
  from your spec. `core/daytime`'s budget becomes a rail;
  `core/night/heartbeat.py`'s 10-minute `night.tick` maps to
  `run_under` service beats (gaps then have a *price* — the freshness
  slide — before anyone writes a post-mortem).
- **No LLMs on the Thor (B2)** — the kernel has no model calls, no
  inference, nothing learned. It is arithmetic and bookkeeping. The
  cents rail exists precisely so *cloud* work is priced differently
  from local work in the same auction.

## 3. The smallest useful adoption ladder (each step valuable alone)

1. **See it** (zero integration): `world://why` in thor-world via the
   draft module — the night runner's dashboard gets a live digest of
   what the box's attention is doing. Mock stream included; buildable
   today.
2. **Dogfood the semantics** (this branch): `core/ecology_bridge/` is
   a pure-Python mirror of the auction + rails (no new deps, no
   writer, no event types) with tests in your house style. It exists
   so the *daytime* and *night* teams can feel the semantics — veto
   law, rails conservation, importance classes — against real batch
   shapes before anyone wires a door.
3. **Price real work** (one door, read-only): `/v1/why/summary` behind
   auth, folded into the night report — "here is what the box admitted
   and spent, in your units." Your audit log gains a new *source*, not
   a new writer.
4. **Exchange currency** (the study's door, fully open): infinigen
   render jobs (and eventually genbatch/TRELLIS jobs) bid for
   GPU-seconds through the auction — the infinigen-thor branch
   (`research/ecology-admission`) is the same proposal from the
   workload side, with a runnable supervisor prototype.

## 4. What we are NOT asking for

- No merge, no move, no rewrite of `core/why`, `core/night`, or
  `core/daytime`. The vendored kernel stays; the golden corpus stays.
- No second writer, ever. If the ecology ever needs to *record*
  something in your ledger, it goes through a door like everyone else.
- No commitment from this study — it's a report of what now exists and
  where the doors would be, for the team that wrote the spec to
  weigh.

## 5. Verification notes (how to check our claims)

- The kernel: `git clone` SI-Thor/ecology-thor (ask Casey), then
  `cargo test --workspace` — 34 tests including the golden
  determinism hash; `docs/BENCHMARKS.md` carries every number with its
  machine; `docs/SAFETY.md` is the memory-safety review policy
  (zero-dep core, one `unsafe`, no allocation in steady state).
- The semantics mirror vs. your `core/why`: both sides' freshness
  math is the same shape (`grace = horizon/3`, linear to 0,
  weakest-link, `PROBATION_CAP = 0.5`, service ends parole) — the
  bridge module on this branch is deliberately line-comparable.
- The infinigen side: `python -m thor.ecology_admission.sim` on the
  infinigen-thor branch (fake clock, no GPU) demonstrates
  stall→UNKNOWN→checkpoint→revive end to end.

*— the ecology-thor team*
