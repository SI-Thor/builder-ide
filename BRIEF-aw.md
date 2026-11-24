# Brief: integrate agent-world (`worlds/minecraft`) into builder-ide

You are working in the git worktree `/home/proart/lm-wt/fold-aw` (branch `fold-aw`) of the
builder-ide repo. `worlds/minecraft/` was just imported (with history) from the separate
agent-world repo: a Minecraft world (Paper server, four mineflayer builders, a reflex
decision seam, a gym, a viewer) that runs on the Jetson Thor. You are the lead: plan,
spawn subagents for independent pieces, review their output, integrate.

**The Thor is offline.** You cannot run the live world. Work only on code, tests and docs
that run on this laptop. Do not change `worlds/minecraft/ops/` behaviour (paths may be
updated, see below).

## Context (read first)
- `worlds/minecraft/README.md`, `worlds/minecraft/docs/agent-world.md`, `PLAY.md`.
- builder-ide: `CLAUDE.md`, `docs/design/three-minds.md` (agent-world's reflex/canon/mediator
  IS this design), `core/events.py`, `core/store.py`, `core/night/ledger.py`,
  `core/tiles/`, `core/vocab/`, `core/sim/` (the batched-sim interface), `core/why/`.

## Goal (in this order; stop and report if a step turns out to be a bad idea)
1. **One ledger.** agent-world keeps two ledgers (`reflex/agent_world_reflex/ledger.py`,
   `gym/agent_world_gym/ledger.py`). Make them write builder-ide events through `core/events`
   / the core store (an adapter is fine), so a builder-ide morning report and "Why?" can see
   Minecraft builder decisions. Keep reading old ledger files working (migration or reader).
2. **Skills are capabilities.** Map the skill library (`reflex/skills/`, ~65 JSON skills) onto
   builder-ide's `core/tiles` or `core/vocab` records (whichever genuinely fits — say which
   and why), so a skill and a capability are one record. A loader + tests is enough; do not
   rewrite the skills.
3. **Gym as a world type.** Assess whether `gym/agent_world_gym` fits `core/sim`'s interface.
   If it fits, add an adapter + tests. If it does not, write down precisely why in
   FOLD-REPORT.md and leave it as an adapter-free package. Either answer is acceptable.
4. **Paths.** Anything that hard-codes `~/lm-wt/agent-world` or the old repo layout should
   work from `worlds/minecraft/` inside builder-ide. List every change to `ops/` scripts.
5. Make `worlds/minecraft`'s Python and JS tests runnable from builder-ide (document the
   commands; wire Python tests into pytest if cheap).

## Constraints
- House style per CLAUDE.md. No fake numbers. Additive, reversible changes.
- Don't touch `tools/gc/`, `engines/`, or unrelated seats.

## Done check (paste evidence into FOLD-REPORT.md)
- Python: `/home/proart/projects/builder-ide/.venv-local/bin/python -m pytest -q -p no:cacheprovider --continue-on-collection-errors`
  from the worktree root: the set of FAILED/ERROR lines equals `.baseline-fails.txt`
  (laptop-environment failures; CUDA/mujoco/USD/mesh libs live only on the Thor). Zero new
  failures. New adapter tests pass. (Install extra pure-Python deps into that venv only if needed, and list them.)
- agent-world's own tests pass from their new location (Python; JS if node deps install offline-ish).
- Commit on branch `fold-aw` in small, described commits. Do not push. Do not merge.
- `FOLD-REPORT.md` at the worktree root: what changed, files touched, evidence, what must be
  verified on the Thor at cut-over (an exact checklist), open questions. End with
  `STATUS: DONE` or `STATUS: BLOCKED: <reason>`.
