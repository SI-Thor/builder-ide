# The screen watcher: StreamVibe's "when to speak", over screens as well as cameras (Casey, 2026-11-01)

> "streamvibe is important as a concept. think about how it can be a screen watcher just as well as a camera watcher"

StreamVibe (`docs/research/streamvibe.md`) poses one question every second: **given only the past, stay silent or speak?** It tracks the user's intents as states with lifecycles, and it is scored on *timing* (help-point precision/recall, false positives) as much as on content. Nothing in that question needs a camera. A screen is a stream too, and usually a better one.

## Why a screen is easier than a camera
A camera gives pixels and nothing else. **Most screens we care about come with their state:**
- the Minecraft world (server events, mineflayer's view);
- the night (the ledger);
- the seats (tmux panes, logs, git);
- the builder IDE (its own model);
- the spectator page (the world-stream deltas).

So the watcher reads a **change stream**, not frames: time-first, as Casey's rule asks (rates of change, events with Δt). It is the same projection Syzygy does for vision, turning a continuous view into cheap text deltas. Pixels are the fallback for screens whose state we cannot reach (a third-party app, a video), and then a streaming VLM reads them under a lease.

## The shape (the three minds, again)
- **The reflex decides *whether* to speak, every second.** A small time-first gate over the change stream: d1-class, local, milliseconds. Its inputs are rates (success rate falling, stall time rising, error bursts), not levels.
- **The mediator decides *what* to say,** asynchronously, only after the gate fires. A cloud LLM or a template, never on the per-second path.
- **The canon holds the intents.** Each one ("watch for the water boiling", "tell me if a seat stalls", "help me build this wall") is a ledger object with a lifecycle: stated, implied, revised, satisfied, abandoned. The same object type as dsmc's gaps.
- **Silence is an action,** logged and scored. During flow the watcher observes (`design/three-minds.md`, "Flow").

## Where we would use it, cheapest first
1. **The seat watcher: the director's own job, automated.** Today the director watched screens by hand, and every intervention was a help point: hung seats, quota exhaustion, the JAX runaway, the lock starvation, the Wi-Fi saturation. **Those interventions, with timestamps (TEAM.md, last-mile-ops.md) and the board's state before each, are a labelled dataset we already have.** The first experiment: replay the day's board and logs as a stream, and measure a time-first gate's help-point precision/recall and false-positive rate against the director's actual interventions. No privacy question, our own data, and it pays off at once (fewer missed stalls, fewer wasted wakes).
2. **The coach in agent-world:** it watches the *game state* of a human player (not their screen pixels) and speaks when the success rate falls or an intent goes unmet, scored on StreamVibe's timing metrics.
3. **The spectator's narrator (the Orin's screen):** it speaks, through a Paradee voice, when something worth noticing happens. The Biographer, live.
4. **The builder IDE:** it watches the IDE's own state while Casey works and stays silent in flow. When it speaks, it says one line in the first mile's voice.

## Privacy (a hard rule, not a preference)
- Watching a human's screen is watching a human. The kids' privacy rule stands: **no human audio, transcripts or screen pixels stored.** The watcher keeps derived events only (what changed, and the decision), in memory or the ledger, never frames.
- Magnus's play is watched through game state only, and only when Casey opts in.

## Measures (StreamVibe's, adopted)
- **Timing:** precision and recall of help points, and the false-positive rate (speaking when silence was right).
- **Quality** of what was said, scored separately.
- **Cost:** gate milliseconds per second of stream; mediator calls per hour (in flow it should be near zero).

## First experiment
`seat-watcher`: replay 2026-11-01's board states and logs (06:00–15:00) as a one-second change stream. Label the director's interventions as help points. Measure a rate gate against a level gate on help-point P/R and FPR, and the minutes of stall each would have saved. Data: `~/lm-ops/TEAM.md`, `BOARD.md` history, the seats' `.out` mtimes, and the Thor's `last-mile-ops.md`.
