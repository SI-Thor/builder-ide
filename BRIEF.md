# general-contractor (read ~/lm-wt/DOC-RULES.md first). A new standalone repo; this dir is its root.

## Casey's idea, verbatim (2026-11-02) — the spec's source of truth
"you, in this TUI is my general-contractor. and you subcontract work. when you a general-contractor makes a deal with a
subcontractor, they don't write a blank check and ask the subcontractor to let them know when the job is done. The
general-contractor instead plans out the greater-project as a sequence of subcontracts. And they are thinking
holistically about their budget- both time and money. So the subcontractor doesn't just aimlessly get to work. the
subcontractor sees the job by the general-contractor and makes a bid on it. They tell the general-contractor, for
example, how much they charge per square foot of carpet and how many days it will take. the subcontractor then makes
his money by knowing his crew's speed at the job and having enough experience to understand the typical rate at which
they lay their carpet. Some jobs get underbid and the subcontractor doesn't make any money himself because he has to
hire more crew to get the job done in the time window he bid on. or the subcontract has to take a penalty for the days
behind he is on the job- either way. these problems impact the viability of the business of the subcontractor. So the
subcontractor's work is to learn from the jobs he failed to make money on: he needs to retools his crew, train his crew
better, learn how to calibrate his bids better, And remember that overbidding is better than underbidding since the
reputation of successfully getting the job done on time is paramount to getting hired again. And getting the job done
within his allowance of crew-time is paramount for his business to succeed financially. in this analogy. crew-time is
token-use, and job-time is the t-minus kicking-it-over-the-goal-line so you can close the job complete."

## Prior art in our own repos — read first, reuse with credit (gh repo clone, read-only)
SuperInstance/crab-cell ("a crab is something that owes, a watcher is something that checks, and the ledger is where
they meet"), SuperInstance/nursery-v2 (tokens, debts, recomputable lineage), lucineer/cuda-contract (agent contracts,
SLA), lucineer/flux-market (reputation), lucineer/cuda-budget (token allocation), SuperInstance/trust-ledger,
decision-ledger, ledger-continuity, and SuperInstance/AI-Writings "THE-TWO-ECONOMIES-OF-CORRECTNESS". Write
docs/prior-art.md: what each already has, what we take, what is missing.

## The model (refine it; keep Casey's words as the names)
- **Job** (written by the GC): scope; a machine-checkable **acceptance test** (the goal line: a command that exits 0,
  or a named metric crossing a threshold); a **deadline** (job-time, T-minus); a **budget ceiling** (crew-time);
  the job class (e.g. lab-experiment, merge-fix, research-read, build-feature, long-run-babysit).
- **Bid** (by a subcontractor = a seat type + model, e.g. zcode, mcode, pi:MiMo): crew-time estimate, job-time
  estimate, confidence, plan of milestones; computed from the sub's **track record** for that job class (bid at a high
  quantile of its past actual/estimate ratios: overbidding beats underbidding).
- **Award**: the GC picks by expected cost, on-time probability (reputation) and fit; one ledger event.
- **Execution**: milestones with checkpoints; at each, burn vs bid (earned value). At 80% of bid crew-time without the
  acceptance test passing, the sub must stop and report (no open-ended runs). The GC can re-scope, extend (a change
  order, recorded), or cancel.
- **Close**: acceptance test passes -> job closed. Actuals recorded: crew-time, job-time, change orders, penalties
  (late days), overrun.
- **Debt and reputation**: an overrun is debt the sub carries (crab-cell); underruns repay it; on-time rate is
  reputation. A sub in deep debt on a job class gets **retooled** (different model, better brief template, a tool, a
  smaller job size) before it is hired for that class again; the retooling is a ledger event with its reason.
- **Crew-time measurement** (be honest about precision): pi seats report tokens; zcode/mcode are flat plans with 5-hour
  usage windows: measure crew-time as active wall time x the plan's window share, plus message/turn counts from their
  output; say which is measured and which is estimated.

## Build (v1)
- Rust, std only (docs/design/language-fit.md in builder-ide): one binary `gc` with an append-only JSONL ledger
  (`ledger.jsonl`, every row hash-chained) and subcommands: `job new`, `bid` (computes a bid from track record; a sub
  can also submit one), `award`, `checkpoint`, `close`, `change-order`, `report` (per sub, per class: bids vs actuals,
  calibration curve, debt, on-time rate), `brief` (renders the contract terms as a block a seat's BRIEF.md includes).
- Seed the track record from REAL history: the director's lanes of 2026-11-01..02 (the .out files in
  /home/proart/lm-ops/wt on the ProArt via `ssh proart`? no: you run on the ProArt desk; read
  /home/proart/lm-ops/wt/*.out, /home/proart/lm-ops/zqueue.txt, board-history, and the Thor's ~/lm-wt/*/NOTES.md for
  start/end times, quota stops, relaunches, and outcomes). Reconstruct each lane as a job with what was asked, what it
  took (wall time, relaunches) and whether it crossed its goal line. Label everything reconstructed as such.
- Integration: a `gc brief <job>` block that ~/lm-ops/desk.sh can append to a seat's brief (propose the 3-line change to
  desk.sh in docs/integration.md; do NOT edit desk.sh yourself).
- Tests: ledger hash chain, bid calibration math, close/penalty/debt arithmetic, determinism.
- README.md in Casey's terms (the carpet example), docs/model.md, docs/prior-art.md, NOTES.md as you go.
Token thrift; commit locally (main); there is no remote yet; never push.

## ADDENDUM (Casey, 2026-11-02, verbatim): "agents who finish jobs then have evidence for themselves to understand how long their work takes for the next jobs. and the subcontractors learn to specialize based on their abilities to estimate work-time which has to come from experience working with their developer and their tools"
So: (1) every closed job writes the sub its own evidence record (estimate vs actual, per job class, with the developer and tools it worked with), and its next bid reads that record first; (2) specialization is measured, not declared: per sub, per job class, track calibration error (|actual/estimate - 1|) and on-time rate; a sub specializes where its estimates are reliable, and the GC routes classes to the subs that estimate them best; (3) the evidence is keyed by (sub, developer/GC, toolset), because estimating skill comes from experience with a particular developer and toolchain and does not transfer for free.

## ADDENDUM 2 (Casey, 2026-11-02): the design goal
Casey: the carpet story is an ANALOGY to seed the project; in code it looks different. Do not stick strictly to the older repos either: a scout lane (scout-gc) is mining them for ideas into docs/prior-art.md; take what is good.
The goal, in his words: "the ideal for this system is that there's a lot of buzz about this project as a way to make multi-agent construction more effective and efficient. but it's so good that it embeds itself into just-how-systems-should-function and the concept fades into workflow management and people forget about the source. the best tools are the ones you forget you're holding because you're thinking about what you are creating with them. like a pencil or wall-socket."
So design for disappearing: (1) tiny core, plain formats (a JSONL ledger and a few verbs) any agent CLI or script can call; (2) modular: each piece is useful alone (the acceptance-test gate alone, the bid calibrator alone, the evidence record alone) and adoptable one at a time; (3) zero lock-in: no daemon required, no account, no framework, works with Claude Code, zcode, mcode, pi, aider or a shell script; (4) the default path is the obvious one: a job without an acceptance test and a deadline is the thing that feels wrong; (5) the README shows a developer the effect in 5 minutes on their own repo. The docs stay plain (DOC-RULES: no hype words); the effect should speak.
