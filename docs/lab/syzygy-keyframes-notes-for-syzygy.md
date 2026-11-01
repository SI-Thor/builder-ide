# NOTES-FOR-SYZYGY — keyframes, deltas and the idle-time cache

**From:** the syzygy-keyframes crew · **Date:** 2026-11-01 (first note 2026-10-31)
**Full write-up, numbers and receipts:** `exp-syzygy-keyframes.md`

---

## The short version

Casey's idea — hold a high-resolution frame in the reader's cached prefix, send
only what changed — **works as a mechanism and is worth building.** On the Thor,
a reader that holds the keyframe reads **1,731 tokens per frame instead of
10,112** when nothing has changed, and runs at **2.29 fps instead of 0.42** —
5.5× the frame rate at the same resolution.

The catch is motion. On a real walk at 148×80, **63.5 % of the glyph cells
change every frame**. The library's critique was right: the cell diff is not
cheaper than the frame. Measured with Groq's own tokenizer, a delta costs
19→**36,405 prompt tokens against the full frame's 8,491** — 4.3× *more*, and on
every one of the 19 frames we tried it did not fit the local reader's 32k
context at all.

So the cost moves into idle time **only while the scene is still**. The idle
trigger is the one that earns its keep; cut and drift are about *when to
refresh*, not about saving tokens.

**And then the reading experiment answered a different question, and the
answer was not the one we expected.** See item 1 below: the picture itself
carries almost nothing about the motion, and the thing that carries it is one
character per cell.

## Eight things the crew can take

1. **A picture does not carry its own motion; a motion channel does — and the
   channel is one character per cell.** On the Infinigen scenes with exact
   ground truth (72 frames, 3 scenes, Groq gpt-oss-20b; the blind control is
   the wrong frame with the right markers):

   | what the reader sees | "which way is the scene moving?" |
   |---|---:|
   | the text frame alone | **0.431** — *below* the blind floor of 0.486 |
   | the text frame **+ the motion channel** | **0.889** — +40.3 points, p < 0.00001 |
   | the previous frame too | 0.522 — at the floor |
   | the cached keyframe + the delta | 0.403 — at the floor |
   | the truth in words (the ceiling) | 1.000 |

   And it **survives the resolution drop**: at 74×40 instead of 96×52 the
   frame's prompt tokens fall 34 % (3,320 → 2,180) and the motion channel
   still scores **0.873, +41.7 points over blind, p < 0.00001**. The reader is
   reading the channel, not inferring past it: the channel's own information
   content (the frame-wide median flow direction) is 62/72 = 0.861 against the
   reader's 0.889.

   **What this suggests for the kernel:** the kernel already emits three
   planes; a fourth — the per-cell flow direction and magnitude, quantised to
   the existing glyph set — is a small change, and it is the only thing here
   that carried information into the reader. It also says the brief's premise
   holds in a sharper form: *the resolution can be scaled down and the motion
   information kept, because the motion was never in the resolution.*

2. **A cell delta needs a cheap encoding before it can win.** The addressed
   form (`"g 12 34 X"`, ~9 characters per cell) costs more than the cell's own
   text. Run-length encoding (row, x0, x1, the glyphs) cut ours 2.3× on one
   plane (59,785 → 25,803 characters) and 3.1× across all three
   (186,794 → 59,430) — and *still* is 5× the full frame, because half the
   grid changes. Please treat "the delta encoding" as a kernel-side concern: a
   bitmap plus a change list is the shape we want, and it belongs next to the
   0008 wire buffer, not in the reader.

3. **The knower's gate should be a max-cell, not a mean.** We ported
   quilt-jepa to the Syzygy text (numpy and torch; the two agree to
   1.6 × 10⁻⁶, and the GPU port runs the 148×80 grid in 34.6 ms a frame) and
   injected a real object into a walking scene. The **max-cell** surprise saw
   it (contrast 1.51, detected, 4 frames later, 0 false alarms in 23 frames);
   the **mean** surprise did not (contrast 1.04) — and on a *static* scene
   neither did (contrast 1.00). That is quilt-jepa's law (b) confirmed on our
   world, and it also says the surprise is only meaningful on a hard world.
   The max-cell gate fires **5.2 frames before** the change it predicts, with
   no false alarms.

