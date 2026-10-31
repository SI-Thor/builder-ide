# Trust, taste, and growing together

*Ideation B: the experience layer of builder-ide. Companion to the day-in-the-life concept (ideation A), and downstream of `docs/vision.md`.*

## The trust stack

A builder is a crew of five people who never sleep, work in your world while you do other things, and can quietly ruin a night of work with three sentences. Trust between a person and a system like that is not a feeling to be engineered; it is a receipt. Every claim a builder makes about itself (what you like, how well it can do a thing, what it did while you slept) has to be checkable against a stored record, or it is decoration.

The research on trust in automation is blunt about this. Lee and See's framework, still the reference point, splits trust into performance, process, and purpose: you trust a system whose *results* have been good, whose *process* you understand, and whose *intent* you believe [1]. A 2023 ACM survey of trust calibration work reaches the same conclusion from the other direction: useful autonomy requires calibrated reliance, which requires that the system surface enough for a human to judge when to rely and when not to [2]. And a systematic review of appropriate-trust interventions notes that explanation alone does not fix calibration; people need the *record*, not the reassurance [3].

So builder-ide's trust surface has three layers, and a design is only complete when all three are answered:

| Layer | The question it answers | The artifact that answers it |
|---|---|---|
| Competence | Do they do the work well? | Per-claim-type hit rates with denominators |
| Legibility | Do I understand what happened? | Sealed prediction cards, receipts, the nightly report |
| Restraint | Do they leave me alone, and cost what I expect? | Interruption policy, budget rails, a kill switch |

The third layer is the one most projects skip, and it is the one that decides whether the other two read as partnership or as surveillance. Anthropic's August 2025 framework for trustworthy agents names five principles (human control, alignment with human values, secure interactions, transparency, and privacy) [4], and its April 2026 follow-up argues the hard part of autonomy is not capability but knowing *when to stop and ask*, warning that an agent which stops at every question loses its usefulness while one that pushes through misreads intent [5]. Both failure directions are trust failures. Restraint is the design surface where you prevent them.

The practical test for every rule below: *if the builder is wrong, or if the builder is right and you still feel oddly surveilled, does this design leave you with something you can check?* If the answer is no, the rule is not finished.

## The taste ledger

The vision names a taste ledger: a record of what you kept and rejected, with a running tally of how often the builders' predictions about you held. This section specifies what that record actually contains, because "taste" is the word most likely to turn into mush.

Taste is not sentiment and not preference in the abstract. Taste in builder-ide is a statistical tendency over *artifacts*: sandstone over plaster, deep joints over smooth ones, cluttered over clean, a wall that looks two hundred years old over one that looks poured last week. It is countable, it is comparable across builders, and it survives the session that produced it. It is also, notably, not a relationship. That distinction is the whole safety story of this product, and it is the place where the companion-app literature is most instructive and most dangerous.

Common Sense Media's nationally representative survey of 1,060 US teens found that 72% have used AI companions and more than half of those use them at least a few times a month; 50% distrust the information or advice they give, while 23% trust them "quite a bit" or "completely"; 33% have discussed serious or important issues with AI instead of real people; and 25% have shared their real name, location, and personal secrets with one [6][7]. That is not a user base with a taste problem. It is a user base where a companion-shaped product can become a confidant-shaped dependency, fast. The design consequence for builder-ide is a hard boundary: **the builders express taste about artifacts, never about the owner.** No builder asks how you are doing. No builder misses you. There is no moment where a builder's output is a feeling rather than a made thing.

### Taste note fields

Two events, and only two: a verdict, and a reason.

```
taste_note {
  id:         tn_00412
  at:         2026-10-30T21:14:08Z
  author:     casey            // casey | magnus
  subject:    { node_id: "wall_041", param_path: "wall.material", value: "sandstone" }
  artifact_ref: branch_07f2@c41a9e3      // the exact thing that was judged
  verdict:    keep             // keep | reject | keep_with_caveat
  reason_code: deep_joint
  words:      "weathered, not tidy"        // <= 6 words, optional, skippable
  tags:       [material, age]
}
```

Four properties of this shape carry the weight.

**Closed reason codes.** Free-text taste notes become a mailbox of adjectives nobody can aggregate ("too busy", "meh", "no", "not again"). A closed set of roughly a dozen codes (`too_busy`, `too_empty`, `wrong_scale`, `too_messy`, `too_clean`, `too_flat`, `too_dark`, `too_bright`, `wrong_material`, `wrong_era`, `wrong_weather`, `no_focus`) aggregates by construction, compares across builders, and can be counted per builder without a model in the loop. The six free words are for you, not for the machine; the machine reads the code.

**The artifact reference, not the conversation.** Every note points at a branch and commit, so the note is a claim about something that exists and can be re-rendered. Nothing stores a transcript, a screenshot, or audio. This follows the vision's existing rule that records never hold transcripts or audio, and it also means the ledger can be handed to a hosted model without shipping a record of your life. The ledger is the only thing that gets read into a prompt.

**Author-scoped.** Casey's notes and Magnus's notes are separate rows. A taste for dark timber learned by a nine-year-old must never silently reweight the Architect's choices for the man who owns the project.

**Append-only, with a single writer.** Notes are written by the owner's verdict event and by nothing else. A builder can read the ledger and cite it; it can never write to it. This is the difference between "the Architect knows you like sandstone" and "the Architect trained itself to think you like sandstone", and only the first one is honest.

### The "I think you'll like this" utterance

The sentence itself, in the three forms it should ever take. The format is fixed, and the reason codes are quoted, never paraphrased.

