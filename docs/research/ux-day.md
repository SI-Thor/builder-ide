# REPORT — Ideation A: a day and a night with your builders

One night, told concretely enough to test. Casey (owner) and Magnus (kid
co-designer) are building **Fjellvik**, a harbor hamlet in a fjord, with five
builders — the Architect, the Landscaper, the Prop-maker, the Critic and the
Companion — on the Thor, viewed from the ProArt (`~/src/builder-ide/docs/vision.md`,
`~/src/builder-ide/CLAUDE.md`).

Every moment below carries: **what you see/hear, what you say, how long it
takes, and the nearest failure with its recovery**. Buildability tags:

- **[now]** — plain Python core + logs + a web/IDE panel; needs no 3D client
  (vision.md phases 3–4: the core, one night's work).
- **[later]** — needs the thin client / avatars / streaming (phase 5).
- **[north star]** — holodeck-direction only; we design toward it, we don't
  promise it.

## The three clocks (the latency doctrine)

Every interaction belongs to one of three clocks, and the UX rule is: **nobody
ever waits on the wrong clock.**

| Clock | Budget | Owns | If it can't be met |
|---|---|---|---|
| **Talk** | ≤ 2 s | speech, HUD, plan items, keep/reject | never batch, never spin |
| **Watch** | ≤ 5 s per card | the night feed, verdicts, provenance | pre-render, cache, show stale-then-fresh |
| **Workshop** | ≤ 60 s, with progress and a cancel | previews, critic runs, generations | it goes to the night queue instead of the screen |

The morning feels instant for one architectural reason: **the night already did
the rendering.** The report is a viewer over cached artifacts (thumbnails,
verdicts, diffs), so every morning latency is a UI latency. Idle games prove the
pattern — offline progress is computed before you return and shown the moment
you open the app ([Wikipedia: idle games, "offline earnings"](https://en.wikipedia.org/wiki/Idle_game)).

---

## 1. The evening — planning with the builders (20:41–21:16)

### 20:41 — the recognized return **[now: text · later: voice]**

Casey opens Fjellvik on the ProArt. The world streams in (glTF/USD, ~8 s warm
[later]); before he has walked three steps the Companion is beside him:

> "You're back. Yesterday you kept the north jetty and dropped the spiral
> stairs — I'm reading that as 'straight lines, weathered wood.' Want me to
> push that line tonight, or are we changing course?"

**Feel:** ≤ 2 s from world-load to that line, and the line must cite something
real from the taste ledger — a fact, not a greeting. First-run fallback, said
plainly: "First night. I'll learn what you keep." (Never fake memory.)

- **Fails when:** the ledger is empty and the Companion improvises anyway.
  **Recovery:** there is no recovery — this is a hard rule. Recognition must be
  backed by a ledger row or it must be first-run honest.
- **Test:** clear the ledger, open the world; the first line must contain
  "first" and no invented fact.

### 20:47 — the walk: point-and-say planning **[later]**

Casey and Magnus walk the hamlet. This is Sims-style **watch-more-than-click**
time ([The Sims](https://en.wikipedia.org/wiki/The_Sims_(video_game))): the
pleasure is being in the place with someone who knows it. As they walk, Casey
points and talks; each spoken intention becomes a **plan item** pinned where he
pointed — a small chip over the slope, not a form.

- Casey, at the east slope: "This hill's too bare. Forest it — but the big
  oak stays." → chip: `forest east slope · keep the oak · Landscaper` — 1.2 s.
- Magnus, on the south span: "Can the bridge *swing* when you run on it?"
- Casey, at the harbor: "This needs life. Crates, drying racks, lanterns."

**Feel:** each item lands ≤ 1.5 s after the sentence, as a chip you can tap to
correct. The plan is never a done deal while you're standing in it.

- **Fails when:** "this" is ambiguous (the slope? the whole east shore?). The
  Companion asks, in-world, naming candidates by what they are: "The slope, or
  the whole east shore?" — one tap. **Never guess** (vision.md: ambiguity is
  resolved by asking).
- **Fails when:** Magnus is talking. His chips get a Magnus badge; nothing
  about him is stored beyond taste labels, and his words are never quoted in
  the report (privacy rules live in ideation B).

### 21:02 — the plan slate **[now]**

They sit the avatars down (Magnus loves this beat) and open the slate: the
evening's one screen of decision-making. Four intentions, each with owner,
predicted cost, and the builder's own one-line take:

| # | Intention | Owner | Cost (model-time) | Builder's line |
|---|---|---|---|---|
| 1 | Forest the east slope, keep the oak | Landscaper | 2.0 h | "Two passes: birch first, then undergrowth. I think you keep pass one." |
| 2 | Harbor life: 12 props (crates, racks, lanterns) | Prop-maker | 1.5 h | "Six from the library, six new. I predict you keep 8 of 12." |
| 3 | A swingier south bridge | Architect | — | "I can fake sway with loose planks. Real rope isn't in my hands yet." |
| 4 | Winter-dawn light check on everything | Critic | 0.7 h | "I'll judge at the light you keep coming back for." |

Below the list, one **budget bar**: tonight the Thor has ~8 h and a 6.0
GPU-hour budget. Current ask: 4.2. Casey slides it to 5.5 ("leave headroom").

**Feel:** the whole slate transaction ≤ 30 s. The Sims' action-queue taught
the shape — a visible, cancelable list of what agents will do — and
RimWorld's work tab taught the assignment-by-priority feel
([RimWorld](https://rimworldgame.com/)).

- **Fails when:** the ask exceeds the budget. The bar goes red and the builders
  cut their own lists first ("I'll do birch only, 1.2 h"), before asking Casey
  to raise the budget. **Recovery is a proposal, never an error.**

### 21:08 — the limit, and calling the computer **[now: text · later: voice]**

The Architect's line — *real rope isn't in my hands yet* — is the evening's
key move. A character hits the edge of the closed vocabulary and says so, out
loud, in one sentence. Casey, standing on the south span, says:

> "Computer, I want rope bridges that swing."

Eleven seconds later, one line back (compiled from the context packet — the
selection, the camera ray, the conversation, the open budget; vision.md):

> "Rope bridge with real sway for the south span, hempen rope, 8 planks;
> the critic passes it at 2× load before you see it. About 3 hours tonight.
> Go?"

> "Go."

**Feel:** compile ≤ 20 s; the confirm ≤ 25 words; accept is one word. The
order leaves the evening and appears as a card on the **work-order board**
(`#WO-14 · compiling`), and the Architect gets a "coming soon" note pinned to
her vocabulary. Devin's plan-approval beat and Copilot Workspace's
task→plan→implement scaffold are the studied precedents — the human approves a
plan, not a diff ([Devin](https://devin.ai),
[GitHub Copilot Workspace](https://githubnext.com/projects/copilot-workspace/)).

- **Fails when:** the compile is wrong ("3 arches" when he meant the south
  span). The confirm line exists to be cheap to reject — "no, the south span"
  costs one sentence. **Fails when:** it's ambiguous and the computer guesses
  anyway. It must ask ("The south span, or both spans?").
- **Test:** say an order with two plausible referents; the second line must be
  a question, not a plan.

### 21:14 — the handoff **[now: commit · later: cinematic]**

Casey taps **Start the night**. The slate folds into the builders' districts —
[later] they each walk to their patch of Fjellvik, a 10-second beat you can
skip — and the Companion gets the last word:

> "Birch, crates, rope. We'll leave the questions we can't answer at the door
> for you. Goodnight."

World closes on the ProArt at 21:16. **The builders start at 21:20** — and the
scheduler waits for the client to detach before the big batches, so the GPU
belongs to the night (CLAUDE.md: the whole box belongs to this project).

---

## 2. The night — the workshop you may peek at (21:20–06:40)

### 23:04 — one loop in full: the fish-crate bet **[now]**

The night is a long run of small sealed bets (the Vibe Dictionary pattern from
last-mile: predict → seal → test → verdict → keep or undo). The Prop-maker's
crate loop, in full:

1. **Edit** (2 s): a typed vocabulary call, never code —
   `props.harbor.crates: {count: 12, style: weathered, from_library: 6}`.
2. **Predict** (4 s): "Casey keeps 8 of 12. Critic passes texture on 12,
   geometry on 9." The prediction is **sealed** — hashed into the ledger
   *before* any render exists. It cannot be edited after the fact.
3. **Preview** (38 s, workshop clock): six 480p renders through the model
   scheduler, batched with the night's other image-to-3D jobs so the Thor
   never swaps models twice ([now]; measured numbers are the phase-1 spike's
   job).
4. **Critic** (9 s): the vision model reads every render.
   `texture 12/12 · geometry 9/12 · hollow-looking from below: crates 7, 11`.
5. **Act** (1 s): 10 kept, 2 reverted to library crates; the recipe diff is
   412 bytes.

The bet is now *resolvable* — but the drama is held until someone peeks or
morning (below). Nothing in the night requires a human; everything in the
night is *legible to* a human.

### In parallel — the computer's night: WO-14, the rope bridge **[now]**

While the characters work the plan, the computer works the work order in a
sandbox branch: implement → render → critic. Attempt 1 fails the critic at
1.1× load (a snapped rope in the sim). Attempt 2 fails on plank spacing.
Attempt 3 passes at 2.3×. Evidence — the render, the critic's numbers, the
commit — attaches to the card. It is **not** promoted into the vocabulary
yet; it waits as a preview for the morning, exactly like Devin's
session-with-evidence and Copilot Workspace's plan-with-steps, but landing in
a *world*, not a repo.

### 02:07 — the peek **[now]**

Casey can't sleep, opens the night feed on the ProArt (or a phone, read-only
[north star-ish · later]). Join takes 4 s because **the feed is the log, not
the stream** — the durable ledger already exists, so peeking is reading, and
rewind is free. What he sees is not a screensaver; it is a workshop:

- A live card stream, one card per sealed bet: *who · what change · their
  sealed prediction · critic verdict · kept or reverted*, with before/after
  thumbnails. Any card legible in ≤ 5 s.
- The world behind the cards [later]: builders at their districts with their
  current action overhead — "placing crates 10/12" — the way RimWorld shows
  what a pawn is thinking, and The Sims shows the action queue
  ([The Sims](https://en.wikipedia.org/wiki/The_Sims_(video_game))).
- Rewind/replay at any speed (RimWorld's speed keys taught the gesture) — but
  **never fast-forward of live work.** The one dishonesty we refuse: fake
  progress. Animal Crossing keeps the same pact — the world runs on the real
  clock and never pretends you weren't gone
  ([Animal Crossing: New Horizons](https://en.wikipedia.org/wiki/Animal_Crossing:_New_Horizons)).

The best card of the night is already there, waiting:

> **Landscaper · 01:44 · east slope, pass 2 (undergrowth)**
> predicted: "you keep pass 1, revert pass 2 — too busy against the oak"
> critic: pass 2 blocks the oak's drip line · **reverted** · prediction
> sealed 21:32 ✔

He didn't watch it happen; at 02:07 it *reads* like it happened. That gap —
**the story surviving compression** — is the whole craft of the night feed.
Dwarf Fortress and RimWorld generate years of retellable events from terse
logs ([Dwarf Fortress](https://www.bay12games.com/dwarves/),
[Tynan Sylvester, GDC 2017](https://youtu.be/VdqhHKjepiE)); our night must do
the same from recipe diffs and verdict lines.

**Test:** kill -9 the feed server mid-night; reopen. The feed must render from
the ledger alone, complete to the last sealed bet.

### The night's failures and recoveries **[now — all of them, in the log]**

| Time | Failure | Recovery, as the night handles it |
|---|---|---|
| 03:12 | image-to-3D returns crates 7, 11 hollow from below | Critic flags; Prop-maker retries one seed, then falls back to a recolored library crate; parks a note for morning |
| 03:5x | the critic model OOMs during a big texture batch | Scheduler demotes to the smaller local critic for 3 verdicts, marks them `verdict@low-res`, logs it; morning report says so in one line |
| 04:2x | the Landscaper's pass 2 loses the oak's drip line (a constraint!) | Constraint check fails before the critic even runs; auto-reverted; the prediction still resolves — that bet she *lost* |
| 05:0x | budget bar hits 5.5 GPU-hours with the north-lantern batch unrun | Queue stops cleanly at the bar; the batch is re-queued for tomorrow; the report's first line says what didn't get done |
| any | the Thor reboots / power cut | The night is a durable queue; on boot it resumes from the last sealed step; the report states lost time in minutes, never hides it |

Rules that make these *watchable* rather than sad: every recovery is narrated
by the builder who did it, in one line ("Hollow from below. Library crate,
darker stain, done."); every failure produces a card, not an error; and
**no card without an artifact** — a render, a diff, a hash. A night that
cannot show its work did not happen.

### What the builders say at night (the line budget) **[now]**

At most ~6 lines per builder per hour, and **only on state change** — a bet
resolved, a fallback taken, a question parked. No filler, no chatter to seem
alive. The Sims' autonomy works because sims never narrate themselves; ours
get six lines an hour, so each one is worth reading.

---

## 3. The morning — the report, the branches, the call (07:03–07:38)

### 07:03 — the report opens **[now]**

Casey opens the project and gets **the report before the world** — Animal
Crossing's rule: Isabelle briefs you before you're allowed to roam
([Animal Crossing: New Horizons](https://en.wikipedia.org/wiki/Animal_Crossing:_New_Horizons)).
First paint ≤ 3 s (it's a static page over the ledger), and the whole thing is
digestible in ≤ 2 minutes:

- **The night line:** `8 h 20 m · 61 recipe edits · 23 sealed bets · 17 kept ·
  4 reverted · 2 parked · 5.3 of 5.5 GPU-h · prediction score 8/10 (was 7)`
- **The filmstrip:** a before/after scrubber down the east slope and the
  harbor, 60 fps on the ProArt because these are cached renders.
- **Three branches** (below).
- **Two parked questions**, each answerable in one tap.
- **One landed work order:** `WO-14 rope bridge · passed at 2.3× load ·
  preview ready`.

Idle games taught the shape of this screen — "while you were away, X" — but
we take the *honesty* version: nothing appears in the report that wasn't
worked, and the tally includes the bets they lost
([Cookie Clicker](https://orteil.dashnet.org/cookieclicker/),
[Universal Paperclips](https://www.decisionproblem.com/paperclips/),
[idle games](https://en.wikipedia.org/wiki/Idle_game)).

### 07:11 — choosing branches **[now]**

Branch flip ≤ 2 s each — because **the night pre-rendered the comparisons**
(you can't choose what you can't see instantly). Factorio's blueprint library
is the ancestor here: a design becomes a portable, instant-to-apply artifact
([blueprints](https://wiki.factorio.com/Blueprint)).

- **A — Kept line:** conservative forest, clean harbor. *The Landscaper's
  prediction: "you pick this one."*
- **B — Wild wood:** bolder undergrowth, moss to the waterline.
- **C — Magnus's swing:** the rope bridge with full sway.

Casey flips A/B/C three times (6 s), keeps **A**, and Magnus, arriving at
07:19 with no coffee, points at **C**: "that one." Applied in 9 s — branch
choice is a recipe pointer, not a re-render; the world re-streams in ~12 s.

### 07:19 — Magnus and the parked questions **[now]**

The Landscaper's parked card, with two thumbnails:

> "The oak you kept shades my new stream. Move the stream 2 m west, or thin
> the oak? I don't bet on your oaks."

Magnus taps *move the stream*. One tap, one line back: "West it goes. The
frogs will like it." — short words, read-aloud sized, nothing stored about
him beyond the taste label `kid-keeps-wobbly: 3/3`.

### 07:26 — calling the computer again, in-world **[later]**

Casey walks the new bridge in-world, feels the sway, and says:

> "Computer — these sturdier, but keep the sway."

Context packet compiles (selection + camera + last night's WO-14 evidence):
one-line confirm — "Tighter rope, same flex: the critic re-checks at 2× load;
about 40 minutes; go?" — and the run goes to the background **while he keeps
building** with the Architect. Minecraft players leave AFK farms running and
go play elsewhere ([Minecraft](https://www.minecraft.net)); Roblox Studio's
Team Create made "someone else is editing while I edit" feel native
([Roblox collaboration](https://create.roblox.com/docs/studio/collaboration)).
The computer should feel like that: a co-worker whose building is visible as
**ghost scaffolding** beside yours — Factorio's blueprint-ghost and
construction robots are the exact reference: your plan, built by agents,
visible while it happens
([construction robots](https://wiki.factorio.com/Construction_robot)).

### 07:34 — the growth beat **[now in the ledger · later in-world]**

Because WO-14 landed and Casey kept it, the vocabulary gains `bridge.rope`.
The Architect, standing at the north span:

> "I can do rope now. North span too?"

Two ways of growing in one morning: she learned his taste (the ledger ticked),
and the computer extended her hands. The second is the moment builders stop
feeling like tools — see ideation B for the trust half; this brief's claim is
only that the *reveal* of a new skill must be staged like this: in-world, in
one sentence, at the moment it becomes useful.

---

## 4. The ten moments that must feel great (and their latency budgets)

| # | Moment | Latency budget | Tag |
|---|---|---|---|
| 1 | **The recognized return** — first line cites the ledger, ≤ 2 s after world-load; first-run says "first night" honestly | ≤ 2 s | now (text) / later (voice) |
| 2 | **Point-and-say planning** — a spoken intention becomes an editable chip where you pointed, while you're still talking | ≤ 1.5 s per item | later (in-world) · now as text+click |
| 3 | **The one-line work order** — "Computer, rope bridges" compiles to a ≤ 25-word confirm you can veto in one word | compile ≤ 20 s; confirm readable ≤ 5 s | now |
| 4 | **The handoff** — budget bar + "Start the night"; the walk-to-districts beat is 10 s and skippable | transaction ≤ 30 s | now / cinematic later |
| 5 | **The 2 a.m. peek** — join the night feed cold and understand *who did what, kept or reverted* | join ≤ 5 s; each card legible ≤ 5 s; rewind free, no fast-forward | now |
| 6 | **The unseal** — verdict and prediction revealed *together*, thumbnail ≤ 2 s after the critic; the tally ticks in front of you | ≤ 2 s reveal; prediction sealed before render, always | now |
| 7 | **The morning report opens** — before the world; the night in one line; the filmstrip scrubs at 60 fps | first paint ≤ 3 s; whole report ≤ 2 min | now |
| 8 | **The branch flip** — A/B/C with full imagery; choose and apply | flip ≤ 2 s per branch; apply ≤ 10 s; re-stream ≤ 15 s | now (report) / later (in-world) |
| 9 | **"Why?" in one tap** — provenance on anything: prompt, seed, model, licence, critic note, who decided | ≤ 1 s to open the evidence card | now |
| 10 | **The computer lands in-world** — the work order arrives as a preview that was *ready before you got there*; keep/reject on the spot | ready on arrival; keep/reject ≤ 2 s; evidence one click | later (ghost in-world) / now (diff card) |

If we can only make three of these great in phase 4, make them **5, 7, 8**:
the peek, the report, and the branch flip are the loop's promise kept. A night
that was honest (5), legible (7), and cheap to decide on (8) earns the next
evening's plan.

## 5. The screens

### 5.1 In-world view (the ProArt client) **[later]**
The live world, streamed glTF/USD; builders as avatars with their current
action overhead; the plan chips; selection + camera ray feeding the context
packet; the "Computer," call; work-order previews as ghost scaffolding.
Figma's multiplayer is the presence reference — other people's work appearing
where it happens, never in a panel first
([How Figma's multiplayer technology works](https://www.figma.com/blog/how-figmas-multiplayer-technology-works)).

### 5.2 The plan slate **[now]**
The evening's single decision screen: intentions with owners, costs, builders'
one-line takes, one budget bar, Start the night. The Sims action queue +
RimWorld work tab; keep it to one screen.

### 5.3 The night feed **[now]**
The peek and the replay: cards of sealed bets, filter by builder or district,
scrub/rewind at will, live tail when joined. It is a log viewer with taste —
RimWorld letters meets a CI log meets Devin's progress timeline
([Devin](https://devin.ai)).

### 5.4 The morning report **[now]**
Night line → filmstrip → branches → parked questions → landed work orders →
prediction tally. Static over the ledger, so it's fast forever. Shareable as
a permalink (a night is kilobytes — vision.md).

### 5.5 The work-order board **[now]**
Open orders with status (queued / compiling / building / testing / landed /
parked), each with its one-line confirm, its budget, and its evidence
attached as it accrues. The bridge between the world and the computer; shows
the *vocabulary's edges* — what builders asked for that doesn't exist yet.

### 5.6 The asset library **[now]**
Every generated asset with provenance (prompt, model, seed, version) and
licence badge; regenerate, swap model, promote to the shared shelf; the
builders' **skills shelf** (learned recipes, exported as portable skills).
Factorio's blueprint library is the model: instant to apply, cheap to share
([blueprints](https://wiki.factorio.com/Blueprint)); the licence column is a
checked list, not a footnote (CLAUDE.md).

## 6. What makes it fun to watch, not just useful

1. **Stakes from sealed bets.** The prediction is hidden until the verdict;
   the unseal is the beat. You root *against* your own habits sometimes.
   Dwarf Fortress made terse logs dramatic; we make the prediction the drama
   ([DF](https://www.bay12games.com/dwarves/)).
2. **Characters who narrate their own recoveries.** "Hollow from below.
   Library crate, darker stain, done." Failures become character moments,
   not errors — six lines an hour, only on state change.
3. **Legible micro-work.** Every action is a card with before/after. Watching
   = reading; reading = caring. (RimWorld letters; the Sims queue.)
4. **Named specialists with visible taste.** The Landscaper who won't bet on
   your oaks; the Critic who judges at winter dawn. Preferences you can
   learn and argue with — RimWorld pawns and DF dwarves are loved for this.
5. **Presence of the absent.** Overnight work that *would have happened
   anyway* — Animal Crossing's clock, Minecraft's AFK farms, idle games'
   offline earnings — but shown as *work*, not as a number.
6. **The computer builds beside you.** Ghost scaffolding appearing while you
   keep building = Factorio construction robots; the async report you can
   audit = Devin / Copilot Workspace
   ([construction robots](https://wiki.factorio.com/Construction_robot),
   [Copilot Workspace](https://githubnext.com/projects/copilot-workspace/)).
7. **Honest idleness.** If nothing runs, show the workshop dark and the
   builders asleep. A quiet world you trust beats a busy world you suspect.
8. **The morning is a gift, not a queue.** Report before world; three
   branches; one-tap questions; nothing that wasn't worked.
9. **The night is replayable and shareable.** "Watch Fjellvik's Tuesday" as
   a permalink; later, a 60-second timelapse with captions [later].
10. **Growth you can see.** "I can do rope now" lands in-world, at the moment
    it's useful — the payoff of the whole loop.

## 7. Inspirations, what we take and what we don't

| Inspiration | Take | Don't take |
|---|---|---|
| [The Sims](https://en.wikipedia.org/wiki/The_Sims_(video_game)) | watch more than click; visible action queues; autonomy with personality | micromanaging needs meters for builders |
| [Animal Crossing: NH](https://en.wikipedia.org/wiki/Animal_Crossing:_New_Horizons) | real clock; the briefing-before-roaming; change while away, honestly | punishing absence (weeds/shame) |
| [Minecraft](https://www.minecraft.net) | leave-it-running overnight reward; the world as the UI | none — the AFK farm is our night queue |
| [Roblox Studio Team Create](https://create.roblox.com/docs/studio/collaboration) | "others edit while I edit" as a native feeling | its social surface; we need only presence |
| [Dwarf Fortress](https://www.bay12games.com/dwarves/) | story from terse logs; specialists with preferences | unreadable UI; we must stay legible in 5 s |
| [RimWorld](https://rimworldgame.com/) + [GDC 2017 talk](https://youtu.be/VdqhHKjepiE) | story generator, letters, speed controls for replay | cruelty as the fun; ours is a workshop, not a tragedy engine |
| [Factorio blueprints](https://wiki.factorio.com/Blueprint) + [robots](https://wiki.factorio.com/Construction_robot) | recipes-as-items; instant apply; ghosts of things being built | none |
| [Idle games](https://en.wikipedia.org/wiki/Idle_game) ([Cookie Clicker](https://orteil.dashnet.org/cookieclicker/), [Universal Paperclips](https://www.decisionproblem.com/paperclips/)) | offline-progress reveal; the return ritual | fake numbers, engagement farming |
| [Figma multiplayer](https://www.figma.com/blog/how-figmas-multiplayer-technology-works) | presence where the work happens | live-conflict editing; our agents edit a recipe, CRDTs not needed |
| [Copilot Workspace](https://githubnext.com/projects/copilot-workspace/) (research preview, since retired) | task → plan → approve → evidence scaffold | living in the repo UI; ours lands in a world |
| [Devin](https://devin.ai) | async run, progress timeline, session evidence, replay | opaque autonomy; every step of ours must open in ≤ 1 s |
| The holodeck ([Memory Alpha](https://memory-alpha.fandom.com/wiki/Holodeck)) | "Computer, …" with the room already knowing the context | promising it; we ship the compile-and-confirm line, not magic |

## 8. Buildability map

**Now (phases 3–4, plain Python + panels):** recipe store, sealed-bet ledger,
audit log, night queue runner, model scheduler with budget bar; the plan
slate, night feed, morning report, work-order board and asset library as
web/IDE panels (Theia or plain web) over the ledger; the one-line confirm for
work orders as text; prediction tallies; failure narration in the log.

**Later (phase 5, thin client):** the in-world view with avatars and presence;
point-and-say chips; voice in-world; ghost scaffolding for landing work
orders; branch flipping in-world; the morning timelapse; read-only phone peek;
Magnus's read-aloud mode fully voiced.

**North star (design toward, don't promise):** speech anywhere that compiles
to work orders with the room's context; builders interruptible mid-task who
hand work to each other; the night watchable as cinema; skills arriving so
smoothly the vocabulary feels infinite.

## 9. Handoffs to ideation B (trust, taste, growing together)

This brief fixed the *shape* of the night and its latencies. B owns: what the
ledger records on keep/reject; how a builder says "I think you'll like this,
here's why"; surfacing prediction track records over weeks; kid-safety and
privacy (no transcripts); and the anti-sycophancy, anti-spam rules in depth.
One shared constraint crosses both: **the tally only counts sealed
predictions** — a builder's opinion of your taste is only ever scored where it
was committed before the render existed.
