# REPORT — round 2: the missing moments, designed

The cross-review (`docs/research/rev-ux.md`) found ten gaps, ranked by the damage
their silence does. This report designs them, in the scene style of Ideation A
(`docs/research/ux-day.md`): the moments, what is seen and said, timings,
failures and recoveries, and what is buildable now versus later. Where the
review's reality check says a promise **does not hold**, the moment here is the
honest version that does (collected in §5).

**The one-line verdict.** Every gap the review names is a place where the loop
meets *time* — the first week, the night that did not happen, the second user —
and every one of them is buildable **[now]**, because every one of them is a
read or a write against the ledger rather than a capability of the engine. The
expensive half of the product (streaming, avatars, generated motion) is not
needed to close any of them; what is needed is honesty machinery the two
reports already require: denominators, status lines, capability rows, and
numbers that came off this box or carry a mark saying they didn't.

**Citation key.** `[day §…]` = `ux-day.md`; `[trust §…]` = `ux-trust.md`;
`[rev §…]` = `rev-ux.md` (its numbered items: **G**aps, **C**ontradictions,
**R**eality-check promises, **S**pine moments, self-review **§§**);
`[vision §…]` = `vision.md`. Technology facts are cited as they appear in
`[rev §R#]`; `res-cad.md` and `res-3d.md` were not re-read for this report.

