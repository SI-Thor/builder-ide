# SPEC — tiles: the system that gets better

Status: design for implementation, **version 1** (2026-10-31). This is the
design of the **tile seat** (`core/tiles`): the scripts a cloud model writes,
the library they live in, the record of every time one is played, the small
models on the Thor that choose between them, and the nightly loop that turns
the outcomes into better options.

It does not supersede `docs/design/core-spec.md` (v2) — the core service is
unchanged. Tiles are a new kind of record inside it, and where the core spec
is silent this file decides and says why.

**Citation shorthand**

- **V** = `docs/vision.md` — §"What the Thor is for" is Casey's B2 decision.
- **D** = `docs/decisions-for-casey.md` — B2, "No LLMs on the Thor".
- **S** = `docs/design/core-spec.md` (v2) — §1.0 (ids, hashes, the log),
  §1.5 (the vocabulary), §1.7 (the ledgers), §1.8 (the closed event set),
  §5.1 (seal before render).
- **P** = `docs/plan.md`, **L** = `docs/lab/*`.

**The one sentence.** *The cloud writes the options; the Thor learns which
ones work, and when* (V, §"What the Thor is for").

---

## 0. Decisions at a glance

| # | Question | Choice | Where it comes from |
|---|---|---|---|
| 1 | What is a tile? | A **script in the closed, typed vocabulary** — a list of steps, each a vocabulary word with bounded params. Never code. | V: the builders "never write code"; the vocabulary is the only door (S §1.5) |
| 2 | What identifies a tile? | Its **content**: `tile_<sha256-12>` over the canonical body. The same script is the same tile, whoever wrote it. | S §1.0: content hashes over canonical JSON |
| 3 | What is a tile *version*? | A **family** (`harbor.crates.style`) plus a sequence number. A new body in a family is version N+1; the old one stays. | the library is versioned and append-only (this doc, §2) |
| 4 | Can a tile be deleted? | **No.** Tiles are retired, never deleted. A retired tile keeps its plays and its history. | this doc; the same rule as the taste ledger (S §1.7) |
| 5 | Where do play records live? | In the **audit log** (`tile.played`), like everything else. The chooser's statistics are a fold over the log, never a private cache. | S §1.0: the log is the source of truth |
| 6 | What counts as "won"? | One of three **measures**, recorded on every play: the critic's verdict, the owner's keep or undo, or a sealed prediction that held. The measure is on the record, so a tile's win rate is always "wins by *this* measure". | the brief; S §1.7 (three writers, three record types) |
| 7 | Who chooses a tile? | A **small local decision model** on the Thor, chosen by a parameter with a default. The first is a contextual bandit; a learned ranker and RL come after it, each behind the same door. | V: "many small decision models" |
| 8 | What does the night do? | **Retrain** from the night's play records, then **feed the losers back** to the cloud author: "write a better one, here is why it lost". | the brief; V: "each night adds scripts and outcomes" |
| 9 | May a tile be played with nobody watching? | **Yes, after the gate**: the chooser may act alone once it has two prior observations on that context (S §3.5's rule, applied to tiles). | the confidence gate (S §1.7, `core/vocab/gate.py`) |
| 10 | Where does the tile run? | **Nowhere, by itself.** A tile is data; the engine, the scheduler and the recipe store execute its steps. | the recipe is the source of truth; renders are caches (S §1.1) |

---

## 1. The tile — what a cloud model writes

A tile is **one option**, written by a cloud LLM, that a local decision model
can pick in the moment. Three kinds:

| kind | what it is | what it changes |
|---|---|---|
| `behaviour` | how a builder acts | a behaviour entry in the recipe |
| `build_step` | a step of a build | a generator, a prop set, a material |
| `recipe_edit` | a change to the world | typed ops on named recipe entries |

**A tile is a script, but not code.** The body is a list of *steps*, and each
step is a vocabulary word with bounded parameters:

```python
class TileStep(BaseModel):
    word: str                 # "props.harbor.crates" — a word of §1.5
    path: str                 # the recipe entry it writes: "harbor.crates"
    op: Literal["set", "add", "remove"] = "set"
    params: dict[str, Json]   # bounded by the word's schema; never free text
```

The word's schema is enforced **at the door**, exactly as a builder's call is
(`core/vocab/call.py`): a tile that names an unknown word, or a parameter
outside the word's schema, is **refused** — not repaired, not clamped. The
cloud author is as bound by the vocabulary as a character is. That is the whole
point: the cloud may be slow and smart, but it may not smuggle free text into
a world that a child builder can also touch.

### The schema

```python
class TileAuthor(BaseModel):
    model: str            # "minimax/MiniMax-M2.1" — who wrote it
    provider: str         # "minimax" | "z.ai" | "claude" | "fake"
    prompt_hash: str      # sha256 over the prompt that produced the tile
    cost_cents: int       # what that call cost — the authoring is not free
    temperature: float | None = None

class Precondition(BaseModel):
    key: str              # a context key: "wanted_style", "phase", "budget_left"
    op: Literal["eq", "ne", "in", "gte", "lte", "lt", "gt"]
    value: Json           # compared against the context

class Tile(BaseModel):
    id: str               # "tile_<12 hex>" — the content address
    family: str           # "harbor.crates.style" — what it is for
    version: int          # the family's sequence number, assigned by the library
    kind: TileKind        # behaviour | build_step | recipe_edit
    title: str            # one line, shown on cards
    steps: list[TileStep]
    preconditions: list[Precondition]
    author: TileAuthor
    provenance: dict      # free-form but bounded: the seed, the work order, the parent tile
    created_at: str
    status: Literal["active", "retired"] = "active"
    retired_at: str | None = None
    retire_reason: str | None = None
```

**Provenance is not decoration.** `author.prompt_hash` is what makes a tile
*comparable*: two tiles written by the same model from the same prompt are the
same tile, and a tile written after a losing one carries the losing tile's id
in `provenance`, so the chain "this was written because that lost" is
readable in the log rather than inferred.

### What a tile is *not*

* **Not a recipe.** A tile is an *option to edit*; the recipe stays the
  source of truth (S §1.1). Playing a tile produces a typed edit, which the
  recipe store validates and commits like any other.
* **Not a job.** A job is something the scheduler runs on the GPU (S §1.9). A
  tile is a decision about what to do; the job is the doing.
* **Not a prediction.** A prediction is a *bet* about the world, sealed before
  the render (S §5.1). A tile may carry a sealed prediction with it — the
  builder seals "these crates will read weathered" before it renders the tile
  — but the tile is the option and the prediction is the evidence.

---

## 2. The library — content-addressed, versioned, never deleted

The library holds the options. It is a **content-addressed store of
immutable tiles**, with a version index per family.

### Rules

1. **Content addressing.** A tile's `id` is `tile_<sha256-12>` over the
   canonical body (family, kind, title, steps, preconditions, author). The same script
   written twice is the same tile: adding it twice is a no-op, not a second
   version. The **family** is part of the body — what a tile is *for* is
   part of what it is, so the same script serving two families is two
   options, not one.
2. **Versioning.** A tile belongs to a **family** — what it is *for*. A new
   body in a family is the next version of that family. The library assigns
   the version; the author does not get to claim it.
3. **No deletion.** `delete` is refused, always, with the reason
   `tiles_are_never_deleted`. A tile leaves the *eligible* set by being
   **retired** — status `retired`, a reason, a timestamp. Its body, its plays
   and its history stay.
4. **Retirement is auditable.** `tile.retired` goes into the log with the
   reason and the plays it had. A retired tile is still a tile: it can be
   un-retired by a new version of the family, and it is still the answer to
   "why did this lose?" in the morning.

### Why not just a table of rows

Because the render and the mesh are caches (S §1.1) and the tile is a
*recipe of behaviour*: the same argument applies. If the recipe is the source
of truth, the tiles are too, and the meshes and the plays are caches over
them. A tile you cannot reproduce byte-for-byte is not a tile.

---

## 3. The play record — what happened, where, and who chose it

Every use of a tile is recorded. **This is the only thing that teaches
anything**, so the record carries everything a learner needs and nothing it
does not.

```python
class Outcome(BaseModel):
    result: Literal["win", "lose", "partial"]
    measure: Literal["critic", "owner_keep", "owner_undo", "sealed_prediction"]
    score: float | None   # the reward, when the measure gives one
    detail: str = ""      # bounded: why, in a few words

class PlayCost(BaseModel):
    gpu_minutes: float = 0.0
    wall_seconds: float = 0.0
    hosted_cents: int = 0

class PlayRecord(BaseModel):
    id: str               # "play_<12 hex>"
    at: str
    tile_id: str
    tile_version: int
    context: dict[str, Json]     # the game context the tile was chosen in
    outcome: Outcome
    cost: PlayCost
    chooser: str         # which decision model chose it: "bandit/ctx-v1"
    chooser_version: str
    night: str | None = None
```

### The three measures

"Win" is not one thing, and the record says which one it is:

| measure | what it means | who writes it |
|---|---|---|
| `critic` | the Critic's verdict on the result | the Critic (S §1.7) |
| `owner_keep` / `owner_undo` | you kept it, or you undid it | you |
| `sealed_prediction` | a sealed bet about the outcome **held** | the score of the bet |

A tile that wins by the critic and loses by the owner is a *different tile*
from one that loses by both, and the library keeps both facts. The chooser
learns from one measure at a time — the retrain says which — so a critic's
optimism cannot quietly become the builder's taste.

### The reward

The chooser's arithmetic needs one number. The mapping is fixed and stated
here, not tuned per tile:

```
win → 1.0    partial → 0.5    lose → 0.0
```

and `outcome.score`, when the measure provides one, overrides the mapping.
The mapping is a parameter with a default (`reward_map`), because the critic's
verdict is a coarse three-valued thing and a later measure may be continuous.

### The context

The context is **data, bounded**: a small dict of key → value, the same shape
as the core's context packet (`pkt_`) but smaller — the features a decision
model actually branches on (`wanted_style`, `phase`, `budget_left`,
`builder`). It is stored with the play, because a play without its context
cannot be learned from: the whole point of a *contextual* bandit is that the
same tile wins in one situation and loses in another.

The ledger caps a payload at 4 KiB (S §1.8); a play that would exceed it is
**refused**, not truncated. A truncated context is a lie about the context.

---

## 4. The decision models — the chooser

The Thor hosts **many small decision models** that agents and game engines
call at millisecond speed (V). A tile chooser is one of them.

### The door

Every chooser is behind one interface:

```python
class TileChooser(Protocol):
    def choose(self, context: Mapping[str, Json], tiles: Sequence[Tile]) -> Choice: ...
    def update(self, record: PlayRecord) -> None: ...
```

and every chooser is **a parameter with a default** — `bandit/ctx-v1` — so the
night's configuration can swap it without touching the callers. The chooser
that is in service is stamped on every play record (`chooser`,
`chooser_version`), because a win rate that mixes two choosers is not a win
rate.

### The ladder

| rung | what it is | why it comes then |
|---|---|---|
| 1 | **contextual bandit** — per (context bucket, tile) reward estimate; ε-greedy with a decaying ε and a Beta-style prior | simple, measurable, and it beats uniform within a night; it is the floor everything else must beat |
| 2 | **a small learned ranker** — features → score, trained on the play records | handles more context features than a bucket can hold, and shares weights across tiles |
| 3 | **RL** — a policy over tiles, trained on the accumulated return | the only rung that can trade a win now against a win later |

Each rung is served **resident and batched** (V): the chooser is a small model
that stays in unified memory, and a night asks it for a batch of choices
rather than one call at a time.

### Eligibility before choice

A tile that cannot apply in this context is **not an option**. The chooser
filters by preconditions *before* it scores anything, and a context with no
eligible tile is a refusal with a named reason — never a fallback to some
other tile. A tile that was played when it did not apply is a bug in the
preconditions, and the play record carries the context, so the bug is
readable.

### Cold start

With no observations, the bandit has no prior and picks deterministically
among the eligible tiles (by id), and says so: `reason="cold"`. It still
**explores** — a builder that never explores never learns, and the whole
system's value is the learning. The first night's plays are therefore the
price of the second night's win rate; the design says so out loud rather than
pretending otherwise.

---

## 5. The learning loop — the nightly retrain

Every night, after the world's work:

1. **Fold** the night's `tile.played` rows into play records.
2. **Refit** the chooser from the records — the statistics are a fold over
   the log, so a restart or a crash loses nothing and a replay gives the same
   answer (S §1.0).
3. **Rank** the tiles by their win rate, **by measure**, with the denominator
   kept (`7/11 won by the critic`).
4. **Retire** the tiles that lost — if the policy says so — with the reason
   and the plays they had. A tile that lost 11 times in a row is not an
   option; it is a lesson.
5. **Feed the losers back** to the cloud author: a **feedback packet** per
   losing tile, saying what it lost, where it lost, and what it used.

### The feedback packet

This is the bridge back to the cloud, and it is deliberately blunt:

```python
class FeedbackPacket(BaseModel):
    tile_id: str
    family: str
    kind: TileKind
    words: list[str]        # the vocabulary words it used
    plays: int
    wins: int
    win_rate: float
    measure: str            # which measure said so
    contexts: list[str]     # the context buckets where it lost
    request: str            # "write a better tile for this family; here is why it lost"
```

The cloud author receives the packets and returns **new tiles** for the
families that lost. The new tiles are validated at the door (unknown word →
refused; out-of-schema params → refused) and admitted to the library as the
next version of the family. The old tile stays, retired, with its plays.

### Where the loop stops

The loop does **not** invent tiles, and it does not edit the world by itself.
It proposes options to the cloud, and the cloud proposes options to the
library. The chooser picks among what is in the library. Nothing in this
chain can write an unvalidated step into a recipe.

---

## 6. Motion as virtual robotics — where the policies slot in

The builders are robots in a simulation (V). Their walking, reaching and
carrying are **policies trained on the GPU**, not clips. A policy is a
tile-chooser of a different kind: it does not score tiles, it *proposes* them.

So there are two ways a policy meets a tile, and both are legitimate:

* **the policy as a prior** — the policy's action distribution over the
  vocabulary becomes the chooser's exploration distribution instead of a
  uniform one. The bandit still decides what *worked*; the policy says what
  is *plausible*;
* **the policy as a tile** — a trained policy is itself a tile (a behaviour
  that a decision model may choose), with the same play record, the same
  outcome measures, the same library. A motion policy that wins its plays
  earns its place in the library like anything else.

The second is the deeper one, and it is the reason the tile schema is a
**behaviour / build step / recipe edit** triple rather than a recipe-edit
alone: on the day a policy is a tile, everything the learning loop already
does applies to it for free.

**This section is a design, not a build.** Nothing in the first slice
implements policies. It is here so that the seam is chosen now: the chooser's
interface (§4) is the same interface a policy-driven chooser implements, and
the play record (§3) is the same record a policy's outcomes are written to.

---

## 7. What it costs and where it runs

| what | where | what it costs |
|---|---|---|
| **authoring** a tile | the **cloud** (z.ai, MiniMax, Claude — each a parameter priced per call, D B2) | hosted cents per call, recorded on `tile.authored` |
| **validating** a tile | the Thor, CPU lane | microseconds — a schema check, not a model |
| **choosing** a tile | the Thor, GPU (resident, batched) | a few milliseconds per choice; the model's residency is the real cost |
| **playing** a tile | the Thor | the work itself: a render, a build step, a behaviour |
| **learning** | the Thor, nightly | a retrain over the night's records — a bandit refit is milliseconds; a ranker or RL is minutes on the GPU |
| **the feedback loop** | the cloud | one authoring call per losing family per night |

**The Thor never hosts an LLM** (D B2). The choosers are small models —
tables, a small network, a policy — and they are exactly the kind of thing
the box's unified memory is good at: many of them, resident, batched, called
every tick.

**The authoring budget is the honest cost of this seat.** The number of tiles
a night may write is a rail, like every other rail (S §5.5), and the tile
seat's spend is in *hosted cents* — the one rail the Thor cannot enforce
itself.

---

## 8. The seams

| seam | what it answers | who owns it |
|---|---|---|
| **the ledger** | append an event; read it back | `core-api` — the tiles seat writes through `LedgerPort` |
| **the vocabulary** | is this word known? are these params in schema? | `core/vocab` — the tiles seat refuses against it |
| **the recipe store** | does this tile's edit validate and commit? | `core/recipe` — the tiles seat does not write the recipe |
| **the cloud author** | write me a tile for this family, here is why the last one lost | the cloud, through `TileAuthor`; a scripted fake stands in for tests |
| **the game** | what happened when this tile was played? | the engine and the critic; the tiles seat writes the record |

The tiles seat **writes audit events and nothing else** (the night runner's
rule). It has no tables of its own; the library and the chooser's statistics
are folds over the log.

---

## 9. The first slice — what it builds, and what it does not

`core/tiles/` implements:

1. the **tile schema** — the records above, with the closed vocabulary
   enforced at the door;
2. the **library** — content-addressed, versioned, retire-never-delete;
3. the **play records** — written to the ledger, folded back;
4. a **contextual-bandit chooser** — the first rung of the ladder;
5. a **nightly `retrain`** — refit, rank, retire, and the feedback packets.

**Plus one acceptance test**: a scripted cloud author writes K tiles, a
simulated game scores them over N plays, and the chooser's win rate rises
above a uniform pick **with a stated confidence**. No real LLM call is made
in any test: the author sits behind an adapter, and the adapter's fake is
deterministic.

**Not in this slice:** the learned ranker, RL, the policies of §6, the cloud
transport's real endpoint, the recipe-store integration (playing a tile
end-to-end), and the morning report's tile column. Each is a small step
after this one, and the seams for them are already named.