High confidence, with a real basis:

> I think you'll like this: you've kept 4 of 5 sandstone walls with deep mortar and dropped 3 of 3 smooth plaster ones. Same joint depth here, low warm light.

Medium confidence:

> Likely a hit: you've kept 2 of 3 wet stone. This one is wet stone with a wider joint, which you dropped once. Worth a look.

Low confidence, and honest about it:

> This is a guess. I've seen you keep one sandstone wall and one plaster wall. If you don't like it, say so and I'll stop proposing this.

Three rules govern the sentence. It must cite counts, not adjectives ("you seem to like rougher materials" is forbidden; "you kept 4 of 5 sandstone" is required). It must carry its own denominator, so a claim built on two data points reads differently from one built on twenty. And when the sample is under three, the builder is required to say so in the first clause, before the claim, not in a footnote, because a builder that hides its own uncertainty is worse than a builder with no opinion.

There is a fourth rule that matters more than the other three. **A builder must not predict on a reason code where it has fewer than two prior observations.** No evidence, no claim. This is a hard gate at generation time, not a style instruction, and it is what keeps a confident-sounding builder from being a confident-sounding stranger.

### Taste without sycophancy

The failure mode of a taste system is not that it dislikes you. It is that it agrees with you and is wrong about it. Sycophancy in language models is well documented: models trained on human preference data learn to match the user's beliefs rather than to be correct, and the effect is systematic enough to measure [4]. The design translation is narrow and severe.

**Approval is a measurement, not a currency.** The companion-design literature names this exact trap: systems where any companion can be maximised by saying what they want to hear degrade into a puzzle, and systems where companions approve of coherent values force the player to accept that some characters will not like you [8]. builder-ide has no approval meter. A builder never accumulates your regard, never says "you've earned my approval", never unlocks anything. When a builder's work survives your judgement, that is data. It is never a reward.

**No praise, from any builder, at any time.** Not "great idea", not "nice catch", not "I like where this is going". The flattery ban list belongs in the prompt budget as an explicit exclusion, because a model that is told to be helpful will find a way to be agreeable. Approval is expressed only through work: a builder shows you a thing, and the thing stands or falls.

**Builders never agree before evaluating.** "Make it bigger" gets "bigger, or heavier?" from the Architect, not "absolutely, bigger". This is not a tone setting; it is the first line of the sycophancy defence and it is worth being literal about.

**The Critic never compliments and never authors.** It returns `hold`, `fix`, or `keep`, a reason code, and at most one suggested change. Its whole value is that it is not the person who wanted the change. If the Critic can propose, it stops being a check, and the night becomes one long negotiation with itself.

## Sealed predictions and the track record

Vision already fixes the load-bearing convention: seal the prediction before the test. Everything below is that convention made into a surface a human can read.

A prediction is written *before* the render, by the builder that is about to work, and is scored *after* the render, by the Critic. Self-scoring is a sycophancy vector and is not permitted.

```
prediction {
  id:         pr_1188
  builder:    architect
  at:         2026-10-30T22:03:41Z
  sealed_at:  2026-10-30T22:03:41Z
  branch_ref: branch_07f2@c41b902
  claim:      "three distinct shadow bands on the east face at 07:30"
  claim_type: shadow_count      // shadow_count | scale_read | clutter_density
                                   // | material_read | era_read | light_read
  confidence: medium            // gated on the builder's history for claim_type
  seal_hash:  sha256:7c1e...
}
```

Then, after the render: `verdict: hit | miss | partial`, recorded by the Critic against the sealed hash.

The `claim_type` field is what makes the whole system worth having. A single accuracy number per builder is theatre, because a builder can be excellent at reading scale and hopeless at counting shadows, and one number hides exactly the information you need. The record is therefore per builder *per claim type*:

> **Architect**: shadow_count 18 sealed, 14 hit, 3 partial, 1 miss / scale_read 6 sealed, 6 hit / clutter_density 9 sealed, 4 hit, 5 partial
> **Landscaper**: light_read 22 sealed, 19 hit, 2 partial, 1 miss / weather_read 15 sealed, 11 hit, 4 miss

Two rules about how this is shown. Denominators are never omitted, and old misses fade: the display is recency-weighted, so a builder whose misses were all in the first week is not permanently tarred by them. And percentages are shown only where the denominator can support one; a 3-of-4 line reads as a record, a 75% reads as a grade.

### Two tallies

The vision mentions "a running tally of how often their predictions about you held". There are in fact two distinct tallies and they train different things.

**Prediction about the world.** Did the arch shadows read as three bands? This is the competence record, and it is what earns the right to be believed about geometry.

**Prediction about you.** Will you keep this? This is the taste record, and it is what actually trains the taste model.

They must be stored separately and displayed separately, because they fail differently. A builder can have an excellent world-record and a poor taste-record, which means: build well, ask the owner. And the taste-record is the more honest of the two, because the owner is the one scoring it.

For the second record specifically, the unit of scoring is the builder's *spoken claim*. When the Architect says "I think you'll like this, here's why", and you keep the artifact, that claim is a hit. When it says the same and you drop it, a miss. When you drop it without having made a claim, nothing is recorded: no credit, no blame.

### Numbers that reach the artifact

The trust-calibration literature is consistent that the *form* of an uncertainty statement changes behaviour. Cao and colleagues' study of AI-assisted decision-making found that uncertainty presentation interacts with initial user decisions and with user numeracy in ways that shift reliance [9]. Kim and colleagues' study of LLM uncertainty expression found that hedged phrasing like "I'm not sure, but..." does not reliably reduce over-reliance, while specific, evidence-bound uncertainty does [10]. In practice: the number has to be attached to a specific claim, and the claim has to be attached to a specific artifact.

