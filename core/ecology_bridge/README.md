# core/ecology_bridge — dogfood the ecology-thor auction semantics

A pure-Python mirror of the attention auction and rails from
[SI-Thor/ecology-thor] (`crates/ecology-core/src/{attention,rails}.rs`),
added by the `research/ecology-bridge` branch for review. See
`docs/research/ecology-thor.md` for the full follow-up study.

## What this package is

Arithmetic, not authority. `admit_full(bank, bids)` answers *"what would
the auction admit, given this bank and these bids?"* — the veto law
(score ≤ 0 never transacts, even for Kernel class), rails conservation
(spend only what's held, never negative), importance classes (Kernel
bypasses the admission cap, never the rails), and the deterministic
strict order (class desc, score desc, id asc).

Since the rebase onto core-judge (2026-11-01), two things changed:

- **The units are the night's own.** Rails speak `gpu_minutes` /
  `hosted_cents` / `wall_minutes` — `core.records.Rail`'s field-for-field
  shape, with the same `add`/`subtract`/`fits`/`is_zero` arithmetic —
  so a bid's cost *is* a cost-model estimate, no conversion anywhere.
  (The kernel's joules axis maps onto `CostEstimate.joules`, the
  measured `VIN` column, which the cost model carries per job.)
- **A winning bid maps onto a thor-admit lease** (`lease_for`). The
  auction prices value and rails; the memory daemon prices the box's
  headroom; they compose once per admission. The daemon's lifecycle
  events map back onto the WHY ledger's states
  (`LEASE_EVENTS_TO_WHY`): granted → served, watchdog-stop → harvested
  to UNKNOWN (questionable, not gone), killed → dead with reason.

## What this package is NOT

- **Not a writer.** No ledger, no journal, no state beyond the bank you
  hand it. core-spec §1.0 (single writer owns the ledger) is untouched.
- **Not a kernel.** No tick loop, no freshness, no WHY states — those
  live in the vendored `core/why` (semantics authority for our world)
  and in the native ecology-thor process.
- **Not accounting.** Rails are admission envelopes in float; the
  ledger keeps the books.
- **Not a second admission daemon.** Memory is thor-admit's axis
  (kernel-held leases, the 250 ms watchdog, learned peaks feeding the
  cost model's memory column). The ecology's contribution there is the
  *ledger* — every daemon decision journaled as a WHY transition —
  which is the question the bake-off (`docs/research/ecology-thor.md`
  §"the bake-off") answers.

## Why it exists

The daytime and night teams can now run real batch shapes through the
auction semantics — night jobs as bids, the measured p50/p95 costs from
`core/night/cost/` as rail costs, daytime's budget as the refill — and
argue with the semantics *before* anyone wires a door. The recorded
night to try first is the mini-night-2 replay
(`tools/replay_mini_night2.py` in the ecology-thor repo): at the
runner's own prices the auction makes the identical allocation; priced
from the box's own night-1 ledger, the veto law refuses the six
third-seed variants whose expected gain was zero — 30% less GPU at
identical winners.

## Tests

`tests/ecology_bridge/test_auction.py` — each test names the law it
checks (veto, the night's units, conservation, determinism,
kernel-class rules, the lease mapping). Pure unit tests, no fixtures,
no core.* imports beyond this package.