---

## 10. Open questions for Casey

These are the decisions this design cannot make on its own. Each has a
default, so the seat keeps working while they are open.

1. **How many authoring calls per night, in cents?** The tile seat's only
   real rail. Default: the night's existing hosted-cents rail, with a named
   per-family cap.
2. **Who reviews a tile before a builder may play it?** Options: (a) nobody —
   the library admits any valid tile and the learning is the filter; (b) the
   Critic, on the first render; (c) you, in the morning. Default: (a) for
   *recipe edits* the recipe store's own validation, (b) nothing extra.
3. **Which measure trains the chooser?** The critic is cheap and always on;
   the owner's keep is the truth and arrives days later; a sealed prediction
   is evidence about a claim, not about the tile. Default: the critic's
   verdict at night, with the owner's keep folded in when it arrives.
4. **May a chooser act alone at night?** The confidence gate says a builder
   with fewer than two observations may bet but not decide (S §3.5). Default:
   yes, after two observations on that context — the same rule.
5. **Does a retired tile get another chance?** Default: a new version of the
   family supersedes it; the retired tile keeps its plays and its history.
6. **How long are play records kept, and do they leave the machine?** The
   taste ledger never leaves by default (S §7.6); play records are the same
   kind of data about the owner's world. Default: local, forever, never in a
   model call slice without the owner asking.
7. **One chooser for the whole world, or one per builder character?** Default:
   one per (character, context family), because a tile that wins for the
   Architect is not automatically right for the Prop-maker.
8. **What is a tile's family?** The name is chosen by the author today.
   Default: the author names it; the library refuses a family that changes
   meaning — but nothing checks that yet. This is the weakest part of the
   design and the first thing to harden.
