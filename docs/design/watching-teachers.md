# Watching teachers: the screen watcher as a student of other agents (Casey, 2026-11-01)

> "go further thinking about how the screen watcher can be watching other agents as teachers"

The screen watcher (`screen-watcher.md`) asks each second: *stay silent or speak?* Turned around, the same machinery asks: **is what I just saw worth learning?** The watcher becomes a **student** of whoever is acting on the stream:
- a cloud LLM agent playing slowly and well;
- another bot;
- Casey or Magnus (game state only, opt-in);
- a recorded dataset.

## The loop: predict, notice surprise, keep the lesson
1. **Predict.** The student (a d1-class reflex, or the skill chooser) predicts the teacher's next action from the same change stream the teacher sees.
2. **Notice surprise.** When the teacher does what the student would *not* have done, and it works (the outcome is good), that moment is a **teaching moment**. This is the knower's signal from `three-minds.md` ("Flow") run backwards. Low prediction error means "I already know this"; high error on a good outcome means "learn this". Error on a bad outcome is the teacher's mistake, not a lesson.
3. **Keep the lesson,** as data (a demonstration in a standard format), then as a **tile** (a cloud-written skill that reproduces it, admitted by replay against the recording: the shadow-conductor gate), then, if it recurs, as **weights** (the student's policy fine-tuned on the demonstrations).
4. **Retire the teacher, skill by skill.** Track student–teacher agreement per skill. When the student predicts the teacher reliably, stop asking the teacher for that skill: the teacher becomes the escalation rung, as the cascade already works. **Silence is the measure of trust.** Mediator calls per hour fall as the student grows: the system gets cheaper by watching.

## Teachers, cheapest and safest first
| Teacher | What it teaches | Notes |
|---|---|---|
| **The cloud mediator** (an LLM agent playing slowly) | new skills, plans | We pay for it once, then the reflex does it. LLM scripts becoming tiles, made continuous |
| **Other bots** | local tricks, coordination | Peer learning; the room's propagation decides who hears whom |
| **Recorded datasets** (MineRL demonstrations, Crafter episodes) | broad priors | Licences checked before use (MineRL's data has its own terms) |
| **Casey / Magnus** | taste, intent, what is fun | **Game state only, opt-in; no pixels, audio or transcripts stored** |
| **The director's own interventions** (the seat watcher) | when to step in | Our first labelled data (`screen-watcher.md`) |

## How it fits what we have
- **Three minds:** the teacher is the mediator (slow, rich); the student is the reflex (fast); the canon keeps the demonstrations and the lessons. The mediator is never on the reflex path. It *teaches* the reflex instead.
- **The anti-GAN:** learning by joining, not by losing. The teacher's move is the continuation the student adopts.
- **Presence:** distillation and fine-tuning are **practice-tier** night work; watching is cheap live work.
- **The judge:** the teacher's own confidence decides which moments to trust. Today's lesson applies: a confident teacher can be confidently wrong (the decoy finding), so a lesson is kept only when its outcome confirms it.

## Measures
- Student–teacher agreement per skill, over time (the learning curve).
- Teacher calls per hour (should fall).
- Task success with the student alone vs with the teacher (it must not fall).
- Sample efficiency: lessons needed per skill. Compare learning from teaching moments only (surprise-filtered) against learning from everything.

## Measured, 2026-11-01 (correction)

The first test of the teaching-moment filter (`docs/lab/exp-crafter-lab.md`, Crafter, scripted teacher,
8 eval seeds, one compute budget) does **not** support the mechanism this note assumed:

| student (behaviour cloning) | frames | achievements |
|---|---:|---:|
| all teacher frames | 51,395 | 0.875 |
| teaching moments (surprise + good outcome) | 3,757 | 1.375 |
| random frames, same count | 3,757 | **2.25** |
| PPO alone, 131k steps | – | 1.125 |

The moments beat "all frames", but ~~a random subset of the same size beats the moments~~ (the
8-seed round-2 test did **not** replicate this; see "Measured, 2026-11-02"): at a fixed
budget, the gain came from fewer frames (more gradient passes per frame), not from which frames.
Action agreement with the teacher did not track score either. ~~Until a test at a larger budget, with a
memoryful student, says otherwise, the ladder's "demonstration" step should keep a random-subset
control, and score students on per-skill decisive frames, not overall agreement.~~
**Superseded, 2026-11-02** — that test now ran; see the last section below (old text kept visible).
Also see `docs/lab/exp-sleep-dreaming.md`: one policy trained on all demonstrations risks erasing old
skills (measured next in exp-refit-drift).

## Measured, 2026-11-02 (round 2: bigger budget, memoryful student, 8 seeds)

The test the 2026-11-01 caveat asked for ran on the ProArt: 3 frame selections x 2
students x 2 gradient budgets x 8 seeds, canonical 10000-step eval episodes, 8 held-out
seeds. Full table, intervals and contrasts live with the experiment, in
`/home/proart/lm-wt/crafter-r2/docs/exp-crafter-r2.md` (numbers not copied here).
What changes in this note:

1. **Moments ≈ random at a small budget; all frames win at 3x.** At the round-1
   budget both subsets beat all frames and do not differ from each other; with 3x
   the gradient budget all frames beat both subsets by ~1.8 achievements and the
   subsets improve not at all. Subsampling is a compute-limited shortcut (more
   passes per frame), not better lesson selection: the "demonstration" step should
   use **all** frames when the fine-tune budget allows it (this box: ~30 passes per
   frame), and subsample only under a tight budget — where a random subset does as
   well as the surprise filter and is cheaper.
2. **Surprise+good-outcome is a label, not a data filter.** It kept 98.8 % of the
   decisive frames (nearly vacuous), and students trained on it memorized exactly
   that selection (decisive-frame action agreement 0.989-1.000) while stalling at
   ~1.2 achievements and 0.16 agreement elsewhere. Keep it to say which moment
   mattered; do not let it decide what the weights see.
3. **Flip the measure.** Per-decisive-frame agreement is gameable (it saturates while
   competence stalls); overall agreement on the teacher's states tracked score
   (r = 0.65 across the 12 arms). So "retire the teacher" must key on agreement over
   **held-out** frames or the student's own visitation — a memorizing student would
   otherwise silence its teacher and fail.
4. **Memory and clone ceiling.** A 16-frame GRU student changed no score in 6 paired
   contrasts (4-8.5x training cost; unverified for long streams), so the reflex can
   stay memoryless here; and the best clone reached 38 % of the teacher, so keep
   retiring skill by skill rather than expecting full distillation from recordings.