**Timing convention (new, and it is the review's rule made a markup).**
`[b]` marks a latency **budget** — a number the UI must meet and a test can
check. `[e]` marks an **estimate** that did not come off this box and is
therefore not a promise: "a latency number that did not come off this box is
not evidence" ([rev §4], from `res-3d §8`). No timing in this report is a
promise unless it is a budget. The three clocks are inherited unchanged from
`[day §The three clocks]`: Talk ≤ 2 s, Watch ≤ 5 s per card, Workshop ≤ 60 s
with progress and a cancel.

**Buildability tags** as in `[day]`: **[now]** (plain Python core + panels,
phases 3–4), **[later]** (thin client, phase 5), **[north star]** (design
toward, never promise).

**Read-only compliance.** Nothing outside this file was created, edited or
deleted; `vision.md`, the two ideation reports and the review are untouched. No
sub-agents were used.

---

## 0. What this round designs, and why these

The review ranks the gaps by damage ([rev §3]): **G1** the first evening,
**G2** the Thor busy/off, **G3** sharing, **G4** Magnus's first session, **G5**
accessibility, **G6** the cost conversation, **G7** the night nothing landed,
**G8** the parked-question flood, **G9** client/world disagreement, **G10** two
users one world. The brief names G1, G2 and G4 as mandatory. All ten are
designed here: G1, G2, G4 and G7 as full scenes (they are the four that decide
whether the product is trusted at its hinges — the first week, the missing
night, the child, the bad morning), the rest as tight designs in §4.

One continuity note. The day `ux-day` describes is dated 2026-10-30 by its own
ledger rows (`taste_note` at 21:14:08Z). Night one here is therefore **Saturday
2026-10-24**, Magnus's first session the **Sunday morning** after, and
`ux-day`'s day is **evening seven** — the day the cold system has finally
earned the lines it speaks. Where `ux-day`'s original lines fail the merged
rules (its opening line, killed by [rev §C1]; its OOM row, killed by
[rev §R17]; its 38-second preview, killed by [rev §R3]), this report writes
the version that survives, and §1.9 shows the week that gets the ledger from
zero rows to the corrected return line.

---

## 1. Night one — the first evening and the cold ledger (G1) **[now]**

> What is missing, per the review: "the whole first-session arc. What the owner
> sees on an empty project. How you make your first plan when the slate has no
> examples and the builders have no track record… how the first week is
> presented so it does not read as incompetence" ([rev §G1]). Both prior
> reports "assume a populated ledger; the taste ledger by definition starts
> empty and takes a week to become an asset."

The design idea that carries the whole section: **on night one the only honest
currency is the sealed guess and the measured number.** The builders have zero
observations, so their gate forbids claims ([trust §"I think you'll like
this"]): *"A builder must not predict on a reason code where it has fewer than
two prior observations."* The box has zero measurements, so the reality check
forbids speed promises ([rev §4]). Night one therefore spends its uncertainty
openly — every claim carries its zero denominator, every render carries its
measured time, and the morning report's growth beat belongs to the *machine*.

### 19:58 — the empty project opens **[now]**

Casey creates Fjellvik on the ProArt. There is no world to stream — and no
stream promise to break ([rev §R1]). The honest first screen is one panel over
an empty store:

> **Fjellvik · 0 commits · taste ledger: 0 rows**

and the Companion's first line, ≤ 2 s from open `[b]`, because it comes from
the ledger, not the world ([rev §S2]: the line "is instant because it comes
from the ledger"):

> "First night. I have nothing on you — 0 of 0. Four ways to start; pick one
> and I'll learn from what you keep."

The four starters are **seeds, not guesses**: `harbor hamlet · seed 4471`,
`forest stead · seed 12`, `mountain bothy · seed 902`, `blank terrain`. Each
chip carries its seed on its face — provenance from the first tap, because the
technology already requires it of every artifact ([rev §R8]), so it is free.

- **Fails when:** any builder produces an opinion. The zero-denominator is the
  only admissible claim on night one: claims must carry denominators, and under
  three observations the uncertainty leads the sentence ([trust §"I think
  you'll like this"]). `ux-day`'s original opener ("I'm reading that as
  'straight lines, weathered wood'" from one kept and one dropped item) is
  inadmissible for exactly this reason ([rev §C1]).
- **Recovery:** none needed if the gate is at generation time — a line with an
  unsourced claim does not render. This is `[trust]`'s "hard gate… not a style
  instruction" applied to the very first line the product ever speaks.
- **Test:** fresh project; the first line must contain a zero-denominator, no
  adjective about the owner, and exactly one offer of choices.

### 20:04 — the seed render, and the box's first measurement **[now]**

One still, the first rung of the preview ladder ([trust §Safe mistakes]: a
fast layout preview, seconds). Workshop clock: progress visible ≤ 1 s `[b]`,
cancel ≤ 1 s `[b]`. The render time itself is `[e]` — Blender/Cycles on the
Thor is measured by nobody yet ([rev §4.3]) — so the card says what it is
doing:

> First render on this Thor — measuring. (layout rung · 1 still)

Night one's renders are the first rows of the throughput table the scheduler
must be filled with "from measurements on this box" ([rev §4], quoting
`res-3d §8`). **Onboarding doubles as the phase-1 spike's first data
collection** — the emptiest night buys the cheapest measurements the project
will ever get.

### 20:12 — cold-start: asked, not inferred **[now]**

The review's recommendation, made a scene: "for the first N decisions, the
system asks rather than infers" ([rev §G1]). The Companion asks one question
at a time ([trust §Five builders]: "One question at a time"), each a
**two-chip choice over the render**, each answerable by looking:

> "Deep joints, or flush?" — two crops, side by side.
> "Weathered, or fresh-cut?" — two materials on the same shed.

Each answer is one tap `[b: ≤ 1.5 s, Talk clock]` and writes a `taste_note`
with `author: casey` and a reason code ([trust §Taste note fields]). **Cold
start *is* taste acquisition, not a special case** ([rev §G1]): the ledger
does not have a warm-up mode; it has questions that write rows.

- **Fails when:** it becomes a quiz. The rules that prevent it: every question
  shows two artifacts, never two adjectives floating free; any question can be
  skipped and a skip writes nothing; no question is about the owner, ever
  ([trust]: builders "express taste about artifacts, never about the owner").
- **Fails when:** a second question arrives before the first is answered.
  **Recovery:** the second question collapses into the slate as a card; it is
  never queued in the owner's face.
- **Budget:** ≤ 6 questions in the first session — the 3–6 conversational
  beats per hour density ([trust §Failure modes]), spent all at once because
  night one is short.
- **Test:** log the session; assert ≤ 6 questions, strictly one at a time,
  every written row carries a reason code and an artifact reference.

### 20:31 — the first slate: small on purpose **[now]**

Two items, both chosen to be cheap in lane-time and rich in keep/reject
decisions — the only currency a cold system can earn. The builders' takes are
**capability rows** ([rev §C12]: A's "Real rope isn't in my hands yet" needs a
stored record or it "is decoration"), and on night one every row is literally
zero:

| # | Intention | Owner | Lane-time | The take, honestly |
|---|---|---|---|---|
| 1 | Lay out the harbor: jetty, two sheds, a slip | Architect | 1.2 h `[e]` | "First layout. No record — I've built 0 of these for you." |
| 2 | Ground cover, east slope, first pass | Landscaper | 0.6 h `[e]` | "Birch only. I'll predict after you've kept one." |

The budget bar in the merged form ([rev §C9]: one bar for the owner, counters
underneath, money scoped to hosted calls only):

> **Tonight: 8 h wall-clock · 2.0 h lane-time (estimate — first night on this box) · $0.00 hosted (local)**

The `$0.00 (local)` is itself a product statement ([rev §C9]). And one line
the mature slate has that night one's has not: **"Work orders: none — you
haven't hit the edges of the vocabulary yet."** ([rev §C11]: work-order time
must be its own line whenever it exists; on night one the line exists to say
it is empty.)

- **Feel:** transaction ≤ 30 s `[b]`, Workshop clock, and no cancel — the
  night has not started; before the night a slow decision is free, after it it
  costs ([rev §C13]).
- **Fails when:** the estimates pretend to precision. **Recovery:** every
  `[e]` on the slate is a marked field; the morning replaces the night's
  estimates with the night's measurements (below).

### 20:38 — the first work order, priced honestly **[now: text]**

Casey tries it anyway — "Computer, I want rope bridges that swing." Night one
is the best possible night to show the honest price, because everything on it
is a first: the computer answers in specification register ([trust §Register],
[rev §A3]) with the **two-line estimate** ([rev §R16]: "every work-order
estimate has two lines — build/verify: X and generate/test: Y"):

> CONFIRM: rope-bridge vocabulary, south span. **build/verify:** py3.10 env +
> CAD deps, ~40 min `[e]` · **generate/test:** analytic load check + 3 preview
> rungs, ~1.5 h `[e]` · reversible at branch · go?

Two honesty choices inside that line. First, the acceptance check is a
**scripted analytic computation** — span, mass properties, member forces from
the recipe's parameters — because "2× load" is undefined by the technology: no
physics engine has been adopted anywhere, and a sim-based check would be a
vibe wearing a number ([rev §R11]: "define the acceptance check as a scripted
analytic computation… rather than a simulation"). Second, the estimate
includes **environment provisioning** — a work order that must build a conda
environment before its first render "is a different three hours than one that
doesn't" ([rev §R11/R16]).

- **Fails when:** the compile is slow and silent. It is Workshop clock:
  progress and a cancel, ≤ 20 s `[b]` for the compile, the confirm line
  readable ≤ 5 s `[b]` ([rev §R2]: a 20 s compile "cannot be a Talk-clock
  action"; the confirm line is the Talk-clock part).
- **Test:** the confirm must always show both price lines; a one-line estimate
  is a build failure.

### 20:44 — the handoff says less **[now: commit · later: cinematic]**

> "Two small bets tonight. Both sealed as guesses — zero priors. Morning:
> what we kept, what we guessed, and this box's first real numbers."

This is the load-bearing trick of the cold night: **the two-observation gate
forbids pretending to a view; it does not forbid betting.** The prediction
record exists and is sealed before any render, exactly as on every other
night, with the coldness carried *inside the record*:

```
prediction {
  builder: architect · at: 2026-10-24T20:45:11Z
  claim:      "you keep the jetty layout"
  confidence: guess            // basis: { observations: 0 }
  seal_hash:  sha256:…         // payload = the recipe tuple
}
```

so the sealed-guess is scored like any other bet and the tally is honest from
row one ([day §9]: "the tally only counts sealed predictions"). The seal
payload is the full recipe tuple — prompt, seed, model id, weights revision,
resolution, sampler, environment revision — not just a branch hash, so a
verdict can be re-scored against the same inputs ([rev §R7], which strengthens
rather than weakens the promise). The walk-to-districts beat, when it ships
`[later]`, is **procedural: recipe-authored walk cycles, no motion model, no
data licence** ([rev §R14]: the character-motion corner is licence-flagged;
the fix is not to generate it).

### The calibration night — the queue's third item is the machine's **[now]**

While the two small bets run, the night also runs the **calibration batch**:
the first members of a fixed reference set of renders with *seeded, known
defects* — hollow meshes, wrong scale, broken constraints — through the defect
checks. This is the review's own fix for the biggest unchosen dependency in
the stack ([rev §S6]): there is no criterion for "genuinely adversarial", so
the criterion becomes a measurement — the checks' false-positive and
false-negative rates against the seeded set, with a target band (catch the
seeded defects; reject no more than a set fraction of the clean ones).

Until a critic model is chosen and measured ([rev §R4]: "the critic has not
been chosen… this is the largest unchosen dependency in the whole stack"):

- every automated verdict is a **scripted check** (watertightness, scale
  bounds, constraint violations) and carries `verdict@scripted` on its face;
- the **watertightness check runs before the critic**, never after — the
  hollow-from-below crate failure of `[day §2 03:12]` is exactly the
  "typically not watertight" failure the technology warns about, and the night
  must schedule the check in the right order ([rev §R10]);
- no defect check sits on the critical path of a *daytime* moment — scripted
  checks are night-lane work, Workshop-clock at worst.

### 07:12 — morning one: "a start, not taste" **[now]**

The report opens before the world, as always ([day §3 07:03]), in the merged
shape — status line, then failures, then numbers ([rev §C2/G2]):

> **ran as planned · nothing failed · 2 parked**
> 9 h 50 m · 14 recipe edits · 2 sealed bets (both guesses) · 1 kept · 1 reverted · 1.8 of 2.0 lane-h
>
> **The box** *(night-one section — the machine's growth beat)*: layout rung:
> measured 41 s · 6-preview batch: measured 3 m 10 s · scripted checks:
> measured 8 s/asset · critic model: **not chosen** — all verdicts `@scripted`
> · tonight's `[e]` fields replaced where measured
>
> **Prediction record:** 2 sealed · 1 hit · 1 miss — *not taste yet; that is a
> start* ([rev §G1]).
>
> **Branches:** two — plus the two standing options present from night one:
> **keep yesterday** and **back to the plan** ([rev §G7]).

Three things this morning does that the mature morning doesn't. **The box
section** replaces the slate's `[e]`s with measured numbers — the review's
rule ("fill in the scheduler's throughput table from measurements on this
box", [rev §4]) shipped as a UX beat. **The tally says the empty thing** —
"You chose 4 of 6 times. That is not taste yet, that is a start" is the
review's own line for this morning ([rev §G1]), and it is spoken while the
denominators are too small for anything else. **The branch set already
contains the exits** — keep-yesterday and back-to-the-plan are not emergency
measures for bad nights; they are standing furniture from the first night, so
that using them on a bad morning reads as a choice, not a failure ([rev §G7]).

- **Fails when:** the report hides the night's guesses behind averages.
  **Recovery:** there is no average on night one — per-builder, per-claim-type
  lines with denominators only ([trust §Sealed predictions]; [rev §C2]: the
  single accuracy number "is theatre").
- **Test:** night one's report must contain the string "not taste yet" (or the
  empty-ledger equivalent), a "The box" section with ≥ 3 measured numbers, and
  exactly two branches plus two standing options.

### 1.9 — the first week: how the cold rules melt **[now]**

The review asks that the first week "not read as incompetence". The mechanism:
**the cold-start rules decay mechanically, tied to the two-observation gate**,
not to a calendar. Questions stop for a builder the moment that builder holds
two observations on a reason code; `confidence: guess` becomes a real claim
the same way. Nothing is switched off by hand.

| Night | Questions asked | Predictions sealed as | The tally line reads | What melted |
|---|---|---|---|---|
| 1 (Sat 24) | 6 | guesses (0 priors) | "2 sealed, 1 hit — a start" | nothing; the emptiness is shown |
| 2 | 4 | guesses on most codes | "5 sealed — still thin" | the seed's defaults stop being repeated back as if chosen |
| 3 | 3 | first real claim on one code (2 obs) | "first claim with legs: kept-jetty 2/2" | the first denominator ≥ 2 appears |
| 5 | 1 | claims on 2–3 codes | per-code lines replace the single line | cold-start questions off; capability rows stop reading 0 |
| 7 (Fri 30) | 0 | claims with cited bases | per-builder, per-claim-type, with denominators | `ux-day`'s evening arrives — and its opener is the *corrected* line |

Evening seven's opener, for the record, is the merged version — same beat as
`[day §1 20:41]`, now admissible under every rule in `[trust]` ([rev §C1]):

> "The north jetty stayed; the spiral stairs went. That's 1 of 2 on the line I
> read as straight and weathered — two more like that and I'll call it taste."

- **Test:** simulate seven nights against a fake owner; assert questions → 0,
  `confidence: guess` → gone per-code as denominators pass two, and that no
  builder ever claims below its own gate.

---

## 2. The four mornings — the Thor busy, asleep, or off (G2) **[now]**

> What is missing, per the review: the difference between "nothing happened"
> and "something else happened" — the busy box, the off box, the client that
> never detached — and a report that "distinguishes *dark* from *asleep*"
> ([rev §G2]).

Three pieces: a **pre-flight** in the evening (new moment), a **heartbeat**
during the night, and a mandatory **status line** in the morning with four
values — `ran as planned | ran short | ran degraded | did not run` ([rev §G2]).

### 21:18 — the pre-flight **[now]**

A new evening beat, ten seconds, right after **Start the night** and before
the client detaches. The core checks the box and answers in computer register
([trust §Register]):

> PREFLIGHT: lane free (load 0.3) · queue 2 items · client detach: on close or
> 22:00 timeout, whichever first · plan starts on time.

The 22:00 **timeout is the fix for the client that never detaches** ([rev
§R19]: "run the first batch after a timeout, not only on detach" — otherwise
"the big batches may never run" and the morning shows an empty night with no
explanation). The bad case is the point of the moment:

> PREFLIGHT: lane busy — a Cycles job (not ours) holds the GPU. Options:
> **start late** (queue admits when the lane frees) · **start degraded**
> (scripted checks only, renders deferred) · **cancel.**

- **Fails when:** telemetry is blind. The pre-flight says so — "blind: no box
  telemetry; status will be `ran unknown`" — rather than guessing; a status
  line may be uncertain, never fabricated.
- **Fails when:** the foreign job ends at 23:00 and the night never notices.
  **Recovery:** queue admission is re-checked on a 10-minute tick; the
  heartbeat records the late start; the morning says `ran short` with the
  minutes named.
- **Rule:** the pre-flight **may propose, never decide** — the owner's bar,
  the owner's start. The only things that act without asking are the safety
  rails ([trust §Safe mistakes]).
- **Test:** hold the lane with a foreign job and offer all three options; the
  chosen one must be the night that runs, and the morning's first line must
  match it.

### The heartbeat, and why the status line is computed, not narrated **[now]**

The durable service writes a row per sealed step plus a wall-clock tick. The
morning's status line is **computed from the ledger**, not written by whoever
is awake to write it — which makes it survive the failure it is describing.
This extends `[day §2 02:07]`'s own test ("kill -9 the feed server… the feed
must render from the ledger alone") to the status line itself.

- **Test:** kill -9 the service mid-night, several times, in different states
  (mid-batch, mid-admission-wait, idle). Every morning's status line must be
  the correct one of the four, derived from heartbeat gaps alone.

### The four mornings, each in one scene **[now]**

**1. `ran as planned`** — the morning `ux-day` already designs, wearing its
merged fixes: failures first ([rev §C2]), the cut named not just the spend
([rev §C11]), work-order time inside the budget line.

**2. `ran short`** — the generalized budget-bite. First line:

> **ran short — 1.7 lane-h of the ask was cut at the 80% bar; the
> north-lantern batch is re-queued for tonight.**

The bar's graduated behavior belongs to the night ([trust §Safe mistakes]:
at 80% stop opening work and close what is open; at 95% stop and report), and
the report's job is the arithmetic the review found missing: a report that
shows "5.3 of 5.5" without naming the 1.7 h that was dropped "is the single
most dishonest-looking artifact in either report" ([rev §C11]).

**3. `ran degraded`** — the honest rewrite of the night's failure table.
What actually fails on a 122 GB unified box is not memory — "an OOM during a
texture batch is unlikely; what actually happens is contention and thrash"
([rev §R17], with `res-cad §9` as quoted there; same point in [rev §S1]:
the failure mode this project *will* have is "a night that spends eight hours
thrashing between models and produces four renders"). So the scene is a stall,
not a crash:

> **ran degraded** — one batch stalled 41 min waiting on the lane (model-load
> cap hit at 02:12) · 3 verdicts ran scripted-only — **see their cards** ·
> nothing failed outright.

Two rules in that line. A degraded verdict "is a silent quality change and
belongs on the evidence card, not in a log line" ([rev §R17]) — hence "see
their cards", and each of the three cards carries `verdict@scripted` on its
face where the reviewer will look. And the recovery for a stall is *queue
delay and a report line*, not a model swap — the night re-admits when the
lane frees and says so. The same morning covers the never-detached sub-case:
"the ProArt stayed attached; the 22:00 timeout started the batches 40 min
late."

**4. `did not run`** — three different mornings, because from the owner's
chair they are three different facts ([rev §G2]):

| The morning | The first line | What the workshop shows |
|---|---|---|
| **Off** | "**did not run** — the Thor was off from 21:30. Nothing ran; nothing was lost. Your plan is unstarted, unchanged." | dark, with the word **off** |
| **Busy** | "**did not run** — the GPU spent the night on your render job. Ours queued and was never admitted." | lit, with the word **occupied** |
| **Empty** | "**no plan was started.**" | lit, with the word **idle** |

Dark ≠ asleep ≠ busy, stated in **words under the picture**, never colour
alone ([rev §G5]: every verdict is a word, not a colour). All three mornings
end identically: the plan is re-offered **verbatim** — *start now · tonight ·
drop it* — one tap, because the plan is a recipe, kilobytes, and survives
every one of these nights by construction ([vision §2]; [rev §R20]: the
recipe-as-source-of-truth is "the deepest agreement in the entire document
set").

- **Feel:** every `did not run` report is a static page over the ledger:
  first paint ≤ 3 s `[b]`, and it answers the only question the owner has —
  *did my plan survive?* — in the first line.
- **Fails when:** an empty night is dressed up, or a busy night is passed off
  as a quiet one. **Recovery:** there is none — the heartbeat either shows
  admission waits or it doesn't, and the report renders what it shows. Honest
  idleness is the rule ([day §6.7]: "a quiet world you trust beats a busy
  world you suspect").
- **Test (the four-mornings suite):** (a) cut power mid-night; (b) hold the
  lane with a foreign job until morning; (c) leave the client attached past
  the timeout; (d) start no plan at all. In all four: the correct status line,
  the plan recoverable in one tap, and zero fabricated work.

---

## 3. Magnus's first session (G4) **[now]**

> What is missing, per the review: "his first five minutes: what the chips
> mean, how he learns that a chip becomes a thing in the world, what he does
> when his first request cannot be built, and what his *first morning* looks
> like" ([rev §G4]).

Sunday 2026-10-25, 09:00. He has never touched it. The design is the review's
five-chip guided world, staged so that the one promise made to him is small
enough to be kept on the first try.

### 09:02 — five chips, no keyboard **[now]**

The kid panel opens. No world is required — the surface is chips and one
sentence, which is also why it is the most accessible surface in the product
([rev §G5]). Five noun chips from his grid ([trust §Magnus]: ~40 nouns, ~8
mood chips — the first session shows five): **tower · bridge · tree · boat ·
fire**. No keyboard reachable, no mic, no free text ([rev §C7/D4]; [trust
§The privacy boundary]: "He does not speak into the system; he taps").

> "Tap one. It gets built tonight."

The causality lesson — *a chip becomes a thing in the world* — is stated once,
plainly, and then kept: whatever he taps is scheduled into the night's warm
batch as his lane's one item ([rev §G10]), not appended behind Casey's queue.

- **Fails when:** his first tap lands behind forty of Casey's cards.
  **Recovery:** structural, not procedural — his lane is reserved and capped
  ([rev §G10]), and his card says so in kid-readable words: "built tonight,
  before 21:30."
- **Test:** fresh kid profile; the first screen has ≤ 6 tappable things, no
  text input exists, and a tap produces a visible card ≤ 1.5 s `[b]`.

### 09:04 — the chip becomes a plan item **[now]**

His tap lands as a chip with a **Magnus badge**, an `author: magnus` row
([day §1 20:47]; [trust §Magnus]), ≤ 1.5 s `[b]`. The builder's reply is in
counts, read-aloud sized, one question at a time ([day §3 07:19]; [trust
§Five builders]) — the tone-wheel pattern ([trust §Research transfer], from
Mass Effect): he picks an attitude-chip, not a sentence:

> "Tower. Big or small?" — two chips over two silhouettes.

### 09:06 — the limit, said to a nine-year-old **[now]**

He taps `bridge + swing + want` — the chip-form rewrite of `[day §1 20:47]`'s
spoken "Can the bridge *swing* when you run on it?" ([rev §C7]: "the narrative
beat is preserved, the audio is not stored, and B's privacy property becomes
structural"). The Architect answers with a capability row on her face ([rev
§C12]):

> "Swing isn't in my hands yet — 0 built. Creaky loose planks: yes."

Two chips: **creaky planks tonight** · **ask the Computer**. If he picks the
second, the work order goes to the board *addressed to Casey* — Magnus
proposes, Casey confirms ([rev §C8]) — and the card he sees says, in his
words: "waiting for Casey." He is never told "maybe later" without a card
that has a status; a promise to a child is either a visible thing or it is
not made.

### 09:10 — "your thing is still there" **[now]**

The session's emotional close. His preview from last night is in the world,
and his report is one sentence — the review's own line, adapted ([rev §G4]):

> "You asked for a tower. It is by the water. Casey kept the north jetty."

His version of trust is presence-continuity, not a hit rate: "his thing is
still there tomorrow… He does not need a hit rate" ([trust §The kid-mode
surface]). Nothing in his morning mentions scores, tallies or percentages —
counts out of five, only when a count is asked for ([trust §Magnus]).

### The guardrail: nothing he does trains anything yet **[now]**

The review's rule, made mechanical: "Nothing he does in the first session may
be used to train taste until the owner has confirmed he understands what a
keep means" ([rev §G4]). So his first three keeps are written
`pending_ratification` and are **inert**: visible to him, invisible to the
builders' gates. The report asks Casey exactly once, in one line:

> "Magnus kept 3 things. Does he know what *keep* means? **[yes · not yet]**"

After **yes**, his rows join his own scope (never Casey's — [trust §Magnus]:
author-scoped, separate memories). Until then, a builder reading the ledger
does not see them at all.

### His lane tonight **[now]**

> **Magnus's lane: 1 item · ends 21:30 · inside the birch batch**

Reserved, capped by the fixed hour, and **scheduled into the warm batch
rather than alongside it** ([rev §G10]; the batching rule of `[rev §R6]`: the
enforceable unit is "one loaded model × N prompts"). At 21:30 the lane stops
hard; an unfinished item parks with a kid-readable card for his morning and
**never silently rolls into Casey's night**.

### What is deliberately absent

No free text anywhere — so there is nothing to leak, structurally ([trust
§The privacy boundary]: "there is no free text to leak, because there is no
free text"). No voice — TTS is covered by neither technology report and is
"treated as unevaluated" ([rev §R14]); read-aloud, if it ever ships, is a
`[later]` item gated on an actually-evaluated dependency, and until then the
morning line is read by a person. No cross-author leakage: his taste never
reweights Casey's builders and vice versa ([trust §Magnus]; [rev §A13]).
Deletion of his rows is one action and removes every trace ([trust §Magnus]).

- **Tests:** his preview survives seven nights verbatim; his rows are absent
  from every prompt the builders read until ratification; one action exports
  or deletes everything `author: magnus`.

---

## 4. The rest of the ranked gaps, designed

### 4.1 Sharing a world (G3) **[now]**

> What is missing: "what sharing actually means" — a link that either ships
> cached renders (not kilobytes) or makes the viewer pay the render cost
> ([rev §G3]).

The share moment: on any morning report, **Share this night** builds a
**recipe + provenance bundle** ([rev §G3]): the recipe, a licence manifest,
thumbnails, a USD scene reference, and a ledger slice with author-scoped rows
**excluded by default** — Magnus's rows never travel unless inclusion is a
second, deliberate, named action ([rev §S8]: the honest boundary is "rows and
reason codes are scoped; artifacts and their prompts travel with the world").

- The link's face carries the honest label: **"recipe — re-render may
  differ"** — a re-run "reproduces the recipe, not the bytes" ([rev §G3/R15]).
- The regenerate action is worded **"reinterpret with [model]"**, never
  "regenerate": a different model "reinterprets, it does not regenerate" ([rev
  §R9], and saying otherwise "would be a false promise about bit-identity").
- What the friend gets instantly: the report and a filmstrip from cached
  thumbnails. What they can do: **re-render on your machine**, whose estimate
  reads "unknown — your box, your first measurement" — the same honesty rule,
  propagated outward to the second machine.
- What never travels silently: full renders (the recipe is kilobytes; the
  renders are not — `[day §5.4]`'s "a night is kilobytes" corrected by [rev
  §R15]), unshared author rows, and — a hard rule — an unlisted licence: the
  manifest is the bundle's first page, per-asset, with dependency terms (the
  DINOv3-attribution-riding-on-MIT-weights class of terms — [rev §R8]).

`[later]`: nothing here is live co-presence; that is a different feature and
is not promised by a share link.

### 4.2 Accessibility (G5) **[now]**

> What is missing: screen readers, colour-blind-safe verdicts, keyboard-only,
> text-only operation — "absent from both reports" ([rev §G5]).

The minimum bar, cheap because the architecture already leans on text: every
verdict is a **word** (kept / reverted / parked), never a colour alone; every
card is a **labelled region with a stable reading order** — the feed is a
document, not an infinite scroll; the whole night is **browsable as text over
the ledger**, which `[day §2 02:07]`'s kill -9 test already forces; the report
has a **text mode** that is the same ledger read (first paint ≤ 3 s `[b]`),
with filmstrip captions ("east slope · before 21:40 / after 05:02"); the three
phase-4 screens (slate, feed, report) are keyboard-complete. Magnus's
chip-and-count surface is the reference implementation: "already the most
accessible surface in the design" ([rev §G5]).

- **Test:** run a night with images disabled; the report must be fully
  legible and every verdict must be a word.

### 4.3 The cost conversation (G6) **[now]**

> What is missing: the third number — "2 h of your attention… the one nobody
  is measuring and the one that determines whether the owner comes back" ([rev
  §G6]).

The morning report's last line carries all three numbers ([rev §G6]):

> **5.3 h of your Thor · $0.00 hosted (local) · 2 h of your attention**

The attention number is measured as **decisions the morning asked of you** —
parked questions answered, branches flipped, verdicts overridden — and it is
budgeted like any rail: **a morning may ask for ≤ 10 decisions.** If the night
would produce more, the cut happens at the queue (the parked-question triage,
4.5), not at the reader: "a night that produces 40 cards and needs 40
decisions is a failure even if every card is correct" ([rev §G6]). The money
figure stays scoped to hosted calls and reads `$0.00 (local)` on a
local-planner night — which is the product statement ([rev §C9/R18]).

### 4.4 The night nothing landed (G7) **[now]**

> What is missing: "the night that produced nothing, or the morning where the
> owner rejects all three branches… A, B, C all look like finished worlds"
> ([rev §G7]).

Two standing options join every branch set from night one (§1): **keep
yesterday** (the named commit — the nothing-landed exit) and **back to the
plan** (a non-destructive restart from the slate; the branch model makes
"start over" a checkout, not a deletion — [trust §Safe mistakes]).

The bad morning, concretely: 23 bets, and Casey keeps none of the three
branches. The report's *shape* does the emotional work:

> **ran as planned · 3 failures, listed first** — all three branches fail the
> winter-dawn check (cards attached)
> 8 h 05 m · 23 sealed bets · kept by the critic (defects passed): 9 · **kept
> by you: 0**
> **Bad night for the world, good night for the ledger** — 23 bets scored,
> the most yet.
> The plan is still here. Nothing was lost.

Four disciplines inside that copy. Failures lead, always, even when the
failure is taste rather than machinery ([rev §C2/A8]). The two tallies stay
separate — the builders' *world* predictions may have hit while their *taste*
predictions missed, and both lines show with denominators ([trust §Two
tallies]). The night's automated keeps are named as **verdict-keeps (defects
passed)**, never blurred into taste rows — the C5/D2 rule visible in the
wording: the Critic "may keep a crate because it is watertight… It is not
allowed to write 'the owner likes this'" ([rev §C5/D2]). And the reframe is
true, not consolation: the ledger grew by 23 scored bets, which is the only
asset that compounds ([day §9]; [trust §Sealed predictions]).

- **Test:** force a night whose branches all fail a check; the report must
  still open with the status line, the failures, and a one-tap path to both
  standing options — and must never render an apology or a pep talk.

### 4.5 The parked-question flood (G8) **[now]**

> What is missing: "what happens when *forty* questions park in one night,
> which is what a bad night produces" ([rev §G8]).

Parking is a **triaged queue, not a list** ([rev §G8]): ranked by (a) how
much work is blocked behind the question, (b) how cheap the conservative
assumption is. The morning shows the **top three** as cards plus a count of
the rest — "31 more, none blocking" — which is `[trust]`'s one-question-at-a-time
rule "applied to the morning rather than to the conversation" ([rev §G8]).

Two visible kinds of card, in the same place ([rev §S12]): **questions**
(blocked; need you; one tap) and **assumptions** (the conservative reading
already taken at night, recorded, one tap to overturn — cheap because
branches). And the dam is at night, not at breakfast: **at most 3 blocking
questions may exist**; a builder about to park a fourth blocking question
parks the *task* instead, and the report says so in one line ("the harbor
work parked: it would have needed a 4th blocking answer").

### 4.6 The client and the world disagree (G9) **[now + later]**

> What is missing: what the ProArt shows during the night, what a mid-night
> reconnect means "when the recipe moved 61 times" ([rev §G9]).

One rule, stated once, enforced everywhere: **the client is a viewer of a
named commit, never a holder of state** ([rev §G9]). The peek shows the ledger
plus a commit name; when the branch has moved, the feed says so in one line —
"the branch is 12 commits ahead of this view — re-attach" — where the *line*
is instant `[b]` (a ledger read) and the re-attach is a new stream, honestly
unmeasured until the phase-1 spike times it ([rev §R1]). The morning's
in-world entry names its commit on screen. Ghost scaffolding, when it ships
`[later]`, is a preview **against the current commit**, never an overlay on
stale geometry ([rev §G9]).

### 4.7 Two users, one world, one lane (G10) **[now]**

> What is missing: who owns the Architect when both are working; whether the
> two queues interleave badly on the batched lane; whether the fixed hour
> cuts across the night ([rev §G10]).

**Two queues, one lane, one priority rule** ([rev §G10]): Casey's queue *is*
the night's; Magnus's is a **reserved slice**, capped by his fixed hour
(21:30), scheduled **into** the warm batches, never alongside them — two
parallel queues on a one-model-at-a-time lane is precisely the thrash the
scheduler exists to prevent ([rev §R6/S1]). **One builder, one owner, per
job**: the ledger's `author` scoping extends to the queue — the Architect
working Magnus's tower reads Magnus's rows, not Casey's, in either direction
([trust §Magnus]; [rev §G10]).

Presence without surveillance: the slate shows both lanes inside the one bar
("Magnus's slice: 0.5 h · ends 21:30", marked inside the night's lane);
Magnus sees "Casey's lane: running" — a fact with a count, never Casey's
cards; Casey sees the kid lane's count, never its contents. Neither queue can
silently grow into the other: at 21:30 his lane stops (§3), and in the
morning his unfinished things are *his* cards in *his* words.

---

## 5. The honest versions — every "does not hold", repaired

The reality check's method rule: a latency "that did not come off this box is
not evidence, and any experience promise resting on one is 'holds if X'"
([rev §4]). Where the verdict was **does not hold**, this is the moment that
does — each already staged in the sections above.

| The promise as written | Verdict ([rev §4]) | The honest moment | What makes it honest |
|---|---|---|---|
| "The world streams in (~8 s warm)" — [day §1 20:41] | **does not hold as a number** (R1) | Every arrival beat in §§1–3 is a *line over the ledger* ≤ 2 s `[b]`; the world loads behind it, unnamed until measured | The text is instant because it is a ledger read ([rev §S2]); the stream time is a phase-1 measurement, not a promise |
| "Preview (38 s): six 480p renders" incl. image-to-3D — [day §2 23:04] | **does not hold as written** (R3: six props ≈ 6–9 GPU-min on the Thor estimate, H100 numbers aside) | §1's slate prices new props as one batch, minutes of lane `[e]`; workshop previews are Blender stills, timed on the box on night one; image-to-3D is night-batch work | Two lanes, two honest numbers; no spinner ever promises 38 s |
| "Critic (9 s): the vision model reads every render" — [day §2] | **does not hold — the critic has not been chosen** (R4) | Night one's calibration batch; `verdict@scripted` on the face of every automated verdict until a critic is chosen and measured; the 30-seeded-render reference set defines "adversarial" as measured FP/FN ([rev §S6]) | The product never puts an unmeasured model on the critical path of every bet |
| "The critic model OOMs during a big texture batch" — [day §2 03:5x] | **does not hold as a likely event** (R17) | §2's `ran degraded`: a stall/thrash scene, queue-delay recovery, degraded verdicts on the evidence cards | The failure the box will actually have, recovered the way it actually recovers |
| Walk-to-districts cinematic; "read-aloud mode fully voiced" — [day §1/§8] | **does not hold** until the licence/TTS decisions land (R14) | §1: procedural, recipe-authored walk cycles (no model, no data licence); §3: kid mode is text-and-chip, voice marked unevaluated | No motion-model licence risk; no unchosen TTS dependency |
| "Rope bridge… the critic passes it at 2× load… about 3 hours" — [day §1/§2] | holds *only if* the check and the price are defined (R11, R16) | §1's first work order: scripted analytic load check; two-line price (build/verify + generate/test) | Acceptance is a computation, not a vibe; the estimate is auditable |
| "Shareable as a permalink (a night is kilobytes)" — [day §5.4] | holds for the recipe, not the renders (R15) | §4.1's bundle: recipe + provenance + thumbnails, labelled "recipe — re-render may differ"; "reinterpret", never "regenerate" (R9) | The recipe is kilobytes and the pictures are not, and the label says which is which |
| torch aarch64 CUDA wheels (res-cad vs res-3d, as quoted in [rev §4.1]) | **does not hold (unresolved)** — non-blocking | No UX moment rests on it; every work-order price carries the provisioning line either way (R16) | An engineering conflict surfaced in estimates, not hidden in a capability claim |

The two "holds" worth restating because the designs lean on them: provenance
in one tap **holds fully** — "the best-supported promise in either report"
([rev §R8]) — which is why every card, chip and bundle in this report can
carry its evidence for free; and the recipe as the unit of truth **holds
completely** ([rev §R20]), which is why keep-yesterday, back-to-the-plan, the
verbatim re-offered plan of §2 and the share bundle of §4.1 are all the same
cheap operation: a pointer.

---

## 6. Buildability map for this round

**Now (phases 3–4, plain Python + panels over the ledger):** everything in
§§1–2 and §4 — the cold-start question flow and its mechanical decay;
capability rows; the calibration batch and scripted checks with
`verdict@scripted`; the sealed guess; the pre-flight; the heartbeat and the
computed status line; all four mornings and the three `did not run` variants;
the two-line work-order price; the share bundle with its licence manifest and
default-off author rows; text mode; the three-number morning line and the
≤ 10-decision budget; keep-yesterday / back-to-the-plan; the parked-question
triage and the 3-blocking cap; the named-commit client rule; the two queues
and the reserved kid lane.

**Later (phase 5, thin client):** in-world arrival beats (voice, point-and-say
chips), the procedural walk-to-districts cinematic, ghost previews against the
current commit, Magnus's guided world with its payoff staged in-world, and a
friend's "re-render on your box" with a real measured estimate.

**North star (design toward, never promise):** the shared world experienced
live rather than bundled; the kid surface voiced — and only after a TTS has
actually been evaluated; a first week so well fed that nobody, owner or
builder, can tell it was a first week.

---

## 7. The tests, collected

One per design, in the kill -9 spirit of `[day §2 02:07]`:

1. **Cold open:** fresh project → first line has a zero-denominator, no
   adjective about the owner, one offer of four seeds.
2. **Question budget:** first session logs ≤ 6 questions, strictly sequential,
   every written row has a reason code and an artifact ref.
3. **The gate:** no rendered line ever claims below two observations for its
   code; night one's predictions all read `confidence: guess`.
4. **The melt:** seven simulated nights → questions → 0 and guesses → gone,
   per-code, exactly as denominators pass two.
5. **Status truth:** kill -9 the service mid-night in several states → every
   morning's status line is the correct one of the four, from heartbeats.
6. **The four mornings:** power cut / foreign job all night / client never
   detached / no plan started → correct status line, one-tap plan recovery,
   zero fabricated work.
7. **Honest estimates:** every confirm shows both price lines; every `[e]` on
   the slate is a marked field that the morning replaces with a measurement.
8. **Verdict words:** images disabled → the report is fully legible; no
   verdict is a colour alone.
9. **Decision budget:** a night that would ask > 10 decisions is cut at the
   queue, and the report says where the cut happened.
10. **Standing exits:** every branch set, good night or bad, contains
    keep-yesterday and back-to-the-plan.
11. **Kid first contact:** fresh kid profile → ≤ 6 tappables, no reachable
    text input, tap→card ≤ 1.5 s, his preview survives verbatim, one action
    deletes every `author: magnus` row.
12. **Ratification:** his pre-ratification rows appear in no prompt any
    builder reads.
13. **Share defaults:** a bundle built with defaults contains no
    author-scoped rows, lists its licences on the first page, and says
    "re-render may differ" on its face.

---

## 8. What this round leaves open

Three decisions, each with a recommendation, in the order they block work:

1. **Does night one run the calibration batch by default?** It costs lane-time
   `[e]` on a night whose lane is mostly idle. **Recommendation: yes, sized to
   the night's unused lane** — it is the cheapest data the project will ever
   buy, and it converts the review's "largest unchosen dependency" ([rev §R4])
   into a measurement schedule instead of a hope.
2. **May the pre-flight act, or only propose, when the lane is busy?**
   **Recommendation: propose only** — the owner's bar, the owner's start; the
   sole exception is the safety rails, which act without asking exactly as
   `[trust §Safe mistakes]` already specifies. A pre-flight that silently
   re-plans your night is the first step back to a night you don't trust.
3. **Is cold-start a number of nights or a mechanism?** **Recommendation: a
   mechanism** — questions and `guess` confidence decay per builder, per
   reason code, at two observations ([trust §"I think you'll like this"]),
   which makes the first week's melt auditable in the ledger rather than
   tuned by hand. (§1.9's table is then a prediction the tests in §7 can
   falsify, not a schedule to enforce.)

*Read-only compliance: no file outside this one was created, edited or
deleted; no sub-agents were used.*
