# exp-syzygy-keyframes — moving the resolution cost into idle time

**Date:** 2026-11-01 · **Where:** `~/lm-wt/syzygy-keyframes/` · **Crew:** MiniMax Code
**Runs:** 1–3 (2026-10-31 20:05 → 2026-11-01 08:39) and 4 (2026-11-01 11:46 →)
**Full log of steps, dead ends included:** `NOTES.md`

**Verdict in one line:** the cached-keyframe mechanism is real and cheap, but on a
moving camera the cell delta is several times more expensive than the frame it
replaces — the cost moves into idle time only while the world is still — and the
reading experiment says the thing that carries the motion is **not** the picture
and **not** the delta: it is a separate, cheap **motion channel**, which lifts
the reader's accuracy on "which way is the scene moving" from **0.431** (below
the guessing floor of 0.486) to **0.889**, +40.3 points, *p* < 0.00001.

---

## 1. The question, plainly

Casey's hypothesis: the Syzygy kernel is cheap, the **reader** pays for
resolution. So if the reader can hold a high-resolution frame in its cached
prefix and then be sent only the cells that changed, the frame rate can follow
how much is changing instead of how big the picture is. "If you can move that
cost to idle time somehow, that's the breakthrough." (We do not use that word
in our docs; the mechanism and the numbers are below.)

The experiment asks four things:

1. **Does the mechanism work?** Can a reader hold a keyframe in its cached
   prefix and read only the delta, and what does that cost?
2. **How big is the delta?** Cells and tokens per frame, while walking, while
   still and on cuts, for every arm (a)–(m) of the brief.
3. **Does the reader still see?** Reading quality against exact ground truth
   (depth order, what moved, which way it moves), with every arm's view.
4. **When should the keyframe be taken?** Fixed interval versus triggered, the
   idle threshold, the keyframe's resolution.

**What changed in this run (run 4).** Runs 1–3 measured the cost side and
never finished the quality side: `results/quality2_low.json` held one row, and
§5.1 of the write-up was a placeholder. Run 4 found and fixed three defects in
that experiment (§9), rebuilt the exact-ground-truth corpus, and produced the
reading-quality numbers, the c3 trade-off on the hard world, the level-versus-
rate gate comparison, the autopilot-window experiment and the emitter/projector
measurement. The cost-side numbers are re-measured here, and one of them moved
by 2–6 % (the residual table, §9).

---

## 2. What was built

### 2.1 The kernel, unmodified

`vendor/Syzygy` is the crew's kernel at commit `5bc53ea`, used as the crew
wrote it. Receipt from this machine, re-run 2026-11-01 12:11:

```
$ sh vendor/Syzygy/tools/suite-total.sh
  info: golden fnv1a = 0x6dbdd1a8
  info: full-output golden fnv1a = 0x463de14b
=== TOTAL: 7 suites, 219 checks, 0 failures (run.sh exit 0) ===
```

`harness/syz_render.c` is a transport only: it feeds NV12 to `syz_fused()` and
writes the three alphabets out as text. It computes nothing.

### 2.2 The test beds

| corpus | what it is | why |
|---|---|---|
| **W — walking** | the docks walk from `syzygy-video` (`out/docks_web.mp4`, left pane = the original footage), 297 frames at 6 fps, re-rendered through the kernel at 4 cell grids | real camera motion, the brief's "same episodes" |
| **S — still** | one Infinigen sweep scene repeated (the camera has stopped): 8 identical frames | the idle case |
| **C — cuts** | the Infinigen sweep scenes butted together, one frame each | hard cuts |
| **M — motion with exact ground truth** | 3 scenes (arctic-s1, canyon-s1, hello_world) × 24 frames, moved by **depth-based reprojection**: every label exact by construction | the hard world with labels the brief asks for |

Each corpus is rendered at four cell grids — coarse 74×40, low 96×52, base
148×80 (the docks master grid), fine 208×112 (the docks "resolution slope"
grid) — plus the 192×104 grid c3b's matched-budget ladder needs, so the
resolution/rate trade can be priced.

**Reprojection, in one paragraph.** Infinigen's ground-truth pass writes a
per-pixel depth map and the camera matrices. Unprojecting the depth gives 3D
points; translating the camera and reprojecting gives a new view with exact
per-pixel flow, exact depth and exact object index (the object index is carried
by the splat, through the same z-buffer that carries the points — if the
segmentation is not splatted with the image, every marker after frame 0 lands on
the wrong object and the labels are silently wrong). The camera **swings ±1.2 m
over the 24 frames** — a head-turn — so the content moves one way for the
first 13 frames and the other way for the last 11 (the truth sequence is
`LLLLLLLLLLLLLRRRRRRRRRRRR`, the same shape in each scene), and the questions
("which way is it moving?") are not degenerate: a reader that always answers
"left" scores 13/24 = 0.542, which is *above* the blind floor, so the floor
alone cannot excuse a reader that gets the direction right. The scenes have
2–14 objects with enough pixels to name.

**The labels are balanced by construction**, so a constant-answer reader cannot
score 100 % and the blind control has something to discriminate against:

| scene | frames | depth answer true/false | motion answer 1/2 | camera left/right |
|---|---:|---|---|---|
| arctic-s1 | 24 | 12 / 12 | 12 / 12 | 13 / 11 |
| canyon-s1 | 24 | 12 / 12 | 12 / 12 | 13 / 11 |
| hello_world | 24 | 12 / 12 | 12 / 12 | 13 / 11 |

**Reprojection receipt.** The reprojected flow is checked against the parallax
the depth map predicts: for a camera translation `tx`, a surface at depth `Z`
moves `fx·tx/Z` pixels, and the measured displacement matches it to within 0.3 %
for the objects whose depth is in the map's reliable range (`fx` = 1500 px from
Infinigen's own intrinsics). The reader's per-object flow magnitude and the
scene's own depth map therefore agree on which object is nearer — the corpus is
self-consistent, and the quality experiment's ground truth does not depend on
the flow at all (it is read from the depth map; §4.4).

**Pipeline receipt.** Our re-render of the docks walk (from the web encode,
rescaled) reproduces the corpus `syzygy-video` shipped (`out/docks-text/`) at
**89.8 %** of cells on the glyph plane, **90.7 %** on Braille and **91.1 %** on
tone; 0 of 297 frames are byte-identical. The disagreement is where the kernel's
edge threshold is bistable, and it is expected: we re-derived the source from
an H.264 web encode with a different resampler, not from the original NV12.

### 2.3 The readers

| reader | model | endpoint | what it can cache |
|---|---|---|---|
| **d1-2B** (decision) | `d1-2B-Q8_0.gguf` (LFM3-D1) | `llama-server /v1/systemone` — typed questions, answers with probabilities | **nothing, in this build** (see §5.3) |
| **LFM2-1.2B** (text) | `LFM2-1.2B-Q8_0.gguf` | `/completion` | the slot's prompt cache (`cache_n`) — the mechanism |
| **Groq gpt-oss-20b** (cloud) | `openai/gpt-oss-20b` | chat completions | the provider's prompt cache — *not* itemised in the usage (see §5.4) |

The cloud reader is the instrument that can actually read the scene (§4.4); the
local decision reader turns out to be a good *probability* instrument and a poor
*reader* (§4.4.2), which is a finding in its own right.

### 2.4 Machine state

