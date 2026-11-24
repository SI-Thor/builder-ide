# agent-world — how it works

A Minecraft world on the Thor with four builders living in it, and the
three minds that make them work: a **reflex** that decides, a **canon**
that remembers, and a **mediator** that improves the options while the
world runs.

This document explains the mechanisms. It does not claim anything; the
numbers at the end are what was measured, with the state of the box
beside them.

---

## 1. The box

The Thor (Jetson AGX Thor, aarch64, 122 GB unified memory, 14 cores) is
shared with the other seats of the project, and it is busy. The world's
standing on that box is therefore a deliberate one:

| | |
|---|---|
| Paper 26.1.2 build 74 | the world itself; Java 25 (Temurin, aarch64 tarball, local directory) |
| heap | `-Xms2G -Xmx6G`, at `nice 10` |
| memory floor | the world does not start, and the builders stand aside, while the box has **less than 25 GB free** |
| the heavy lock | **not taken by the world.** The decision model loads through the admission daemon (`thor-admit serve`), which leases only the load |

The 25 GB floor is the rule that came out of the 13:22 OOM, and the
lock is the stopgap that came with it. The world applies the rule
directly rather than the stopgap, because the stopgap is a poor
instrument for a resident service: one long generation sweep on
another seat would otherwise freeze the world for an hour even though
the world uses 2 GB and runs at `nice 10`.

### The addresses

| what | where | protocol |
|---|---|---|
| Minecraft Java | 192.168.0.78:25565 | TCP |
| Minecraft Bedrock (Geyser + Floodgate) | 192.168.0.78:19132 | UDP |
| the 3D view | http://192.168.0.78:8080/ | HTTP |
| the text view | http://192.168.0.78:8080/ascii | HTTP |
| the voices | http://192.168.0.78:8080/voices | HTTP (model and engine in the page) |
| the reflex (internal) | 127.0.0.1:8110 | HTTP, loopback only |
| the decision model | 192.168.0.78:8094 | HTTP (d1-2B, `llama-server`) |

The server binds `192.168.0.78`, never `0.0.0.0`. There is no host
firewall on the box (no `ufw` binary, and the seat has no sudo session),
so "LAN-only" rests on the router's NAT as well as on the bind address;
that is a fact about the box, not a claim about the world.

### The door

The server runs in **offline mode** with a **whitelist**. That is the
trade Casey chose for a LAN-only world: the four builders need no
Minecraft accounts of their own, and the price is that anyone on the
LAN can claim any name — so the whitelist is what actually keeps the
door shut. Paper keys its whitelist by UUID, and in offline mode that
UUID is derived from the name, so the whitelist is applied through the
server's own `whitelist add` command. `ops/world/whitelist.txt` is the
intent; every start re-applies it, and a name in the server that is
not in the file is removed.

---

## 2. The three minds

From `docs/design/three-minds.md`: the reflex is fast and has no
authority; the canon is the one history; the mediator is the reflective
mind that improves the system while it runs. Here is each one, in this
world.

### The reflex — `reflex/`

Every two seconds each builder tells the reflex what it can see and
what it needs. The reflex does three things:

1. **It filters.** The skill library is the source of the options; a
   skill whose preconditions do not hold in this context is not an
   option at all, and a context with no eligible skill is a refusal
   with a named reason — never a fallback to some other skill.
2. **It asks.** The eligible options go to the decision model as **one
   pack**, one question per builder, over one shared description of
   the world. The pack is the reason four builders cost one model call
   rather than four.
3. **It chooses.** The answer comes back as a probability per option.
   That probability is the **cold-start prior**; the learned estimate
   washes it out as the record grows (§4).

The decision model is **d1-2B**, served once on the box and shared —
and "once" is now literal: `ops/run-d1.sh` loads it through the
admission daemon (`thor-admit serve`), which holds a lease only while
the model loads and hands any other seat that asks for d1-2B **this
server's port** instead of letting a second copy onto the box. (The
world ran for an evening with the reflex asking port 8094 while two
other seats each carried their own d1 on other ports — 11,185
consecutive failures, all of them needless; that is what `serve`
exists to prevent.)

It is reached through **builder-ide's judge** (`core/judge`), which is
where the confidence gate, the escalation ladder and the attempt log
live. Every ask is recorded as a `judge.verdict` row, including the
refusals. When the model cannot be reached at all, the world falls
back to the bandit's own prior and says so — the world keeps working;
the log says what happened.