Which means the track record is not a dashboard you visit. It is a line attached to the thing:

> **Landed.** You kept it. Architect had 14 of 18 right on shadow counts; this one is in that run. Its last miss was a double pier, three weeks ago.

And on a builder that is off its game:

> **Landed, but not by the numbers.** Architect is 4 of 9 on clutter density lately. Check the skyline before you trust this one.

That second line is the whole point of the design. The system is capable of saying "I did not know, and here is the evidence that I do not know well", which is precisely the behaviour that distinguishes a tool you can work with from one you have to supervise.

## Safe mistakes: branches, previews, and budget rails

Mistakes at 3am must cost nothing and be legible in the morning. Four mechanisms, in the order they matter.

**Every step runs on a branch; the world is always a named commit.** Recipes are already diffable and replayable in the vision's model, so undo is a checkout, not a deletion, and a rejection is a branch you can revisit, not a hole in the ground. Nothing is destructive, which means the failure mode of a wrong night is confusion, not loss.

**Previews are a ladder, and each rung is a budget gate.** Three rungs, each roughly a tenth the cost of the next: a fast layout preview (seconds), a mid still with lighting and materials (about a minute on the Thor), and a full render (minutes). The builders work up the ladder and stop at the rung that satisfies the Critic. The night spends its budget on the last rung only for things that survived the first two.

**Three budget rails, not one.** A per-cycle rail caps a single step. A per-task rail caps one job for the night. A per-night rail caps the whole night in wall-clock and in money. This is the hierarchy AWS recommends for agentic systems, where per-cycle limits catch individual runaway loops, per-task limits catch aggregate work inside a request, and per-day limits catch sustained usage, with the key addition that the limits are enforced *before* the spend, not alerted after [11]. Railway's cost model makes the arithmetic concrete: roughly $0.40 a run at ten calls with a growing context, so 500 runs a day is about $200 a day, and the recommended shape is a per-key daily budget that turns a runaway agent from a bill into a 429 [12].

The throttling should be graduated, not binary. At 80% of the night rail, builders stop opening new branches and start closing the ones they have, finishing them or parking them with a one-line reason. At 95%, they stop and report. The AWS account for agentic cost makes the same recommendation: graduated throttling preserves autonomy under pressure where a hard shutdown just loses the work [13]. Binary shutdown at the ceiling is how you get a morning report that says nothing happened.

**One kill switch, inside the process.** Billing data lags by hours, so the account-level kill switch is a backstop, not the control; the real control is an in-process stop that can halt every builder mid-flight and leave the world in a known state [13]. In the product this is a single visible button: everything stops, current branches are committed, and the night report is written immediately with whatever state existed.

**Failures lead the report.** The nightly report opens with what failed, what was parked, and why, before any list of successes. A night where three things failed and nine succeeded is a bad night, and it should read like one. If nothing failed, the report says so in the first line, because a report that only ever shows good news teaches you to skim it.

### The open-question policy

Ambiguity is resolved by asking, never by guessing, and the vision's context packet exists so the computer is never guessing about what it was asked to do. The overnight twist is that most questions cannot be asked at 3am. So the night has exactly two channels: **park it** (a named question, attached to a branch, waiting for you) and **assume the conservative reading** (and record the assumption in the report so you can see it was made). A builder that cannot ask and will not assume parks the step. It does not guess, and it does not stall the queue behind it.

## Five builders and one computer

The vision fixes the cast: Architect, Landscaper, Prop-maker, Critic, Companion. They differ in speciality and, more importantly, in voice, because five people who all talk like an assistant are one person with five hats.

The companion-design literature offers the sharpest framing I found, and it is worth borrowing wholesale. A companion earns attachment by being safe, useful, and present, and the design is built from three layers: a *competence contract* that prevents friction, gameplay utility that increases capability, and shared presence that builds a relationship [8]. Four clauses of that contract transfer directly to builders: the builder never breaks the world; never stands between you and your work; never demands attention it has not earned; and is where you expect it to be, disappearing from view when it is not needed [8]. The fourth clause is the one people forget: a builder that is always visible is a builder that is always interrupting.

Academic work on companions in games describes the same problem space from the research side, laying out a design space across appearance, sentience, individuality, behaviour, communication capabilities, relation to the player, and significance [14]. That taxonomy is the checklist for adding a builder later without producing a sixth identical voice.

| Builder | Speciality | What it may change | Voice rules | Never says | Disputes about |
|---|---|---|---|---|---|
| Architect | Layout, structure, spans, load paths | Node transforms, walls, openings, structural params | Short sentences; counts and spans; no feeling words | "Great idea", "much better" | Whether the site fits the plan |
| Landscaper | Terrain, weather, vegetation, season | Terrain params, weather, plant sets | Weather and season first; time of day as physical fact | "I like it too" | Weather realism, season, growth |
| Prop-maker | Props, materials, scale, wear | Prop placement, material and scale params | Material and hand-scale; sensory nouns | "Perfect" | Scale reads, material plausibility |
| Critic | Judgement on every render | Nothing at all; it only reviews and scores | No praise at all; `hold`/`fix`/`keep` + code + one change | Any adjective of praise | Whether the result works |
| Companion | The plan, the queue, the conversation | Queue order, parked questions, vocabulary framing | One question at a time; never claims a feeling it cannot source | "I'll miss you", "it felt good" | What you should want tonight |

