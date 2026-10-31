# REVIEW — round 2: the two experience reports, against each other and against the technology

Cross-review of Ideation A (`ux-day.md`) and Ideation B (`ux-trust.md`), checked
against `res-cad.md` and `res-3d.md`. Written by the author of B. Read-only:
nothing outside this file was changed.

**Citation key.** `[day §…]` = `docs/research/ux-day.md`; `[trust §…]` =
`docs/research/ux-trust.md`; `[cad §…]` = `docs/research/res-cad.md`;
`[3d §…]` = `docs/research/res-3d.md`; `[vision §…]` = `docs/vision.md`.

**Method and honesty note.** `res-3d.md` landed while this review was being
written (it appeared at 22:22, after `res-cad.md` had been read), so it *is*
included here — it changes three verdicts in §4. `casey-ideas-fromgoogle5.md` is
not part of the brief and is not used as evidence. Section references without a
line number are the reports' own headings. Where I quote, the quote is verbatim.

**The one-line verdict.** A and B agree on the *architecture* of the loop and
disagree on the *governance* of it — who may speak, who may write, who may
approve, and what the first line of the morning says. Those disagreements are
all resolvable, but one of them (C5, who writes taste) will corrupt the ledger
if it is left implicit. Against the technology, roughly half the latency
promises in A are unmeasured placeholders that B's evidence discipline would
have caught: `res-3d` §8 states the rule both experience reports needed and
neither had — *"Do not schedule against the published numbers. Fill in the
scheduler's throughput table from measurements on this box."*

---

## 1. Agreements — what both reports independently converge on

These are the strongest candidates for the plan, because two reports written
from different briefs, different evidence bases (games literature vs.
trust/privacy literature) and different scopes arrived at the same place.

### A1. The prediction is sealed before the render exists, and only sealed predictions count

