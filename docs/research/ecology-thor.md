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

---

## 6. The rebase addendum (2026-11-01, onto core-judge)

Main moved 14 commits while this branch sat; this section is the
re-check against what landed, plus two changes the review asked for.
The branch now sits on `f0d846b` (core-judge merged, 1,494 tests).

### 6.1 The units, corrected

The review was right and this branch was wrong: the mirror originally
spoke the kernel's own axes (`gpu_seconds/joules/cents`). Bids are now
priced in **the units `core/night/cost` already uses** — the night's
`Rail`: `gpu_minutes` / `hosted_cents` / `wall_minutes`, field-for-field
and method-for-method (`add`/`subtract`/`fits`/`is_zero`), so a cost
model estimate *is* a bid cost, unconverted. Joules ride the cost side
(`CostEstimate.joules`, the measured `VIN` column), not the bar. Two of
the mini-night's own lessons are now first-class in the tests: the
**wall axis refuses what the GPU axis can afford** (the mesh-tail
lesson — `test_wall_minutes_is_a_rail_axis`), and hosted cents refuse
cloud work the rail cannot pay.

### 6.2 The lease mapping: the auction and thor-admit compose

`tools/thor-admit` (the `thor-admit` branch) is the box's memory
admission daemon, and it is good: kernel-held leases a dead client
cannot leak, a 250 ms watchdog that stops the largest lease long before
the kernel OOMs, and learned peaks (the p95 of a label's history) that
feed the cost model's memory column. The auction does not compete with
it on its axis and does not duplicate it. They compose **once per
admission**:

```
the auction:  is this work worth its gpu-minutes/wall-minutes/cents?
                    │ (a winning bid)
                    ▼
thor-admit:   does the box have room for its peak?  ── no ──▶ the work waits
                    │ (lease granted, kernel-held)
                    ▼
the runner:   spawns the process group; the spend is booked at the actual
```

`lease_for(admission, label)` in the bridge module produces the
`acquire` (peak `"auto"` — the daemon's learned p95; on its refusal for
an unknown label the caller falls back to the cost model's memory
column, never a guess), and `LEASE_EVENTS_TO_WHY` maps the daemon's
lifecycle onto the ledger the ecology journals: granted → served
(`run_under`), watchdog-stop → **harvested to UNKNOWN** (a stopped
lease is questionable, not gone — SIGSTOP loses nothing), killed → dead
with reason, client-gone → harvested (the kernel's flock can speak for
a client that cannot).

The open question the review actually asked — *is the ecology's ledger
something thor-admit should adopt?* — is being answered by a bake-off,
same tests for both daemons (three 30 GiB hogs serialised; a runaway
stopped before MemAvailable hits 2 GiB; daemon overhead), harness in
the ecology-thor repo. Whatever wins, the fold-in we would claim is the
chain-hashed decision journal: every admission, stop and kill a WHY
transition with a chain hash over it, so a 3 a.m. OOM post-mortem reads
one replayable log instead of correlating daemon logs with dmesg.

### 6.3 Re-checks against what merged

- **core/judge** — the `expected_value` factor now has a typed source:
  the judge's `choice` probability stands where a hand-set prior stood,
  exactly as `JudgePriorChooser` already does for the tiles shortlist,
  one level up. The confidence gate composes with the veto law cleanly:
  a judgment below τ is *surfaced, not acted on* — so it sets no EV, and
  a bid that rests on surfaced evidence is a bid that is not placed on
  that evidence. No new rule needed; the two policies already agree.
- **core/tiles + OPE** — the auction's admissions are a logging policy,
  and tiles rule 8 is the lesson: *a play carries the propensity it was
  drawn with, and a missing propensity is never defaulted to 1.0.* The
  live bridge must journal **the bid set at each admission, not just the
  winner** — what else was bidding, at what scores, against what bank
  balance — or the log cannot answer "would a different pricing policy
  have earned more" off-policy later. The mini-night-2 replay (below) is
  exactly that question asked retrospectively; it needed a
  reconstruction because the runner logs only what ran. The auction
  should not repeat that mistake.
- **core-doors (per-agent tokens)** — every bid should carry the `agent`
  claim the way every audit row does, so the answer to "which agent
  asked for tonight's GPU-minutes" is a fold, not an investigation.
  The why stream's door now exists as a full proposal
  (`docs/design/why-door.md`, this branch): `POST /v1/why/digest` (the
  ecology publishes through the door — one `why.digest` audit event,
  the core's single writer, the closed set grown by exactly one the way
  the tiles' four were) and `GET /v1/why/summary` (the fold; an
  unwired core answers 501 with the seam named, the `/v1/world/scene`
  precedent). No new stream door — `GET /v1/events?types=why.digest`
  already is one. thor-world's follow-up branch
  (`research/ecology-why-door`) reads the door end to end and degrades
  honestly when it is not wired; its review round asked for exactly
  this, and the ask was right.
- **The daytime world, ON by default (B3: yes)** — an always-on daytime
  lane is a permanent low-priority bidder, and the importance classes
  are built for exactly that shape: daytime's stand-down-when-night-busy
  is already an attention decision, currently taken by rule; under the
  exchange it is taken by price (daytime's tick budget as a Maintenance
  class refill, yielding to World-class night work by class, not by
  convention). Nothing about B3 blocks the exchange; B3 makes it more
  useful.

### 6.4 The evidence that arrived since the original study

The recorded night the review asked for exists:
`docs/analysis/mini-night-2-replay.md` in the ecology-thor repo
(`tools/replay_mini_night2.py`, every input cited, `--check` verifies
the reconstruction against every published aggregate). In one paragraph:
at the runner's own prices the auction makes the **identical**
allocation (drop-in parity, 6/6 across alternative reconstructions);
priced from the box's own night-1 ledger, the veto law refuses the six
third-seed variants whose expected gain was **exactly zero** by the
box's own prior — **30.6% less GPU, 31.6% less wall, identical
winners** — and the learned-peak pricing shows the 11.76-minute GPU bar
was computed from the wrong band (the same night is a 53.9% night on
the `prop.night` band the cost model already carried). The runner's own
`min_gain = 0.02` already believes marginal seeds can be below the bar;
the tick loop is that belief asked at every admission instead of once
per three-variant round.

*— the ecology-thor team*
