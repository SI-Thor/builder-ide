# Round 8, staged for the director: the two deliverables that live outside this repo

Round 8's items 1 and 2 (BRIEF.md, CONTINUE of 2026-10-31 22:15) are edits
to files outside this repository: the Infinigen sweep worker in
`~/src/infinigen-thor` and the seats' memory rule at `~/lm-wt/MEMORY-RULE.md`.
This round was run under the instruction to modify files only inside this
repository, so both are staged here, finished and tested, ready to be
applied verbatim. Nothing outside this repo has been touched — the
`thor-sweep-admit` branch in `~/src/infinigen-thor` is still where mcode
left it (created, no commits).

## 1. The sweep under thor-admit — `infinigen-thor-sweep-worker.patch`

What it does: wraps every scene step of `thor/sweep-worker.sh` in

```bash
thor-admit run --tier study --peak <auto|bootstrap> --label infinigen.<scene>.<stage> -- ...
```

so each stage is a study-tier lease with a **learned peak per biome and
task** (the label is `infinigen.<scene>.<stage>`). The daemon then admits
w5/w7/w8's stages only when the box has room, and live work pre-empts
them. `--peak auto` is tried first; until a label has three runs of
history the daemon refuses it, and an explicit bootstrap peak stands in
(`16G` coarse, `24G` fine and render — the worst the stages measured on
this box; overridable with `THOR_ADMIT_SWEEP_PEAK_{COARSE,FINE,RENDER}`
without editing the script). The refusal is told apart from a real stage
failure by its message, so a failing stage is never run twice. The
mkdir lock per scene-seed stays: it keeps two workers off the same scene;
the daemon is what keeps them off the same memory.

The fallback logic was smoke-tested on this box against a scratch daemon
(auto refused at 0 and 1 runs → bootstrap peak admitted; a stage that
fails is not retried), and the patch was verified with
`git apply --check` against the current `thor/sweep-worker.sh`.

To apply, on the Thor:

```bash
cd ~/src/infinigen-thor
git checkout thor-sweep-admit        # the branch mcode created for this
git apply ~/lm-wt/thor-admit/tools/thor-admit/round8/infinigen-thor-sweep-worker.patch
bash -n thor/sweep-worker.sh         # syntax check (already done here)
git add thor/sweep-worker.sh
git commit                           # full message; do not push
```

`sweep-worker.thor-admit.sh` is the same content as the patch's result, in
full, for reading without applying.

## 2. The seats' memory rule — `MEMORY-RULE.md`

The drop-in for the seats: `thor-admit run --tier live --peak 20G -- ...`
as the replacement for the bare `flock ~/lm-wt/heavy.lock`, keeping the
flock only for when the daemon (and its binary) is unavailable, plus the
Python shim's shape and the `thor-admit serve` rule against starting the
same model twice. To install:

```bash
cp ~/lm-wt/thor-admit/tools/thor-admit/round8/MEMORY-RULE.md ~/lm-wt/MEMORY-RULE.md
```

## What is deliberately not here

Item 5 — the one-hour measurement with the sweep under the daemon — is
held until the director says the MIG quiet window is over
(`~/lm-ops/QUIET-WINDOW.md`; it did not exist when this round started, so
the window is presumably still on). No GPU work was started in this round:
every test here allocates at most a few gibibytes of CPU memory, and the
load-robustness runs used bounded CPU spinners only.
