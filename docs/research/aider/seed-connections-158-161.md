# Four new seeds — prior art and connections across the corpus

## Seed 158 — Two-sided pruning (low-res pass picks uncertain queries AND relevant memory)

- **Source file:** `lib-dsswarm2.md` (indeterminacy score I), `lib-dsswarm4.md` (budget table, speculation budget controller), `lib-syzygy.md` (`syzygy-forge/readerside3` digest channel).
- **Earlier idea:** The indeterminacy score I already combines rejection rate, canon sparsity, and trajectory entropy to decide *where* to spend compute. The digest channel already proved that a cheap computed summary can replace an expensive grid for region questions.
- **What it adds:** The earlier ideas prune *where* to look; this seed prunes *both sides* — the query side (which questions are worth asking at all) and the memory side (which retrieved context is worth attaching). The low-res pass is the cheap filter for both.
- **Combined experiment:** Run 100 bot queries against a 6-tile library. Low-res pass scores each query for uncertainty and each tile for relevance. Compare: (a) full-res on all queries, (b) low-res filter then full-res on the top 20%. Pass bar: ≥ 90% of the full-res answers preserved at ≤ 30% of the cost.

## Seed 159 — Props accepted by executing their action in MuJoCo, with measured priors

- **Source file:** `lib-si-repos2.md` (`constraint-physics` ZHC engine), `lib-si-repos.md` (`constraint-theory-core` Laman check), `lib-dsswarm4.md` (perceptual grammar classification).
- **Earlier idea:** `constraint-physics` already runs constraint satisfaction as physics — Laman check, H1 cycle detection, holonomy resolution — without an integrator. `constraint-theory-core` already checks whether a graph is rigid (determined) or floppy (under-specified).
- **What it adds:** The earlier ideas check whether a *world* is consistent; this seed checks whether a *prop* is usable by executing its affordance in a physics sim and recording the outcome as a prior. The prior is the measured success rate, not a hand-written rule.
- **Combined experiment:** Take 20 candidate props (a door, a lever, a crate). For each, run 50 MuJoCo trials of the bot's intended action. Record success rate as the prior. Pass bar: the prior predicts held-out success with ≥ 0.7 rank correlation, and the Laman check flags ≥ 80% of the props whose affordance is under-specified.

## Seed 160 — Anytime looped models (shared-weight loops, deep supervision, commit at deadline)

- **Source file:** `lib-fromgoogle4.md` (early-exit sub-network, hysteresis barrier), `lib-dsswarm1.md` (never-wait conductor), `lib-dsswarm4.md` (TTO cap).
- **Earlier idea:** The early-exit sub-network already commits at layer 12 if confident, else runs deeper. The never-wait conductor already commits at the deadline with a fallback. The TTO cap already bounds provisional commitment in time.
- **What it adds:** The earlier ideas commit at a *fixed* depth or a *fixed* deadline. This seed makes the depth itself the anytime variable: the same weights loop, each loop adds supervision, and the model commits whatever it has when the deadline fires. The loop count is the budget, not the layer index.
- **Combined experiment:** Take d1-2B, add a shared-weight loop with deep supervision at loops 1, 2, 4, 8. Run 200 decisions with a 40ms deadline. Pass bar: accuracy at loop 4 ≥ 95% of the full-depth accuracy, and the deadline is never missed.

## Seed 161 — Per-skill experience packages a coach updates

- **Source file:** `lib-dsswarm4.md` (trust ladder, annotation tetrad), `lib-dsswarm2.md` (WRM selector, stigmergic trace store), `lib-idea2.md` (strategy tiles).
- **Earlier idea:** The trust ladder already earns autonomy per agent. The WRM selector already ranks candidates against canon. The strategy tiles already swap policy mid-game. The annotation tetrad already records reversibility, grammar, branching, and TTO per commit.
- **What it adds:** The earlier ideas track *agent* trust and *tile* policy. This seed packages experience *per skill* — a bundle of (state, action, outcome, annotation) that a coach can update independently of the agent and the tile. The coach edits the package, not the model.
- **Combined experiment:** Take 3 skills (navigate, mine, place). For each, collect 100 experiences with the tetrad annotation. A coach (human or model) reviews and updates the package. Pass bar: the updated package improves the skill's success rate by ≥ 10 points on 50 held-out trials, with no regression on the other two skills.