### The canon — the log

One SQLite file (`runtime/world-ledger.sqlite3`), the closed event set
from `core-spec` §1.8, and the **tile** event types, because in this
world a skill *is* a tile: the cloud writes the options, the Thor
learns which ones work.

| event | when |
|---|---|
| `tile.authored` | a skill enters the library |
| `tile.played` | a skill is used, with its outcome and its context |
| `tile.retired` | a skill leaves the eligible set, with the reason |
| `tile.retrained` | the chooser was refit from the log |
| `judge.verdict` | every ask of the decision model, including the refused ones |

The library and the chooser's statistics are **folds over this log**, so
a restart loses nothing and a replay gives the same answer. The
builders' own log (`runtime/logs/bots.jsonl`) holds the same decisions
in the order they happened, and holds **nothing about a human**: no
chat, no audio, no transcript. That is a rule, not an intention — the
log format has nowhere to put it.

### The mediator — `reflex/agent_world_reflex/mediator.py`

The mediator watches and, **only when the sign fades**, writes new
skills.

The **sign** is two readings of the recent window of play records: the
failure rate, and the slope of the decision model's confidence. While
the sign holds, the mediator makes **no model call at all** — it logs
and it waits. Intervening during a groove that is working would add
latency, cost and second-guessing.

It steps in on two triggers:

1. the sign faded (failures above half, or failures rising, or
   confidence sliding);
2. a human joined the world.

Then, for each family that is losing, it builds a **feedback packet** —
deliberately blunt: what it lost, where it lost, how many times, what
it used — and asks a cloud model (Groq's `gpt-oss-120b` through
`~/lm-tools/gq.py`) for a better skill. The new skill is held to the
**same door** as everything else, and a refusal goes back to the author
with its reason, so the next attempt is a better one.

That is the anti-GAN: the learner improves by joining, not by losing
against an adversary. The room answers, and the answer becomes the
next phrase.

---

## 3. The skills, and the door

A **skill** is a small JavaScript function over the mineflayer API.
It is a tile in every other respect:

- **content addressed** — `skill_<12 hex>` over the canonical body, so
  the same script written twice is the same skill;