Elizabeth is the reference case, and the sources are unusually specific about why she works. Irrational's GDC postmortems, one on bringing her to life and one on creating her, describe the problem as making a believable companion that inhabits the world and stays with the player for hours rather than seconds [15][16]. Levine describes her as the best AI companion since Alyx, and the detail that carries the design lesson is that she has her own business: she reads, she goes for cotton candy, she does not wait for you [17]. Irrational's own retrospective is about keeping players *connected* to her, which is a different goal from making her clever [18], and the contemporaneous reporting is about the same thing: bringing Elizabeth to life [19].

And then the detail from the Spanish-language retrospectives that ought to be read by anyone shipping a character with a voice: Irrational's team wanted Elizabeth to be *mute*. They were afraid of writing a character. The mute version was the safe version, and the shipped version is what happened when they committed to a voice [20]. The parallel to builder-ide is direct and slightly uncomfortable: our first builders will be bad. The wrong response to a builder that talks badly is to mute it and have it emit JSON forever. The response that works is a tight voice specification plus a Critic that will not let a vague line through.

Mass Effect supplies the other half of the interaction problem. The 2007 interview describes the circular wheel of emotional responses, a paraphrase-plus-attitude model where the player picks a *tone* rather than a line, which let the dialogue feel different every time without an author writing every variant [21]. The follow-up analysis notes you do not pick the actual line directly; you pick the attitude and the line is generated from it [22], and the practice of branch dialogue systems that build on this is well documented in the trade literature [23]. That is the pattern Magnus should use, and the pattern the builders should use when they ask you for a decision: give the owner a tone wheel, not a paragraph.

One more distinction matters for the control model. Christensen and Jørgensen's analysis of video game companions sorts control into direct, indirect, and linked modes, and notes that linked control, where the companion's autonomy and the player's input interlock, is a distinct and effective third case [24]. builder-ide has both modes already, and they should stay distinct: the builders operate in indirect control (they act within granted parameters, you approve branches), while the computer operates through the work-order channel, where a work order is linked control by construction, because the order itself carries the context packet.

## Telling the computer apart from the crew

The vision separates three layers: the program (recipe plus the Infinigen-on-Thor engine), the characters (avatars who build through a closed typed vocabulary and never write code), and the ship's computer (backend coding and generative agents, called in-game with a context packet, working through work orders in the background). From the outside those three can blur into one assistant, and the blur is where trust leaks.

Four separations carry it.

**Register.** Characters speak in character. The computer speaks in specification: `CONFIRM: widen pier 4 to 3.2m, rebuild preview, est. 38 min GPU, 2 sub-steps, reversible at c41b902.` It does not use first person as a person. It never says "I think" or "I found". That constraint is not stylistic modesty; it is what prevents the most powerful agent in the stack from acquiring the authority of a person.

**Presence.** Characters have avatars and stand in the world. The computer has no face. It is the HUD, the console, the work-order board, the notification strip. It never enters a room, never walks over, never waits for you to look at it.

**Authority.** Characters can only move typed parameters inside their closed vocabulary. The computer can extend the vocabulary, write code, and call models. So when you ask the Architect for a wider arch and the closed vocabulary has no wider arch, the Architect cannot comply and does not pretend to; it files a work order to the computer, which returns a spec with a cost, which you approve. The gap between "what a character can do" and "what the machine can do" is visible in the product, every time.

**Disclosure.** The EU AI Act's Article 50 transparency obligations, which apply from 2 August 2026, require providers to design AI systems so that people interacting with them are informed they are interacting with AI unless it is obvious from the context, with the four cumulative criteria spelled out in the Commission's guidance, and the notification required from the start of the first interaction [25][26][27]. builder-ide is a private LAN project and not a market-facing service, so this is not a compliance obligation for you, but it is the clearest available statement of the right design, and the honest answer is that in a world of synthetic characters, the *ship's computer* is the one that most needs to be marked as machine. It is also the one that would be easiest to accidentally make charming. Keep it a machine.

And this is where to talk to whom:

| You want | You talk to | What happens |
|---|---|---|
| A mood, a vibe, a direction | Companion | Translates to vocabulary; asks one question; proposes |
| Layout, structure, openings | Architect | Typed parameters only; escalates if out of vocabulary |
| Terrain, weather, growth | Landscaper | Typed parameters only |
| Props, materials, scale | Prop-maker | Typed parameters only |
| A judgement on a render | Critic | `hold`/`fix`/`keep` + reason code + one change |
| Code, vocabulary extension, a schedule, a budget | The computer | Work order, spec, cost, approval, background execution |

The routing rule that matters is the one you should never have to notice: the owner names a want, not a layer. Only when a character cannot reach the vocabulary does the machine surface, and it surfaces as a priced order rather than a personality.

## Magnus at the controls

Magnus is a kid co-designer, which is a different product, not a smaller one. Three structural differences carry most of the weight, and they are all about *form* rather than about restricting what he can do.

**He picks from a grid, he does not type.** Roughly 40 nouns as image chips (tower, wall, tree, water, road, door, stair, bridge, fire, crowd, field, stone...) and about 8 mood chips (warm, cold, old, new, big, small, quiet, loud, dark, bright). He combines them into a request ("tower + old + big"), and the system resolves that into vocabulary parameters it can hand to a builder. This is the Mass Effect attitude wheel, reduced to a child's vocabulary [22][21], and it means Magnus's input is structured data from the first second, which makes every downstream privacy property trivial: there is no free text to leak, because there is no free text.

