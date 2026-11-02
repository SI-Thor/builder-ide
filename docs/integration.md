# Integration: putting the contract in the seat's brief

`gc` is only worth something if the terms reach the seat that has to keep
them. `gc brief --job J001` renders the contract as a markdown block; the
integration is to append that block to the seat's `BRIEF.md` when the seat is
launched.

**`desk.sh` is not edited by this seat.** The change below is a proposal for
the desk's owner. It is three lines.

## The proposal

`~/lm-ops/desk.sh` writes the standard desk brief into `$W/BRIEF.md` with a
heredoc, then launches the seat. The three lines go immediately after that
heredoc, before the `case "$A" in` block:

```bash
# the contract terms for this lane, from the general contractor's ledger
if [ -n "${GC_JOB:-}" ]; then
  ssh -n thor-lan "~/lm-wt/general-contractor/target/release/gc brief --job $GC_JOB" >> $W/BRIEF.md 2>/dev/null || true
fi
```

`GC_JOB` is the job id in the general contractor's ledger (`J001`, `J002`,
...). The ledger lives on the Thor, and the desk seat lives on the ProArt, so
the block is fetched over `ssh -n thor-lan` — `-n` because nothing is piped
into it, and `|| true` because a missing ledger must not stop a seat from
launching.

Two things this proposal deliberately does not do:

- it does not edit `desk.sh` — the desk's owner applies it;
- it does not run `gc` on the ProArt. The ledger is on the Thor, and the
  ledger is the only copy that matters.

## The flow it enables

```
GC side (on the Thor)                         desk side (on the ProArt)
-------------------                          ----------------------
gc job new --title ... --accept-cmd ...      GC_JOB=J001 desk.sh night-v6 zcode
gc bid --job J001 --sub zcode --submit         -> the brief is written with
gc award --job J001 --auto                       the contract block appended
                                               -> the seat reads the terms
... the seat works, reporting burn ...
                                               gc checkpoint --job J001 --crew-used-min 45
gc close --job J001 --crew-min 120 --accepted
gc report --sub zcode
```

The seat's own `gc` calls also need the ledger, so the seat must be told
where it is. One more line in the brief block covers it, and it is already
there: the block names `ledger.jsonl` in the ledger section, and the desk's
standard brief can add the path it uses:

```bash
ssh -n thor-lan "~/lm-wt/general-contractor/target/release/gc checkpoint --ledger ~/lm-wt/general-contractor/ledger.jsonl --job $GC_JOB --crew-used-min 45"
```

A seat that reports from the Thor writes into the Thor's ledger directly,
which is the simpler case and needs no ssh.

## What the block gives the seat

The rendered contract states, in the seat's own terms:

- what was asked (the scope);
- the goal line — the acceptance command that must exit 0, or the metric
  that must cross its threshold;
- the job-time allowance (the T-minus) and the crew-time ceiling;
- the GC's estimate and the seat's own bid, with the confidence;
- the milestones;
- the stop rule: at 80% of the bid without the goal line, stop and report;
- the penalty for a late day, and the fact that an overrun becomes debt;
- how change orders work, and that the ledger is right if the block and the
  ledger disagree.

## Why the brief is rendered from the ledger and not written by hand

A hand-written brief drifts. The seat's brief is generated from the rows at
the moment it is launched, so the terms in front of the seat are the terms in
the ledger, and the ledger is the hash-chained record the GC and the seat
will be judged against. If they disagree, the block says so: *if this block
and the ledger disagree, the ledger is right.*
