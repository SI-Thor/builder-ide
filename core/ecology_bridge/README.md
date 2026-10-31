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

## What this package is NOT

- **Not a writer.** No ledger, no journal, no state beyond the bank you
  hand it. core-spec §1.0 (single writer owns the ledger) is untouched.
- **Not a kernel.** No tick loop, no freshness, no WHY states — those
  live in the vendored `core/why` (semantics authority for our world)
  and in the native ecology-thor process.
- **Not accounting.** Rails are admission envelopes in float; the
  ledger keeps the books.

## Why it exists

The daytime and night teams can now run real batch shapes through the
auction semantics — night jobs as bids, the measured p50/p95 costs from
`core/night/cost/` as rail costs, daytime's budget as the refill — and
argue with the semantics *before* anyone wires a door. If the team
adopts the exchange, this module is the reference the door is tested
against; if not, it is a self-contained thought experiment that cost
one file.

## Tests

`tests/ecology_bridge/test_auction.py` — each test names the law it
checks (veto, conservation, determinism, kernel-class rules). Pure
unit tests, no fixtures, no core.* imports beyond this package.