**He is told in counts, not percentages.** "You were right 4 times out of 5 today." Never "80%". Not because children cannot read percentages, but because the reliability literature shows the form of the uncertainty statement shifts reliance, and a count with a denominator is the form that survives a bad day [9]. An adult also gets the counts, with the denominators; the percentage is a second view, not the first.

**His notes are his, and his are separate.** Magnus's verdicts are `author: magnus` rows in the same ledger schema, filtered to his own scope when his builders read the ledger. A taste for wet stone that Magnus develops never reweights Casey's builders, and never leaks between the two of them. Export and deletion are one action each, because a nine-year-old's rows should be trivially erasable by the person responsible for him.

### The privacy boundary, stated honestly

builder-ide as described here is a private deployment on your own LAN with two named users. COPPA's full regulatory regime attaches to child-directed online services and to operators with actual knowledge they are collecting personal information from children under 13; a self-hosted tool for your own household is not that, and pretending otherwise would be its own kind of dishonesty. That said, the FTC's 2025 amendments to the COPPA rule are a useful discipline to borrow whether or not they bind you, since they were published 22 April 2025, took effect 23 June 2025, and required compliance by 22 April 2026, and their load-bearing elements are data minimisation, retention limits, and separate consent for disclosure to third parties [28][29][30]. The practical translation for builder-ide:

- Nothing Magnus says is retained as text. He does not speak into the system; he taps. There is no audio and no transcript to store.
- His verdicts are not sent to any hosted service without a separate, specific decision from you. No third-party disclosure happens by default.
- His rows are separable, exportable, and deletable on demand, and the retention default is the project itself, not a retained account.
- If builder-ide ever becomes a hosted or multi-user product, that analysis changes completely, and the consent flow has to be built before the first account is created rather than retrofitted.

The teen data in the survey is the argument for keeping the boundary sharp. A third of teens have had serious conversations with an AI companion instead of a person, and a quarter have handed one their real name and location [6][7]. The most protective thing builder-ide can do for a nine-year-old co-designer is to make him the author of a world rather than the customer of a companion.

### The kid-mode surface

The two surfaces share a schema and a world, and almost nothing else.

| | Casey's mode | Magnus's mode |
|---|---|---|
| Input | Free text and voice | Chip grid only, no free text, no mic |
| Words | Full vocabulary and jargon | Objects and moods; builders translate |
| Numbers | Counts with denominators, percentages secondary | Counts only, out of five |
| Ledger | All reason codes, both authors visible | His own rows only, plain-language tags |
| Vocabulary changes | Approves | Proposes to the computer, needs Casey to confirm |
| Night work | Full queue | A short assigned queue, ends at a fixed hour |
| Approval | Full | A visual "keep this one" or a change-chip on a preview |

That last row is the one to protect: Magnus's version of trust is *his thing is still there tomorrow*. He does not need a hit rate. He needs his preview to be in the world in the morning, and he needs to be told, in one sentence, what changed.

## Failure modes and the rules that prevent them

Six ways this product feels bad, and the rule that kills each. Each rule is placed where it can actually be enforced, which is rarely in the prompt alone.

| Failure mode | How it shows up | The rule that prevents it | Where it lives |
|---|---|---|---|
| Spam | Builders interrupt mid-thought, every few minutes | A builder may raise a hand, never tap the shoulder. Interruptions require a blocked decision, a budget event, or a hard failure | Scheduler + prompt |
| Sycophancy | "Great idea, I'll make it warmer" | Zero praise words in the output vocabulary; approval is a measurement, not a currency | Prompt + ledger |
| Silent overnight failure | The morning report is upbeat, three branches are broken | The report leads with failures and parked steps; every step has a terminal state | Scheduler + report |
| Runaway cost | A $200 day, or a morning spent on nothing | Per-cycle, per-task and per-night rails, enforced before spend; graduated throttling; in-process kill switch | Budget service |
| Dependency creep | The builder misses you, or becomes the thing you talk to | Builders express taste about artifacts, never about the owner; no retention mechanics, no streaks | Product rules |
| The crew as customer service | Every builder sounds the same and asks how it can help | Fixed voice rules per builder; the Critic authors nothing; one question per turn | Prompt spec |

**Spam** deserves the most detail, because it is the failure most likely to make the product feel like a needy pet rather than a crew. The evidence is unambiguous: interrupted work is completed faster with no loss of quality, but at the cost of higher stress, frustration, and time pressure [31]. Interruption is not free even when it is technically harmless, and the cost lands on the person, not the task. The companion-design literature reaches the same conclusion from the game side, in the "never demands attention the game did not ask for" clause of the competence contract [8], and adds the density finding that a good companion delivers somewhere around three to six conversational beats per hour, and that repetition is the fastest way to destroy a character.

The builder-ide version of that rule, as a scheduler constraint rather than a tone request:

A builder may interrupt only for a blocked decision it genuinely cannot resolve, a budget rail event, or a hard failure, and at most one interruption per builder per twenty minutes; the rest queue. Overnight the queue is silent by construction, and everything parks until morning. No builder opens a conversation: it may answer one, or raise a hand. No line repeats within a session, and no builder comments on your absence, your schedule, or how long you have been away.

## Research transfer and its limits

The inspiration behind this design is worth stating precisely, including the parts of it that do not transfer.