4. **d1-2B cannot hold state yet, and it cannot read the scene either.**
   It is LFM3-D1, a decision model: llama.cpp serves it at `/v1/systemone`
   (nice: typed questions with probabilities), but `--cache-reuse` is refused
   for this context and `/slots/0?action=restore` fails with `failed to
   restore sequence state`. The brief's "Liquid state snapshot for d1" is a
   **build**, not a flag. Separately: d1 sits on the *blind floor* for every
   arm we tried, including the motion channel that moved the cloud reader by
   40 points, while its instruction-following control is perfect
   (0.997/1.000/1.000). It is a good probability instrument and a poor reader —
   so if you want to know whether an arm helps a reader, d1 is not the reader
   to ask.

5. **The codebook does not change the keyframe arithmetic.** A frame at
   148×80 costs 6,523 tokens in d1's vocabulary and 10,112 in LFM2's (the same
   text, two vocabularies). A learned codebook maps a cell to one
   *token-friendly* symbol, which lands in the same order of magnitude. What the
   codebook *can* change is the cost of a *changed* cell. The forge's lever is
   the delta, not the keyframe.

6. **Motion compensation with one global shift makes the delta worse, not
   better.** On the walk, shifting the previous frame by the estimated global
   motion and re-diffing leaves **21,909** changed cells against the plain
   delta's 19,464 — one shift cannot describe a parallax field, so the residual
   grows. The motion channel (h) has to be *per-cell* to work; a global
   displacement vector is not enough at this grid.

7. **A small, free win: the motion channel's alphabet.** The per-cell flow
   channel (arm (h)) is one character per cell — but if that character is a
   Unicode arrow the same plane costs **14,845 tokens**, and if it is an ASCII
   character (`<`, `^`, `>`, `v`) it costs **2,986** — **5× cheaper for the
   same information**. The kernel's own alphabets are chosen for the eye; the
   reader's budget is spent on the tokenizer. Worth a line in the forge's
   codebook discussion: the cheapest symbol is the one the reader's tokenizer
   already knows. (This run also fixed a bug in our own quantiser, which
   indexed a 4-character string with 4 or 6 and so died on any diagonal flow.)

8. **The emitter/projector split sends 157× fewer bytes and builds the wrong
   picture.** 228 pose bytes a frame against the text frame's 35,828, and the
   reader's local kernel run is 5 ms. But the picture the reader builds for
   itself agrees with the true picture on **12 % of its cells** (cell IoU
   0.51 against the true object mask): the projection knows *where* the
   objects are and not *what they look like*. The wire is the easy half.

## What we need from the director

- **Groq does not itemise cached tokens** for `openai/gpt-oss-20b`: the usage
  record has no `prompt_tokens_details`, and `usage_breakdown` is `null`; a
  repeat-prefix probe shows no measurable cache effect either (1.22 s cold
  against 1.52 s warm). The brief's fallback is "DeepSeek through aider, so ask
  the director" — there is no aider or DeepSeek seat on this box. Please pick
  one: seat DeepSeek, name a provider that itemises cached tokens, or accept
  the local llama.cpp text reader as the cached reader for all cost work (our
  recommendation — it shows the token counts, not just the latency).
- **The Infinigen ground-truth renders of the 92-scene sweep** are still queued
  behind the shared memory lease and did not land in this session either;
  `harness/gt_batch3.sh` will pick them up when the lease frees, and it now
  reuses the sweep's already-rendered terrain so a scene costs ~3 minutes
  instead of ~90. Our exact-ground-truth corpus is three scenes (arctic-s1,
  canyon-s1, hello_world) — 72 frames of exact labels.

## And the thing worth trying next

Not a delta. **A fourth plane.** The kernel emits three alphabets; the reader
that could read the scene could not read the *motion* from any of them, and
could read it from one character per cell of a fourth. The delta is a codec
problem that needs a cheap encoding first (item 2). The motion plane is a
kernel problem that looks like a small change now.