`day` §2 (23:04) makes it step 2 of the loop — *"Predict (4 s) … The prediction is
**sealed** — hashed into the ledger before any render exists. It cannot be edited
after the fact"* — and §9 closes with the shared constraint: *"the tally only
counts sealed predictions — a builder's opinion of your taste is only ever scored
where it was committed before the render existed."* `trust` §Sealed predictions
fixes it as the load-bearing convention (*"Vision already fixes the load-bearing
convention: seal the prediction before the test"*), adds `seal_hash` to the
schema, forbids self-scoring (*"Self-scoring is a sycophancy vector and is not
permitted"*), and resolves the verdict by the Critic against the sealed hash.

**Why this is the strongest convergence.** It is the one rule that makes every
other number in both reports meaningful. `[3d §5]` independently justifies it:
a re-run reproduces *the recipe*, not the bytes, so the only honest anchor for
"what was promised" is a pre-committed artifact reference.

### A2. Ambiguity is asked about, never guessed

`day` §1 (20:47): *"The slope, or the whole east shore?" — one tap. **Never
guess**"*, and §1 (21:08): *"it must ask ('The south span, or both spans?')"*,
with a test attached (*"say an order with two plausible referents; the second
line must be a question, not a plan"*). `trust` §The open-question policy takes
the same rule and then solves the problem A never states: the question is that
most questions cannot be asked at 3 a.m., so the night has exactly two channels —
**park it** (a named question attached to a branch) or **assume the conservative
reading** (and record the assumption in the report so you can see it was made).

**Merged value.** A gives the interaction; B gives the night-time closure. This
is the clearest case where the two reports are complementary rather than
competing.

### A3. The computer is a separate authority from the characters, with no personality

`day` §1 (21:08) and §2 ("the computer's night: WO-14") keep the computer
distinct: it compiles a line, it takes a *"Go?"*, it works in a sandbox branch,
it lands as a preview with evidence, and it is *not* promoted into the
vocabulary on its own. `trust` §Telling the computer apart from the crew gives it
four separations — **register** (specification, not first person: *"It never says
'I think' or 'I found'"*), **presence** (*"The computer has no face"*), **authority**
(it can extend the vocabulary; characters cannot), and **disclosure** (keep it
visibly a machine). `trust` adds the routing rule: *"the owner names a want, not
a layer"*, and the computer only surfaces *"as a priced order rather than a
personality."*

**Convergent in substance, different in vocabulary** — which is the sign of a
real convergence rather than a shared source.

### A4. Approval is a measurement, never a currency, and nobody praises the owner

`day` §2 hides the prediction so the unseal is the drama, §4 moment 6 makes the
tally tick in front of you, and §6.1 calls the stakes *"the prediction is the
drama"* — but `day` never states the principle. `trust` §Taste without
sycophancy states it flatly: *"builder-ide has no approval meter. A builder
never accumulates your regard… When a builder's work survives your judgement,
that is data. It is never a reward,"* plus the ban on praise and the rule that
builders must not agree before evaluating (*"Make it bigger" gets "bigger, or
heavier?"*).

**Note the one thing A has that B lacks:** A actually dramatises the principle
(moment 6, "the unseal") rather than only asserting it. B's rule is better; A's
scene is better. Keep both — see S6 in §5.

### A5. The Critic is a separate, adversarial, non-authoring role

`day` §2 (23:04) gives the Critic its own timed pass over every render
(*"Critic (9 s): the vision model reads every render"*) and gives it the
constraint checks (*"Constraint check fails before the critic even runs"*) and
the failure of record (*"Critic flags; Prop-maker retries one seed"*).
`trust` §Taste without sycophancy: *"The Critic never compliments and never
authors. It returns `hold`, `fix`, or `keep`, a reason code, and at most one
suggested change. Its whole value is that it is not the person who wanted the
change."* `trust` §Five builders: the Critic's row is *"Nothing at all; it only
reviews and scores."*

### A6. Everything runs on a branch; the world is a named commit; undo is a checkout

`day` §2 (23:04) ends each bet with *"the recipe diff is 412 bytes"*, and
§3 (07:11) makes the branch choice *"a recipe pointer, not a re-render"*.
`trust` §Safe mistakes: *"Every step runs on a branch; the world is always a
named commit. Recipes are already diffable and replayable… undo is a checkout,
not a deletion, and a rejection is a branch you can revisit, not a hole in the
ground. Nothing is destructive, which means the failure mode of a wrong night is
confusion, not loss."*

**Technology backing:** `[cad §8]` says the same thing from the format side —
*"the recipe (our own typed format) is the source of truth; USD is a compiled
output and assembly cache"* — and `[3d §5]` says the recipe is *"the honest unit
of reproducibility."* Three documents, one rule.

### A7. Budgets are set before the work, and the queue degrades rather than overruns

`day` §1 (21:02) puts the budget bar in the owner's hands *before* the night
(*"tonight the Thor has ~8 h and a 6.0 GPU-hour budget. Current ask: 4.2. Casey
slides it to 5.5 ('leave headroom')"*) and makes the builders cut their own
lists first (*"the builders cut their own lists first… before asking Casey to
raise the budget. **Recovery is a proposal, never an error.**"*). `day` §2
(05:0x) shows the queue stopping cleanly at the bar and re-queueing for
tomorrow. `trust` §Safe mistakes gives it a hierarchy — per-cycle, per-task and
per-night rails, *"enforced before the spend, not alerted after"* — and adds
graduated throttling at 80% and 95%.

**Technology backing:** `[cad §9]` makes batching by model the mechanism that
makes a rail enforceable at all — *"hundreds of prompts through one loaded
model, not one load per prompt."*

### A8. Failures are first-class, visible, and carry an artifact

`day` §2: *"every recovery is narrated by the builder who did it, in one line"*
and the hard rule *"**no card without an artifact** — a render, a diff, a hash. A
night that cannot show its work did not happen."* `trust` §Safe mistakes: *"The
nightly report opens with what failed, what was parked, and why, before any list
of successes. A night where three things failed and nine succeeded is a bad
night, and it should read like one. If nothing failed, the report says so in the
first line, because a report that only ever shows good news teaches you to skim
it."*

**The convergence is on the principle; the two reports then disagree on the
first line of the screen** — see C2.

### A9. Provenance is a first-class citizen, not a feature

`day` §4 moment 9 (*"'Why?' in one tap — provenance on anything: prompt, seed,
model, licence, critic note, who decided"*, ≤ 1 s) and §5.6 (the asset library's
licence badge, regenerate, swap model). `trust` §Taste note fields (*"The
artifact reference, not the conversation"*, `artifact_ref: branch_07f2@c41a9e3`)
and §Research transfer (the ledger *"is the only thing that gets read into a
prompt"*).

**Technology backing, and this is the strongest of all the convergences:**
`[cad §9]` (*"it stamps every artifact (prompt, model id, weights repo+revision,
seed, library versions, wall-time, licence)"*) and `[3d §5]` (*"Every asset should
carry the prompt, the model and weights revision, the seed, the sampling
parameters, the output format, the licence string… and the environment revision
of the Thor that produced it"*). See R8 — this promise **holds**, with two fields
added.

### A10. The night must survive compression: a terse log has to read as a story

`day` §2 (02:07): *"He didn't watch it happen; at 02:07 it *reads* like it
happened. That gap — **the story surviving compression** — is the whole craft of
the night feed,"* with the Dwarf Fortress / RimWorld precedent. `trust` §The
trust stack's middle layer is **legibility** (*"Do I understand what happened?"*
→ *"Sealed prediction cards, receipts, the nightly report"*) and §Numbers that
reach the artifact requires the record to arrive *attached to the thing* rather
than on a dashboard you visit.

### A11. Honest idleness: no fake progress, no fast-forward, no cheerleading

`day` §2 (02:07): *"**never fast-forward of live work.** The one dishonesty we
refuse: fake progress"*; §6.7: *"Honest idleness. If nothing runs, show the
workshop dark and the builders asleep."* `trust` §Failure modes → dependency
creep and spam: *"no builder comments on your absence, your schedule, or how long
you have been away."*

### A12. The builders have fixed, distinct voices; the Companion keeps the plan and asks one question at a time

`day` §1 (20:41, 20:47, 21:02, 21:14) gives the Companion the plan-keeping and
the conversation role and gives each builder a speciality and a one-line take.
`trust` §Five builders and one computer specifies it as a table — speciality,
what it may change, voice rules, what it never says, what it disputes about —
and §Failure modes adds *"the Critic authors nothing; one question per turn."*

### A13. Magnus is a separate surface with author-scoped records and a hard privacy boundary

`day` §1 (20:47) gives him a badge on his chips and rules that *"nothing about
him is stored beyond taste labels, and his words are never quoted in the
report"*, and §3 (07:19) records the label `kid-keeps-wobbly: 3/3`. `trust`
§Magnus at the controls specifies the chip grid (~40 nouns, ~8 mood chips), the
author-scoped rows, one-action export and deletion, the counts-not-percentages
rule, and §The privacy boundary: *"Nothing Magnus says is retained as text. He
does not speak into the system; he taps."*

**Convergence on the principle, direct contradiction on the mechanism** — C7.

### A14. Licence is a checked list, never a footnote

`day` §5.6 (*"the licence column is a checked list, not a footnote"*), `trust`
throughout (every ledger row, every asset, every model), `[vision §]` (*"Licences
are a checked list"*), and both technology reports make it concrete:
`[cad §3]` (FLUX.1-dev non-commercial → skip; SDXL OpenRAIL++-M OK; Poly Haven
and ambientCG CC0 → adopt now), `[3d §3]` (a whole licence register, including
the two dependency licences nobody sees: nvdiffrast commercial-OK, **nvdiffrec
research-only**, and DINOv3's attribution and end-use terms riding along with
MIT weights).

### A15. The evening plan is one screen, and the night is handed over deliberately

`day` §1 (21:02, 21:14): one slate, one budget bar, one button; the builders
start at 21:20 and the scheduler *"waits for the client to detach before the big
batches."* `trust` §Research transfer: *"Plan Mode, which shows the plan up
front and lets the human edit and approve the whole thing, shifting oversight
from the individual step to the overall strategy [5], is the morning-plan
interaction, and it is the same move."*

**Convergence, with a gap** — neither report says what happens on the *first*
night, when there is no plan to approve (G1).

---

## 2. Contradictions — where they differ, with a recommendation and why

Ordered by how much damage they do if left unresolved.

### C1. The Companion may not comment on your absence — which kills A's best opening line

- **A** §1 (20:41) opens with: *"You're back. Yesterday you kept the north jetty and dropped the spiral stairs — I'm reading that as 'straight lines, weathered wood.' Want me to push that line tonight, or are we changing course?"*
- **B** §Failure modes → dependency creep: *"No builder misses you, or becomes the thing you talk to"*; §Taste without sycophancy: *"**the builders express taste about artifacts, never about the owner.** No builder asks how you are doing. No builder misses you."*; §The spam rule: *"no builder comments on your absence, your schedule, or how long you have been away."*

**The collision is three-way, not two-way.** "You're back" is a comment on
absence; "I'm reading that as 'straight lines, weathered wood'" is an inference
from *one* kept and *one* dropped item — which B's fourth rule forbids
outright: *"A builder must not predict on a reason code where it has fewer than
two prior observations"*; and the line carries no denominator, which B's
utterance rules require (*"It must carry its own denominator"*).

**Recommendation.** Keep A's scene, rewrite A's line, and narrow B's rule to its
real target. B's ban exists to prevent *dependency* — the builder as confidant.
A greeting is not dependency; it is recognition, which A §1 (20:41) explicitly
requires to be *"a fact, not a greeting"*. So: **ban longing and absence-duration,
not recognition.** The corrected rule: *"No builder comments on how long you have
been away, expresses longing, or asks how you are. It may state what changed in
your absence, with a count."*

And the corrected line for 20:41 — same beat, now admissible:

> "The north jetty stayed; the spiral stairs went. That's 1 of 2 on the line I
> read as straight and weathered — two more like that and I'll call it taste."

That one sentence satisfies B's denominator rule, B's two-observation gate, A's
"cite something real from the taste ledger", and B's ban on praise and on
absence commentary. **This is the single most valuable merge in the two
reports**, because it is the moment the product is judged on and both drafts
currently fail it for opposite reasons.

### C2. What the morning report leads with — and the one number both reports must kill

- **A** §3 (07:03) leads with the **night line**: *"8 h 20 m · 61 recipe edits · 23 sealed bets · 17 kept · 4 reverted · 2 parked · 5.3 of 5.5 GPU-h · prediction score 8/10 (was 7)"*, then the filmstrip, then the three branches, then the parked questions, then the landed work order.
- **B** §Safe mistakes: *"The nightly report opens with what failed, what was parked, and why, before any list of successes."*

These are directly opposed about the first thing on the screen. And A's line
contains a number that B explicitly calls theatre: *"A single accuracy number per
builder is theatre, because a builder can be excellent at reading scale and
hopeless at counting shadows, and one number hides exactly the information you
need."* A's *"prediction score 8/10 (was 7)"* is exactly that number — one score,
untyped, undifferentiated, and compared against last night's score.

**Recommendation.** Split the first line into two lines and put the failure line
first. The report should open:

> **3 things failed, 2 are waiting for you.** ← first line, always present, even when it is "nothing failed"
> **8 h 20 m · 61 edits · 23 bets · 17 kept · 4 reverted · 2 parked · 5.3 of 5.5 GPU-h**

and the tally moves *down* the screen, per builder and per claim type, with
denominators, replacing the single score:

> **Architect** — shadow_count 14/18 · scale_read 6/6 · clutter_density 4/9 · last miss: double pier, 3 wks ago
> **Landscaper** — light_read 19/22 · weather_read 11/15

A's *"prediction score 8/10 (was 7)"* is the most quotable thing in the report
and also the most misleading; the per-claim-type line is what A's own §4 moment
9 (*"'Why?' in one tap"*) demands. **Why this matters:** the report is the
product's only artefact that the owner reads without supervision. A report whose
headline number is a single average teaches the owner to stop reading at line
one — which is precisely the failure B says the report exists to prevent.

### C3. The night is not silent — A narrates recoveries at 03:12, B forbids it

- **A** §2 (the failures table, 03:12 row): the Prop-maker *"retries one seed, then falls back to a recolored library crate; parks a note for morning"*, and §2's rules: *"every recovery is narrated by the builder who did it, in one line ('Hollow from below. Library crate, darker stain, done.')"*.
- **B** §The spam rule: *"A builder may interrupt only for a blocked decision it genuinely cannot resolve, a budget rail event, or a hard failure, and at most one interruption per builder per twenty minutes; the rest queue. **Overnight the queue is silent by construction, and everything parks until morning.**"*

A hollow-crate recovery is a *recovery*, not a blocked decision, a budget event,
or a hard failure. Under B's rule it is not spoken at 03:12.

**Recommendation — split the channel, do not pick a winner.** A's narrated
recovery is one of the best lines in either report, and B's silence is right
about *interruptions*. The distinction is: **a narration is not an
interruption.** B already allows one interruption per builder per twenty
minutes; A's rule is *"at most ~6 lines per builder per hour, and only on state
change"*. A's 6/hour is 3/hour — twice B's cap, and B's cap is derived from the
evidence B cites (three-to-six conversational beats per hour, and the cost of
interruption).

**Merge:** *interruptions* (addressed to you, requiring a response) are capped at
one per builder per twenty minutes, overnight only for a blocked decision, a
budget event, or a hard failure. *Narrations* (written into the feed, addressed
to nobody, on state change) are capped at six per builder per hour and are
**never read to you at night** — they are cards in the feed, and they become
read-aloud only in the morning. This preserves A's craft and B's evidence, and it
resolves C4 at the same time.

### C4. The line budget: 6 lines per hour (A) versus 3 per hour (B)

- **A** §2 (the line budget): *"At most ~6 lines per builder per hour, and **only on state change** — a bet → resolved, a fallback taken, a question parked. No filler, no chatter to seem alive."*
- **B** §The spam rule: *"at most one interruption per builder per twenty minutes"* (≈ 3 per hour), citing a companion-design density finding of *"somewhere around three to six conversational beats per hour, and… repetition is the fastest way to destroy a character."*

**Recommendation.** Adopt 3/hour for **interruptions** and 6/hour for
**feed narrations** (the split in C3). The literature B cites is about
*conversational* beats, and a feed card is not a conversational beat — it is a
log line. B's "repetition is the fastest way to destroy a character" is the part
that must survive into the merge: add the rule B has and A does not — **no line
repeats within a session**, and no builder's line uses the same construction
twice in a row.

### C5. Who writes the ledger: the owner, or the Critic? *(the most consequential conflict in this review)*

- **A** §2 (23:04) has the night decide for itself: *"Act (1 s): 10 kept, 2 reverted to library crates"* — the Critic's verdict stands in for the owner's taste, overnight, without asking.
- **B** §Taste note fields: *"**Append-only, with a single writer.** Notes are written by the owner's verdict event and by nothing else. A builder can read the ledger and cite it; it can never write to it. This is the difference between 'the Architect knows you like sandstone' and 'the Architect trained itself to think you like sandstone', and only the first one is honest."*

If A is right, the taste ledger fills itself overnight and B's entire privacy,
author-scoping and honesty architecture is decorative. If B is right, A's night
loop cannot keep 10 of 12 crates — it can only *propose* 10 of 12 and leave the
owner to accept them in the morning.

**This is resolvable, and the resolution is what makes A's night possible.**

**Recommendation — two ledgers, one store, three record types with different
writers.**

| Record | Written by | What it means | May it drive a change? |
|---|---|---|---|
| `taste_note` | **the owner only** (Casey or Magnus) | *"I chose this and this is why"* — the reason code | yes — it is the taste model |
| `prediction` | the builder, **sealed** | *"I think you'll keep this"* | no — it is a claim awaiting scoring |
| `verdict` | **the Critic** | *"this artifact has defect X"* — a quality finding | yes — it is a defect, not a taste |

The night's automated keep/revert in A §2 (23:04) is therefore a **`verdict`
write, not a `taste_note` write**: the Critic is allowed to keep a crate because
it is watertight, correctly scaled and correctly textured, and that is a
*quality* decision the owner delegated. It is **not** allowed to write "the
owner likes this". Taste notes are only ever written by an owner verdict event
— so A's morning still has a taste story ("17 kept") but the taste *ledger*
has only rows Casey or Magnus actually produced.

A's §1 (21:02) has the Prop-maker saying *"I predict you keep 8 of 12"* — that
is a `prediction` (sealed, scored later by the owner's keep/reject), which is
exactly B's §Two tallies rule: *"the unit of scoring is the builder's spoken
claim… When you drop it without having made a claim, nothing is recorded: no
credit, no blame."* **A and B are already compatible here — they just never said
so.** B's "single writer" rule should be restated as **single writer per record
type**, not single writer per store.

**Why this matters more than the other eleven.** If the Critic writes taste
notes, then `kid-keeps-wobbly: 3/3` (A §3) and `author: magnus` (B) become
decorative, the taste model trains on its own output, and A's sealed predictions
become unfalsifiable — the system would be scoring itself, which is precisely
what B forbids one layer down (*"Self-scoring is a sycophancy vector"*). Fix
this before anything else is built.

### C6. The Critic judges by your taste (A) or by checkable defects (B)?

- **A** §1 (21:02) gives the Critic a taste-based mandate: *"I'll judge at the light you keep coming back for."*
- **B** §Two tallies and §Taste without sycophancy: the Critic scores **world**
claims (did the shadow count read as three bands?), and **taste** claims are
scored by the **owner's verdict**; the Critic's whole value is *"that it is not
the person who wanted the change."*

This is a real conceptual collision, and it is the same failure as sycophancy
pointing the other way: a critic that has learned your taste approves anything
that matches it. "The light you keep coming back for" is a taste criterion, and
taste criteria are not checkable.

**Recommendation — split the Critic into two surfaces with different inputs.**

1. **The defect Critic** (the Critic as B defines it): mechanical, checkable,
   non-authoring. Constraint violations, holes and non-watertight meshes,
   texture failure, geometry errors, scale errors. Its output is
   `hold | fix | keep` + a reason code + one suggested change. It never sees
   the taste ledger. It is the only thing allowed to auto-revert.
2. **The taste critic** (A's "light you keep coming back for"): it may only
   **rank** candidates it has produced — *"this one, or that one"* — against
   the ledger, and it may never accept, keep, revert or author. The owner's
   verdict converts a rank into a `taste_note`.

**One sentence for the product:** the Critic decides whether a thing is *good*;
you decide whether it is *yours*.

### C7. Magnus speaks (A) or taps (B)?

- **A** §1 (20:47) has Magnus talking in-world: *"Magnus, on the south span: 'Can the bridge swing when you run on it?'"*, and A §1 (21:08) has the Architect's line answer a spoken question.
- **B** §Magnus at the controls: *"**He picks from a grid, he does not type.** Roughly 40 nouns as image chips… about 8 mood chips"*; the kid-mode table's input row: *"Chip grid only, no free text, no mic"*; §The privacy boundary: *"Nothing Magnus says is retained as text. He does not speak into the system; he taps. There is no audio and no transcript to store."*

**Recommendation: B wins, and A's evening is rewritten rather than dropped.**
A's grid is a rich design; B's constraint is a genuine safety property, not
mere caution. B's own stated reason is the strongest argument in either
report: *"it means Magnus's input is structured data from the first second,
which makes every downstream privacy property trivial: there is no free text to
leak, because there is no free text."*

So: A's 20:47 walk becomes a **two-surface walk** — Casey speaks and points
(chips appear where he pointed, ≤ 1.5 s each); Magnus taps chips and his chips
appear with a Magnus badge (≤ 1.5 s each). A's spoken *"Can the bridge swing
when you run on it?"* becomes a Magnus chip: `bridge` + `swing` + `want`. The
narrative beat is preserved, the audio is not stored, and B's privacy property
becomes structural rather than a policy.

**Second, smaller collision in the same area:** A §3 (07:19) has the Companion
answer *"West it goes. The frogs will like it."* — a feeling claim about frogs,
which B's Companion voice rule forbids (*"never claims a feeling it cannot
source"*). Fix: *"West it goes."* and let the frogs be silent, or make it
observable (*"the frogs will like it — you picked wet stone 3 times this
month"*). B's rule is right; the line was nicer because it was warm, and warmth
can be earned with a count.

### C8. How much power does Magnus have over the world?

- **A** §3 (07:11–07:19): Magnus arrives, points at branch C (*"that one"*), and *"Applied in 9 s"*. He has chosen a **world branch**.
- **B** §Kid-mode surface, approval row: *"A visual 'keep this one' or a change-chip on a preview"*; and the vocabulary-changes row: *"Proposes to the computer, needs Casey to confirm."* A §3's own label is `kid-keeps-wobbly: 3/3` — taste, not authority.

**Recommendation.** Distinguish three powers and give Magnus the first two:

| Power | Magnus | Why |
|---|---|---|
| Choose among *previews* the builders already made | **yes** | a keep/reject on a preview; creates a `taste_note` with `author: magnus` |
| Change a **parked question**'s answer | **yes, with a preview** | it is a one-tap choice, and the world is unchanged until the builders act on it |
| Choose a **world branch** (a recipe pointer) | **no — Casey confirms** | a branch changes the recipe; A §3 (07:11) says a branch choice is *"a recipe pointer, not a re-render"* — a recipe pointer is a real edit, and B's kid-mode table reserves recipe-affecting authority to Casey |

**Why:** a nine-year-old should be able to say "that one" about a picture of a
bridge. He should not be able to repoint the whole hamlet's recipe at 07:19
with no coffee. The fix is one confirmation step, and it keeps A's best beat
(Magnus's "that one" is the emotional payload of the morning).

### C9. One budget bar in GPU-hours (A) versus three rails including money (B) — and the technology says both are partly wrong

- **A** §1 (21:02): a single bar, in **GPU-hours** and wall-clock hours.
- **B** §Safe mistakes: three rails — per-cycle, per-task, per-night, *"in wall-clock and in money"* — plus graduated throttling at 80%/95% and an in-process kill switch.
- `[cad §9]`: *"The constraint on Thor is not VRAM capacity (122 GB unified; nothing here needs more than ~10 GB) — it is **GPU compute-time and weight-swap thrash**"*, and the fix is *"Batching by model is the whole game."*

**Recommendation — one bar for the owner, four counters underneath, and no
"GPU-hour" as the unit.** GPU-hours are not a unit the scheduler can enforce
before the spend, because res-cad contains no per-job cost model; and on the
Thor, GPU time is nearly free in money and precious in wall-clock. So:

- **What the owner sees (one bar, A's design):** *"Tonight: 8 h wall-clock, 5.5 h of GPU-lane time, $0.40 of hosted calls."* If the planner runs locally, the money figure reads **$0.00 (local)** — which is itself a product statement.
- **What the scheduler enforces (B's hierarchy, plus the one A and B both miss):**
  1. per-job cap (a single render or generation)
  2. per-task cap (one item's whole life: predict → preview → critic → keep)
  3. per-night cap (the owner's bar)
  4. **per-model-batch cap** — the one res-cad §9 forces into existence, because with a batched GPU lane the enforceable unit is *"one loaded model × N prompts"*, and the failure mode of ignoring it is thrash, not overspend
  5. money cap, scoped to hosted calls only.

B's 80%/95% graduated throttling then maps cleanly onto res-cad §9's lane
ordering: at 80% stop opening new model batches and finish the current one; at
95% stop and report.

### C10. Bulk approval of the evening (A) versus per-action risk gating (B)

- **A** §1 (21:02, 21:14): one slate, one button. The whole night runs unattended on that approval.
- **B** §Research transfer (OpenAI's guide): *"rate every builder action on those four axes, and the ones that write irreversibly or cost a lot get a mandatory approval, while the rest run unattended overnight"* — listed under **Later** in B's build-order table (§Budget rails: *"Per-tool risk ratings driving auto-approval"*).

**Recommendation: A's bulk approval is the phase-4 rule; B's risk gating is a
phase-5 refinement with one exception now.** Bulk approval is the whole
product — if every action needs a sign-off, nobody leaves the builders
overnight and the product dies. But B's risk axis is right, and one case
genuinely needs it on day one: **the first time a builder writes outside a
reversible branch, or the first time a work order pulls a hosted service, the
owner should be asked once**, and then the answer should be remembered per
tool. So: *approve the slate tonight; approve each risky tool once, ever.*

### C11. The numbers in A's night do not reconcile with A's own slate

- A §1 (21:02): the slate shows *"~8 h and a 6.0 GPU-hour budget. Current ask: 4.2"* (and the table sums exactly: 2.0 + 1.5 + 0.7 = 4.2), Casey slides the rail to **5.5**.
- A §1 (21:08): **after** the slate, he approves WO-14 — *"About 3 hours tonight."*
- A §3 (07:03): the morning line reads *"8 h 20 m · … 5.3 of 5.5 GPU-h"*.

Three problems:

1. **The slate's ask was incomplete when it was shown.** The 3-hour work order was approved four minutes later and was never added to the bar, so the night's real ask was **7.2 against a 5.5 rail** — and the morning shows 5.3 spent. The story is actually coherent (1.9 GPU-hours were dropped, which matches the 05:0x row: *"the north-lantern batch unrun… re-queued for tomorrow"*) — but as written, the reader cannot reconstruct it, and the report's *"5.3 of 5.5"* looks like a comfortable pass rather than a night where a fifth of the ask was cut.
2. **The wall-clock rail was exceeded.** The slate promised ~8 h; the night ran 8 h 20 m. Either the rail is 8 h and it overran (which A's own §2 "any — the Thor reboots" row says must be disclosed: *"the report states lost time in minutes, never hides it"*), or the rail is not 8 h.
3. **The report doesn't say the budget bit.** A's 05:0x row promises *"the report's first line says what didn't get done"*. The 07:03 first line does not say it.

**Recommendation.** The plan slate must show the work-order time as its own
line (*"Work orders: 3.0 h — approved separately"*). The morning's first line
must show the cut, not just the spend. And the wall-clock rail must either be
honoured or the overrun disclosed in the same line. **A report that shows
"5.3 of 5.5" without naming the 1.7 h that was dropped is the single most
dishonest-looking artifact in either report, and it is a direct violation of
A's own rule.**

### C12. A's capability claims have no record; B requires one

- **A** §1 (21:08), the Architect's line: *"I can fake sway with loose planks. Real rope isn't in my hands yet."* — this is the evening's best beat, and it is a **capability claim**.
- **B** §The trust stack: *"Every claim a builder makes about itself (what you like, how well it can do a thing, what it did while you slept) has to be checkable against a stored record, or it is decoration."*

A's line has no backing row anywhere in B's schema. B's `prediction` records
claims about the world; `taste_note` records the owner's judgements; neither
records *"what can I do"*.

**Recommendation: add a third record type.**

```
capability {
  id:        cap_0031
  builder:   architect
  at:        2026-10-30T21:08:12Z
  scope:     bridge.rope
  state:     unavailable            // available | unavailable | partial
  basis:     { rope_spans_built: 0, span_variants_tried: 0 }
  note:      "real rope isn't in my hands yet"
}
```

This preserves A's beat, satisfies B's rule, and buys something neither report
has: **the work-order board can show the vocabulary's edges quantitatively**
(A §5.5 calls it *"the vocabulary's edges — what builders asked for that
doesn't exist yet"*) — a capability row per missing word is exactly that edge,
and it is what makes A §3 (07:34)'s growth beat (*"the vocabulary gains
`bridge.rope`"*) measurable rather than anecdotal.

### C13. The clock doctrine has no bucket for A's own 30-second decision screen

A §The three clocks defines Talk ≤ 2 s, Watch ≤ 5 s per card, Workshop ≤ 60 s
with progress and a cancel. A §1 (21:02) then says the plan slate transaction
is **≤ 30 s**, and A §4 moment 4 repeats *"transaction ≤ 30 s"*. A 30-second
decision is not a Talk action, and calling it Workshop means it inherits
"progress and a cancel" semantics it does not want.

**Recommendation.** State explicitly that the slate is a **Workshop-clock
transaction** (it fits under 60 s) and that it does *not* need a cancel —
because the night has not started and Cancel means "go back", not "stop the
GPU". The rule that matters for the product is the inverse of the usual one:
**before the night, a slow decision is free; after it, it costs.** This is also
the cleanest statement of why the evening is the right place for all human
judgement.

---

## 3. Gaps — what neither report covers, and the user experience needs

Ordered by how much damage the silence does.

### G1. The first evening — onboarding a cold system

Neither report describes the first night. A §1 (20:41) has the first-run
fallback line (*"First night. I'll learn what you keep"*) and calls it honest;
B forbids any claim below two observations, so on night one the Companion has
nothing to say, and A never says what it says instead.

**What is missing:** the whole first-session arc. What the owner sees on an
empty project. How you make your first plan when the slate has no examples and
the builders have no track record. What "I have no idea what I like yet" looks
like as a product state — and, crucially, **how the first week is presented so
it does not read as incompetence**. Both reports assume a populated ledger; the
taste ledger by definition starts empty and takes a week to become an asset.

**Recommendation.** Add a **cold-start mode** to the ledger schema: for the
first N decisions, the system asks rather than infers (*"deep joints or flush?"*
as a two-chip choice, answered by you, recorded as a `taste_note` — so cold-start
*is* taste acquisition, not a special case). And make the emptiness a feature
in the first-morning report: *"You chose 4 of 6 times. That is not taste yet,
that is a start."* The report's own §5.5 shows this is the shape of the
problem — you cannot show a track record you do not have.

### G2. The Thor is busy, off, or shared — and the night that did not happen

A §2's failure table covers exactly one machine failure: *"any — the Thor
rebovers / power cut … The night is a durable queue; on boot it resumes from the
last sealed step; the report states lost time in minutes, never hides it."*
That is the right answer to a reboot. Neither report covers:

- **The Thor is busy with something else.** `[cad §9]` describes a *serial* warm
  tier — one generative model resident at a time. If anything else on the box
  holds the GPU, the night's batches queue behind it. `CLAUDE.md` says the
  Thor is dedicated to this project, so this is a low-probability event, but the
  *product* must know the difference between "nothing happened" and "something
  else happened".
- **The machine is off all night.** The morning report must be able to say *"the
  Thor was off. Nothing ran. Here is your plan, unstarted."* — and A §6.7's
  *"honest idleness"* principle (*"show the workshop dark and the builders
  asleep"*) is the right model, but only if the report distinguishes *dark*
  from *asleep*.
- **The client never detached.** A §1 (21:14) says the scheduler waits for the
  client to detach before the big batches. If the ProArt stays open all night,
  the big batches may never run — and the morning report must say so rather than
  showing an empty night with no explanation.

**Recommendation.** The morning report gets a mandatory **status line** with
four values: `ran as planned | ran short | ran degraded | did not run`, and a
one-line reason in the last case. It also has to distinguish *"the GPU was busy
with your other job"* from *"the queue was empty"* from *"the machine was
asleep"*, because from the owner's chair those are three different mornings.

### G3. Sharing a world

A §5.4 says the report is *"Shareable as a permalink (a night is kilobytes —
vision.md)"*, and §6.9 promises *"Watch Fjellvik's Tuesday" as a permalink*.
Neither report covers what sharing actually means: two people on a LAN, a
project that moves to another box, a world handed to a friend.

**Technology constraints that bear on it:** `[cad §8]` fixes the direction of
truth — *"recipe → USD, never USD → recipe"* — and `[3d §5]` says a re-run
reproduces *"the same recipe rather than the same bytes"*. So a shared link
either ships cached renders (not kilobytes) or makes the viewer pay the render
cost. **Recommendation:** a shared link is a **recipe + provenance bundle**
(recipe, ledger slice, USD scene reference, thumbnails), marked clearly as
*"recipe — re-render may differ"*; and `[cad §9]`'s per-asset licence and
weights-revision fields must travel with it, because a world handed to someone
else carries the licences of everything in it. B §Open decisions (six) already
asks *"Does the taste ledger ever leave the machine?"* — this is the same
question with a second user attached, and the answer must be scoped per
recipient.

### G4. Magnus's first session

A has Magnus arriving at 07:19 with coffee-less enthusiasm; B specifies his
chip grid and his rows. Neither describes his first five minutes: what the
chips mean, how he learns that a chip becomes a thing in the world, what he
does when his first request cannot be built, and what his *first morning*
looks like. B §The privacy boundary gives him a *"kid-mode surface"*; it does
not make it legible.

**Recommendation.** Magnus's first session is a **five-chip guided world**: he
picks one of five nouns, the world shows it *actually built* within the
morning, and the report to him is one sentence (*"You asked for a tower. It is
by the water. Your brother kept the north jetty."*) — which is B's own stated
core: *"Magnus's version of trust is his thing is still there tomorrow. He does
not need a hit rate."* Nothing he does in the first session may be used to
train taste until the owner has confirmed he understands what a keep means.

### G5. Accessibility — absent from both reports

Neither report mentions screen readers, colour-blind-safe verdict display,
keyboard-only operation, low-bandwidth or text-only operation, or captions.
A §8 does list *"Magnus's read-aloud mode fully voiced"* as a later item, which
is the only accessibility-adjacent line in either report — and it frames
accessibility as a voice feature for a child rather than as a property of the
product.

**Why it matters concretely:** a verdict system that renders quality as colour
(green kept, amber parked, red reverted) is unreadable to a significant
minority of users; a night feed that is a scrolling card stream is hostile to a
screen reader unless the card is a labelled region with a stable reading
order; and the entire product is a LAN-local app, which is exactly the
environment where a text-first, low-bandwidth mode is worth having.

**Recommendation.** Minimum bar, cheap to build, and it strengthens the product
rather than diluting it: **every verdict is a word, not a colour**; every card
is a labelled region with a text summary; the whole night is browsable as text
over the ledger (which A §2 (02:07) already requires: *"The feed must render
from the ledger alone"*); and Magnus's mode is text-and-chip, which is
already the most accessible surface in the design.

### G6. The cost conversation — what a night is worth, in money and in attention

B §Open decisions asks for *"the nightly money rail"* and admits it cannot be
answered from the documents. The technology reports do not answer it either:
`[cad §9]` says the Thor's constraint is compute-time and thrash, and the
money figures in B come from hosted-agent guides (`[trust]`'s AWS and Railway
citations), while the default planner is local (`[vision §3]`: *"a local LLM,
plus the cloud on a budget"*).

**Recommendation.** The product should make the trade explicit in the morning
report: *"5.3 h of your Thor · $0.40 of hosted calls · 2 h of your attention."*
The third number is the one nobody is measuring and the one that determines
whether the owner comes back. A night that produces 40 cards and needs 40
decisions is a failure even if every card is correct.

### G7. A night where everything failed, or where you kept nothing

A §3's morning assumes a good night (17 kept, 4 reverted). Neither report
covers the night that produced nothing, or the morning where the owner rejects
all three branches. The three branches in A §3 (07:11) are all *variations on
success* — A, B, C all look like finished worlds.

**Recommendation.** The branch set must include a **"nothing landed" option**
and a **"start over from the plan" option** (A §5.5's asset library makes a
recipe-level reset cheap, and B §Safe mistakes' branch model makes it
non-destructive). And the morning report must be able to say *"nothing was
kept"* without it reading as a system failure — with the failure list first,
per B's rule, and the parked questions still answerable.

### G8. The parked-question flood

A §3 (07:03) has two parked questions; A §2 has a "question parked" as one of
the three night line states. B §The open-question policy says the night has
exactly two channels, park or assume — but neither report says what happens
when *forty* questions park in one night, which is what a bad night produces.

**Recommendation.** Parking is a queue with triage, not a list: questions are
ranked by (a) how much work is blocked behind them, (b) whether the conservative
assumption is cheap. The morning shows the **top three** and a count of the
rest (*"31 more, none blocking"*). This is B's "one question at a time" rule
applied to the morning rather than to the conversation.

### G9. The client and the world disagree while the night runs

A §1 (21:14) says the scheduler waits for the client to detach; A §3 (07:26)
then has the owner *in the world* while a work order lands and previews appear
*"beside yours"*. Meanwhile the night has been editing the same recipe. What
the ProArt shows during the night, what happens when you reconnect mid-night,
and what "the world re-streams in ~12 s" means when the recipe moved 61 times
are all undefined.

**Recommendation.** One rule, stated once: **the client is a viewer of a
named commit, never a holder of state.** The ProArt shows commit `c41a9e3`;
the night moves the branch; a reconnect shows a diff (*"12 commits behind —
reconnect"*). A §3 (07:26)'s "ghost scaffolding" then becomes a preview
against the *current* commit, not an overlay on stale geometry.

### G10. Two users, one world, one set of builders

B §Kid-mode surface gives Magnus *"A short assigned queue, ends at a fixed
hour"* — a real scheduling concept neither A nor the technology reports
contains. Who owns the Architect when both are working? Does Magnus's queue
compete with Casey's for the same GPU lane (`[cad §9]` batches by model, so
two queues interleave badly)? Does Magnus's fixed hour cut across the night?

**Recommendation.** Two queues, one lane, one priority rule: **Casey's queue
is the night's; Magnus's is a reserved slice of it**, capped by B's fixed hour
and scheduled into the model's warm batches rather than run alongside them. And
one builder, one owner, per job — the ledger's `author` scoping (B) should
extend to the queue.

---

## 4. Reality check against the technology

Every experience promise that depends on a speed or a capability, checked
against `res-cad` and `res-3d`.

**The method rule both technology reports agree on, and the one that governs
this whole section:** `[3d §8]` — *"Do not schedule against the published
numbers. Fill in the scheduler's throughput table from measurements on this box,
and record the measurement alongside each model's provenance entry"* — and
`[3d §7]`, which catches two claims as *"simply transplanted datacenter
numbers"* (TripoSR's "less than 0.5 seconds" is explicitly *"an NVIDIA A100
measurement"*, and TRELLIS.2's 3 s / 17 s / 60 s ladder is *"an H100
measurement"*; *"No Thor or Jetson benchmark of any model on this list is
published"*). `[cad §9]` says the same about the asset pipeline. **So: a latency
number that did not come off this box is not evidence, and any experience
promise resting on one is "holds if X", where X is the phase-1 measurement.**

One caveat on scope: **neither technology report covers Infinigen, Blender,
Cycles, the vision critic, the planner LLM, or speech.** `[cad §]` is about
CAD and assets; `[3d §]` is about 3D generation models. So a whole band of
experience promises — the morning filmstrip, the branch pre-renders, the
peek's before/after thumbnails, the critic's 9 s — have *no* technology
evidence available at all. They are marked accordingly rather than assumed.

### 4.1 The platform fact the two technology reports contradict each other on

**This comes first because it decides whether the pipeline installs at all.**

| | Claim | Evidence |
|---|---|---|
| `[cad §TL;DR, §2, Appendix]` | *"stock PyPI `torch` 2.15.0 now ships an aarch64 CUDA wheel built against CUDA 13.2 with `sm_110` (Blackwell) kernels inside `libtorch_cuda.so` (verified by downloading the 462 MB wheel and scanning the fatbin arch strings; deps pin `cuda-toolkit==13.2.2`, matching this box exactly). The whole 'Jetson needs a special PyTorch index' problem that bit AGX Orin is gone for Thor: `pip install torch` should just work."* | Downloaded and scanned; version 2.15.0 |
| `[3d §1, §2, §7]` | *"The aarch64 torch wheels published on PyPI are CPU-only builds — the 2.6.0 aarch64 wheel declares no `nvidia-*` runtime dependencies whatsoever — so a working Thor install must point at NVIDIA's own indexes. The Jetson AI Lab SBSA cu130 index carries torch 2.9 through 2.11 for cp312 aarch64, and cu132 carries the 2.9.1 series."* | Wheel metadata for 2.6.0 |

**Verdict: does not hold (unresolved) — but it does not block anything.**
Both can be true at different versions: 2.6.0's aarch64 wheel was CPU-only;
2.15.0 may genuinely ship CUDA. `res-cad` verified the newer release by
download-and-scan, which is stronger evidence than metadata inspection of an
older one, but `res-3d` is the report that reasoned about it rather than
sampled it.

**Recommendation.** Settle it with one command on the Thor (`pip download
torch==2.15.0 --only-binary=:all: --platform manylinux_2_28_aarch64` and look
for `nvidia-*` runtime dependencies), and **plan on the NVIDIA cu132 index
either way** — `[3d §1]`'s path is correct in both worlds, and it also solves
the cp312 pin collisions (`[3d §1]`: *"Python 3.12 collides with several
upstream pins, and the fix is a per-model environment"*).

### 4.2 Promise-by-promise

| # | Experience promise (source) | What the technology says | Verdict |
|---|---|---|---|
| **R1** | *"The world streams in (glTF/USD, ~8 s warm)"* (day §1 20:41); *"the world re-streams in ~12 s"* (day §3 07:11) | `[cad §6]`: `usd-core` aarch64 wheels verified; but it *"has no Hydra/GPU rendering; that's fine, rendering stays in Blender/Cycles and the ProArt."* `[cad §7]` rules FALSE the claim that *"The Thor has dedicated hardware pipelines that read and stream OpenUSD scenes."* No stream time is measured anywhere. | **Does not hold as a number.** The architecture holds (USD is the interchange layer, the ProArt renders — `[vision §8]`), but no one has measured a compose → stream → first-frame time on the ProArt. **Holds if X:** X = one measured cold and warm client-stream time from the phase-1 spike. Note this is the number that decides whether the *in-world* half of the product is phase-5 or phase-6. |
| **R2** | *"Eleven seconds later, one line back"*; *"compile ≤ 20 s"* (day §1 21:08) | No LLM is evaluated in either technology report. `[vision §3]` allows *"a local LLM, plus the cloud on a budget."* | **Holds if X** — X = a measured compile latency for the chosen planner (local or hosted), *and* a clock decision. **A 20 s compile cannot be a Talk-clock action** (day's Talk is ≤ 2 s); it is a Workshop action, so it must show progress and a cancel — exactly as day §4 moment 3 says (*"compile ≤ 20 s; confirm readable ≤ 5 s"*). The *confirm line* is the Talk-clock part and it is the one that matters. |
| **R3** | *"Preview (38 s, workshop clock): six 480p renders through the model scheduler, batched with the night's other image-to-3D jobs"* (day §2 23:04) | `[3d §4.1]`: TRELLIS.2's published ladder is H100-only — *"roughly 3 s at 512³, 17 s at 1024³ and 60 s at 1536³"* — and the Thor estimate is *"the tens-of-seconds to roughly 90-second range"* at 1024³. `[3d §7]`: *"TRELLIS.2 is 'sub-minute on the Thor' — **Unverified**."* `[cad §2]`: modly's *texture* path *"needs `custom_rasterizer` + `differentiable_renderer` CUDA C++ extensions built from source for aarch64/CUDA 13 — the one genuinely heavy item."* | **Does not hold as written for the image-to-3D half.** Six image-to-3D props at the Thor estimate is **6–9 GPU-minutes, not 38 seconds**. **Holds if X** for the *preview render* half (Blender preview of six thumbnails) once Cycles is timed. **Recommendation:** rewrite the crate loop as *"predict 4 s → seal → six previews, batched (measured: X) → critic (measured: Y)"* and keep the 38 s only if the phase-1 measurement supports it. |
| **R4** | *"Critic (9 s): the vision model reads every render"* (day §2 23:04) | `[cad §9]` puts *"the critic (vision model)"* in the hot tier but **evaluates no critic model**; `[3d §]` does not mention one at all. `[cad §9]` notes hot-tier residency is what makes the critic cheap between batches. | **Does not hold as a promise — the critic has not been chosen.** **Holds if X:** X = a chosen critic model, its measured latency on the Thor, and proof it stays resident (otherwise the 9 s becomes a load time, and the critic is on the critical path of *every* bet). **This is the largest unchosen dependency in the whole stack:** both UX reports put the Critic at the centre of the product, and no technology report has evaluated one. |
| **R5** | *"8 h 20 m · 61 recipe edits · 23 sealed bets · 17 kept · 5.3 of 5.5 GPU-h"* (day §3 07:03) | `[cad §9]`: *"The constraint on Thor is not VRAM capacity (122 GB unified; nothing here needs more than ~10 GB) — it is GPU compute-time and weight-swap thrash"*; batching by model is *"the whole game."* `[3d §8]`: *"Fill in the scheduler's throughput table from measurements on this box."* | **Holds if X** — the *shape* is exactly what `[cad §9]` prescribes (many small bets, batched by model, one lane), but every number in that line is a placeholder, and **"GPU-hour" is not a unit the scheduler can enforce** (there is no per-job cost model in either technology report). **Also internally inconsistent** (C11): the slate showed a 4.2 ask and the work order added 3.0, so the real ask was 7.2 against a 5.5 rail and 1.7 h was cut — which the report does not say. |
| **R6** | *"the budget bar hits 5.5 GPU-hours… Queue stops cleanly at the bar; the batch is re-queued for tomorrow"* (day §2 05:0x); 80%/95% graduated throttling (trust §Safe mistakes) | `[cad §9]`: the warm tier holds *"one generative model at a time"*; jobs are batched by model precisely so the scheduler *"is not thrashing environments"* (`[3d §6]`). | **Holds if X** — but X changes the *unit*. With a batched lane, a **per-cycle** rail (trust) is not enforceable; the enforceable granularity is *"one loaded model × N prompts."* Map the rails: per-job → per-batch-item; per-task → per-item-of-work; per-night → the owner's bar; **plus a per-model-load cap**, which is the rail neither report has and the one the hardware demands. At 80% stop opening new batches and drain the current one; at 95% stop and report. |
| **R7** | *"The prediction is sealed — hashed into the ledger before any render exists"* (day §2 23:04); `seal_hash` (trust §Sealed predictions) | `[3d §5]`: *"Seeded is not the same as bit-identical… The honest unit of reproducibility is the recipe: prompt, seed, model identifier, weights revision hash, resolution, sampler settings and environment revision."* | **Holds — and is strengthened.** `[3d §5]` says the recipe is the unit, which is exactly what a seal must reference. **Recommendation:** the sealed payload should be the recipe tuple (`prompt, seed, model id, weights revision, resolution, sampler, environment revision`), not just a branch hash, so a verdict can be re-scored against the same inputs. |
| **R8** | *"'Why?' in one tap — provenance on anything: prompt, seed, model, licence, critic note, who decided"* ≤ 1 s (day §4 moment 9) | `[cad §9]`: *"it stamps every artifact (prompt, model id, weights repo+revision, seed, library versions, wall-time, licence)"*. `[3d §5]`: the same tuple plus *"the output format… and the environment revision of the Thor that produced it."* `[3d §6]`: *"The licence field should be written by the model registry rather than by the job that happens to call it."* | **Holds.** This is the best-supported promise in either report — the technology *requires* exactly this record, so the evidence card is nearly free once the scheduler exists. **Two additions:** *weights revision* and *environment revision* (per `[3d §5]`), and the licence must come from the registry, so the card can say *"this asset: MIT weights, DINOv3 encoder terms apply"* and not just a badge. |
| **R9** | *"The asset library: regenerate, swap model, promote to the shared shelf; licence badge"* (day §5.6) | `[cad §3]`: FLUX.1-dev is non-commercial → skip; SDXL OpenRAIL++-M; Poly Haven and ambientCG CC0 → *"adopt now"*. `[3d §3]`: a full licence register, including the dependency terms (nvdiffrast commercial-OK, **nvdiffrec research-only**, DINOv3 attribution/end-use). `[3d §5]`: *"a re-run should be expected to reproduce the same recipe rather than the same bytes."* | **Holds — with one word changed.** Swapping models is the register's entire purpose. But a re-run with a *different* model **reinterprets**, it does not regenerate: the card must say *"reinterpreted with TRELLIS.2 — not the same asset."* Saying "regenerate" here would be a false promise about bit-identity, which `[3d §5]` explicitly warns against. |
| **R10** | *"Harbor life: 12 props (crates, racks, lanterns)… Six from the library, six new"*; *"image-to-3D returns crates 7, 11 hollow from below"* (day §1 21:02, §2 03:12) | `[cad §2]`: modly's Jetson guide is Orin-proven (mesh-only, ~6 GB, *"typically not watertight"*), but *"rembg/ONNX Runtime aborting on Tegra CPU… **still a real risk**"*, and textures need source builds. `[3d §4.1, §8]`: **TRELLIS.2 via the ComfyUI native path** — MIT code, MIT ungated weights, **no region restriction**, **no compiled CUDA extension**, seeded, PBR out; TripoSR as the parallel MIT baseline that *"forces the scheduler plumbing."* | **Holds if X** — and **X is a different stack than `res-cad` proposed.** `res-3d` supersedes `res-cad` here: the ComfyUI-native TRELLIS.2 path removes `res-cad`'s one "genuinely heavy item" (the texture CUDA extensions) and removes the Hunyuan licence problem. **Recommendation:** prop-maker = TRELLIS.2 native + TripoSR baseline, textures via TRELLIS.2's shape-conditioned texturing; modly's FastAPI/MCP *pattern* is still worth stealing (`[3d §4.3]`: *"the interface pattern"*). **Budget:** six new props ≈ 6–9 GPU-min at the Thor estimate, which fits a night — but only as a *batched* group, never one prompt per load (`[cad §9]`). **And note the hole:** A's crates-7-and-11-are-hollow-from-below failure is *exactly* the "not watertight" failure `[cad §2]` warns about, so the night must schedule a watertightness check before the critic, not after. |
| **R11** | *"Rope bridge with real sway… the critic passes it at 2× load… About 3 hours tonight"* (day §1 21:08); *"Attempt 3 passes at 2.3×"* (day §2) | `[cad §1]`: build123d/CadQuery are pure CPU, *"a typical part is milliseconds to a few seconds"*, no GPU, *"Determinism is total… same script + pinned wheel version → byte-identical geometry. That is why CAD parts are 'recipe-native': the script is the asset."* `[cad §6]`: SimReady gives *"the schema/profiles"* — rigid-body, joints, collision, material and semantic taxonomy — **not a solver**. `[3d §4.8, §6]`: *"The CAD part role stays on parametric code, because no shortlisted model emits a B-rep or STEP and none will be trustworthy for a bolt that has to fit."* | **Holds if X** — the bridge *is* buildable as a deterministic CAD script, which is the strongest form of "recipe-native" in either technology report. **But "2× load" is undefined by the technology:** no physics engine is adopted anywhere. **Recommendation:** define the acceptance check as a *scripted analytic* computation (span, mass properties, member forces from the recipe's parameters) rather than a simulation. If a simulation is genuinely wanted, that is an engine decision that has not been made — and the work order's 3-hour estimate should include **environment provisioning** (`[3d §1]`: each model family needs its own conda environment; `[3d §8]`: TRELLIS.2's own answer is a py3.10 conda env). A 3-hour estimate that does not include provisioning is wrong. |
| **R12** | Textures and PBR for the world (vision §"The engineer also makes things"; day §5.6) | `[cad §3]`: StableMaterials *"generates in ~4 steps"*, SDXL-class fp16 ≈ 7–10 GB, OpenRAIL weights; MatForger **gated (401)** → skip. `[3d §4.8]`: TRELLIS.2's shape-conditioned texturing is *"MIT, already resident in the same environment as the prop path, and it introduces no compiled dependency — it is the first thing to adopt."* | **Holds.** **And `res-3d` supersedes `res-cad` here:** `res-cad` says *"textures deferred past the spike"* because of modly's texture CUDA builds; `res-3d` shows the texture role can be done inside the prop environment with no source builds. **Recommendation:** adopt TRELLIS.2 texturing for the prop path, StableMaterials + SDXL for scene-wide materials, and CC0 libraries (Poly Haven, ambientCG) as the curated baseline — with `[3d §3]`'s point that licences must be inherited from a registry, not remembered per job. |
| **R13** | Music and ambience for the world (vision §"music and sound") | `[cad §5]`: ACE-Step — Apache-2.0 code **and** weights, *"up to 4 min of music in ~20 s on an A100"*, RTF 27×, ~8 GB VRAM. Stable Audio Open Small — *"~11 s clips @ 44.1 kHz… marketed as real-time on Arm CPUs"*, gated weights. MusicGen — CC-BY-NC → *"not for shipped assets."* | **Holds if X** — the 20 s figure is an **A100** number and the Thor is well below an A100 on dense throughput (`[3d §1]`'s framing). Expect roughly an order of magnitude slower, which is fine for a night and fatal for a live cue. `[cad §9]`'s lane layout puts ACE-Step at the end of the GPU chain and SAOS on the CPU lane, where it is *"effectively free."* |
| **R14** | *"[later] they each walk to their patches of Fjellvik, a 10-second beat you can skip"* (day §1 21:14); *"Magnus's read-aloud mode fully voiced"* (day §8) | `[cad §4]`: MoMask is the fastest motion model and MIT-code, *"but HumanML3D/AMASS data provenance restricts shipped use"*; the data licence *"flows into any shipped output."* `[3d §6]`: *"The character role stays on recipe and rig, because none of these models produce skinned or rigged characters."* | **Does not hold (for shipped assets) until the licence decision lands.** A walking avatar needs character motion, which is exactly the licence-flagged corner (`[cad §4]`: *"for a shipped commercial game it is the one corner of the pipeline that likely needs either a licence review or replacement with mocap/proc-animated clips"*). **Recommendation:** the cinematic walk-to-districts becomes **procedural walk cycles authored in the recipe** (no model, no data licence), and the 10-second beat is explicitly a *recipe* feature, not a generation feature. Read-aloud voice is a TTS dependency that **neither technology report covers at all** — treat it as unevaluated. |
| **R15** | *"Shareable as a permalink (a night is kilobytes)"* (day §5.4); *"a 60-second timelapse with captions"* (day §8) | `[cad §8]`: the recipe is the source of truth, USD is a compiled cache, *"Deterministic emission (sorted prims, no timestamps) keeps USD diffs meaningful as a review artifact."* `[3d §5]`: *"the mesh file itself is the artifact of record, and a re-run should be expected to reproduce the same recipe rather than the same bytes."* | **Holds** — for the *recipe*, with a caveat: a shared link that re-renders reproduces the recipe, not the bytes, so the viewer either gets cached renders (not kilobytes) or pays the render cost. **Recommendation:** ship recipe + provenance + thumbnails, and label it *"recipe — re-render may differ."* The timelapse needs an encoder; `[cad §7]` notes the Thor has hardware video encode for streaming rendered output, but nothing measures it. |
| **R16** | The computer works in a sandbox branch: implement → render → critic → evidence → preview (day §2; vision §architecture) | `[3d §1, §6]`: *"each model family wants its own environment, because torch versions, compiled extensions and licence conditions differ per family"* — and `[3d §8]` recommends *"a conda environment on Python 3.10."* `[cad §]`: nothing on sandboxes. | **Holds if X** — X = environment provisioning inside the work order's budget and time estimate (see R11). A work order that must build a py3.10 conda environment before its first render is a different three hours than one that doesn't. **Recommendation:** every work-order estimate has two lines — *"build/verify: X"* and *"generate/test: Y"* — so the estimate is auditable. |
| **R17** | *"the critic model OOMs during a big texture batch → demote to the smaller local critic for 3 verdicts"* (day §2 03:5x) | `[cad §9]`: *"The constraint on Thor is not VRAM capacity (122 GB unified; nothing here needs more than ~10 GB) — it is GPU compute-time and weight-swap thrash."* | **Does not hold as a likely event.** The failure row is aimed at the wrong constraint — on a 122 GB unified box with every model under ~10 GB, an OOM during a texture batch is unlikely; what actually happens is **contention and thrash** (a batch waiting for a model that is still resident for something else). **Recommendation:** keep the fallback (defence in depth is free) but replace the row with a thrash/stall scenario, because that is the failure the night will actually have, and it has a different recovery: *queue delay and a report line*, not a degraded verdict. **A degraded verdict (`verdict@low-res`) is a silent quality change and belongs on the evidence card, not in a log line.** |
| **R18** | The budget bar as a cost control (day §1 21:02; trust §Safe mistakes) | `[cad §9]`: the Thor is local; the constraint is compute-time and thrash. `[vision §3]`: the planner may be *"a local LLM, plus the cloud on a budget"*. `[3d §]`: no hosted model costs appear at all. | **Holds if X** — X = the rail is relabelled and split (C9). "GPU-hours" measures local compute, which is nearly free in money and precious in wall-clock; the money rail applies **only** to hosted calls. **Note for `trust` specifically:** its runaway-cost framing (AWS per-cycle caps, Railway's ~$0.40/run and 500-runs-a-day → ~$200/day) is imported from a hosted-agent world that does not describe this project's default path. See S1 in §6. |
| **R19** | *"the scheduler waits for the client to detach before the big batches"* (day §1 21:14) | Nothing in either technology report covers client-detach signalling. `[cad §9]`'s lane layout is compatible. | **Holds (engineering, not capability)** — with one failure mode both reports should own: if the client never detaches, the big batches never run, and the morning must say so (G2). A cheap mitigation: run the first batch after a timeout, not only on detach. |
| **R20** | The recipe is the source of truth; renders and meshes are caches; a night's work is kilobytes (vision §2; day §3 07:11; trust §Safe mistakes) | `[cad §8]`: *"Both — with one direction of truth: the recipe (our own typed format) is the source of truth; USD is a compiled output and assembly cache."* `[3d §5]`: *"the honest unit of reproducibility is the recipe."* | **Holds — fully, in both technology reports.** This is the deepest agreement in the entire document set, and it is what makes A's *"branch choice is a recipe pointer, not a re-render"* and B's *"undo is a checkout"* true rather than aspirational. |

### 4.3 What the technology reports do *not* cover, and therefore what no experience promise can be checked against

`res-cad` and `res-3d` are asset-pipeline reports. They contain **no** evidence
about: Infinigen world generation; Blender 4.2 on aarch64 (`CLAUDE.md` notes
the Thor currently has 4.0.2 and the install matrix has no Linux ARM64 column);
Cycles render times on the Thor; the vision critic (R4); the planner LLM (R2);
speech recognition; TTS (R14); the ProArt client; and the HUD. **Every
in-world, voice, and critic-latency promise in both experience reports is
therefore currently unbacked.** That is not a criticism of the experience
reports — it is the phase-1 spike's agenda, and the honest way to write it.

---

## 5. The merged experience spine — 15 moments, in order

Each moment carries: the clock it belongs to (A's doctrine, §The three clocks),
the latency budget, the screen it lives on, its source, and its verdict from
§4. **Screens are A's six, unchanged** (day §5): *In-world view* (the ProArt
client), *Plan slate*, *Night feed*, *Morning report*, *Work-order board*,
*Asset library*.

| # | Moment | Clock · budget | Screen | From | Reality |
|---|---|---|---|---|---|
| **S1** | **First night, empty ledger.** The Companion states plainly what it cannot yet do and offers four starter choices instead of a guess. | Talk · ≤ 2 s | In-world view (evening panel) | A §1 20:41 fallback + B's two-observation gate + **G1** | Holds (text) |
| **S2** | **The recognized return.** The Companion states what changed in your absence **with a count and a denominator**, and never comments on how long you were gone or how it felt. | Talk · ≤ 2 s from app open — *typed over the ledger while the world still loads* | In-world view | A §1 20:41 + B §utterance rules + **C1** | Holds if X (client stream, R1) — but the **line** itself is instant because it comes from the ledger, not the world. |
| **S3** | **Point-and-say planning (Casey).** A spoken intention becomes an editable chip where you pointed; ambiguity is asked, never guessed. | Talk · ≤ 1.5 s per chip | In-world view | A §1 20:47 + B §open-question policy | Holds (text+click now; voice later) |
| **S4** | **Magnus's request.** Chips only — no mic, no free text — each with a Magnus badge, each an `author: magnus` row. | Talk · ≤ 1.5 s per chip | In-world view (kid panel) | B §Magnus + A §1 20:47 **rewritten** + **C7** | Holds (chips) |
| **S5** | **The plan slate.** One screen: four intentions, owner, predicted cost, the builder's one-line take, one budget bar, *work-order time shown as its own line*, and a risk flag on anything irreversible. | Workshop · ≤ 30 s transaction, no cancel needed (the night has not started) | Plan slate | A §1 21:02 + B §safe mistakes + **C9, C11, C13** | Holds if X (cost estimates are model-dependent, R5/R6) |
| **S6** | **The one-line work order.** "Computer, I want rope bridges that swing." → a ≤ 25-word confirm with cost and acceptance check, *or* a question. Never both. | Workshop · compile ≤ 20 s with progress and cancel → Talk · confirm readable ≤ 5 s | Work-order board (+ in-world later) | A §1 21:08 + B §Register + **R2, R11** | Holds if X (planner latency R2; "2× load" needs a definition, R11) |
| **S7** | **The handoff.** "Start the night." The builders walk to their districts (recipe-authored, 10 s, skippable). Builders start after the client detaches. **The night is silent by construction.** | Workshop · ≤ 30 s | Plan slate → In-world view | A §1 21:14 + B §spam rule + **R14, R19** | Holds (walk cycle is procedural, not generated — R14) |
| **S8** | **The sealed bet (no screen — the ledger).** edit → predict → **seal** → preview → critic → keep/revert. Every artefact stamped; every write tagged `taste_note` / `prediction` / `verdict`. | Night · the only user-visible surface is the feed | (ledger; Asset library for artefacts) | A §2 23:04 + B §sealed predictions + **C5** | Holds if X (R3 preview, R4 critic, R7 seal) |
| **S9** | **The 2 a.m. peek.** Join cold; understand who did what, kept or reverted; rewind free; **never fast-forward**. Read-only. One stop button, always visible. | Watch · join ≤ 5 s, each card legible ≤ 5 s; stop ≤ 2 s | Night feed | A §2 02:07 + B §kill switch + **C3** | Holds (feed is the log, not the stream — A's own test) |
| **S10** | **The morning report opens.** **Before the world.** First line is the status line, then the failure line, then the night's numbers, then the filmstrip, the branches, the parked questions, the landed work orders, the per-claim-type tallies with denominators, and any model-change notice. | Watch · first paint ≤ 3 s, digestible ≤ 2 min | Morning report | A §3 07:03 + B §failures lead + **C2, G2, G7** | Holds if X (the report is a static page over the ledger; the filmstrip is cached renders, R1/R2 unmeasured) |
| **S11** | **The branch flip and apply.** A/B/C with full imagery, pre-rendered by the night; one tap to apply; the world re-streams. | Watch · flip ≤ 2 s → Workshop · apply ≤ 10 s → re-stream ≤ 15 s | Morning report → In-world view | A §3 07:11 + **C8** (Magnus proposes, Casey confirms) | Holds if X (pre-renders are the night's render budget — R1; apply is a recipe pointer — R20) |
| **S12** | **The parked question — or the assumption that replaced it.** One tap to answer. If a builder assumed instead, the assumption is on the same card, in the same place. | Talk · ≤ 2 s | Morning report | A §3 07:19 + B §open-question policy + **G8** | Holds (both are ledger reads) |
| **S13** | **"Why?" in one tap.** Prompt, seed, model id, weights revision, licence + dependency terms, sampler, environment revision, critic note, who decided. | Talk · ≤ 1 s to open | Anywhere (feed / report / Asset library) | A §4 moment 9 + **R8** | **Holds** — the best-supported promise in either report |
| **S14** | **The growth beat.** The new capability is announced in one sentence, in world, at the moment it becomes useful. If a builder's model changed, that is announced too. | Talk · ≤ 2 s | In-world view / Morning report | A §3 07:34 + B §continuity + **C12** (capability records make it measurable) | Holds (ledger + registry) |
| **S15** | **The ledger line that reaches the artefact.** Not a dashboard: the count is attached to the thing — *"Architect had 14 of 18 right on shadow counts; this one is in that run."* | Talk · ≤ 1 s | Morning report / Asset library | B §Numbers that reach the artifact + **C2** | Holds (a ledger read) |

**Reading of the spine.** The evening (S1–S7) is where every human decision
in the product happens, and it is nearly free of GPU cost — which is why the
budget bar, the slate and the confirm line all belong there. The night (S8–S9)
is machine time and legibility. The morning (S10–S13) is pure UI over cached
artefacts, and therefore *fast forever*. The loop closes (S14–S15) with the
ledger, which is the only thing that grows.

**Where the two reports' "must feel great" lists disagree.** A §4 says: if only
three of the ten moments can be great in phase 4, make them **5, 7 and 8** —
the peek, the report, and the branch flip. B's build order puts its weight on
the ledger, the sealed prediction, budget rails and the kill switch. **The
merged answer:** phase 4's three are **S9 (peek), S10 (report), S11 (branch
flip)** — A's list — but S10 is *built* with B's rules (failures first, tallies
with denominators), and S9 ships with B's stop button. A's list is about
*moments*; B's is about *rules inside* the moments. They are not in conflict;
B's rules are the spec for the three moments A prioritises.

---

## 6. Where `ux-trust` is weakest — self-review

The brief says to review B as hard as A. B's own §Open decisions lists six
things it could not decide. Here is what a hostile reviewer finds in B itself.

### S1. B's cost model is imported from a world that is not this project

B §Safe mistakes grounds the runaway-cost failure mode in AWS per-cycle caps
and Railway's *"roughly $0.40 a run at ten calls… 500 runs a day is about $200 a
day"*. Those are hosted-agent economics. **builder-ide's default planner runs
locally on the Thor** (`[vision §3]`: *"a local LLM, plus the cloud on a
budget"*), and `[cad §9]` says the Thor's real constraint is *"GPU compute-time
and weight-swap thrash"*. So B's most detailed cost mechanism is aimed at a
failure mode this project is unlikely to have, and the failure mode it *will*
have — a night that spends eight hours thrashing between models and produces
four renders — is not in B's table at all.

**Fix:** keep the money rail, scope it to hosted calls, and **add a thrash
rail**: a per-night cap on *model loads* (not GPU-hours), and a per-model-batch
policy that drains rather than churns. B's graduated 80%/95% throttling
survives, but it should throttle *batch admission*, not just spend.

### S2. B specifies no screen and no latency for anything

B's most concrete UI claims — *"the nightly report opens with what failed"*,
*"a single visible button"* — never say which screen, what the layout is, or
how fast it must be. A's whole method is latency budgets and screens. **B's
rules cannot be built or reviewed without them.** A rule like *"the report
leads with failures"* is unimplementable without a screen; a rule like *"one
interruption per builder per twenty minutes"* has no user-visible cost until
someone says what the user sees when it fires.

**Fix:** every rule in B should carry a clock (A's three) and a screen (A's
six). That is the merge's main mechanical work, and it is the reason §5 of this
review exists.

### S3. B's silence rules are right in principle and too absolute in practice

As C1 and C3 show, B's absolute bans ("no builder comments on your absence",
"never claims a feeling it cannot source") kill the two best lines in A — the
recognition beat and the frogs. A rule that is *always* violated is a rule that
will be quietly dropped in implementation.

**Fix:** narrow each ban to its target. Ban longing, absence-duration and
unearned feelings; permit recognition, ledger-cited counts, and observable
warmth.

### S4. B conflates three record types under one single-writer rule

B §Taste note fields says *"Notes are written by the owner's verdict event and
by nothing else"* — but B also specifies `prediction` records written by the
builder and `verdict` records written by the Critic, all in the same store.
The "single writer" rule, read literally, forbids two thirds of B's own
schema. This is the exact confusion that produced C5.

**Fix:** one store, three record types, one writer per type — and state the
table explicitly (C5).

### S5. B's confidence gate is unimplementable as written

B's fourth rule: *"A builder must not predict on a reason code where it has
fewer than two prior observations."* But B's `prediction` schema uses
`claim_type` — `shadow_count | scale_read | clutter_density | material_read |
era_read | light_read` — while the taste utterance cites *reason codes* —
`too_busy | too_empty | wrong_scale | …`. **Two different taxonomies are
conflated in one gate**, and B's `confidence: medium // gated on the builder's
history for claim_type` is then used for both the world claim and the taste
claim.

**Fix:** two namespaces, two gates — a world-claim gate (per `claim_type`,
denominator required) and a taste gate (per reason code, ≥ 2 observations) —
and the `prediction` record must say which namespace it is in.

### S6. B never measures the Critic, and the technology has not chosen one

B §Build order: *"The heavy lift is the Critic becoming genuinely adversarial,
and that is prompt work plus one new role in the queue."* **There is no
criterion for "genuinely adversarial".** A Critic that rejects everything
scores perfectly and is useless; a Critic that never rejects scores badly and
does nothing. Neither report has a metric, and `[cad §9]` puts a critic in the
hot tier without evaluating a single critic model (R4).

**Fix:** a fixed reference set of, say, 30 renders with known defects; the
Critic's false-positive and false-negative rates against it; and a target band
(roughly: it must catch the seeded defects, and it may not reject more than a
set fraction of the clean ones). Without this, "the critic passes it at 2× load"
(A §1 21:08) is not a checkable acceptance criterion — it is a vibe.

### S7. B has no evening

B's rules — the Companion keeps the plan, one question at a time, Plan Mode
"shows the plan up front and lets the human edit and approve the whole thing" —
all bite in the evening, and **B never describes the evening.** The slate, the
walk-and-talk, the handoff and the first night are unowned by B, so B's rules
are untested against the half of the loop where humans are present.

**Fix:** assign S5–S7 of the spine to B explicitly, with the same clock and
screen discipline as the rest.

### S8. B's privacy claim is broader than its evidence

B §Taste note fields: *"the ledger can be handed to a hosted model without
shipping a record of your life."* True for the *text*. But `[cad §9]` and
`[3d §5]` require every artefact to carry provenance, and those artefacts
include renders of a world a child helped design; and `[cad §9]`'s stamps
include prompts, which can contain text the owner typed. Magnus's *rows* are
excluded — and that is the right boundary — but the *artefacts he judged*
remain in the world and travel with any shared permalink (G3).

**Fix:** state the boundary as it is: *rows and reason codes are scoped;
artefacts and their prompts travel with the world.* And make the permalink
action exclude author-scoped rows by default, with an explicit share that
includes them.

### S9. B's six "open decisions" — one is already decided, and one is decided by the technology

B §Open decisions asks six questions. **"Does Magnus's taste count toward
Casey's at all?"** is answered by A: A §1 (20:47) and §3 (07:19) already keep
Magnus's rows separate and badge them (`kid-keeps-wobbly: 3/3`). B should have
marked it closed and cited A. And **"What is the nightly money rail?"** is
partly answered by the technology: the Thor is local and free, so the money
rail applies to hosted calls only, and the real rail is compute-time and
loads (S1).

**Fix:** close one, narrow one, and re-ask the four that remain with the
recommendation attached — that is what the owner actually needs.

### S10. B's ledger is diffable and shareable, and B never says so

Both technology reports make the recipe the unit of truth and reproducibility
(`[cad §8]`, `[3d §5]`). B's ledger is the same kind of artefact — rows with
hashes, written by named authors, never edited. **B never mentions that the
ledger can be reviewed like a git log**, which is the most natural trust
artefact in the whole system and the cheapest possible answer to "why should I
believe this?"

**Fix:** one sentence, and a screen: the ledger is a diffable history; show it
as one.

---

## 7. The decisions this review forces on the owner

Six, each with a recommendation, in the order they block work.

| # | Decision | Recommendation | Blocks |
|---|---|---|---|
| **D1** | Who writes the ledger — the owner only, or the Critic too? | **Three record types, three writers, one store** (C5). `taste_note` = owner only. `prediction` = builder, sealed. `verdict` = Critic, defects only. | The ledger schema, the night loop, the taste model. **Build this first.** |
| **D2** | Can the night keep things without asking you? | **Yes for defects, no for taste** (C5, C6). The Critic may auto-revert on a checkable defect; only your verdict writes a taste note. | The night queue, the morning report, the sealed-bet ledger |
| **D3** | What does the Critic judge — quality, or your taste? | **Two surfaces** (C6). The defect Critic never sees the ledger; the taste critic may only rank, never accept. | The Critic's prompt, the taste model, the "light you keep coming back for" line |
| **D4** | Does Magnus speak? | **No — chips only** (C7). Rewrite A's 20:47 as a two-surface walk; keep the narrative beat, drop the audio. | The kid surface, the privacy boundary, the evening flow |
| **D5** | What is the night rail, in what unit, and how many rails does the owner see? | **One bar for the owner, four counters under it, money scoped to hosted calls only** (C9, R18). Add the per-model-load cap the batched lane requires. | The scheduler, the budget service, the slate UI |
| **D6** | When the night did not happen, what does the morning say? | **A mandatory status line** — `ran as planned / ran short / ran degraded / did not run` — and the report leads with failures and what was cut (C2, G2, C11). | The report format, the failure taxonomy, the queue |

**And one thing that is not a decision, because the technology already made
it:** the prop-maker stack is **TRELLIS.2 via the ComfyUI native path, plus
TripoSR as the parallel baseline** — not modly's texture path. `res-3d` is
newer than `res-cad` on this point and it is the one that removes the source
builds and the licence problem. Worth a line in the plan before the phase-1
spike is scoped, because it changes what the spike measures.

---

## Appendix — what was read, and what was not

**Read:** `~/src/builder-ide/docs/vision.md`; `~/src/builder-ide/docs/research/ux-day.md`;
`~/src/builder-ide/docs/research/ux-trust.md`; `~/src/builder-ide/docs/research/res-cad.md`;
`~/src/builder-ide/docs/research/res-3d.md` (which appeared during this review and
is included in full); `~/src/builder-ide/CLAUDE.md` for the machine and phase
context. **Not used as evidence:** `docs/research/casey-ideas-fromgoogle5.md` — a
Google-search ideation dump, outside the brief.

**Not verified:** anything about Infinigen, Blender 4.2 on aarch64, Cycles render
times, the ProArt client, the vision critic, the planner LLM, or speech — none
of it is covered by either technology report, so no promise resting on it has
been marked "holds" (§4.3). The torch-wheel conflict between `res-cad` and
`res-3d` (R19) is unsettled by inspection and needs one command on the Thor.

**Read-only compliance:** no file outside this directory was created, edited or
deleted; the two research reports and `vision.md` are byte-identical to how I
found them.