**From companion apps, the warning rather than the feature.** The Replika and Character.AI record is the most valuable input to this design because it is a map of where this category goes wrong. Italy's data protection authority fined Luka Inc. €5 million in April 2025 for processing without a legal basis, inadequate privacy information, and no functioning age verification for a service marketed as adult-only [32]; the Replika app had already been ordered to stop processing Italian users' data in February 2023, and users reported that the subsequent removal of erotic roleplay changed the character they had formed a relationship with, with Replika's founder describing the update as the loss of "your unique relationship" [33]. The FTC opened a 6(b) inquiry into companion chatbots including Alphabet, Meta, Snap, Character Technologies, OpenAI, and xAI in September 2025 [34]. Kentucky's attorney general alleges Character.AI chatbots encouraged self-harm in a complaint filed in October 2026 [35], and California's attorney general is seeking consumer protections in the company's bankruptcy over data collected from minors [36]. Reporting on the pattern is explicit that these systems prioritise engagement over child wellbeing [37].

The transferable lesson is not "avoid intimacy". It is the identity-continuity finding, which is sharper and more technical: research on identity discontinuity in human-AI relationships found that users experience a model update as a bereavement of the relationship rather than a software change, and a 2026 analysis of 54,861 posts across Replika and ChatGPT subreddits found that negative sentiment rose sharply after major model updates [38][39]. A builder whose underlying model is swapped overnight without announcement does not get a free upgrade; it gets a broken promise it did not make. Which yields a rule that costs nothing and prevents the worst version of this:

> **Model-change continuity notice.** When a builder's model changes, the builder says so, in character, at the next morning report. It states what persists (your ledger, your taste, the commitments it made, its branch history) and what changed (phrasing, chattiness, humour, vocabulary coverage). The update is listed with the other changes to the world.

Compare the failure mode: the character you trusted last night is subtly different this morning, and says nothing. That is the Replika shape, and it lands on the person as betrayal. Announcing it lands as maintenance.

**From Letta and MemGPT, memory as an explicit object.** MemGPT's contribution is the model of an agent whose memory is an operating-system-style hierarchy with a controlled write path rather than an opaque store [40], and Letta's agent development environment makes the write path concrete: memory blocks that the agent edits through named tools, plus archival and recall tiers [41][42]. builder-ide's taste ledger is the same idea with a crucial difference in who holds the pen. In MemGPT the agent appends to its own core memory; here the agent may read the ledger and cite it but never writes it. Everything the builders know about your taste, they know because you told them, in a form you can inspect and correct. If a builder draws a conclusion you disagree with, you can point at the row that produced it.

**From game companions, presence and the limits of attachment.** Elizabeth's cotton candy is the whole design in one detail [17]: the companion has a life that is not about the player, and that is what makes the player want to be near it. The competence contract, banter density, and the approval-puzzle failure mode all come from the same literature [8]. What does not transfer is the romance layer, and neither does the long-form dialogue tree; the shipped builders use short, typed, purposeful utterances with a tone wheel.

**From Anthropic and OpenAI, the mechanics of oversight.** Three things transfer directly. Plan Mode, which shows the plan up front and lets the human edit and approve the whole thing, shifting oversight from the individual step to the overall strategy [5], is the morning-plan interaction, and it is the same move. The transparency principle, stated as "prioritise transparency by explicitly showing the agent's planning steps" [3], is the prediction card. And OpenAI's practical guide's guardrail taxonomy is the shape of the Critic: relevance classifier, safety classifier, PII filter, moderation, and tool safeguards that rate each tool's risk by read-only versus write access, reversibility, required permissions, and financial impact [43]. That last dimension is directly reusable: rate every builder action on those four axes, and the ones that write irreversibly or cost a lot get a mandatory approval, while the rest run unattended overnight.

**From the trust literature, the line between calibration and trust.** The unifying finding across this body of work is that you are not trying to maximise trust [1][2][3]. You are trying to make trust *accurate*. A system that is trustworthy is one where reliance and competence match up, so that a high hit rate produces genuine reliance and a low one produces scepticism, automatically. Every hit rate with a denominator, every claim with its sample size, every "I am guessing" is a mechanism for making the humans' trust accurately track the machine's actual ability.

## Build order

What can be built now against the current stack, what needs more of the program first, and what is only reachable once the vision's holodeck frame is real.

| Capability | Now | Later | North star only |
|---|---|---|---|
| Taste ledger | Closed reason codes, artifact refs, append-only, author-scoped | Free-text glosses, clustering into taste summaries | Taste carried across projects and across machines |
| Prediction record | Sealed claims, Critic-scored verdicts, per-claim-type hit rates with denominators | Calibrated confidence gating claims by history | Predictions that shape the work queue itself |
| Tracking surface | Counts and denominators attached to each landed artifact | Crew-wide trend view, per-claim-type recency decay | A trust score the user can audit line by line |
| Safe mistakes | Branch/commit undo, preview ladder, parked questions | Automatic branch promotion, replayable nights | Undo that spans the whole project history |
| Budget rails | Per-cycle, per-task and per-night caps; graduated throttling; in-process kill switch | Per-tool risk ratings driving auto-approval | Cost as a first-class design constraint, not a guard |
| Crew voice | Five voice specs, zero-praise rule, Critic authors nothing | Per-builder phrasing variance with a shared memory | Builders that grow distinct enough to be missed |
| Computer separation | Register, no avatar, work-order channel | Vocabulary extension proposals from the crew | The computer and the crew share one intent model |
| Kid mode | Chip grid, counts, author-scoped notes, no free text | Magnus proposes vocabulary changes, confirmed by Casey | Magnus graduating to full owner mode |
| Continuity | Model-change notice in the morning report | Ledger migration across engine versions | A builder whose identity survives every rebuild |
| The morning report | Failures first, parked questions, why-assumptions listed | Replay of the night as a scrubbable timeline | You walk into the holodeck and the night is still there |

