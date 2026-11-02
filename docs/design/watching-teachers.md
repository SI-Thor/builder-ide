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
