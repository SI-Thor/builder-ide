# Prior art

What our own repositories already had, what `gc` takes from each, and what
each one is still missing.

All of these were cloned read-only on the Thor (`~/prior-art-readonly`,
`git clone --depth 1`) and read. Nothing was forked, vendored or modified.

**Not reachable**: `SuperInstance/AI-Writings` (the "TWO ECONOMIES OF
CORRECTNESS" essay) is not public and the Thor's `gh` token is invalid, so
this document says what the brief says it is and does not pretend to have
read it. There is no `builder-ide` repository under either owner, so
`docs/design/language-fit.md` in this repo is written from scratch and cites
the pattern by name only.

| repo | what it is |
|---|---|
| `SuperInstance/crab-cell` | a crab owes, a watcher checks, the ledger is where they meet |
| `SuperInstance/nursery-v2` | tokens, debts, recomputable lineage |
| `lucineer/cuda-contract` | agent contracts: SLA clauses, compliance, penalties |
| `lucineer/flux-market` | a market of agents, reputation and learning failure |
| `lucineer/cuda-budget` | allocation, spend, utilisation, priority |
| `SuperInstance/trust-ledger` | trust as a scalar recomputed from an append-only ledger |
| `SuperInstance/decision-ledger` | decisions, claims, calibration |
| `SuperInstance/ledger-continuity` | an agent dies, the ledger carries the work on |

---

## crab-cell

**Has.** A debt is a first-class object with a due date ("float plan"). The
routine does the work and the watcher decides whether it runs; the watcher
answers GO, NO-GO or ESCALATE. Every run appends a token to the ledger, and
the debt is fulfilled by an honest report before the due date. "Nothing runs
free."

**Taken.** The debt-as-an-object idea is the spine of `gc`'s debt model, with
credit: an overrun is an obligation the seat carries, and it is discharged by
a later underrun rather than forgiven. The watcher/routine split is the
GC/subcontractor split — the GC decides, the seat executes, and the ledger
holds both. The float plan is the deadline: a job with a deadline makes
silence meaningful, which is what `gc`'s checkpoints and the stop rule rely
on.

**Missing.** crab-cell has no money. It knows that a debt is owed and to
whom, but not what the work cost or what the general contractor should pay
for it. It has no bidding: the routine is assigned, not negotiated. It has no
reputation across debts, so a crab that fails repeatedly is treated exactly
like one that has never run. `gc` adds the two things crab-cell lacks — a
price and a record of who has been reliable.

## nursery-v2

**Has.** The token (a committed algorithm with a counterparty and declared
debts) as the thing that crosses between cells. "Audit by recomputation":
the record is not trusted, the score is replayed from the ledger. Trials
(repeatable experiments with a frozen input) and lineage (`replay.sh`).

**Taken.** *Audit by recomputation* is a rule of this codebase: no score is
stored, every number in `gc report` is recomputed from the rows. The
token's "counterparty" idea is what makes a bid a contract — a promise is
incomplete without the party that owes it, which is why every bid row names
its seat and every close row names the job it pays for. The trial idea is the
determinism test: the same commands with a frozen clock must write the same
bytes.

**Missing.** nursery-v2 has no economy: it breeds agents, it does not pay
them. There is no award, no cost, no deadline, no calendar. Its debts are
declared rather than incurred, so it never has to ask how much a failure
cost.

## cuda-contract

**Has.** A `Contract` between a provider and a consumer with SLA clauses
(`SlaClause`), a QoS tier, capability lists, an expiry, a compliance record
per measurement, and penalties per contract.

**Taken.** The shape of the contract: parties, clauses, a metric, a record
of what was measured, a penalty, an expiry. `gc`'s job is a contract with the
GC as the consumer and the seat as the provider; the close row is the
compliance record; `change-order` is how a contract is amended rather than
replaced.

**Missing.** cuda-contract checks each contract on its own. It has no
reputation carried across contracts, so the same provider can fail the same
clause repeatedly at no extra cost, and nothing tells the consumer which
provider to prefer. It has no mechanism for learning from a failure — no
retooling, no smaller job, no better brief.

## flux-market

**Has.** A market of agents with roles: market makers, greedy traders,
adaptive traders. It measures how much of the activity is structural waste,
and it has the uncomfortable finding that learning to trade makes the
adaptive traders worse, not better (its "Law 75"), because the coordination
law and the feedback loop fight each other.

**Taken.** The reputation idea and, more importantly, the learning-failure
idea: a seat's repeated failures should change what happens next, not just
its score. That is `gc`'s retooling — a seat in deep debt is not merely
scored down, it is changed before it is hired again, and the change is
recorded. The market framing is also why the award is a *market* decision
(cost, on-time record and fit) rather than a first-come rule.

**Missing.** flux-market is a simulator of a financial market. Its agents
have no jobs, no deadlines, no acceptance tests and no deliverables; a trade
that nobody wanted is indistinguishable from a trade that was wanted and
mishandled. Nothing in it knows whether the work was done.

## cuda-budget

**Has.** `Allocation` (allocated, spent, limit), `AgentBudget`, `spend`
returning Ok/Alert/Exhausted/OverLimit, `utilization`, `alert_threshold`,
`transfer` between agents, and a `forecast` that projects the spend from
elapsed time.

**Taken.** The budget shape — allocated versus spent versus limit, and
utilisation as the number to watch — is `gc`'s burn against bid. Its
`alert_threshold` is the direct ancestor of the stop rule: a threshold on
utilisation that raises a flag, with the flag being the thing that forces a
decision. The `forecast` from history is the ancestor of the calibrated bid.

**Missing.** cuda-budget has no quality dimension. Its spend is spent whether
or not anything was delivered, so it cannot tell a job that was finished
cheaply from one that was abandoned early. It has no debt between agents and
no way to make one agent's overrun another's problem.

## trust-ledger

**Has.** Trust as a number recomputed from an append-only ledger of decisions,
never stored as a config value; per-stake ceilings (how much the agent may
do alone); decay unless the agent keeps acting well; and a line-by-line
explanation a human can audit.

**Taken.** The recomputed-score discipline and the requirement that a score
be explainable: `gc report` prints the three rates the reputation is made of
(on time, goal line, in budget) rather than a bare number. The decay idea is
in the reputation as it stands — a seat's standing is the average of its
finished work, so a good seat that stops working loses its standing.

**Missing.** trust-ledger scores one agent's decisions; it has no notion of
a job, a price, a deadline or a second party. It can say "this agent may
close an issue alone" but not "this seat should be given this job at this
price".

## decision-ledger

**Has.** A ledger of decisions with the claim that was actually made (and a
script that rewrites the claim before it is recorded), a calibration note
with a real protocol — Platt scaling, ECE and Brier, fit on one half of the
corpus and evaluated on the other, with the n, the base rate and the joins
all written down.

**Taken.** The calibration discipline: a calibration number is worth nothing
without the protocol that produced it, the sample it was fit on and the one
it was evaluated on. `gc` follows the same habit — the factor's inputs, the
n, the shrinkage weight and the prior are all in `docs/model.md`, and the
report prints the raw run times behind every factor. The "rewrite the claim
before recording it" idea is why the seeded history records what the lane
was asked to do *and* marks the promise it never had.

**Missing.** decision-ledger fits one decision model to one corpus. There is
no economy, no deadline, no seat identity: the question "is this model
calibrated" has no counterpart here, only "is this seat reliable on this
class of work".

## ledger-continuity

**Has.** Three claim types (task, per-unit result, heartbeat) and one rule:
re-check before claiming, so a successor does not duplicate work. The
heartbeat is the non-obvious part — without liveness in the ledger a
successor cannot tell "dead" from "slow".

**Taken.** Two things. First, the self-contained claim: everything a
successor needs to finish the work lives in the ledger, not in the dead
agent's memory — which is why the acceptance test, the scope, the deadline
and the promise are all ledger fields, and why `gc brief` can be rendered
from the ledger alone. Second, liveness: `gc checkpoint` is the heartbeat of
a job. A job with no checkpoint is a job whose seat died, and the GC sees
exactly that.

**Missing.** ledger-continuity knows whether work happened, not what it cost
or whether it was any good. A recovered task can be a bad task.

---

## What is still missing, everywhere

None of these repositories has the whole thing, which is why `gc` exists
rather than being another crate in one of them:

1. **A price.** Every repo has obligations, budgets or trust. None has a
   market where a party states what the work will cost and another party
   chooses between competing statements.
2. **A deadline with consequences.** Deadlines exist (float plans, expiries,
   heartbeats) but nothing connects lateness to money.
3. **Learning that changes the next job.** trust-ledger decays a score,
   flux-market shows that learning can backfire, crab-cell escalates — but
   no repo records *what was changed* about a failing party and then applies
   that change to the next job.
4. **A machine-checkable goal line.** The acceptance test is the thing that
   makes a close a fact rather than an opinion. The decision-ledger has
   ground-truth labels for one model; nothing has an acceptance test per job.

`gc` is deliberately small and does not try to be a scheduler, a market
simulator or a trust framework. It is the missing piece that lets the other
pieces talk: a job, a price, a deadline, a promise, and the arithmetic of
what happens when a promise is kept or broken.
