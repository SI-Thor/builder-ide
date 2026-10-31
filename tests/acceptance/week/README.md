# The seven-night melt run — a simulated owner, as an executable week

Week 3 item 13 of `docs/plan.md`: *seven-night melt run (real or simulated
owner); capability rows; two-line estimates everywhere; standing exits in
every branch set; decision budget at the queue*. This directory plays
**seven evening → night → morning cycles** against a **simulated owner**
(`owner.py` — a fixed, seeded taste, stated as rules), reusing the M1
driver's seats (`../m1`) — **rewired to the integrated core** (branch
`m1-real`): the spine, the recipe store and the cold-start seat are the
merged `core.*` packages, the melt's whole ledger **is the spine's one
ledger** (`core.ports.SpineLedgerPort`; the three mirror bridges are
deleted), and the render rungs run **on the core's engine seam behind the
fake engine** (`core/engine`; M1's `seats/engine.py` holds the one
configuration line). The scripted critic and the stub engineer remain
stubs. Every step asserts its outcome and its budget and records what
served it, exactly as in M1; the run ends with the per-night table —
G §1.9's melt table, reproduced **from the ledger alone**.

## Run it

One venv for the repo:

```sh
.venv/bin/python -m pytest tests/acceptance/week -q   # as a test
.venv/bin/python tests/acceptance/week/meltweek.py    # headless; prints the tables
```

105 steps, seven cycles, one fresh `$BUILDER_HOME`. The step table and the
melt table land in `run/<timestamp>/steps.txt`.

## The week, in one table (from the last run)

```
NIGHT  EVE-QS  TASTE BETS SEALED AS         WORLD BET             STATUS        DEC  ATT
------------------------------------------------------------------------------------------
1           6  guess·0 obs + guess·0 obs    guess·0 obs → hit     ran short      10   16
2           6  guess·1 observation          low·1/1 hit → hit     ran degraded    3    9
3           2  low·2/2 kept                 guess·0 obs → hit     ran degraded    2    4
4           2  guess·1 observation          low·2/2 hit → miss    ran degraded    2    4
5           0  low·1/2 kept                 guess·0 obs → hit     ran degraded    2    2
6           0  guess·1 observation          guess·0 obs → hit     ran degraded    2    2
7           0  low·2/2 kept                 medium·2/3 hit → hit  ran degraded    2    2
```

`EVE-QS` is the evening's ask-mode questions; `DEC` the decisions that
morning asked of the owner; `ATT` the two added together — the attention
cost, falling 16 → 2. Night 1 is the deliberate stressor: three blocking
questions (the dam refuses the fourth), twelve candidate decision cards of
which the **queue admits five and cuts seven at the budget** — the morning
sits exactly at 10, never over it, and the report names where the cut
happened. Night 4 is the honest miss (the critic finds `wrong_scale`, the
bet scores miss, the owner keeps yesterday — the standing exit, taken as a
choice) and the mid-week fold check (a gate rebuilt from the ledger alone
agrees on every builder × code).

## The simulated owner (`owner.py`)

Five rules over one seeded table, no judgment, no randomness:

1. **The value table is the taste** — exactly one kept side of every pair
   the product can offer (the eight bank pairs and the night edits' value
   labels). Checked at boot: every bank question splits one keep / one
   reject.
2. **Ask answers pick the kept chip** — every answer writes a keep row on
   the question's reason code.
3. **The morning's branch choice follows the same table** — apply the
   night's branch when the table keeps its value; keep yesterday (the
   standing exit) when it does not.
4. **Unprompted verdicts name the night's scripted flaw** — the flaw
   classes are the four codes the question bank does *not* cover, so the
   owner's unprompted rows (unattributed — they count for **every**
   builder) melt a different track than the bank's questions (attributed —
   they melt only the Companion that asked). Two tracks, cleanly separable
   in the ledger; that is the per-builder proof.
5. **A sealed taste bet scores the way the artifact ruled** — keep → hit,
   reject → miss, no forgiveness.
6. *(stated here because it must be)* **Parked questions are answered with
   the first option** — their content is the builders'; only ask-mode chips
   and artifact values are taste.

The bets ride the **unprompted track**, because the bettor is the
prop-maker and the prop-maker's observations come from the owner's
unprompted rows: night 1 a guess at zero observations, night 2 a guess at
one (the true count in the basis), night 3 the first real claim at two —
G §1.9's own arc on one code (`too_busy`), the other flaw codes following
a night later. The bank codes melt the Companion, which is why the
*questions* fall 6 → 0 while the *bets* warm on their own schedule.

## The plan's item-13 checks, and where each is asserted