- **versioned per family** — a family is one job ("mine stone and leave
  it at the depot"), and the library assigns the version;
- **never deleted** — a skill leaves the eligible set by being
  **retired**, with a reason and a timestamp. Its body, its plays and
  its history stay, and it is still the answer to "why did this lose?";
- **the latest version of a family is the live one** — when a new
  version is admitted, the older versions of that family are retired
  with the reason "superseded by ...".

### The vocabulary

The world's vocabulary is closed. A skill may only use these words:

```
observe:  position, health, food, time_of_day, light, inventory,
          inventory_count, block_at, find_block, find_chest,
          nearby_players, look_at
act:      dig, place, move_to, equip, craft, attack, wait,
          open_chest, deposit, withdraw,
          depot, leave_at_depot, take_from_depot
```

Three checks, in order of strength:

1. **no escapes** — `require`, `process`, `globalThis`, `fetch`,
   `eval`, `Function`, `constructor`, `__proto__` and the rest are
   refused **by name**, before anything else is looked at;
2. **no unknown words** — every function the skill calls is either a
   word of the vocabulary or a name the skill itself declared. A skill
   that reaches for a word the world does not have is not a skill with
   a bad word in it, it is not a skill;
3. **it parses** — the body is compiled by Node's own parser, and a
   refusal carries the parser's message.

And at run time there is a fourth door: the skill runs in a `vm`
context that has no `require`, no `process`, no `Buffer`, no `console`,
no `eval` and no `new Function` (string code generation is off). The
API wrappers are built *inside* the context, so even reaching for
their `constructor` lands in the sandbox's realm and not the host's.

**The low-level work stays in mineflayer's own planners.** A skill
says *what* to do ("mine that oak log"); `mineflayer-pathfinder` works
out how to get there and `bot.dig` does the mining. The reflex chooses
the decision, not the footsteps.

### The measure

"Win" is not one thing, so the record says which one it is. This world
writes the first of the three measures in `tiles.md`:

| measure | what it means |
|---|---|
| `sealed_prediction` | the skill declared what it expected to change, and the world checked it |
| `owner_keep` / `owner_undo` | Casey kept or undid the work (for the day he watches) |
| `critic` | a critic's verdict on the result (not implemented yet) |

So every skill carries a prediction:

```json
"predict": {"kind": "inventory_delta", "item": "cobblestone", "min": 1}
```

and the kinds are `inventory_delta`, `block_placed`, `block_broken`,
`moved_to` and `none`. A skill that makes no measurable effect is
recorded as **partial** — it ran, but it cannot be called a win or a
loss, and it says so.

A partial play carries **no reward**. The arithmetic that stood here
before the playtest of 2026-11-01 scored a partial as 0.5, which read
"we could not measure this" as "this wins half the time" — a constant,
fabricated reward, and a high one, which held the scout's role on a
number nobody measured (the survey skill: 18,066 plays, reward exactly
0.5 on every one; the playtest note has the numbers and the fix). A
partial is not half a win; it is no measurement, the chooser does not
learn from it, and an unscored skill keeps the judge's prior — which is
the designed cold-start rule — until real evidence arrives.

The context travels with the play, because a play without its context
cannot be learned from: it is the difference between a contextual bandit
and a lookup table. The context carries the role, the phase (day or
night), the health and food, whether the builder is holding material,
whether a human is near, and the confidence the decision model gave.

---

## 4. The chooser

Two things know how to pick, and they are combined in
`reflex/agent_world_reflex/chooser.py`:

- **the decision model** (d1-2B), which is the reflex: it runs in tens
  of milliseconds and it is the only thing that runs on every tick;
- **the learned estimate**, a contextual bandit over (context bucket,
  skill) — builder-ide's own `core/tiles/chooser.py`, with its
  ε-greedy exploration, its posterior mean and its propensity
  arithmetic.

How they are combined is the rule the tiles seat already uses: **the
judge is the cold-start prior**. Where the bandit has no observation
of a skill in this bucket, the judge's probability stands where a flat
prior stood; as real plays arrive, the learned estimate washes the
prior out at the rate the bandit's prior count sets:

```
w = prior / (plays + prior)          # 1 for a skill nobody has played
score = (1 - w) * learned + w * judge # w -> 0 as the record grows
```

"Plays" here means **plays that could be scored**. A partial play — no
reward, §3 — does not enter the bandit's record at all: it counts as no
observation, and the skill it belongs to stays exactly where the judge's
prior put it. A skill whose every play is unscorable (a survey) is
therefore chosen, for as long as that lasts, on the decision model's
opinion alone — which is what the cold-start rule says for a skill the
record cannot speak about.

Nothing is thrown away: the judge's answer is in the log, the
propensity is measured **at the choice** (it cannot be reconstructed
afterwards, because the exploration rate decays and the greedy arm
moves), and the candidates the choice was made from travel with the
play record — so the log stays off-policy evaluable.

---

## 5. Presence

The Thor's finite resource is time, and the world's standing on a busy
box has to be honest about it:

- the world is **resident**: it runs whether or not anyone is watching,
  and it keeps working when Casey goes to bed;
- it is **low priority**: `nice 10`, a 6 GB heap, and it never takes the
  heavy lock;
- it **yields on the rule, not on the lock**: while the box has less
  than 25 GB free, the builders do not act, and the log says so
  ("yielded: the box has N GB free; the rule is 25 GB");
- the **decision tick is light** and never takes a lock. The one
  heavy step the world has — loading the decision model — goes through
  the admission daemon, which leases only the load and shares the
  loaded model with every other seat on the box (`ops/run-d1.sh`).

So live work pre-empts the world without being blocked by it, and the
world's cost to the rest of the box is bounded and visible.

---

## 6. The three views

All of them are projectors of the same world, in different media.

**The 3D view** (`/`) is prismarine-viewer: the world as a spectator
sees it, with the builders in it. A "Watcher" joins the world for it —
a spectator that stands at the depot and needs no account of its own.

### The 3D view draws a version the browser has

The world runs **Minecraft 26.1**. The browser's 3D view cannot draw it.

prismarine-viewer 1.33.0 is the newest published build, and its assets
(textures, block models) and the minecraft-data tables inside its browser
bundle stop at **1.21.4**. Its version lookup answers `null` for `26.1`
— `26.1` is not a major.minor it knows — so the page says **"null is not
supported"** and draws nothing. Casey saw that on the morning of
2026-11-01: a blank canvas.

Relabelling the version is not enough. Blocks added since 1.21.4 shift
the global block-state ids, so the chunks would decode into the wrong
blocks. So the translation happens **on the server**, where minecraft-data
has both versions (`viewer/src/translate.js`):

```
26.1 state id  →  (block name, properties)  →  1.21.4 state id
```

Every chunk palette and every block update is re-encoded on its way to
the page, and the page is told `1.21.4`. The world is not changed: the
builders, the skills and the reflex all still speak 26.1. Only the bytes
on their way to the browser are re-encoded.

Three kinds of palette container exist in a chunk — the usual `indirect`
one (a list of states and a bit array of indexes), `single` (one state
for a whole section) and `direct` (the bit array holds the states
themselves) — and all three are re-encoded. A palette keeps its length,
so the bit array that indexes into it still means the same thing.

**What is approximated, and said out loud.** The page carries a strip
that says how the world is being drawn:

> agent-world · Minecraft 26.1 drawn as 1.21.4 — 1 block has no 1.21.4
> twin (iron_chain → chain) · the text view · the voices · the status

- **74 blocks** exist in 26.1 and not in 1.21.4 (the copper furniture,
  the shelves, the ground cover of 26.1). Each is drawn as the nearest
  block 1.21.4 has, from an explicit table
  (`viewer/src/fallback-blocks.js`), and the count of those actually in
  view is on the page.
- **One block** keeps its name but gains a value: 26.1's note block can
  be a copper trumpet, which 1.21.4 has no note block for. The bell is
  drawn instead.
- **One block** renamed a property: the creaking heart says what state
  it is in now, where 1.21.4 said whether it was creaking.

`ops/check-translation.js` checks all of that without a browser: every
26.1 state id lands on a state id of the same block (or of its
documented stand-in), the properties survive the round trip, the
stand-ins are real 1.21.4 blocks, and a chunk keeps its shape.

**The page never goes blank.** If the version cannot be drawn at all,
the page says so in words and points at the text view, instead of
showing an empty canvas.

**The mobs the browser has no model for are left out.** prismarine-viewer
has models for 94 mobs; an axolotl is not one of them. Rather than draw
it as a magenta box and say so in the console, the server leaves it out.
Players are drawn as players, with their name above them.

**The entities the browser cannot even name are left out too.** An
entity with no name — 26.1 knows entities the viewer's 1.21.4 tables do
not — used to fall through to the browser's fallback box, which is sized
from the entity's `width` and `height`; a name-less entity has neither,
so the box was `BoxGeometry(undefined, undefined, undefined)` and its
geometry was pure NaN. Every page load printed about a dozen
"computeBoundingSphere(): Computed radius is NaN" console errors for the
dozen such entities in view (the playtest of 2026-11-01; the diagnosis
is in the playtest note). `drawable()` now leaves them out, like the
model-less mobs, and departures still pass so the page forgets what it
once drew.

### The check

`ops/check-views.sh` drives a real browser over all three pages and
checks, per page: no page errors, nothing saying a version is not
supported, **no console errors at all**, no failed requests, and — for
the 3D view — that the canvas holds more than one colour and that the
page says how the world is being drawn. A 200 with live frames would not
have caught the blank canvas; the pixels do. Run it after any change to
the viewer.

(Correction, 2026-11-01: this check used to excuse the "Computed radius
is NaN" console errors as a harmless three.js artifact of empty
sections. They were not empty sections — they were the name-less-entity
boxes above, a dozen per load — and the excuse is gone: a console error
now fails the check.)

**The text view** (`/ascii`) is the Syzygy-style projection: one
perspective, projected into characters by a kernel with two properties
the 3D view does not need —

- **integer**: the whole projection is integer arithmetic over a fixed
  cosine table, so no floating point creeps in through trigonometry;
- **deterministic**: no clock, no randomness. The same world state
  always gives the same characters, so two readers of the same state
  read the same thing, byte for byte.

The kernel is a small raycaster: one ray per cell, marching in integer
steps, taking the first block it meets, and rendering it as a glyph.
It is not a renderer; it is the same information in a medium a person
can read at a glance and a decision model can read exactly.

**The voices** (`/voices`) narrate the world as it works: each builder
has one fixed voice (Pebble `af_heart`, Timber `am_puck`, Kite
`bm_fable`, Sprout `bf_isabella`), and the model that speaks them —
Kokoro-82M v1.2 int8, Apache-2.0, the Paradee voices of the brief —
runs **in the page** through ONNX Runtime Web over wasm. That choice
is the brief's: no new process on the shared, memory-tight Orin; the
spectator screen pays for its own voice. Three rules shape it:

- **the feed is the world's own log.** `/events` tails the builders'
  log and joins each play to its family through the reflex. That log
  holds decisions and outcomes and has nowhere to put a human's chat
  or voice (the kids' privacy rule), so there is nothing on the page
  that could speak a person even by accident.
- **a voice in the room, not a babble.** One line every four seconds
  at most, three lines waiting, the oldest dropped first; wins only
  (a survey that looked around is silence); a follow-agent mode that
  voices one builder plus the wall — the one build every hand is in —
  and a mute toggle.
- **local after the first load.** The page redirects the engine's
  model fetches to the viewer's own mirror of the model
  (`viewer/public/paradee/`, not in git; `ops/install-runtime.sh`
  re-creates and checksums it), so the Orin's Firefox loads 92 MB
  once from the Thor and never needs the internet again.

The page shows its own numbers: time to first audio per line, last
and median, and lines spoken. What it cannot show from inside a
browser — the Orin's CPU and RAM while speaking — is measured the
first time that page runs on the Orin; the numbers below are from a
headless chromium on the Thor.

---

## 7. What it does not do yet

- **no owner measure yet.** `owner_keep` and `owner_undo` are in the
  schema and are not written; the day Casey watches, a human's undo
  should be a measure like any other.
- **no critic.** The `critic` measure is not written.
- **the learned ranker and RL rungs** are not built: the bandit is the
  floor, and the floor is what everything else has to beat.
- **the night retrain** is in the mediator's shape (refit, rank,
  retire, feedback packets) but runs on demand (`ops/bots.sh
  mediate`), not on a clock.
- **the perception spec** — "the mediator authors the perception spec,
  as data, for its fleet" — is not built. The context the builders
  send today is a fixed set of keys.
- **the voices have not run on the Orin.** The engine is verified in
  a browser on the Thor; the Orin's own Firefox numbers (time to first
  audio there, CPU/RAM while speaking) are the first measurement of
  the day its screen opens the page.