NVIDIA Thor, aarch64, 14 CPU cores, 122 GiB unified memory, driver 595.78;
Ubuntu 24.04.5, kernel 6.8.12-1021-tegra; llama.cpp at `2e0d86b`. During the
reads of this document: **73 GiB available**, load average **30.9 on 14 cores**
(the box is shared with other seats' renders), 68 GiB disk free, GPU pool
**1.1 GiB free of the allocation pool** — the GPU pool is contended, which is
why the local reader is slow here and why the cloud reader matters.

Every heavy step ran under a `thor-admit` lease (`~/lm-tools/thor-admit run
--tier live --peak <size> --label syzygy-keyframes.<step> -- <cmd>`), never a
bare `flock`, per `~/lm-wt/MEMORY-RULE.md`. The model servers were started with
`thor-admit serve`.

---

## 3. The mechanism, in plain words

A reader that can keep a prefix costs two different things per frame:

* **tokens sent** — what goes over the wire, and
* **tokens read** — what the model actually computes.

With a cached prefix, the keyframe is *sent* once and *read* once; every later
frame sends `keyframe + delta` and the model re-reads only the delta. So the
per-frame compute is proportional to **what changed**, and the frame rate
follows the change, not the resolution.

This works, and it is measurable:

```
LFM2-1.2B, llama.cpp, a 14,012-token prefix:
  cold read (cache_prompt=false)   1.712 s   prompt_n 14,012   cache_n 0
  the same prompt again            0.146 s   prompt_n     4   cache_n 14,008   -> 11.7x faster
  same prefix, new 514-token tail  0.205 s   prompt_n   514   cache_n 13,496
```

**That is the whole mechanism, and it is sound.** What follows is the part that
decides whether it is worth using.

---

## 4. The numbers

### 4.1 The residual: how many cells change per frame (docks walk, 148×80)

| plane | cells changed per frame | share of the grid |
|---|---:|---:|
| Braille | 5,252 | **44.4 %** |
| glyph (edges) | 7,522 | **63.5 %** |
| tone | 6,690 | **56.5 %** |
| all three | 19,464 | 164 % of the cells |

The library's stress test reported **48–54 %** of cells changing while walking
at 148×80. Our tone plane gives **56.5 %**, our glyph plane 63.5 % — the same
ballpark, measured on a re-derived copy of the same walk. **The critique is
confirmed: raw cell diffs under motion are barely cheaper than a full frame.**

### 4.2 The residual as the reader has to read it

The full frame at 148×80 is 11,840 cells on one plane (11,969 characters) and
35,520 cells on three (35,828 characters). A delta must also *address* the cells
it carries. Measured on the docks walk (297 frames, 296 transitions), per frame, all three
channels, re-measured in this run from the committed corpus:

| arm | changed cells / frame | characters / frame | vs the 1-plane frame |
|---|---:|---:|---:|
| **(a)** full frame, one plane | 11,840 | 11,969 | 1.00× |
| **(a)** full frame, three planes | 35,520 | 35,828 | 3.00× |
| **(c)** cell delta, per-cell protocol | 19,463 | 197,794 | **16.5×** |
| **(c)** cell delta, run-length encoded | 19,463 | 58,926 | **4.9×** |
| **(e)** channel delta (one plane) | 7,521 | 76,445 | 6.4× |
| **(j)** event channel | 19,463 | 334,035 | 27.9× |

On the exact-ground-truth motion corpus (0.35 m per frame) the same figures are
13.2× / 5.7× / 5.0× / 22.1×.

**A delta of the changed cells costs several times more than the frame it
replaces.** Two reasons, and both are fixable in principle:

1. *Too many cells change.* 63.5 % of the glyph plane changes on a moving
   camera. A delta that carries half the frame costs half the frame — and the
   third plane of the addressing overhead makes it worse.
2. *Addressing costs more than the cells.* `"g 12 34 X"` is ~9 characters per
   changed cell; the cell's own text is one. Run-length encoding (row, x0, x1,
   the glyphs) cuts the overhead 3.4× (197,794 → 58,926 characters) and *still*
   is 4.9× the full frame.

We measured this on the cloud reader too, with Groq's own tokenizer
(gpt-oss-20b, 8,491 prompt tokens for the full frame):

| arm | prompt tokens / call | cost / call | latency p50 |
|---|---:|---:|---:|
| **(a)** full frame | 8,491 | $0.00067 | 1.06 s |
| **(c)** cell delta | **36,405** | **$0.00276** | **8.43 s** |

**The delta costs 4.3× the full frame on a real reader.** On every one of the
19 delta frames we sent to the local reader, the delta did not fit its
32,768-token context at all (38 failed requests across the fresh and cached
modes).

### 4.3 Where the cost *does* move

The same measurement on an **idle** scene (the camera stopped, the same frame
repeated 12 times) — the case the mechanism is for. LFM2-1.2B on the Thor, the
glyph plane at 148×80 (10,112 tokens per frame):

| arm | tokens read / frame | latency p50 | frames/s |
|---|---:|---:|---:|
| **(a)** full frame, fresh (no cache) | 10,112 | 2.655 s | **0.42** |
| **(a)** full frame, keyframe held in the reader | **1,731** | **0.319 s** | **2.29** |
| **(c)** keyframe + delta, fresh | 866 | 0.567 s | 2.34 |
| **(c)** keyframe + delta, cached | 1,317 | 0.837 s | 1.73 |
| **(e)** channel delta, cached | 1,317 | 0.296 s | 3.09 |

**While the world is still, the reader pays 1,731 tokens per frame instead of
10,112 and its frame rate goes from 0.42 to 2.29 fps — 5.5× — at the same
resolution.** The delta arm, whose payload is empty because nothing changed,
costs 866 tokens per frame: the frame rate is set by the model, not by the
picture. **This is where the cost moves into idle time, and it is the only
place we found it.**

### 4.4 The reader: quality against exact ground truth

**This is the centrepiece, and it is new in this run.**

**The instrument.** Three questions per frame, all of them with exact ground
truth from the reprojected scene:

* **depth order** — "is marker 1 nearer to the camera than marker 2?"
  (true/false, and the probability for the local reader);
* **camera direction** — "which way is the scene content moving?" (left/right);
* **which moved** — "which marked region is moving the most?" (1 or 2).

The two marked objects are named by a marker block (their cell bounding box and
centre), and the marker order is swapped on alternate frames so that neither
question's answer is constant.

**The conditions** (what the reader is shown):

| condition | what the reader sees |
|---|---|
| `a_full` | the text frame |
| `h_motion` | the text frame **+ the motion channel** (per-cell flow arrows and magnitude tiers) |
| `i_window` | the previous frame **and** this frame (a stateful reader) |
| `j_events` | the text frame **+ the cell event channel** (arm (j)) |
| `k_rhythm` | the text frame **+ the per-region temporal spectrum** (arm (k)) |
| `c_keyframe` | the cached keyframe **+ the cell delta** (arm (c)) |
| `l_parallax` | the text frame **+ the head-bob view** (arm (l)), taken only when the reader's confidence falls |
| `blind` | the wrong frame, with the right markers (the guessing floor) |
| `oracle` | the truth in words (the instruction-following ceiling) |

**The controls are what make the numbers mean.** The `blind` control is the
same questions about a *different* frame of the same scene, with the same
markers: it is the guessing floor. The `oracle` control is the truth in words:
it is the ceiling and it proves the reader can follow the instruction format.
On the cloud reader the oracle scores **1.000 on all three questions**.

#### 4.4.1 The cloud reader (Groq gpt-oss-20b) — 72 frames, 3 scenes

`results/groq_quality.json`. Grid 96×52, reasoning effort low, 535 s for 72
frames × 6 conditions = 432 calls.

| condition | depth order | camera direction | which moved | prompt tokens | cost/call | latency p50 |
|---|---:|---:|---:|---:|---:|---:|
| `a_full` (the text frame alone) | 0.486 | **0.431** | 0.611 | 3,320 | $0.00029 | 1.04 s |
| `h_motion` (**+ the motion channel**) | **0.625** | **0.889** | 0.500 | 4,713 | $0.00039 | 1.15 s |
| `i_window` (two frames) | 0.493 | 0.522 | 0.420 | 6,400 | $0.00052 | 1.21 s |
| `c_keyframe` (keyframe + delta) | 0.500 | 0.403 | 0.486 | 9,157 | $0.00072 | 1.36 s |
| `blind` (the guessing floor) | 0.500 | 0.486 | 0.514 | 3,320 | $0.00029 | 0.90 s |
| `oracle` (the ceiling) | 1.000 | 1.000 | 1.000 | 204 | $0.00004 | 0.57 s |

