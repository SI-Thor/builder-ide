# StreamVibe: proactive video agents that decide when to speak (2026-11-01)

**Correction first.** On 2026-10-31 the director took Casey's "streamvibe" to be two GitHub movie-streaming web apps (amirrezaRst/StreamVibe, BAD-WOLF/StreamVibe) and wrote their ideas into agent-world's coach section. Casey meant **this**, which the AI Search roundup of 2026-11-01 links: https://stream-vibe.github.io/ (arXiv 2610.34662, UCSB, Google, Stanford, Oxford and others). The earlier section is kept, marked as superseded.

## What it is
A benchmark (StreamVibe-Bench), a streaming video-language model (StreamVibe-VL) and a memory harness (StreamVibe-Harness) for **proactive assistants**. The agent watches a video stream and, **each second, seeing only the past, chooses to stay silent or respond.**
- **Intents** are explicit ("tell me when the water boils"), implicit ("help me make these jam rolls"), or dynamic (revised, extended or interrupted mid-task). The harness keeps each intent as a **persistent state with a lifecycle**, with task progress and past replies in hierarchical memory.
- **Training:** adaptive streaming SFT that balances silence against response, then GRPO on short rollouts around "help points", rewarding timing, content and consistency.
- **Reported:** +10.7% timing and answer quality over baselines, +12.3% from the harness. It is scored on timing (P/R/F1, false-positive rate) as well as quality. Implicit and dynamic intents remain hard for every model.
- **Release:** the paper is out; code and weights "soon" (7 days, pending approval). No licence stated yet. Re-check.

## Why it is the coach
Our coach ("cues, not commands; observes during flow; steps in when the sign fades") is the same problem: **when to speak**, scored on timing as much as content. StreamVibe gives us:
1. **The metric:** score the coach on *timing* (precision/recall of help points, false-positive rate: speaking when it should be silent), not only on what it says.
2. **The state:** the player's intent as a persistent object with a lifecycle: stated, implied, revised, finished. Our dsmc "gaps" and the canon ledger can hold it.
3. **The training signal:** silence is an action and must be balanced and rewarded; a coach trained only on replies over-talks.
4. **The model, when released:** a candidate for the coach's eyes, reading the spectator frames, under a lease. Check the size and licence first.

## Next
agent-world's coach work (after the playable round and the dsmc foundations) uses StreamVibe's timing metrics and intent states. Watch the repo for the code and weights.