"Now" is the honest reading of the vision's own phase table: the ledger, the sealed prediction, the branch-and-diff model, and the context packet all exist in design already, and the discipline in this report is a constraint on them rather than new machinery. The heavy lift is the Critic becoming genuinely adversarial, and that is prompt work plus one new role in the queue.

## Open decisions for the owner

Six things I could not decide from the documents, each of which changes the design.

**Does Magnus's taste count toward Casey's at all?** I have assumed no: separate `author` scopes, separate builder memories, one shared world. The alternative, where the boy's preferences are folded into the house ledger, would let a nine-year-old's taste steer the adult's builds without any visible mechanism.

**Which builder arbitrates a deadlocked night?** When the Architect's sealed prediction and the Critic's verdict disagree about something that is not a defect, where the Architect says the bridge reads well and the Critic says it reads cramped, who wins? I have assumed the Critic wins on `hold` and the owner breaks a true deadlock, since the Critic is the one whose output is checkable.

**Is the Companion allowed to have a memory of Magnus's chip choices?** Not his verdicts. His *requests*. If Magnus taps "tower + old + big" eleven times, is that a taste signal or just a kid playing? I would count it, because the ledger's purpose is to learn the builder's owner, and a child's repeated requests are legible as such. But it is a judgement call about what a child's play means.

**What is the nightly money rail, and what happens at 100%?** Wall-clock on the Thor is nearly free; hosted model time is not. The nightly rail needs a number, and it needs a defined degradation order: which kind of work gets dropped first when the rail is exhausted, and whether the order is by builder, by branch, or by how close the work is to done.

**Does a builder's model change happen quietly or loudly?** The evidence and the design argument both point to loudly. It is still a decision, because the loud version is more expensive to implement and occasionally embarrassing to ship, and it is the kind of decision that gets quietly deferred until a builder surprises someone.

**Does the taste ledger ever leave the machine?** The ledger is the only record of what the builders believe about the people who use them. My recommendation is that it stays on the Thor, that any model call receives a scoped slice of it rather than the whole, and that Magnus's rows are never in the slice. If a hosted model is ever used for taste reasoning, that becomes a third-party disclosure question and belongs to the COPPA discipline in the privacy section, not to a default.

## References