| check (plan §3 item 13 / G §7) | steps |
|---|---|
| the melt: ask→act flips per builder × reason code, exactly as cold-start specifies | `night/n{k}-bets` (the gate's decision restated independently and compared), `week/melt-table` |
| questions 6 → 0, visible in the ledger | `evening/n{k}-ask`, `week/melt-table` (== [6,6,2,2,0,0,0]) |
| `guess` → real claims per code as denominators pass two | `night/n{k}-bets` (seal policy), `week/melt-table` (no guess ever sealed at two; the `too_busy` arc; the never-fed code stays guess) |
| the melt is a fold — kill -9 safe | `night/n4-gate-rebuild` (a rebuilt gate agrees on every axis); `week/melt-table` (the spine's ledger carries it code for code) |
| capability rows present every morning; stop reading 0 | `evening/n{k}-slate`, `morning/n{k}-capability-and-estimates` (zeros on night one, non-zero from morning two) |
| two-line estimates everywhere | `evening/n{k}-work-order` (both halves on every confirm), `morning/n{k}-capability-and-estimates` (every order the morning reads; the landed order's estimate carries both halves) |
| `[e]` replaced by measurements | `evening/n{k}-slate` (marked asks), `morning/n{k}-report` ("the box" carries the night's measured verdict timings) |
| standing exits in every branch set | `morning/n{k}-branches` (both surfaces, all seven mornings) + `week/melt-table` |
| decision budget at the queue, never exceeded | `night/n1-queue-dam` (dam + admission + cut, named), `morning/n{k}-attention` (≤ 10 every morning; night 1 exactly 10), `week/melt-table` |
| attention cost falls across the week | `morning/n{k}-attention` (per-cycle counts), `week/melt-table` (16 > 9 > 4 ≥ 4 ≥ 2 ≥ 2 ≥ 2) |
| the status line computed, one of the four | `night/n{k}-stop` (ran short on the cut night; ran degraded elsewhere — the scripted critic is degraded by construction, RV patch 15) |
| evening seven's earned line | `evening/n7-open` (a claim that renders with its denominator, uncertainty leading — the [now] shape of spine moment 2) |

## The seats, and what is real

Same map as M1 (see `../m1/README.md`), with the week's own persistence now
free: **one ledger** — the week's ask-mode sittings, the melt's gate, its
seal policy and its scored bets all read and write the spine's one SQLite
log (`core.ports.SpineLedgerPort` through the door), so the melt survives
sittings, kills and reboots by construction (the `night/n4-gate-rebuild`
check rebuilds the gate from that log). The mirrors this directory used to
carry — taste rows, policy-sealed bets, verdicts mirrored back, the
apply-scores-taste bridge — are deleted; what they were papering over is
fixed in the core (see `tests/test_integration_melt_ledger.py`).

**One bridge remains** (`bridge:queue-half`): the decision-budget admission
(G §4.3 / spec §3.2.8-7) — the spine owns the blocking dam, but the queue
service that would enforce the morning's budget of 10 AT the queue does not
exist yet; `weekseat.admit_ask_cards` performs it, cutting and naming.
Stubs, as the plan expects (M1 risks): the scripted critic
(`verdict@scripted` on its face) and the stub engineer — the same two
remaining pieces as M1, each with its missing piece named in
`../m1/README.md`. The render rungs and the gate's engine half are no
longer stubs: they run on the core's engine seam (`core/engine`) behind
the **fake engine** (`fake:engine` in the step table) — the real seam, a
fake engine, one configuration line from a real one.

## Honest notes (what this run is and is not)

* **The latencies are in-process microseconds**, kept as the regression
  gate for the day real services stand behind the same interfaces.
* **There is one ledger** — the melt table below was folded from the
  spine's own log, and it reproduces the stand-in run's numbers exactly
  (the melt is a mechanism; the store it folds changed underneath it).
* **Two README findings of the stand-in run, fixed in the core** (branch
  `m1-real`, with tests):
  1. *the three-number line counted decisions cumulatively* — it now
     scopes to the night (decisions since its `night.started`, and G §4.3's
     full decision list); morning seven reads its own morning, not the
     week's 15.
  2. *a promotion reset the word's capability counter* — `vocab.word.added`
     keeps the calls the word already earned; morning one now asserts
     `built 1` through the keep where it used to name the drift.
  3. *(still open, unchanged)* the dam's one-liner is not in the report:
     the parked task carries "would have needed a 4th blocking answer" in
     its audited `last_reason`, but the report renders no parked-task line
     (spec §3.2.6 says it says so "in one line"). The cut tasks are named;
     the parked one is not.
  4. *Every night reads "ran degraded" — honestly.* Until a critic model is
     chosen and calibrated (week 3 item 18), every verdict is a scripted
     check and the degraded flag rides it (RV patch 15). Night one reads
     "ran short" because its queue cuts win the precedence — also correct.
* **What the one-store run exposed beyond the two findings** (all fixed in
  the core, all with tests): the spine's apply fast-forwarded the night
  branch instead of the world (main), so this driver moved main by hand —
  and that hand-move read as an 11th owner decision on a morning budgeted
  for 10; apply now moves the world and scores the night's taste bets
  inside the one transaction (§1.2, §1.7).
* **The spine's night ids carry the real run date** (2026-10-31…) while the
  branch names carry the fictional week (2026-10-24…, G §0's continuity
  note). Ids are opaque; the dates that matter to the script are the
  branch names'.
* **The simulated owner is not a model.** It is five rules over a table —
  the point of item 13 is the *melt*, and the melt's input had to be
  exactly reproducible. The evening-seven "corrected return line" is
  therefore asserted in its [now] shape (a claim that renders with its
  denominator, uncertainty leading); the content-level jetty-and-stairs
  sentence of G §1.9 is M2's to earn against a real owner.

## Layout

```
owner.py         the simulated owner: the seeded taste table and its five rules
script.py        the seven nights as scripted facts (edits, bets, flaws, WOs, the
                 twelve ask cards, the expected question counts)
weekseat.py      the week's adapters: the melt over the ONE ledger, the queue's
                 decision-budget admission, the per-morning decision count
meltweek.py      the driver: boot → seven cycles → the melt table; `main()` headless
conftest.py      sys.path to m1 (its seats) + a fresh $BUILDER_HOME per run
test_week_session.py   the pytest wrapper (plays the week; re-derives the checks)
run/             scratch, gitignored
```
