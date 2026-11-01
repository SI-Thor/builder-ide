"""ecology_bridge — dogfood the ecology-thor auction semantics, in-process.

A pure-Python mirror of the attention auction and rails from
SI-Thor/ecology-thor (`crates/ecology-core/src/{attention,rails}.rs`),
line-comparable to the Rust, for the daytime/night teams to feel the
semantics against real batch shapes before any door is wired.

Deliberately NOT a kernel: no tick loop, no ledger, no journal, no
state of its own beyond the bank you hand it. builder-ide's ledger
remains the only writer and the accounting truth (core-spec §1.0); this
module is arithmetic for admission decisions — "what would the auction
say" — not a second source of record.

Since the rebase onto core-judge (2026-11-01) the mirror speaks the
night's own units — gpu-minutes / hosted cents / wall-minutes, the
core's ``Rail`` axes and arithmetic — and carries the lease mapping: a
winning bid becomes a thor-admit ``acquire`` before the work spawns
(the auction prices value and rails; the daemon prices memory; they
compose once per admission).
"""

from .auction import (
    LEASE_EVENTS_TO_WHY,
    LEASE_PRIORITY,
    Admission,
    AuctionResult,
    Importance,
    LeaseRequest,
    Rails,
    RailsBank,
    admit_full,
    attention_score,
    auction_order,
    lease_for,
)

__all__ = [
    "LEASE_EVENTS_TO_WHY",
    "LEASE_PRIORITY",
    "Admission",
    "AuctionResult",
    "Importance",
    "LeaseRequest",
    "Rails",
    "RailsBank",
    "admit_full",
    "attention_score",
    "auction_order",
    "lease_for",
]
