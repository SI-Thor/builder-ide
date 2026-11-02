# A general batched simulator for our rule systems (C++/CUDA, with Python bindings)

Casey's question (2026-11-01): *"think how this could be general purpose on our gpus
for our work"* — asked about [AtaraxosAI/stratego](../research/stratego.md). This
doc is the answer for **our** rule systems, not for Stratego.

It has three parts: the interface (§1), where the belief model and the search fit
(§2, §3), and the three first builds, ranked (§5).

---

## 0. What we take from Stratego, and what we leave

Stratego's environment is the part worth copying, and it is three mechanisms:

1. **A game's whole state is a fixed-size POD struct.** `Piece` is exactly 16
   bytes (`src/env/stratego_board.h:80`), `DeathStatus` exactly 2. A batch of
   4096 games is one contiguous allocation; a kernel reaches game *i* by
   pointer arithmetic. No per-game object, no dispatch, no virtual call in the
   step path.
2. **The legal-move mask is computed by the rules engine**, not by the network:
   `LegalActionsMaskKernel` (`src/env/cuda/action_kernels.cu:5`) runs one thread
   per (game, square) and writes a fixed-size bool mask, `(num_envs, 1800)`.
3. **One kernel per rule, one thread per game for the step.** `ApplyActionsKernel`
   (`src/env/cuda/action_kernels.cu:107`) gives one thread the whole move for
   its game; the 100× more parallel mask kernel is a separate launch.