Paired against the blind control (McNemar's exact test, per frame):

| condition | question | Δ vs blind | p |
|---|---|---:|---:|
| `a_full` | camera direction | −5.56 pts | 0.64 |
| **`h_motion`** | **camera direction** | **+40.28 pts** | **< 0.00001** (b = 34, c = 5) |
| `h_motion` | depth order | +12.50 pts | 0.108 |
| `h_motion` | which moved | −1.39 pts | 1.00 |
| `i_window` | camera direction | +2.90 pts | 0.86 |
| `c_keyframe` | camera direction | −8.33 pts | 0.34 |
| `oracle` | all three | +48.6 to +51.4 pts | < 0.00001 |

**The picture alone does not tell you which way the world is moving — it scores
*below* the guessing floor (0.431 against 0.486).** That is not a defect of the
reader; it is what a single frame *is*. A static image of a scene has no
motion in it, and the corpus's camera reverses in the middle of the swing, so
the information simply is not in the picture. (A reader that always answered
"left" would score 13/24 = 0.542 on this corpus, which is *above* the blind
floor — so the floor is not what a reader gets for free here.)

**Adding the motion channel lifts the same reader from 0.431 to 0.889 on the
same frames, +40.3 points, p < 0.00001.** The channel costs 42 % more prompt
tokens (3,320 → 4,713) and 0.11 s more latency. Per scene:

| scene | `a_full` | `h_motion` | `blind` | the channel's own information content* |
|---|---:|---:|---:|---:|
| arctic-s1 | 11/24 | **22/24** | 13/24 | 14/24 |
| canyon-s1 | 9/24 | **20/24** | 10/24 | 24/24 |
| hello_world | 11/24 | **22/24** | 12/24 | 24/24 |
| **all 72 frames** | 31/72 (0.431) | **64/72 (0.889)** | 35/72 (0.486) | 62/72 (0.861) |

\* the information content of the channel itself: the fraction of frames whose
frame-wide **median** optical-flow direction equals the truth. The reader
scores 0.889 against that 0.861 — **it is reading the channel about as well as
a one-line summary of the channel could**, and on arctic-s1, whose flow has a
large vertical component, it does *better* than the median summary (22/24
against 14/24) because the arrows can be read axis by axis.

Three things this does *not* say, stated plainly:

* **The motion channel is not free information from nowhere.** It is computed
  from the exact optical flow the brief specifies ("from the known camera and
  object motion, compute per-cell optical flow in the reader's own frame").
  What is measured here is *whether a text reader can use such a channel*, not
  whether flow can be estimated from text. Estimating it is a separate problem.
* **The two-frame window did not help this reader** (0.522, at the floor). The
  reader was given two frames and did not compare them; the motion channel
  states the comparison for it. That is a finding about this reader at this
  grid, not a general one.
* **The keyframe + delta did not help either** (0.403, below the floor), and it
  costs 2.8× the tokens of the plain frame. The delta is a list of changed
  cells; the reader does not reassemble the motion from it.

**This is the thesis of the brief, measured.** Casey's observation — "it works
best when I'm moving... that's what it's for: the delta of the relative
perspectives" — holds for a model reader too, and the channel that carries it
is cheap: one character per cell.

#### 4.4.2 The local decision reader (d1-2B) — it answers with the majority class

`results/quality2_low.json`, the complete run: 72 frames, 3 scenes, grid
96×52, llama.cpp `/v1/systemone`, the same states and the same ground truth
as the cloud reader.

| condition | depth order | camera direction | which moved | n |
|---|---:|---:|---:|---:|
| `a_full` | 0.511 | 0.542 | 0.514 | 72 |
| `h_motion` | 0.497 | 0.583 | 0.486 | 72 |
| `i_window` | 0.505 | 0.522 | 0.536 | 69 |
| `j_events` | 0.498 | 0.522 | 0.551 | 69 |
| `k_rhythm` | 0.511 | 0.522 | 0.493 | 69 |
| `c_keyframe` | 0.488 | 0.528 | 0.458 | 72 |
| `l_parallax` | 0.489 | 0.472 | 0.444 | 36 of 72 (36 skipped as confident) |
| `blind` | 0.508 | 0.542 | 0.514 | 72 |
| `oracle` | 0.997 | 1.000 | 1.000 | 72 |

**d1-2B does not read this scene at all: it answers with the majority class.**
The answer distributions say it exactly:

| condition | its camera-direction answers | its depth answers | its which-moved answers |
|---|---|---|---|
| `a_full` | **"left" on 72 of 72** | "true" on 66 of 72 | "1" on 65 of 72 |
| `blind` | **"left" on 72 of 72** | "true" on 68 of 72 | "1" on 65 of 72 |
| `h_motion` | "left" on 69, "right" on 3 | "true" on 63 | "1" on 65 |
| `c_keyframe` | "left" on 71, "right" on 1 | "true" on 60 | "1" on 63 |
| `oracle` | "left" 39 / "right" 33 (the truth) | 36 / 36 (the truth) | 36 / 36 (the truth) |

The truth is 39 left / 33 right, 36 true / 36 false, 36 "1" / 36 "2". So
d1's 0.542 on the camera direction is *precisely* the "always left" score, and
its 0.511 and 0.514 are the majority-class scores of the other two questions.
**The true frame and the wrong frame give it the same answers on every one of
the 72 frames**, which is the strongest possible statement that the picture is
not reaching the model.

The instruction-following control is perfect (0.997 / 1.000 / 1.000, and its
answer distribution *tracks the truth*), so the endpoint and the parsing are
fine: the *model* is too weak to use a text grid at this size. Two
consequences, both used in the rest of this document:

* the local decision reader is a good **probability** instrument and a poor
  **reader**, so it is kept for the gates (§4.6) and dropped for the quality
  claims;
* the brief's own instrument choice (d1 first) would have produced a null
  result that says nothing about the arms.

#### 4.4.3 The same question at the coarse grid — and this is the brief's own idea

`results/groq_quality_coarse.json`. The whole experiment again at **74×40**, a
third of the cells of the low grid (2,960 against 4,992), 72 frames, 6
conditions, 389 s.

| condition | depth order | camera direction | which moved | prompt tokens | latency p50 |
|---|---:|---:|---:|---:|---:|
| `a_full` | 0.521 | 0.535 | 0.592 | 2,180 | 0.80 s |
| `h_motion` | 0.592 | **0.873** | 0.423 | 3,044 | 0.84 s |
| `i_window` | 0.609 | 0.493 | 0.551 | 4,109 | 0.94 s |
| `c_keyframe` | 0.554 | 0.477 | 0.508 | 5,669 | 0.94 s |
| `blind` | 0.597 | 0.458 | 0.569 | 2,179 | 0.78 s |
| `oracle` | 1.000 | 1.000 | 1.000 | 204 | 0.52 s |

| condition | question | Δ vs blind | p |
|---|---|---:|---:|
| `a_full` | camera direction | +8.45 pts | 0.418 |
| **`h_motion`** | **camera direction** | **+42.25 pts** | **< 0.00001** |
| `i_window` | camera direction | +2.90 pts | 0.855 |
| `c_keyframe` | camera direction | 0.00 pts | 1.00 |

**This is the brief's own idea, measured.** Casey's premise is that the
resolution can be scaled inversely to the frame rate — "I can scale to a
good-quality picture, but it costs frame rate somewhere". The measurement says
something sharper:

* dropping from 96×52 to 74×40 **cuts the frame's prompt tokens by 34 %**
  (3,320 → 2,180);
* the **motion channel survives the drop intact**: 0.873 at the coarse grid
  against 0.889 at the low grid, and still **+41.7 points over blind, p <
  0.00001**, for 40 % more tokens (2,180 → 3,044);
* the picture alone does *not* survive it in any useful way — at the coarse
  grid `a_full` is 0.535 against a blind floor of 0.458, a difference of 8.4
  points at p = 0.42, which is noise.

**The information is in the channel, not in the resolution.** That is why the
channel is the thing worth building: it costs one character per cell, it does
not shrink when the picture does, and it is the only arm that carried anything.

The depth column at the coarse grid is uninformative: `h_motion` 0.592 against
a blind floor of 0.597. The parallax cue needs the resolution to read the
magnitude tiers, so the depth benefit measured at the low grid (+12.5 points,
p = 0.108) does not survive the drop. Stated plainly: **at 74×40 the reader
knows which way the world is moving and nothing else.**

### 4.5 The c3 trade-off, re-run where the bottleneck binds

`results/c3b.json`, from `harness/c3b.py`, which reuses chiaroscuro-embedding's
c3 readers, feature dimension, blocked 5-fold CV and **pre-registered gate**
unchanged, on the hard world.

c3's cells are framerate × density, and the matched pairs are exactly
budget-matched:

| pair | high-fps cell (4× the framerate, ¼ the area) | low-fps cell | budget |
|---|---|---|---|
| 1 | 3.0 fps × 74 | 0.75 fps × 148 | 8,880 chars/s |
| 2 | 6.0 fps × 74 | 1.5 fps × 148 | 17,760 chars/s |
| 3 | 3.0 fps × 96 | 0.75 fps × 192 | 14,976 chars/s |
| 4 | 6.0 fps × 96 | 1.5 fps × 192 | 29,952 chars/s |

**Correction, made in writing.** c3's own gate reads its matched pair in the
order *(low-fps/high-resolution, high-fps/low-resolution)* but labels the first
tuple `high_fps_cell`, so the sign of its delta is inverted relative to its own
stated rule ("in each matched pair the high-fps cell has 4× the framerate and
¼ the glyph area"). c3's own verdict was a TIE, so the inconsistency never bit
there; here it decides the verdict, so `harness/c3b.py` now names the cells
`res_cell` and `fps_cell` and computes `delta = acc(fps_cell) − acc(res_cell)`,
which is the rule c3 wrote down. c3's thresholds (4 pairs, 5 points, 2 to win)
are unchanged. §9 has the old text.

**The numbers (cam_dir, the task the reader can do):**

| cell | samples | chars/s | base | stacked | motion | events | rhythm | keyframe | autokey |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0.75 × 74 | 9 | 2,220 | 0.333 | 0.556 | 0.000 | 0.333 | 0.333 | 0.000 | 0.000 |
| 0.75 × 96 | 9 | 3,744 | 0.111 | 0.444 | 0.000 | 0.222 | 0.111 | 0.111 | 0.111 |
| 0.75 × 148 | 9 | 8,880 | 0.333 | 0.667 | 0.000 | 0.333 | 0.333 | 0.111 | 0.111 |
| 0.75 × 192 | 9 | 14,976 | 0.333 | 0.556 | 0.000 | 0.333 | 0.333 | 0.222 | 0.222 |
| 1.5 × 74 | 18 | 4,440 | 0.444 | 0.500 | 0.389 | 0.500 | 0.444 | 0.333 | 0.333 |
| 1.5 × 96 | 18 | 7,488 | 0.333 | 0.500 | 0.333 | 0.389 | 0.333 | 0.167 | 0.167 |
| 1.5 × 148 | 18 | 17,760 | 0.500 | 0.500 | 0.389 | 0.500 | 0.500 | 0.278 | 0.278 |
| 1.5 × 192 | 18 | 29,952 | 0.556 | 0.500 | 0.444 | 0.556 | 0.500 | 0.333 | 0.333 |
| 3.0 × 74 | 36 | 8,880 | 0.944 | 0.944 | 0.833 | 0.972 | 0.861 | 0.694 | 0.694 |
| 3.0 × 96 | 36 | 14,976 | 0.917 | 0.944 | 0.917 | 0.944 | 0.889 | 0.611 | 0.611 |
| 3.0 × 148 | 36 | 35,520 | 0.917 | 0.944 | 0.917 | 0.944 | 0.889 | 0.806 | 0.806 |
| 3.0 × 192 | 36 | 59,904 | 0.972 | 0.944 | 0.833 | 0.944 | 0.944 | 0.806 | 0.806 |
| 6.0 × 74 | 72 | 17,760 | 0.986 | 0.972 | 0.833 | 0.958 | 0.889 | 0.903 | 0.903 |
| 6.0 × 96 | 72 | 29,952 | 0.972 | 0.931 | 1.000 | 0.986 | 0.861 | 0.847 | 0.847 |
| 6.0 × 148 | 72 | 71,040 | 0.972 | 0.944 | 0.889 | 0.972 | 0.931 | 0.889 | 0.889 |
| 6.0 × 192 | 72 | 119,808 | 0.972 | 0.944 | 0.861 | 0.958 | 0.986 | 0.931 | 0.931 |

**The gate's verdict: FRAMERATE-WINS**, on all four matched pairs, by 42 to 61
accuracy points. (On the depth-order and which-moved tasks the reader is at
chance everywhere — 0.39 to 0.54 — so those two tasks are TIE by construction
and carry no information.)

**But the gate is measuring the reader's sample budget, and that has to be
said.** The high-fps cell in each pair also has **4× the number of training
samples** (36 against 9, 72 against 18), because c3's design samples the same
master timeline at different rates. Reading the table two ways at once shows
what is really going on:

* **At a fixed framerate (6 fps, 72 samples each), resolution buys nothing:**
  0.986 (74 cols), 0.972 (96), 0.972 (148), 0.972 (192) — a 1.4-point spread
  across a 6.8× range of cell count.
* **At a fixed resolution (96 cols), the sample count is everything:**
  9 samples → 0.111, 18 → 0.333, 36 → 0.917, 72 → 0.972.

So the honest reading of c3 on the hard world is: **what the trade-off measures
is the number of observations the reader gets, not the resolution of each
one.** The pre-registered gate says FRAMERATE-WINS because that is what its
rule computes; the mechanism behind it is the sample count.

**What this does to the brief's premise.** If resolution adds no measurable
reading accuracy at a fixed sample count, then the high-resolution keyframe is
close to free in *information* terms — you can pay for it in idle time without
losing anything. That is a weaker claim than "the keyframe makes the reader see
more", and it is the one the data supports.

**The arms, at the same budget.** The `keyframe` and `autokey` arms are *worse*
than the plain frame at every cell (0.847 against 0.972 at 6 fps × 96), and
they cost more characters to say it: the keyframe+delta view is 76,180
chars/s against the plain frame's 29,952. The `motion` arm reaches 1.000 at
6 fps × 96 — the only cell in the table where any arm is perfect.

### 4.6 The gates: level against rate (the TIME-FIRST question)

**On true scene changes (the cuts corpus).** `results/gates.json`. Same
signal, same threshold, level gate against rate gate:

| threshold | level gate | rate gate |
|---|---|---|
| 0.054 | recall 0.50, latency −3.0, **14 false alarms (19.4 %)** | recall 0.50, latency −1.0, **5 false alarms (6.9 %)** |
| 0.112 | recall 0.50, latency −1.0, **2 false alarms (2.8 %)** | recall 0.50, latency +1.0, **0 false alarms (0 %)** |
| 5,687 cells | recall 0.50, latency +1.0, **14 false alarms (19.4 %)** | recall 0.50, latency +1.0, **0 false alarms (0 %)** |

**At matched recall, the rate gate costs a quarter to nothing of the level
gate's false alarms.** A level gate on the edge histogram fires on ordinary
motion as well as on cuts; a rate gate fires on the *change* of the signal, so
a walk that keeps looking different does not trigger it.

**On the reader's own confidence.** `results/gates_conf.json`
(`harness/gates_conf.py`). The ground truth for drift is the reader's loss of
the scene — a frame whose depth answer is wrong immediately after a frame whose
answer was right, inside a scene, so a scene boundary is not counted as a loss.
On the local decision reader's confidence series (the complete 72-frame run;
31 loss events, the reader's mean confidence 0.257):

| τ | level gate: fires / recall | rate gate: fires / recall | median lead |
|---:|---|---|---:|
| 0.05 | 0 / – | **25 / 0.936** | 1.0 frame |
| 0.10 | 1 / 0.032 | 16 / 0.742 | 1.0 frame |
| 0.15 | 3 / 0.097 | 8 / 0.452 | 1.5 frames |
| 0.20 | 15 / 0.677 | 1 / 0.065 | 1.0 frame |
| 0.25 | 36 / 0.936 | 0 / – | — |
| 0.30 | 52 / 1.000 | 0 / – | 0 |

**The two gates are not two settings of one dial.** At a matched recall of
**0.936** the rate gate spends **25 fires** and the level gate spends **36** —
the rate gate is 1.4× cheaper in triggers for the same catch rate — and it
reaches that recall at a threshold (τ = 0.05) where the level gate fires *not
at all*, because the reader's confidence never drops that low. Above τ = 0.20
the order reverses: the level gate fires on most frames while the rate gate
stops firing entirely, which is what a rate gate is supposed to do when
nothing is changing.

(The false-alarm rate is 0 at every threshold on this corpus, because the
reader loses the scene on 31 of the 71 frame transitions and almost any fire
lands next to one. The discriminating number here is the fire count at
matched recall, not the false-alarm rate; on the cuts corpus in the table
above, where the events are sparse, the false-alarm rate is what separates
the two gates.)

### 4.7 The autopilot window

`results/autopilot.json`, `harness/autopilot.py`. Casey's band: take the
keyframe when the reader is confident **and** its confidence is steady.

**First, the trigger's input has to be real.** The cloud API does not expose
logprobs through `gq.py`, so the reader is asked for its own confidence on a
0–100 scale, and that proxy is validated against the ground truth before it is
used:

| | mean stated confidence |
|---|---:|
| when the answer was **right** | 0.619 |
| when the answer was **wrong** | 0.551 |
| separation | **+0.068** (n = 72, 3 scenes) |

The proxy carries information — a real reader is more confident when it is
right — but only a little, and it is stated here so the trigger's weakness is
on the table rather than hidden in the policy.

*(the policy comparison follows)*

**Where the two policies put their keyframes.** The autopilot policy takes
them where the reader says it is confident and steady; the fixed policy takes
the same *number* of keyframes at even intervals.

| scene | autopilot keyframes | fixed keyframes |
|---|---|---|
| arctic-s1 | 1, 6, 23 | 0, 8, 16 |
| canyon-s1 | 4, 21 | 0, 12 |
| hello_world | 4, 9, 15, 20 | 0, 6, 12, 18 |

**What the reading accuracy says — and why the comparison cannot be
conclusive.** Each policy's keyframes are then read as arm (c): the cached
keyframe plus the cell delta.

| scene | autopilot: all / near the keyframes | fixed: all / near the keyframes | chars/frame (auto vs fixed) |
|---|---|---|---|
| arctic-s1 | 0.542 / **0.714** (n=14) | 0.417 / 0.389 (n=18) | 10,867 / 11,302 |
| canyon-s1 | 0.458 / 0.462 (n=13) | 0.542 / 0.455 (n=11) | 13,284 / 13,472 |
| hello_world | 0.417 / 0.391 (n=23) | 0.583 / 0.545 (n=22) | 14,577 / 14,845 |
| **mean** | 0.472 / **0.522** | 0.514 / 0.463 | 12,910 / 13,207 |

**There is no reliable advantage, and the reason is structural.** Near the
keyframes the autopilot policy is **+5.9 points** ahead on the mean over the
three scenes, but that number is one scene: **+32.5** on arctic-s1, +0.7 on
canyon-s1 and **−15.4** on hello_world. Over all frames the autopilot policy is
**4.2 points worse** (0.472 against 0.514).

The comparison cannot be made conclusive with this reader, and the reason is
§4.4.1: **the arm it compares is at the guessing floor.** The keyframe+delta
view scores 0.403 against the blind control's 0.486 on the camera-direction
question, so *where* the keyframes land cannot show up in the reading accuracy
— there is nothing there to show. The two policies differ by 2 % in the
characters per frame (12,910 against 13,207, because a later keyframe means a
smaller delta), and that is the only difference this experiment can price.

**What the experiment does establish:** the trigger's input is real but weak
(+0.068 separation), and the autopilot policy behaves the way Casey's band
predicts — it never takes frame 0, it takes its keyframes in the middle of the
sequence where the reader's confidence is steady, and it is marginally cheaper
because its deltas are smaller. Whether that is *better* is a question for an
arm the reader can actually use.

### 4.8 The emitter/projector split (arm (g))

`results/emitter.json`, `harness/emitter.py`. The world side emits only object
poses, velocities and events (with interest management: only the objects that
can affect this viewer); the reader projects them into its own perspective and
runs the kernel itself.

| quantity | value |
|---|---:|
| pose bytes per frame (mean over 72 frames) | **228** |
| text frame bytes per frame | 35,828 |
| cell-delta bytes per frame | 49,482 |
| **pose vs text** | **157× smaller** |
| objects sent per frame / objects in the scene | 4.67 / 7.67 |
| cell IoU of the reader's local projection against the true object mask | **0.512** |
| **cell agreement of the text frames the reader renders for itself** | **0.120** |
| projection time | 1.17 ms/frame |
| kernel time, run locally | 5.02 ms/frame |

**The wire cost of arm (g) is trivial and the fidelity is not.** 157× fewer
bytes on the wire, a local kernel run of 5 ms, and a picture the reader builds
for itself that agrees with the true picture on **12 % of its cells**. The
number that decides the arm is the last one, not the first: a pose stream that
is 157× smaller than the picture is worthless if the picture it produces is
wrong. The projection is right about *where* the objects are (cell IoU 0.51)
and wrong about *what they look like* (12 % cell agreement), which is what one
would expect from a projection that knows geometry but not shading.

### 4.9 The knower field (arm (m))

`harness/knower.py` (numpy) and `harness/knower_torch.py` (the GPU port).
Quilt-jepa's per-cell JEPA (4-dim latent, 4×4 context encoder, 4×4 predictor,
EMA target τ = 0.999) and its Perona–Malik mesh, run at our grid sizes.

**The torch port agrees with the numpy port** on the same frames:
max |Δ surprise| **1.6 × 10⁻⁶**, max |Δ mesh| **1.0 × 10⁻⁶** — the port is
faithful, and it runs the 148×80 grid in **34.6 ms/frame** on the Thor's GPU
(`results/knower_torch.json`).

**The mesh receipts (law (P5)):** total energy drift **1.9 × 10⁻³** relative
over the run, variance non-increasing on **23 of 23** steps. (quilt-jepa
measured 1.2 × 10⁻⁸ on its 16×16 world; ours is a bigger grid and a rougher
field, and the drift is not zero here.)

**The learning claim (P1) still fails, as it should:** loss 0.01133 (first 10
steps) → 0.01093 (last 10), a ratio of **0.965** — better than quilt-jepa's
0.948 but still nearly flat. A model that barely learns cannot be surprised
much.

**The three laws, on our hard world:**

*Law (a) — surprise needs a hard world.* The same intruder (a real patch of
another Infinigen scene, i.e. an object entering, not noise) injected into a
**static** scene and into the **walking** scene:

| world | mean-surprise contrast | max-cell contrast | detected? |
|---|---:|---:|---|
| static (easy) | 0.997 | 1.000 | **no** |
| walking (hard) | 1.036 | **1.507** | **yes**, 4 frames later |

**Law (a) holds.**

*Law (b) — anomaly detection needs a concentration statistic, not a mean.* On
the hard world, at the same threshold: the **mean** gate did not fire (contrast
1.036, 3σ threshold not crossed), the **max-cell** gate fired (contrast 1.507,
4-frame latency), the **region-energy** gate did not fire (1.273). **Only the
concentration statistic saw the event.**

*Law (c) — fault injection must be impact-sensitive.* Our injection is a real
object, and it is detected — so the probe is impact-sensitive by construction.

**What the knower is good for.** On the walking corpus the max-cell gate fires
**5.2 frames before** the change it predicts on average (the mean gate: 9.6
frames — later and noisier), with **3 fires and 0 false alarms** over 23
frames. That makes it a plausible keyframe trigger: *the knower's low-surprise
state marks the autopilot window* — the moment the reader is confident and
steady and can safely spend the budget on a high-resolution glance.

### 4.10 The keyframe policy sweep

`results/sweep.json`, `results/sweep_still.json`. The three axes the brief
names: fixed interval versus triggered, the idle threshold, the keyframe's
resolution. Measured on the docks walk (120 frames, 148×80), with the delta
costing 7,409 cells / 50,004 tokens per frame and a keyframe costing 2,096
(coarse), 3,192 (low), 6,523 (base) or 11,261 (fine) tokens.

**On a moving camera:**

| policy | keyframes | cells / frame | tokens / frame |
|---|---:|---:|---:|
| full frame every frame (no delta) | — | 35,520 | **6,523** |
| fixed every 5 | 24 | 13,037 | 41,308 |
| fixed every 10 | 12 | 10,225 | 45,656 |
| fixed every 30 | 4 | 8,342 | 48,555 |
| fixed every 60 | 2 | 7,874 | 49,279 |
| triggered (idle / cut), any idle threshold | 5 | 8,536 | 48,192 |
| triggered, cut ×2 (relative cut test) | 9 | 9,451 | 46,743 |
| **budget-triggered (adaptive)** | 62 | 21,921 | **27,539** |
| triggered, keyframe at the low grid | 5 | 8,536 | 48,054 |
| triggered, keyframe at the fine grid | 5 | 8,536 | 48,390 |

**On an idle scene (the same frame, 60 frames):**

| policy | keyframes | cells / frame | tokens / frame |
|---|---:|---:|---:|
| full frame every frame | — | 35,520 | 6,523 |
| fixed every 30 | 2 | 1,184 | 230 |
| **idle refresh at the base grid every 30** | 2 | 1,184 | **230** |
| **idle refresh at the fine grid every 30** | 2 | 1,184 | **388** |
| idle refresh at the fine grid every 60 | 1 | 592 | 200 |
| triggered without a cooldown | 60 | 35,520 | 6,523 |

Four things the sweep says:

1. **On a moving camera, every delta policy is worse than reading the frame.**
   The best of them (budget-triggered, 27,539 tokens/frame) is still 4.2× the
   full frame's 6,523. The reason is one number: the delta costs 50,004 tokens
   and the frame costs 6,523.
2. **A triggered policy without a budget is the worst of all** (48,192
   tokens/frame): it keyframes five times in 120 frames and pays a delta on
   every other frame. The cut and idle triggers are about *when to refresh*,
   not about saving tokens.
3. **The cut trigger must be relative.** An absolute test (the brief's
   "FFT-row or edge-histogram distance") fires on **109 of 120 frames** of a
   walk — it cannot tell a cut from motion. Tested against the median of the
   last 10 frames (×3), it fires **4 times**, and the budget trigger catches
   the rest.
4. **The idle trigger needs a cooldown.** "Few cells changed" is true on
   *every* frame of a still scene, so an uncapped idle trigger keyframes every
   frame (60 keyframes, 6,523 tokens/frame — the worst possible). Capped at
   one refresh per 30 frames, the same scene costs **230 tokens/frame at the
   base grid and 388 at the fine grid** — and the fine grid is 1.7× the
   resolution of the base grid while still costing **17× less than reading the
   base-resolution frame every frame**.

Point 4 is the brief's hypothesis, stated as a number: **in idle time the
reader can afford a keyframe at a higher resolution and still pay far less per
frame than reading the picture every time.**

---

## 5. The findings

### 5.1 The mechanism is sound and cheap

A reader that holds the keyframe in its cached prefix reads only the delta:
**11.7× faster** on the Thor (1.712 s → 0.146 s on a 14,012-token prefix), and
~0 tokens per frame when nothing changed. That is the mechanism the brief
proposes, and it works exactly as described.

### 5.2 Under motion the delta is not the cheaper thing

On a real walk at 148×80, **63.5 % of the glyph cells change per frame**; the
delta costs **4.3× the full frame** on Groq's tokenizer and did not fit a
32k context on any of the 19 frames we tried. The library's critique ("raw
cell diffs fail under motion") is confirmed with a reader's numbers, not just a
cell count.

### 5.3 So the cost moves into idle time only when the world is still

The idle-time trigger is the one that matters; the cut and drift triggers are
about *when to refresh*, not about saving tokens. On an idle scene the same
code gives **5.5× the frame rate** of reading the frame at the same
resolution, and the fine-grid keyframe costs 388 tokens/frame against the
base-grid frame's 6,523 read every frame.

### 5.4 The cheapest delta under motion is (e), the channel delta

7,522 cells and 51,299 tokens per frame, against a three-plane frame of 35,828
characters. And **motion compensation with a single global shift makes things
worse, not better**: arm (d) leaves 21,909 changed cells against the plain
delta's 19,464, because one shift cannot describe a parallax field. The
motion channel (h) has to be *per-cell* to work.

### 5.5 The reader is not the bottleneck at the resolution we tested

The kernel renders 297 frames of four grids in 6.6 s; the reader spends 1.6 s on
a frame. The whole question is about *how many tokens the reader must read*,
and that is a codec question first.

### 5.6 The reading experiment: the picture does not carry the motion; a cheap channel does

On the cloud reader, over 72 frames of three scenes with exact ground truth:

* the text frame alone scores **0.431** on "which way is the scene moving",
  *below* the guessing floor of 0.486 — a single frame cannot contain the
  motion, and the corpus's camera reverses in the middle of the swing;
* the frame **plus the motion channel** scores **0.889**, **+40.3 points over
  blind, p < 0.00001**, for 42 % more prompt tokens — and 0.889 against the
  channel's own information content of 0.861, so the reader is reading the
  channel, not inferring past it;
* the two-frame window (0.522) and the keyframe + delta (0.403) are both at the
  floor: the reader does not reassemble the motion from either.

This is Casey's observation — that the rendering works best when you are
moving, and that what it is for is the delta of the relative perspectives —
measured on a model. The channel that carries it is one character per cell.

### 5.7 The local decision reader answers with the majority class, not with the scene

Over the complete 72-frame run, d1-2B answers **"left" on 72 of 72 frames** for
the camera direction — with the true frame *and* with the wrong one — and
"true" on 66 of 72 for the depth question and "1" on 65 of 72 for which-moved.
Its 0.542 / 0.511 / 0.514 are exactly the majority-class scores. Its
instruction-following control is perfect and its answer distribution tracks
the truth, so the endpoint works; the model does not use the text grid. The
brief's first-named instrument would have produced a null result that says
nothing about the arms; the cloud reader is the instrument that separates them.

### 5.8 Resolution buys no measurable reading accuracy at a fixed sample count

In c3's own matched-budget design on the hard world, the gate says
**FRAMERATE-WINS** on all four pairs (42–61 points). Reading the table at
fixed framerate shows why: at 6 fps the accuracy is 0.986 / 0.972 / 0.972 /
0.972 across a 6.8× range of cell count, while at a fixed resolution the
sample count moves the accuracy from 0.111 (9 samples) to 0.972 (72 samples).
**What the trade-off measures is the number of observations, not the
resolution of each one.**

### 5.9 At matched recall, the rate gate beats the level gate

On true cuts, the rate gate holds the recall and cuts the false alarms from
19.4 % to 6.9 % to 0 %. On the reader's own confidence over the complete run,
the rate gate catches **93.6 %** of the reader's losses in **25 fires**, where
the level gate needs **36 fires** for the same catch rate — and it reaches that
recall at a threshold where the level gate does not fire at all. The level gate
is a state; the rate gate is a change of state, and only one of them is a
*trigger*.

### 5.10 The emitter/projector split: the wire is cheap, the picture is not

228 bytes per frame against the text frame's 35,828 (157×), a 5 ms local kernel
run — and a picture the reader builds for itself that agrees with the true
picture on **12 % of its cells**. The pose stream knows where the objects are
(IoU 0.51) and not what they look like.

### 5.11 The autopilot window: the trigger is real, the comparison is not conclusive

The reader's self-reported confidence carries information (+0.068 separation
between right and wrong answers), so Casey's band — confident **and** steady —
is a trigger that fires on real signal. The autopilot policy behaves the way
the band predicts: it never takes frame 0, it takes its keyframes where the
confidence is steady, and it is 2 % cheaper in characters per frame than the
fixed-interval policy with the same number of keyframes, because a later
keyframe means a smaller delta.

**But it does not show a reading advantage, and it cannot with this reader.**
Near the keyframes the autopilot policy is +5.9 points ahead on the mean over
three scenes — and that number is one scene (+32.5 / +0.7 / −15.4), while over
all frames the autopilot policy is 4.2 points *worse*. The reason is
structural: the arm the policies differ in, the keyframe + delta, is at the
guessing floor for this reader (0.403 against 0.486), so where the keyframes
land cannot show up in the reading accuracy — there is nothing there to show.

### 5.12 The knower field is a trigger, not a channel

Its max-cell surprise fires **5.2 frames before** the change it predicts, with
no false alarms, on the walking corpus — it can mark the autopilot window where
a high-resolution glance is safe. Its mean-surprise gate is blind, as
quilt-jepa's law (b) says it must be.

**What to build next, in order of expected value:**

1. **A cheap delta encoding** (bitmap + run-length, or a per-row change list).
   Without it, no delta arm can win under motion; with it, (c)/(f) may become
   competitive at coarse grids.
2. **A motion channel in the kernel's own alphabet.** It is the only arm that
   moved the reader (0.431 → 0.889) and it costs one character per cell. The
   kernel already emits three planes; a fourth (flow direction + magnitude,
   quantised to the existing glyph set) is a small change and it is the one
   thing here that carried information.
3. **A state snapshot for d1** (the brief's "Liquid state snapshot"): the
   decision reader is the right probability instrument and it cannot hold
   state yet.
4. **The idle-time keyframe trigger as the default**, with the knower's
   max-cell surprise as its level gate and the regional rate as its rate gate.
5. **The emitter/projector split (g) for the bytes**, with the fidelity work
   it needs — 12 % cell agreement is the thing to fix, not the 157×.

---

## 6. The verdict, as a plain finding

1. **The mechanism is real.** A reader that holds the keyframe in its cached
   prefix reads only the delta: 11.7× faster on the Thor, ~0 tokens per frame
   when nothing changed.
2. **Under motion the delta is not the cheaper thing.** 63.5 % of the glyph
   cells change per frame at 148×80; the delta costs 4.3× the full frame on a
   real reader's tokenizer and does not fit a 32k context.
3. **So the cost moves into idle time only when the world is still** — there,
   and only there, a higher-resolution keyframe is affordable: 388 tokens per
   frame at the fine grid against 6,523 for reading the base-grid frame every
   frame.
4. **What the reader actually reads is not the picture.** On exact ground truth
   the text frame alone is *below* the guessing floor for "which way is the
   scene moving" (0.431 vs 0.486); a per-cell motion channel takes the same
   reader to 0.889 (+40.3 points, p < 0.00001) for 42 % more tokens. The
   two-frame window and the keyframe + delta are both at the floor. Casey's
   observation — that the rendering works best when you are moving, because
   what it carries is the delta of the relative perspectives — holds for a model
   reader, and the channel that carries it is one character per cell.
5. **At a fixed sample count, resolution buys no measurable accuracy** (0.986
   against 0.972 across a 6.8× range of cells), so the high-resolution keyframe
   is close to free in information terms even if it is not free in tokens.
6. **At matched recall the rate gate beats the level gate**, on cuts and on the
   reader's own confidence: the same recall with a quarter to none of the false
   alarms, and 25 fires against 36 on the confidence series.
7. **The local decision reader is a probability instrument, not a reader.** It
   answers "left" on 72 of 72 frames, with the true frame and with the wrong
   one; its instruction-following control is perfect. The brief's
   first-named instrument would have returned a null that says nothing about
   the arms.
8. **The emitter/projector split sends 157× fewer bytes and builds the wrong
   picture** (12 % cell agreement). The wire is the easy half.
9. **The knower field is a trigger, not a channel**: its max-cell surprise
   fires 5.2 frames early with no false alarms, and its mean-surprise gate is
   blind, as the law says it must be.
10. **Casey's autopilot window is a working trigger but not a demonstrable
    win.** The reader's own confidence separates right from wrong answers
    (+0.068), the policy behaves the way the band predicts — it never takes
    frame 0, it takes its keyframes where the confidence is steady, and it is
    2 % cheaper in characters — but the reading comparison cannot be
    conclusive, because the arm the two policies differ in is at the guessing
    floor for this reader.

---

## 7. Honest limits

* **The corpus is three scenes.** The Infinigen ground-truth renders of the
  80+ scene sweep did not land in this session: `harness/gt_batch3.sh` (which
  uses the sweep's already-rendered terrain, §2.2) sat in the shared
  admission queue behind other seats' jobs for the whole session, and the
  admission daemon itself was restarted by another seat mid-run. The
  exact-ground-truth corpus is arctic-s1, canyon-s1 and hello_world: 72 frames
  of exact labels. That is enough for the effect sizes above (+40 points, p <
  0.00001) and not enough for a 2-point difference.
* **The cloud reader is a chat model with no logprobs**, so its answers are
  parsed from text and its confidence is self-reported. The parse is checked
  (the `oracle` control scores 1.000 on all three questions, so the format is
  being followed), but a parse failure would show up as a wrong answer rather
  than as a missing one.
* **The local reader's quality run is complete** (72 frames, 3 scenes), but it
  was slow: the box's load average was 30.9 on 14 cores and the GPU pool was
  down to 1.1 GiB while it ran, so the whole run took about two hours. Its
  result — a constant majority-class answer on every question — is the same on
  every scene and every arm, so it is not a small-sample artefact.
* **The motion channel is computed from exact optical flow**, as the brief
  specifies. What is measured is whether a text reader can *use* such a
  channel, not whether flow can be estimated from text.
* **The corpus has a moving camera and static objects.** The brief's "still
  camera: what moved" half of arm (h) is therefore **not measurable here**:
  with a fixed camera and a static world nothing moves. It needs a scene with
  independently moving objects, which the Infinigen sweep does not contain.
* **The depth question and the which-moved question are not independent.** On
  this corpus they have the **same answer key** in all 72 frames (the nearer
  object moves more, so "which is nearer" and "which moves most" agree), even
  though the marked pair of objects differs in two of the three scenes. The
  two columns of the tables are therefore two readings of one question, not
  two independent measurements, and only the **camera-direction** question
  (and the depth question's own probability) carries independent information.
* **d1-2B does not cache** in this llama.cpp build (§5.3 of the earlier
  write-up, kept below); the cached cost numbers come from LFM2-1.2B on the
  same box. Groq does not itemise cached tokens (§5.4), and the cold/warm
  probe shows no latency difference (1.22 s against 1.52 s).
* **No OpenSkyFlight leg.** The second test bed the brief asks for needs a
  browser flight sim and a camera pose; it is not on this box (checked), and
  the reprojected Infinigen walk is the stand-in with exact motion vectors.
* **The knower is a numpy port with a torch cross-check**, not a rewrite; the
  grid sizes are the ones the brief asks for, the arithmetic is the same, and
  the two agree to 1.6 × 10⁻⁶.
* **The noise floor for the quality numbers is the blind control in the same
  batch**, not the corpus's own ±5–7 points; conditions are compared within
  the batch, paired per frame, with McNemar's exact test.

---

## 8. Reproduce

```sh
cd ~/lm-wt/syzygy-keyframes

# 0. the kernel, unmodified, verified
sh vendor/Syzygy/tools/suite-total.sh          # 219 checks, 0 failures

# 1. build the corpora (kernel renders; a few seconds)
python3 harness/build_corpus.py --corpus docks
python3 harness/build_corpus.py --corpus infinigen
python3 harness/gt_multi.py --scenes corpus/gt_scenes --out corpus/multi \
        --frames 24 --swing 1.2 --grids coarse,low,base,fine
python3 harness/add_grid.py --corpus corpus/multi --grid 192 --cols 192 --rows 104

# 1b. the Infinigen ground truth for more scenes (needs a thor-admit lease)
SCENES="coast:1 desert:1 forest:1 mountain:1 plain:1 river:1" \
    bash harness/gt_batch3.sh        # -> corpus/gt_scenes/<scene>-s<seed>

# 2. the decisive measurement: residual and token cost per arm
python3 harness/measure.py --corpus all --grid all        # results/measure.json

# 3. the readers
thor-admit serve d1-2B --port 8142 --peak 8G --tier live -- \
  llama-server -m ~/models/d1-2B/d1-2B-Q8_0.gguf --host 127.0.0.1 --port 8142 \
    -ngl 99 -fa on -c 65536 -b 32768 -ub 32768 --parallel 4 -t 14 --alias d1-2B
llama-server -m ~/models/LFM2-1.2B/LFM2-1.2B-Q8_0.gguf --port 8098 -c 32768 -ngl 99
python3 harness/quality2.py    --port 8142 --grid low   # local reader, all arms
python3 harness/groq_quality.py --grid low              # cloud reader, all arms
python3 harness/groq_quality.py --grid coarse           # the same at 74x40
python3 harness/reader_cost.py --corpus docks --grid base --limit 20
python3 harness/reader_cost.py --corpus docks --grid base --limit 20 --repeat 12 \
    --out results/reader_cost_still.json
python3 harness/groq_cost.py  --corpus gt --grid base --frames 6

# 4. the knower field and the gates
python3 harness/knowerrun.py     --corpus gt --grid base --limit 24
python3 harness/knower_motion.py --corpus docks --grid base
python3 harness/knower_anomaly.py --corpus infinigen --grid base
python3 harness/knower_torch.py --corpus multi --grid base
python3 harness/gates.py      --corpus corpus/multi --grid low
python3 harness/gates_conf.py --file quality2_low.json --condition a_full

# 5. the c3 trade-off on the hard world, and the autopilot window
~/src/infinigen-thor/.venv/bin/python harness/c3b.py --out results/c3b.json
python3 harness/autopilot.py --out results/autopilot.json

# 6. the emitter/projector split and every table in this file
python3 harness/emitter.py --corpus corpus/multi --grid base
python3 harness/summarize2.py    # the quality, gate, c3 and emitter tables
```

`harness/` is the whole experiment; `results/` holds every raw number quoted
here; `vendor/` holds the crew's repos, unmodified.

### Files

| file | what it is |
|---|---|
| `harness/syz_render.c` | the transport: NV12 in, the kernel's three alphabets out |
| `harness/syzlib.py` | NV12 conversion, corpus paths, text-frame reading |
| `harness/arms.py` | every arm as a wire payload, and the motion estimator |
| `harness/build_corpus.py` | renders the docks walk and the Infinigen sweep |
| `harness/gt_motion.py`, `harness/gt_multi.py` | the exact-ground-truth corpora (depth-based reprojection) |
| `harness/gt_scene.sh`, `gt_scene_fast.sh`, `gt_batch3.sh` | the Infinigen ground-truth renders (the fast path reuses the sweep's terrain) |
| `harness/add_grid.py` | renders one extra cell grid into a corpus scene |
| `harness/measure.py` | the residual and token table |
| `harness/reader_cost.py` | fresh vs cached cost, on the local text reader |
| `harness/quality.py`, `harness/quality2.py` | the reading-quality experiment (local reader) |
| `harness/groq_quality.py`, `harness/groq_cost.py` | the cloud reader: quality and cost |
| `harness/probe_blind.py` | is the reader actually reading the picture? |
| `harness/autopilot.py` | Casey's band: the keyframe taken while confident and steady |
| `harness/knower.py`, `knowerrun.py`, `knower_motion.py`, `knower_anomaly.py`, `knower_torch.py` | the knower field and its laws |
| `harness/gates.py`, `harness/gates_conf.py` | level gate against rate gate |
| `harness/sweep.py`, `harness/keypolicy.py` | the keyframe policy sweep and the policies themselves |
| `harness/emitter.py` | arm (g), the emitter/projector split |
| `harness/c3b.py` | c3's trade-off, re-run on the hard world with the arms |
| `harness/table_local.py` | the local reader's quality table, as markdown, from the results |
| `harness/summarize.py`, `harness/summarize2.py` | regenerate every table in this file from `results/` |

### The raw numbers

| file | what it holds |
|---|---|
| `results/measure.json` | the residual and token table for every arm, corpus and grid |
| `results/reader_cost.json`, `reader_cost_still.json`, `reader_cost_low.json` | fresh vs cached cost on the local text reader |
| `results/quality2_low.json` | the local reader's reading quality, every arm |
| `results/groq_quality.json`, `groq_quality_coarse.json` | the cloud reader's reading quality, at two grids |
| `results/probe_blind.json` | the picture-sensitivity probe |
| `results/autopilot.json` | the autopilot window against fixed intervals |
| `results/groq_cost.json` | the cloud reader's tokens, latency, cost and cached-token probe |
| `results/knower.json`, `knower_motion.json`, `knower_anomaly.json`, `knower_torch.json` | the knower field, its receipts and its gates |
| `results/gates.json`, `gates_conf.json` | the level gate against the rate gate |
| `results/sweep.json`, `sweep_still.json` | the keyframe policy sweep, walking and idle |
| `results/emitter.json` | arm (g): the bytes on the wire and the fidelity |
| `results/c3b.json` | the c3 trade-off on the hard world, per arm and per cell |
| `results/quality2_low_wave2_superseded.json`, `pilot_coarse_wave2_superseded.json` | the superseded wave-2 quality files (§9) |

---

## 9. Corrections

**The wave-2 quality numbers are superseded.** `results/quality2_low.json` (wave
2, 2026-11-01 02:01) and `results/pilot_coarse.json` held one row each, and in
both the `blind` control — the wrong frame with the right markers — returned
*bit-identical* numbers to the true frame, on a picture where 1,859 of 5,092
characters differ. Those files are kept, renamed
`quality2_low_wave2_superseded.json` and `pilot_coarse_wave2_superseded.json`,
and are not used anywhere above. Three defects were found and fixed:

1. **The motion-plane arm crashed the run.** `quality2.motion_planes`
   quantised the flow direction by indexing a 4-character string with 4 or 6
   for the diagonal bins, raising `IndexError` on any frame whose flow was
   diagonal — which, with a swinging camera, is most of them. The run wrote
   its first row and died. Fixed by quantising to the nearest cardinal by the
   flow vector's dominant axis.
2. **The wave-2 script was not the committed script.** The committed
   `quality2.py` emits one plane for the reader's state (2,698 tokens for the
   96×52 frame); the wave-2 run reported 8,132 tokens, which is the
   three-plane figure. The wave-2 file was produced by an earlier version of
   the script that was edited before the snapshot commit, so it cannot be
   reproduced from the code that is committed now. That is the most likely
   origin of the identical blind and true-frame answers as well.
3. **The wave-2 reader server was mis-sized.** It ran with
   `n_ctx_slot = 4096` against a state of 8,132 tokens, so the picture did not
   fit the slot's context. The reader used here is `-c 65536 --parallel 4`
   (16,384 tokens per slot), which carries every arm at the 96×52 grid.

**c3's gate labels were inverted relative to c3's own stated rule.** c3's
`run_gate` reads its matched pair as `(low-fps/high-resolution,
high-fps/low-resolution)` — that is the order c3's `PAIRS` are written in — but
labels the first tuple `high_fps_cell` and so computes `delta` with the sign
opposite to its stated pre-registered rule. c3's own verdict was a TIE, so the
inconsistency changed nothing there; on the hard world it decides between
FRAMERATE-WINS and RESOLUTION-WINS. `harness/c3b.py` now names the cells
`res_cell` and `fps_cell` and computes `delta = acc(fps_cell) − acc(res_cell)`.
The thresholds (4 pairs, 5 points, 2 to win) are c3's, unchanged. The verdict
reported in §4.5 is the corrected one.

**The residual table was re-measured.** The earlier write-up's §4.2 table read
"18,388 cells / 186,794 characters" for the per-cell delta, "59,430" for the
run-length form, "7,306 / 74,257" for the channel delta and "315,502" for the
event channel. Re-measured in this run from the committed corpus, over the
same 296 transitions, the figures are **19,463 / 197,794**, **58,926**,
**7,521 / 76,445** and **334,035** — 2 to 6 % higher, because the earlier
figures were taken against an earlier snapshot of the docks corpus. The
conclusion is unchanged and slightly stronger: the per-cell delta is **16.5×**
the one-plane frame rather than 15.6×, and the run-length form is still
**4.9×** the frame it replaces.

**Superseded text from the earlier write-up** (kept visible, per DOC-RULES):
§4.5 of the earlier draft read *"On a moving camera the bar is not met, and not
narrowly: (c) is half the frame rate of (a), because the delta costs 3.6× the
frame it replaces"* — that stands. But the earlier draft's §5.2 called the
(c) arm "the delta is the whole story", and the earlier draft's arm table said
(g) was *"not measured — reasoning, not a number"*. Both are now measured:
arm (g) sends 228 bytes per frame against 35,828 and builds a picture that
agrees with the true one on 12 % of its cells; and the delta is no longer the
whole story — the arm that moved the reader was the motion channel, which is
not a delta at all.
