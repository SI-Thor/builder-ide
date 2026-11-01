//! `thor-admit` — a memory-admission daemon for the Thor.
//!
//! The box has 122 GiB of **unified** memory and no swap. Several seats can
//! run heavy work at once, and before this crate existed nobody but the
//! operator knew how much was already committed. The daemon holds the leases,
//! orders the queue, and watches the box; the CLI takes a lease and runs a
//! command under it.
//!
//! The pieces:
//!
//! * [`sizes`] — the sizes an operator writes (`40G`).
//! * [`meminfo`] — the kernel's own memory accounting (`/proc/meminfo`).
//! * [`gpu`] — the GPU's view, when the Tegra exposes one.
//! * [`procscan`] — the resident set of a process group, read from `/proc`.
//! * [`admission`] — the rule: admit only if `available - peak >= floor`.
//! * [`queue`] — the priority queue the rule drains.
//! * [`tier`] — the four tiers the work falls into.
//! * [`presence`] — the registered work that runs when the box has room.
//! * [`ledger`] — where the box's time went, and why it was idle.
//! * [`history`] — the learned peaks, as JSON lines.
//! * [`protocol`] — the socket protocol the CLI and the Python shim speak.
//! * [`serve`] — the registry that loads a model once per box.
//! * [`daemon`] — the resident daemon itself.
//! * [`client`] — the CLI's side of the protocol.

pub mod admission;
pub mod client;
pub mod clock;
pub mod daemon;
pub mod gpu;
pub mod history;
pub mod lease;
pub mod ledger;
pub mod meminfo;
pub mod presence;
pub mod procscan;
pub mod protocol;
pub mod queue;
pub mod serve;
pub mod sizes;
pub mod tier;