- **Bedrock joins are unverified.** Geyser + Floodgate are installed
  and listening on UDP 19132, but Geyser logs a warning that the
  newest Bedrock clients want ViaVersion against this Paper build.
  No Bedrock client has joined yet; installing ViaVersion is the
  documented first step if a tablet cannot.
- **Luanti is not built.** The brief puts it in a later re-engineering
  phase; what would have to be rebuilt there is written down in
  [`luanti-later.md`](luanti-later.md) and nothing was built for it.

---

## 8. The numbers

Measured on the Thor (aarch64, 122 GB unified memory, 14 cores). The
box was **shared and busy** during the measurement — another seat was
running a generation sweep, load average 17–19 against 14 cores — so
these are worst-case numbers, not best ones.

**The world, on 2026-11-01 at 10:28** (the day the economy was fixed;
the world itself has been up since 2026-10-31 21:33, interrupted for
code changes):

| what | the number |
|---|---|
| server tick rate (1 m / 5 m / 15 m) | **20.0 / 20.0 / 19.9 TPS** — full rate, with 6 connections (4 builders, the watcher, a probe) |
| Paper's memory | 2.6 GB resident of a 6 GB heap cap, at `nice 10` |
| the bots' memory | 0.44 GB for all four builders; the reflex 0.23 GB; the viewer 0.26 GB |
| d1-2B | served once per box under `thor-admit serve`; ~1 GB resident, on the GPU |
| the box | 80 GB free while the world ran; the world never yielded a tick to the floor rule |
| the time ledger | no lease held: the model load leased ~40 s at 09:24 UTC and nothing since |

