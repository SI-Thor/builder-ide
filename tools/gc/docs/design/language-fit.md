# Language fit

Which language each piece is written in, and why. The rule we use: pick the
language whose failure modes suit the job, and the smallest one that does.

> The brief pointed at `docs/design/language-fit.md` in `builder-ide`. There
> is no `builder-ide` repository under either of our GitHub owners (checked
> 2026-11-02 with `git ls-remote`; the Thor's `gh` token is invalid, so this
> is not a permissions artefact), so this document is written from scratch
> and cites the pattern by name only.

---

## The pieces

| piece | language | why this one |
|---|---|---|
| the ledger and the program (`gc`) | **Rust, std only** | see below |
| the lane reconstruction (`tools/extract-lanes.py`) | **Python 3, stdlib only** | it is a script over text files, timestamps and one ssh call; Python is the shortest honest way to write it, and it needs no environment |
| the briefs, notes and reports | **Markdown** | they are read by people and by seats; no build step |
| the ledger itself | **JSONL** | one row per line, so it can be appended, tailed, diffed and hashed without a parser |

## Why Rust for `gc`

**The failure mode that matters.** This program is the record that a seat's
money and time were spent as promised. It is run at the start and end of
every job, on a box that is shared, and its output is the evidence in an
argument about who owed what. A program that silently corrupts a row, or
that panics halfway through writing one, is worse than no program: the
ledger would be wrong and look right.

Rust gives that by construction: no data races, no use-after-free, no
null-pointer surprises, and an exhaustive match on an enum forces every
event kind to be handled. The domain model in `src/model.rs` is a plain
enum-and-struct design, so the compiler does most of the arguing.

**The other reason: the box.** The Thor is aarch64 Jetson Thor with 122 GB
of unified memory and a busy neighbour (`thor-admit` exists because three
seats loading models at once killed it). The GC's own binary should be
small, start instantly and never be the thing that allocates. A Rust binary
with std only is a few hundred kilobytes, starts in milliseconds, and pulls
in no runtime.

**Why std only.** The one cryptographic thing this program needs is SHA-256,
and the brief asks for std only. So SHA-256 is in `src/sha256.rs` (60 lines,
checked against the FIPS vectors) and the JSON writer and parser are in
`src/json.rs`. The cost is a few hundred lines of code we own; the benefit is
that the ledger's hash chain cannot change under us because a dependency
changed, and that `cargo build` works on a box with no network and no crate
registry.

**Why not Python for the program too.** It could have been. The deciding
factor was the failure mode, not the language: a partially written ledger row
is worse than a crash, and Rust's write-then-flush plus the hash chain make
that recoverable (`gc verify` names the bad row). The Python half of this
repo is a script that reads files and prints JSON; if it dies halfway, it
has written nothing.

**Why not a database.** A ledger that a database rewrites is not a ledger. The
brief asks for an append-only JSONL file where every row is hash-chained;
a database would add a moving part between the seat and the record, and
nothing else in this system needs concurrent writers.

## The shape of the code

- `json.rs` — canonical writer, small parser. The canonical part matters:
  two identical rows must always serialise to identical bytes, or the hash
  chain is noise.
- `sha256.rs` — the digest, with the standard test vectors.
- `ledger.rs` — append, read, verify. The only code that touches the file.
- `model.rs` — the domain types and the replay that folds rows into state.
  Nothing is stored twice: the rows are the record.
- `calib.rs` — quantiles, the factor, the reputation, the award score. All
  the arithmetic that a person might want to check by hand.
- `accounting.rs` — overrun, penalty, debt, repayment.
- `brief.rs`, `report.rs` — rendering. No arithmetic of their own.
- `seed.rs` — the import of reconstructed history.
- `cli.rs` — argument parsing.

The split is deliberate: `accounting.rs` and `calib.rs` have no I/O, so the
numbers can be tested by hand against a table, and the rendering modules
cannot change a number.

## The one number that is a judgement, not a computation

The job class of a reconstructed lane. It is a reading of what the lane was
asked to do, kept in one table in `tools/extract-lanes.py` so it can be
argued with and changed. Everything else in the reconstruction is a fact
about a file's timestamps or an exit code.