We **do not** take: the 355 Stratego observation planes (the *method* transfers,
the planes do not), the action encoding (a consequence of Stratego's rules), the
self-play RL stack (our objectives are different), or the assumption that the
interesting state lives on a 10×10 grid.

What we add, and Stratego does not have: our rule systems have **no simulation
today**. The drift detector folds a ledger and applies thresholds; the critic
measures a mesh; the permission ladder checks a recipe. Each is analytic. There
is no "what happens next" to sample. That is the gap this doc closes, and it is
also what makes the belief model worth having: **without a simulator to roll
out in, a posterior over hidden state has nothing to act on.**

---

## 1. The interface

### 1.1 The shape our three rule systems share

| system | one "world" | one step | hidden state |
|---|---|---|---|
| **d1 decision game** (`tools/d1dec/`) | one character's turn inside a shared world | the d1 model answers a 3-question pack over a ~150-token state | every other character's private context and plan |
| **drift / permission checks** (`core/drift/`) | one agent's slice of the world ledger | advance one window: fold the ledger deltas, update the six signals, run the gates, emit the alarm | what happened in the gap between two windows; whether the agent is stuck or waiting |
| **Crafter-like tasks** (`docs/lab/crafter-lab/`) | one agent's inventory + world slice | one tick of the task rules | the parts of the world the agent has not seen |

Common: many independent copies of a small state; a step that is cheap per copy
and expensive in aggregate; a legal-action set the policy needs; and hidden
state in all three.

### 1.2 The C++ side: `core/sim/`

One generic batch container, one kernel contract, one binding surface, and one
directory per rule system.

```
core/sim/
  state.h          # template <class State> struct Batch — the container
  kernels.h        # the kernel contract every rule system implements
  bindings.cc      # the pybind11 module "pysim"
  systems/
    drift/         # state.h, kernels.cu, planes.json, python.cpp
    d1dec/
    crafter/
```

**`state.h` — the container.** Deliberately shaped after Stratego's
`StrategoRolloutBuffer` (`src/env/stratego.h:66`), because that shape is the
one that works:

```cpp
template <class State>
struct Batch {
    // The batch is one contiguous array of fixed-size states, rows of time.
    State*      d_states;          // num_envs * rows
    int32_t*    d_terminated;      // num_envs * rows
    float*      d_reward;          // num_envs * rows
    bool*       d_legal_mask;      // num_envs * rows * A
    float*      d_obs;             // num_envs * rows * obs_len  (the planes)
    uint32_t    num_envs, rows, A;

    void reset();
    uint64_t apply_actions(const torch::Tensor& actions);
};
```

Rules that come from the port and are not negotiable:

- **Fixed-size state, no per-world allocation.** `sizeof(State)` is known at
  compile time; the batch is `rows × num_envs` states, row-major, the row
  stride is `num_envs` (Stratego: `src/env/stratego.cu:735-737`).
- **Point of view is the caller's problem.** Stratego writes every plane from
  the acting player's POV and mirrors blue (`src/env/cuda/action_kernels.cu:38-41`).
  We keep the same convention, because the observation plane list then does not
  depend on who is acting.
- **The mask is `num_envs × A` bools and is written by the rules engine.** `A`
  is fixed per rule system (Stratego: 1800). The policy gathers on it; it never
  re-derives legality.
- **Tensor lifetime is short and documented.** Stratego's Python wrapper clones
  every tensor it returns (`pyengine/core/env.py:37`), because the backend
  reuses the buffers. We copy that rule verbatim, including the comment.

**`kernels.h` — the contract.** Each rule system supplies five launches:

| kernel | parallelism | what it does |
|---|---|---|
| `ResetKernel` | one thread per world | write the initial state from a seed or from a supplied state table |
| `StepKernel` | one thread per world | advance one world by one ply, in place |
| `MaskKernel` | one thread per (world, cell) or per (world, action) | write the legal-action mask |
| `ObsKernel` | one thread per (world, plane, cell) | write the observation planes |
| `TerminateKernel` | one thread per world | decide termination and the reward |

`ObsKernel` is separate from `StepKernel` on purpose: the policy wants planes,
the rules want state, and the two have different natural parallelisms
(Stratego does the same — the infostate kernels are nine separate launches,
`src/env/cuda/infostate_kernels.cu`).

**`bindings.cc` — one module.** `pysim` exposes:

```python
batch = pysim.make_batch("drift", num_envs=4096, rows=200, device=0, params=...)
batch.apply_actions(actions)        # actions: int32 CUDA tensor (num_envs,)
batch.legal_action_mask()            # bool (num_envs, A)
batch.obs()                          # float32 (num_envs, C, H, W)
batch.reward()                       # float32 (num_envs,)
batch.reset(seed_table=None)        # reset from the seed table, or from a supplied state batch
```

The Python side (`core/sim/__init__.py`) wraps this per rule system and
returns **torch tensors that drop straight into the code we already have**:
the drift detector's numpy windows become torch tensors, the critic's arrays
become torch tensors, the d1 server's batch becomes torch tensors. The point of
the binding is that nothing upstream has to change shape.

### 1.3 The plane manifest: the one contract that matters

Stratego's observation planes are the interface between the rules and the
network: 355 of them, named, documented in `src/env/stratego.h:38-65` and
generated by name in `src/env/boardstate_channels.h`. The network reads the
*names*; the C++ writes the *data*. Adding a rule adds a plane, and nothing
else changes.

We do the same, with a manifest that both sides read:

```
core/sim/systems/drift/planes.json
{
  "version": 1,
  "planes": [
    {"name": "stall_rate",      "shape": [1],      "dtype": "float32", "rule": "signals.stall"},
    {"name": "success_rate",    "shape": [1],      "dtype": "float32", "rule": "signals.success"},
    {"name": "error_burst",     "shape": [8],      "dtype": "float32", "rule": "signals.errors"},
    {"name": "gate_band",       "shape": [2],      "dtype": "float32", "rule": "gate.band"},
    {"name": "paused",          "shape": [3],      "dtype": "float32", "rule": "detect.pause_ladder"}
  ],
  "actions": ["none", "pause_self", "pause_world", "hard_stop"]
}
```

The C++ writes the planes in manifest order; the Python reads the manifest to
build the network's input spec and to name the outputs. **A rule change that
does not change the manifest does not change the network.** A rule change that
does change the manifest bumps `version`, and the training data records the
version, so old data is never silently reinterpreted.

### 1.4 What this buys, concretely

The drift detector today walks windows in Python, one agent at a time. The
ledger has ~29 agents and 5-minute windows; the detector's own lab note
measures its runtime per window. In a batch, the same work is one kernel launch
per window over 4096 agents at once. The win is wall-clock, and wall-clock is
what decides whether the drift detector can run on the tick path at all.

---

## 2. Where the belief model helps

### 2.1 The general statement

Stratego's belief model predicts the types of the opponent's hidden pieces.
It pays for itself because the **search** needs plausible worlds: the belief
samples are the search's branching factor (`pyengine/core/search.py:281-330`),
and a better posterior means the Q estimates are less biased.

That structure transfers exactly when there is (i) hidden state, (ii) a
decision to make, and (iii) a simulator to roll out in. We have all three
now — which is the argument for building the simulator first.

### 2.2 The drift detector: stuck vs waiting

This is the sharpest case, and it is a gap we already know about. The six
signals of §3.4 fire on **rates**; a rate fall has two very different causes:

- the agent is **stuck** — looping, blocked, broken, needs intervention;
- the agent is **waiting** — correctly blocked on a dependency, idling by
  design, needs silence.

Today the detector cannot tell them apart: it reports a rate. The **belief
model** is the natural fit, and the reason to prefer a posterior over a
classifier is the decision. The action is to *wait*, and waiting has an
opportunity cost, so the decision rule is

> intervene when `P(stuck | stream) > λ · P(waiting | stream)`

A classifier returns one label and throws the uncertainty away. A posterior
returns both, and the threshold λ is a policy knob rather than a baked-in
constant.

The latent variable is small and the stream is small: per agent, the observable
stream is the ledger deltas (successes, errors, stalls, tool calls, messages)
plus the screen-watcher deltas when the seat is being watched. A small
sequence model over a 64-window history is ~1 ms on the Thor — affordable at
1 Hz, which is the drift detector's own cadence.

**Training labels we already have.** The director's interventions are labelled
help points (`docs/design/screen-watcher.md`), and the seat's own logs
distinguish "exited with an error" (stuck) from "exited 0 after an hour"
(done). The belief model's training set is the seat-watcher's dataset.

### 2.3 The screen watcher: stuck vs waiting

Same latent variable, different sensor. The screen watcher reads a **change
stream**, not frames (`docs/design/screen-watcher.md`): rates of change, events
with Δt. Its question is StreamVibe's — *stay silent or speak?* — and the
hidden state is the same pair:

- the **user** is thinking (silence is right);
- the **seat** is hung (speaking is right).

The belief model over the change stream answers "which of the two is it?"; the
threshold is set by the cost of a false interruption (annoying, breaks flow)
against a missed stall (an hour lost). The seat-watcher's existing measurement
— a rate gate against a level gate on help-point precision/recall and FPR
(`docs/lab/exp-drift-detector.md`) — is the right test bed: replace the gate
with a posterior threshold and measure the same numbers.

### 2.4 The d1 decision game: other characters' intents

Each character in a tick asks 3 questions over a shared ~150-token state
(`tools/d1dec/README.md`). The hidden state is what the *other* characters
know and intend. A belief over their intents lets the simulator predict the
tick's outcome distribution — the same "sample plausible worlds, roll out"
shape, with the character instead of the game as the unit.

---

## 3. Sampled-belief search as the vibecode pre-flight

### 3.1 What the pre-flight is today

`docs/design/vibecode-in-world.md` §1.2: three checks, on a fork.

| check | what it is | cost |
|---|---|---|
| the validator (`core/recipe/constraints.py`) | scripted, analytic, deterministic, no model | milliseconds |
| the critic (`core/critic/`) | measured, hybrid, published calibration table | 696 ms per verdict |
| the resource lease (`tools/thor-admit`) | the edit must be booked to a tier with a peak | a booking |

All three check the **proposal**. None of them asks what happens *after* the
edit lands.

### 3.2 The missing check

The world keeps moving while the check runs — that is exactly why the pre-flight
must run on a fork (§1.3). So the honest question is not "is this edit
well-formed?" but:

> **if this edit lands, what happens?**

and that question is full of hidden state:

- the other agents' intents (unknown, and the main thing),
- the world's state at the moment of landing (the world moved during the check),
- the resources available at that moment (the lease is a *live* quantity).

A **sampled-belief search** answers it the way Stratego's search does:

1. **Sample the hidden world.** The belief model draws *N* plausible states of
   the world-at-landing: the other agents' intents, the ledger's next windows,
   the branch's likely neighbours.
2. **Roll out.** The batched simulator plays each sampled world forward: the
   drift signals update, the permission checks run, the tasks progress, the
   critic's verdicts land.
3. **Score.** Each candidate action (the edit, or a variant of it) gets the
   average value over the N sampled worlds — and the *tail*, not just the mean.
4. **Decide.** If the tail is bad, the edit does not land, and the sample that
   caused it is what the human reads on return.

### 3.3 Where it sits in the existing ladder

It is a **third tier of pre-flight**, after the validator and the critic:

- it runs on the fork, never on `main` (§1.3);
- it is charged to a lease — the `practice` tier, whose own description already
  names "replaying proposed changes" as practice work (§3.3);
- its output is a **distribution**, not a verdict. The validator and the critic
  keep the verdicts; the search produces the expectation and the tail, which is
  what the human reads when they come back. A P1 agent still cannot commit
  (§1.4) — the search gives it a better report, not a new rung.

### 3.4 The honest cost

The search needs a simulator to roll out in. Our rule systems are analytic
checks over a ledger; there is nothing to roll out. **That is why §1 comes
first.** Without the simulator, a "sampled-belief pre-flight" would be a
classifier with extra steps.

And the search multiplies the simulator's cost by N. On a box whose GPU *is*
its memory, and whose CPU is also doing the world's work, N is a lease-sized
decision, not a constant.

---

## 4. The arrangement model as a learned world/room seeder

### 4.1 The mapping

| Stratego | ours |
|---|---|
| the arrangement: 40 pieces in a 4×10 area | the **room/world seed**: layout, task parameters, tool set, starting conditions |
| trained by the reward of the games it produced | trained by the **critic's verdict** on the worlds it produced |
| the mask: remaining piece counts | the mask: the recipe's own constraints (the same five analytic kinds) |
| symmetry breaking: forced right-handedness | symmetry breaking: the room's own convention (door on the north side) |
| the value head predicts the game's outcome | the value head predicts the **critic's score** for that world |
| the arrangement becomes the env's reset distribution | the seed becomes the simulator's **world distribution** |

### 4.2 The anti-GAN part, stated properly

A generator trained to produce worlds that *score well* finds the critic's
blind spot. That is the classic failure: the generator exploits the judge.

Two anchors, and we already own both:

1. **The critic's verdicts** are the training signal. The critic is calibrated
   and published (`core/critic/CALIBRATION.md`: the hybrid critic, 24 TP / 0 FP
   / 0 FN on the 30-member reference set, 696 ms per verdict). The generator
   proposes; the critic judges; the pair is trained against each other, so the
   generator can only improve against the critic it is measured against.
2. **The human's verdicts are held out.** Casey's accept/reject of a room, and
   the director's interventions, are never in the generator's loss. They are the
   test set. This is the same relationship the seat-watcher has with the
   director's help points: our own labelled data, already collected.

**The metric that matters is therefore not the critic's precision on the
reference set — that is published and known — but the *pair's* precision on the
human's held-out verdicts.** A seeded world the critic likes and the human
rejects is a false positive *of the pair*, and it is counted as such.

Two more properties we should copy from Stratego:

- **the arrangement model's value head predicts the critic's score**, so the
  generator knows which of its own worlds are good without a second critic call;
- **the entropy head**: Stratego's arrangement model predicts the *future
  accumulated entropy* of the game its arrangement creates
  (`pyengine/networks/arrangement_transformer.py:93`). Ours should predict the
  expected variety of the world it seeds — otherwise the generator collapses
  onto one good room and stops covering the space.

### 4.3 The symmetry trick

Stratego forces the flag to the right half and flips half the samples
left-right at random, because equilibrium policies are L-R symmetric
(`pyengine/networks/arrangement_transformer.py:127`,
`pyengine/arrangement/sampling.py:88`). Ours has the same shape: rooms have
mirror symmetries (the door on the north side, the light source, the layout
grid). Fixing one convention and randomising the flip halves the sample cost
of the same coverage.

### 4.4 Where the seeded world is used

The seed becomes the simulator's world distribution: the drift windows, the
permission checks and the tasks all run against seeded worlds, so the training
and evaluation data covers a *space* of worlds rather than one world repeated.
That is the difference between a detector that works in one world and a
detector that works.

---

## 5. The three first builds, ranked

Ranked by: (a) does it unblock something we already want, (b) is the hidden
state real, (c) is the measurement cheap.

### Build 1 — the drift simulator (`core/sim/systems/drift/`)

**What.** A batched CUDA simulator of the drift/permission rule system. One
world = one agent's ledger slice. One step = one window: fold the ledger
deltas, update the six signals, run the rate gate with hysteresis, emit the
alarm, apply the pause ladder.

**Why first.** It has the best combination of properties:

- a **real hidden state** — what happened in the gap between windows, and
  whether the agent is stuck or waiting;
- an **existing reference implementation** (`core/drift/`, 46 tests) and an
  existing labelled dataset (`docs/lab/drift-dataset/`), so the CUDA port can be
  checked **bit-for-bit** against the Python one — the gate on the port is
  agreement, not a new benchmark;
- a **caller that wants it today**: the detector is on the world's path, and
  the seat-watcher would sit on top of it.

**The belief model hooks in here.** The gap between windows is exactly the
hidden state, and P(stuck) vs P(waiting) is exactly the threshold the gate
needs. Build 1 is where the belief model becomes worth training.

**The hard part is not the kernel.** It is matching the Python semantics
exactly: the hysteresis band and dwell (`core/hysteresis/`), the one-sided rate
gate, and `reset_pending()` — the door that drops a pending transition across a
window with no reading. A port that differs by one window in one edge case is
wrong in a way nobody will notice. The bit-for-bit check is the gate.

**Measure.** (i) bit-for-bit agreement with `core/drift` on the world's ledger
over the whole dataset; (ii) env steps/s at 128 / 1024 / 4096 worlds; (iii)
later: the belief model's KL to the uniform reference and the gate's
precision/recall/FPR against the director's help points, using the seat-watcher's
own metrics.

### Build 2 — the pre-flight simulator (`core/sim/systems/preflight/`)

**What.** The vibecode pre-flight as a simulator. One world = a branch + a
proposed edit + the agents' intents. One step = one tick of the world after
the edit lands: the drift signals update, the permission checks run, the tasks
progress. The search samples beliefs about the intents and scores candidate
edits over them.

**Why second.** It is the consumer that makes builds 1 and 3 worth having —
but it needs the **seeder** (build 3) to have a *distribution* of worlds to
roll out in, and it needs the belief model to have something to sample.
Building it before the seeder means rolling out in one world, which is exactly
the trap of §4.2: a search that only ever sees the world it was built in will
report a confident, wrong tail.

**The belief model hooks in here**: P(other agents' intents) is the sampled
belief, and the search over N sampled worlds is the "what happens" check.

**The hard part is the cost.** N sampled worlds × the simulator's cost, on a
box that is also running the world. N is a lease-sized decision. The measure
that settles it is calibration, not speed: *does the pre-flight's predicted
distribution match what the ledger later says happened?* A pre-flight whose
distribution is well calibrated but wide is useful; one that is narrow and
wrong is worse than no pre-flight at all, because it manufactures confidence.

**Measure.** The predicted-vs-actual calibration of the tail on the world's
ledger; the number of edits the search would have blocked that actually caused
harm, and the number it would have blocked that were fine (the pair's
precision/recall).

### Build 3 — the room seeder (`core/sim/systems/seed/`)

**What.** The arrangement model, transplanted: an autoregressive generator over
a room/world seed (layout, task parameters, tool set), trained against the
critic's verdicts, with the human's verdicts held out, with the symmetry
convention and the entropy head from §4.

**Why third.** It is the component that makes the other two *general* rather
than one-off. It is also the one whose failure mode is silent: a generator that
exploits the critic produces worlds that score well and are wrong. So it goes
last, and it goes with the pair-precision metric from the start, and with the
entropy head so that a collapse onto one good room is visible.

**The hard part is the adversarial one**, and it is not a coding problem: the
generator and the critic are trained together, and the only external judge is
a human with a small number of labels. The defence is the held-out human
verdict and the pair-precision metric.

**Measure.** The pair's precision on the human's held-out verdicts (not the
critic's precision on the reference set); the seed diversity — the entropy of
the generator's seeds against the entropy of the seeds a human writes; and the
fraction of generated worlds that the critic passes *and* the human accepts.

---

## 6. Risks, and what is not verified

- **The batched simulator buys wall-clock, not correctness.** The Python
  implementations stay as the reference; the CUDA ones are checked against
  them, bit-for-bit, before anything depends on them.
- **The semantics are subtle.** The hysteresis band, the one-sided rate gate
  and `reset_pending()` are three doors to get wrong, and a wrong door is
  silent. The bit-for-bit check is the gate, not a nice-to-have.
- **The belief models are the risky part.** A posterior trained on our own
  labels learns our labelling habits, including the habits we have not
  noticed. The held-out human signal is the only defence, and it is small.
- **The Thor's GPU is the Thor's memory.** A batched simulator competes with
  the world for the same bytes. Every build runs under a lease with an honest
  peak, and the batch is sized against the *tier's* peak, not the box's.
- **Nothing here is verified yet.** This is a design. The only measurements
  that exist are Stratego's, on another machine, and ours on the port
  ([`docs/lab/exp-stratego.md`](../lab/exp-stratego.md)).

## 7. What this doc does not decide

- **The host language for the Python-facing side.** `docs/design/language-fit.md`
  says "pick what is best, not what is easiest to write" and gives C++/CUDA as
  the GPU default; pybind11 is what Stratego uses and it is battle-tested
  there, which is a reason to use it and not a decision.
- **Fixed-size tensor vs. a sparse plane form for the observation.** Stratego's
  fixed tensor won because the network wants a tensor. Our systems are smaller
  and some planes are ragged. This is decided per rule system, not globally.
- **How many samples the belief search uses.** That is a measurement, not a
  decision, and it belongs in a lab note.