**The decisions** (the 71 minutes from 09:17 to 10:28, which includes
three restarts for skill generations and two world-ops teleports):

| what | the number |
|---|---|
| d1 latency per pack | **67 ms mean** (2,839 packs would be the count at four builders × one question each per tick; measured on 317 packs in the last restart) |
| pack failures | 0 since d1 was served through the admission daemon (the previous 11,185 consecutive failures were the reflex asking a port nothing answered on — see §2) |
| plays per minute, all four builders | ~30 (0.5/s) — the pace is set by the work (a dig, a walk to the depot, a wall play), not by the decisions: d1 answers in 67 ms and waits |
| pack size | 1.0 question/call — plays stagger, so the batching window (120 ms) rarely catches two builders asking at once; the window is there for when the tick cadence tightens |

**The plays** — the honest split. The ledger holds the whole history,
including the evening everything failed (a block search that crashed
on positionless blocks, a place() that could never place, a depot that
was not standable — see the commits of 2026-11-01):

| window | plays | wins | what was true |
|---|---|---|---|
| the whole ledger | 19,105 | 307 | mostly the broken evening; every fix is visible as a bend in this curve |
| 10:17–10:28, after the last fix | 314 | 30 | Pebble 22 wins in 37 plays (59%), Sprout 6 of 23, Timber 2 of 6; Kite's 248 surveys record as *partial* by design — looking around is its work, and it is not scored as a win |

