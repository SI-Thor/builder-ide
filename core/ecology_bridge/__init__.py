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
"""

from .auction import (
    Admission,
    AuctionResult,
    Importance,
    Rails,
    RailsBank,
    admit_full,
    attention_score,
    auction_order,
)

__all__ = [
    "Admission",
    "AuctionResult",
    "Importance",
    "Rails",
    "RailsBank",
    "admit_full",
    "attention_score",
    "auction_order",
]