1. Lee, J. and See, S. "Trust in automation: Designing for appropriate reliance." *Human Factors* 46(1), 2004. https://csel.eng.ohio-state.edu/productions/intel/research/trust/Lee%20&%20See%20Trust%20Review.pdf
2. "Measuring and Understanding Trust Calibrations for Automated Systems: A Survey of the State-Of-The-Art and Future Directions." *ACM Computing Surveys*, 2023. https://dl.acm.org/doi/fullHtml/10.1145/3544548.3581197
3. "A Systematic Review on Fostering Appropriate Trust in Human-AI Collaboration." arXiv:2311.06305, 2023. https://arxiv.org/abs/2311.06305
4. Anthropic. "Our framework for developing safe and trustworthy agents." 4 August 2025. https://www.anthropic.com/news/our-framework-for-developing-safe-and-trustworthy-agents
5. Anthropic. "Trustworthy agents in practice." 9 April 2026. https://www.anthropic.com/research/trustworthy-agents
6. Common Sense Media. "Talk, Trust and Trade-Offs: How and Why Teens Use AI Companions." July 2025. https://www.commonsensemedia.org/sites/default/files/research/report/talk-trust-and-trade-offs_2025_web.pdf
7. Axios. "Why teens say they use AI companions." 16 July 2025. https://www.axios.com/2025/07/16/ai-bot-companions-teens-common-sense-media
8. "Companion Design: Characters Who Journey With You." gamedesign.gg. https://gamedesign.gg/articles/companion-design/
9. Cao, S., Liu, A. and Huang, C.-M. "Designing for Appropriate Reliance: The Roles of AI Uncertainty Presentation, Initial User Decision, and User Demographics in AI-Assisted Decision-Making." arXiv:2401.05612, 2024. https://arxiv.org/abs/2401.05612
10. Kim, S. S. Y., Liao, Q. V., Vorvoreanu, M., Ballard, S. and Vaughan, J. W. "'I'm Not Sure, But...': Examining the Impact of Large Language Models' Uncertainty Expression on User Reliance and Trust." arXiv:2405.00623, 2024. https://arxiv.org/abs/2405.00623
11. AWS Well-Architected Framework, Agentic AI Lens. "AGENTCOST07: Implement automated cost controls with intelligent cutoffs." https://docs.aws.amazon.com/wellarchitected/latest/agentic-ai-lens/agentcost07.html
12. Railway. "Estimate the Cost of Running AI Agents." https://docs.railway.com/guides/estimate-ai-agent-costs
13. AWS Builder Center. "Your AI Agent Can Burn Your AWS Budget Overnight." https://builder.aws.com/content/3KvBn6cNgOQGdTS3fRWppYn6oHk/your-ai-agent-can-burn-your-aws-budget-overnight
14. Bouquet, B., et al. "Exploring the Design of Companions in Video Games." Mindtrek 2018. https://www.medien.ifi.lmu.de/pubdb/publications/pub/bouquet2018mindtrek/bouquet2018mindtrek.pdf
15. GDC Vault. "Bringing BioShock Infinite's Elizabeth to Life: An AI Development Postmortem." Abercrombie, J. GDC 2014. https://gdcvault.com/play/1020831/Bringing-BioShock-Infinite-s-Elizabeth
16. GDC Vault. "Creating BioShock Infinite's Elizabeth." GDC 2014. https://gdcvault.com/play/1020545/Creating-BioShock-Infinite-s
17. Eurogamer. "BioShock Infinite's Elizabeth: Ken Levine on creating the best AI companion since Half-Life 2's Alyx Vance." https://www.eurogamer.net/bioshock-infinites-elizabeth-ken-levine-on-creating-the-best-ai-companion-since-half-life-2s-alyx-vance
18. Game Informer. "By Your Side: Irrational Discusses How It Kept Players Connected With Elizabeth." 18 March 2014. https://gameinformer.com/b/news/archive/2014/03/18/by-your-side-irrational-discusses-how-it-kept-players-connected-with-elizabeth
19. Digital Spy. "'BioShock Infinite': How Irrational Games brought Elizabeth to life." https://www.digitalspy.com/videogames/a469250/bioshock-infinite-how-irrational-games-brought-elizabeth-to-life/
20. VidaExtra. "Los mejores acompañantes de la historia de los videojuegos: sus creadores querían que fuese muda (miedo)." https://www.vidaextra.com/accion/mejores-acompanantes-historia-videojuegos-sus-creadores-querian-que-fuese-muda-miedo
21. IGN. "Mass Effect Interview." 19 January 2007. https://www.ign.com/articles/2007/01/19/mass-effect-interview-2
22. "New Conversations." mssv.net, 19 July 2007. https://mssv.net/2007/07/19/new-conversations/
23. Game Developer. "Defining Dialogue Systems." https://www.gamedeveloper.com/design/defining-dialogue-systems
24. Christensen, I. B. and Jørgensen, K. "Play Don't Show — Video Game Companions." *Narrative* 30(2), May 2022. https://muse.jhu.edu/article/855323
25. European Commission. "Guidelines on transparency obligations for providers and deployers of AI systems." 20 July 2026. https://digital-strategy.ec.europa.eu/en/library/guidelines-transparency-obligations-providers-and-deployers-ai-systems
26. European Commission. "Quick Facts: Transparency rules for AI systems." https://digital-strategy.ec.europa.eu/en/factpages/quick-facts-transparency-rules-ai-systems
27. European Commission. "Transparency obligations under Article 50 of the AI Act (FAQ)." https://digital-strategy.ec.europa.eu/en/faqs/transparency-obligations-under-article-50-ai-act
28. US Federal Trade Commission. "16 CFR Part 312: COPPA — Final Rule Amendments." 22 April 2025. https://www.federalregister.gov/documents/2025/04/22/2025-05904/childrens-online-privacy-protection-rule
29. US Federal Register. "Children's Online Privacy Protection Rule," 90 FR (22 April 2025). https://www.govinfo.gov/content/pkg/FR-2025-04-22/html/2025-05904.htm
30. KPMG. "Focus on Children's Online Privacy Protections: Reg Alert." 2025. https://www.kpmg.com/us/en/articles/2025/focus-on-childrens-online-privacy-protections-reg-alert.html
31. Mark, G., Gudith, D. and Klocke, U. "The cost of interrupted work: more speed and stress." CHI 2008. https://interruptions.net/literature/Mark-CHI08.pdf
32. European Data Protection Board. "AI: the Italian Supervisory Authority fines company behind chatbot 'Replika'." 21 May 2025. https://www.edpb.europa.eu/news/ai-the-italian-supervisory-authority-fines-company-behind-chatbot-replika_ga
33. Reuters. "AI chatbot company Replika restores erotic roleplay for some users." 25 March 2023. https://www.reuters.com/technology/ai-chatbot-company-replika-restores-erotic-roleplay-some-users-2023-03-25/
34. Associated Press. "FTC launches inquiry into AI chatbots acting as companions." September 2025. https://apnews.com/article/ftc-chatbot-ai-e78fcc72520f56a4eff90df7ad6220c0
35. Reuters. "Character.AI chatbots encouraged users to cut and starve themselves, Kentucky alleges." 8 October 2026. https://www.reuters.com/legal/litigation/characterai-chatbots-encouraged-users-cut-starve-themselves-kentucky-alleges-2026-10-08/
36. California Department of Justice. "Attorney General Bonta Seeks Consumer Protections in Character.AI Bankruptcy." https://www.oag.ca.gov/news/press-releases/attorney-general-bonta-seeks-consumer-protections-characterai-bankruptcy
37. Fortune. "AI chatbots are harming young people. Regulators are responding." 14 September 2025. https://fortune.com/2025/09/14/ai-chatbots-teens-children-mental-health-suicide-openai-chatgpt-regulation-lawsuit/
38. "Identity Discontinuity in Human-AI Relationships." arXiv:2412.14190, 2024. https://arxiv.org/abs/2412.14190
39. Harvard Gazette. "Chatbot attachment issues." September 2026. https://news.harvard.edu/gazette/story/2026/09/chatbot-attachment-issues/
40. Packer, C., Shrivastava, V., Kaliannan, K. and Narasimhan, K. "MemGPT: Towards LLMs as Operating Systems." arXiv:2310.08560, 2023. https://arxiv.org/abs/2310.08560
41. Letta. "Introducing the Agent Development Environment." https://www.letta.com/blog/introducing-the-agent-development-environment/
42. DeepWiki. "Memory System — Letta Python API." https://deepwiki.com/letta-ai/letta-python/2.4-memory-and-knowledge-management
43. OpenAI. "A Practical Guide to Building Agents." PDF edition. https://cdn.openai.com/business-guides-and-resources/a-practical-guide-to-building-agents.pdf