The sign, read by the mediator at 10:26: **the sign holds.**

**The reward playtest, 2026-11-01 21:53–22:53 UTC** — after the
constant-reward fix (§3); the box rebooted at ~20:00 UTC and the world
came back at 20:06; two other seats ran throughout; free memory
45–76 GB. The full finding, the three defects under it, and the fixes
are in [`playtest-2026-11-01-reward.md`](playtest-2026-11-01-reward.md);
the hour:

| skill | family | plays | wins | distinct rewards |
|---|---|---|---|---|
| farmer.ground | farmer.ground | 271 | 270 | 0.0, 1.0 |
| gatherer.stone | gatherer.stone | 165 | 164 | 0.0, 1.0 |
| scout.ground | scout.ground | 20 | 1 (moved 25.2 blocks) | 0.0, **1.0** — varies |
| scout.sight | scout.sight | 1,564 | — | 1,564 plays, all unscored — no 0.5 anywhere |

The judge answered 1,828 packs with 0 failures (mean 58.4 ms). Before
the fix the same box had gone three hours with zero wins in any
family and a survey skill at reward exactly 0.5 on every one of its
18,066 plays.

**The build**: the wall east of the depot — the one artifact every
hand is in — laid its first blocks at 10:24, three in its first two
plays, and grows at the pace of the depot it is fed from (each of
Timber's wall plays takes up to four blocks out of the pile the
gatherers leave). It is a slow build on purpose: the community's
supply line is one gatherer with one pickaxe, not a quarry.

**The voices** (headless chromium on the Thor, 09:38–09:39): the
engine loaded from the local mirror with zero network errors, and
spoke 5 lines in the first minute while the builders worked. Time to
first audio: **12.7 s for the very first line** (the 92 MB model
loading and its first inference, cold); the page reports per-line
last and median from there. What these numbers do not yet include —
the Orin's Firefox and its CPU/RAM while speaking — is the first
measurement the day that screen opens the page.

**The library**: 51 skills admitted across 11 generations of seed,
13 live families, every superseded version retired with its reason.
The cloud mediator has authored none yet: the sign has held since it
was last read, and a mediator that writes while the sign holds would
be the babble the design refuses. `ops/bots.sh mediate` is the door
for the day it fades.

---

## 9. The trade-offs, stated plainly

| the trade | why | the price |
|---|---|---|
| offline mode | the builders need no accounts | anyone on the LAN can claim a name; the whitelist is the door |
| Paper 26.1.2, not 26.3 | 26.1 is the newest protocol mineflayer speaks | Casey's client must be 26.1; the launcher installs it beside the newer one |
| Java 25, not the brief's 21 | Paper 26.1 refuses to start on anything older | the 1.21.x line (which wants Java 21) is one line away in `ops/env.sh`, and both JDKs are installed |
| the ground depot, not a chest | a chest needs a crafting table, which needs planks, which needs the thing the chest would hold | items are picked up by walking over them, which is a little less tidy than a chest |
| the builders act every 2 s | a tick is a question, and the question is the expensive part | the world's reaction time is seconds, not milliseconds |
| no chat, ever | the kids' privacy rule | the builders cannot talk to Casey, and nothing anyone says is stored |
