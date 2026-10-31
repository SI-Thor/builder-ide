# Decisions for Casey — one sheet, twelve items

**2026-10-31.** This is the whole of the plan's decision list, condensed
(`docs/plan.md` §4 is the long version, or rather the pointer to this file).
Every item is one line of context, the options, what we recommend, and what
happens if you don't decide.

**Two groups.** **Part A** is already in the spec or in the code — you are
being asked to *say yes*, not to run a debate; a yes takes a minute.
**Part B** is a real choice with more than one reasonable answer; each has a
deadline because something is waiting on it.

**Nothing here is a surprise.** Part A is what the team already wrote down.
Part B is where the team has a view and your call settles it.

---

## Part A — say yes (already adopted; these need your word, not your time)

### A1. Who writes the ledger, and what the Critic may judge
Two rules that stand or fall together. Three record types, three writers, one
store: a taste note is yours only, a prediction is sealed by the builder, a
verdict is written by the Critic for defects only. And the Critic judges
**defects, never taste** — two surfaces: a defect Critic that never sees the
ledger, and a taste critic that may only *rank*. **Options:** (a) the three
writers and the split; (b) owner-only for everything; (c) let the night write
taste rows; (d) one critic that has learned your taste. **Recommendation:
(a).** Without the three writers the sealed bets become unfalsifiable and
Magnus's rows decorative; without the split, "the Critic decides whether a
thing is good; you decide whether it is yours" stops being true. **If you
don't decide:** we keep building on (a) and record it as the team's default —
which is the same as (a), minus your name on it.

### A2. What Magnus may do
Chips only — no mic, no free text, no keyboard — and he *proposes* rather
than applies: he points at a branch, it becomes a proposal, you confirm.
**Options:** (a) chips only, proposals only; (b) spoken input with full apply.
**Recommendation: (a).** His input is structured data from the first second;
a kid should say "that one" about a picture, not repoint the
hamlet's recipe. **If you don't decide:** (a) stands — it is already
structural in the code (separate `author` scopes, forever).

### A3. The night's budget, in what units
One bar for you (wall, lane-time, hosted money), four counters underneath for
the scheduler, including a **per-model load cap** enforced when a job is
admitted. **Options:** (a) the bar and counters; (b) one GPU-hour bar;
(c) money first. **Recommendation: (a).** GPU-hours are not enforceable before
spend; the box's real constraint is weight-swap thrash, and money applies
only to hosted calls — which reads `$0.00 (local)` by default, itself a
product statement. **If you don't decide:** (a) stands.

### A4. The morning report's first lines
Status line (`ran as planned / ran short / ran degraded / did not run` + one
reason) → the failures → the numbers **with the cut named** → the filmstrip →
the branches → the parked questions. **No single "prediction score."**
**Options:** (a) as above; (b) the night's headline first. **Recommendation:
(a).** A report that shows "5.3 of 5.5" without the 1.7 h that was dropped
is the most dishonest-looking artifact in the set. **If you don't decide:**
(a) stands; the single score is killed either way.

### A5. Model changes, and the taste ledger
Model changes are announced in character at the next report — never a silent
swap. The taste ledger never leaves the machine by default; model calls get
author-filtered slices and Magnus's rows never appear in one. **Options:**
announce loudly / swap silently; ledger local / free export. **Recommendation:
both as stated.** The identity-discontinuity evidence is unambiguous, and the
privacy boundary is a product property, not a setting. **If you don't
decide:** both stand.

---

## Part B — real choices (each one has something waiting on it)

### B1. The engine — Infinigen 2.0 + procfunc ⏳ *decide by Nov 7*
**Context:** Infinigen 1.x runs on the Thor today (Cycles GPU is 7.1× the
CPU), but 1.x hands state between processes through `.blend` files, which is
the opposite of the warm scene server the product needs. Our fork is already
pointed at 2.0. **Options:** (a) **2.0 + procfunc**, with our Warp terrain
re-expressed as a v2-native stage; (b) stay on 1.x and rewrite around it;
(c) 2.0 + procfunc but treat terrain as a later add-on. **Recommendation:
(a).** 2.0's single-process, in-memory generation *is* the shape we designed;
procfunc's tracer gives the machine-readable dependency graph the stage cache
was missing; and 2.0 has no terrain, which is the one thing we genuinely
wanted — and we own it in Warp already, bit-identical and 44–56× the CPU
path. Terrain must be in scope from day one or we spend months with no
terrain. **Cost:** 2.0 has no constraint solver (we rebuild it — we were
going to anyway), no mesh export (we write it), and its interfaces may shift
while we build. **Mitigation:** our own recipe schema sits *above* procfunc,
so an upstream change is one adapter, not every recipe. **The confirming
experiment is running** — its first step already passed (a v2 room rendered
on the Thor: 435 s, GPU 98 %, 78.5 W). **If you don't decide:** we keep
building on 2.0 as the default and your yes is recorded as the team's
decision; the risk is that a choice this consequential was never yours.

### B2. Hosted engineers and the money cap ⏳ *decide by Nov 14*
**Context:** hard work orders need an engineer. Claude Code is the strongest
contract in the field (real OS-enforced sandbox, `--max-budget-usd`) but it
costs money; the free local lane (aider + a local Qwen3-Coder-30B) is free in
dollars and expensive in **memory** — ~60 GB of the same 122 GB pool the
renderer wants, and the Thor's model services are currently stopped and
disabled at boot. **Options:** (a) hosted off by default, enabled for hard
orders under a per-night cents cap once the bake-off gives numbers; (b)
always local; (c) hosted by default. **Recommendation: (a).** Price the local
lane as *residency*, not as free. **The bake-off has never been run**, so the
number behind this decision does not exist yet — it lands in week 1. **If you
don't decide:** hosted stays off and the local lane stays off, which means
hard work orders simply do not get done; the work-order loop, the thing that
lets the builders grow, stalls.

### B3. The always-on daytime world (cognitive-ecology's Law 1) ⏳ *decide by Nov 14*
**Context:** the vision's day half is a world that exists before you log in —
characters living and working between sessions. Our own research project
(cognitive-ecology) has built the one thing that does this: an always-on
substrate where "nothing is event-driven internally; events perturb ongoing
processes." We have vendored its WHY kernel (the justification semantics) and
nothing else. **Options:** (a) **yes** — the daytime world runs, starting
small: one room, one clock, reproducible from the recipe and a tick count;
(b) no — the world only exists as far as the night's work and the morning's
report; (c) adopt the ecology's full runtime (tick loop, per-tick bidding,
attention economy) as our core. **Recommendation: (a).** (c) is complexity
without demonstrated value for a two-user product whose night is a scheduled
window, and the ecology's own falsification program hasn't run yet; (b)
gives up the half of the product that makes a world feel like a place. The
ecology stays the research home for this question; we revisit when its
evidence improves. **If you don't decide:** we default to (a) with the
smallest possible version — one room, one clock — which costs a week, so the
cost of silence is low but the *direction* is yours.

### B4. The project licence ⏳ *decide by Nov 14*
**Context:** both repos are public — `SI-Thor/builder-ide` and
`SI-Thor/infinigen-thor` — and **builder-ide has no licence file**. Infinigen
is BSD-3 with attribution kept; the vendored WHY kernel is MIT with its
notice intact. Third-party code keeps its own licence, which is already the
rule (`docs/understanding.md` §2.7's register, 30 rows). **Options:**
(a) **BSD-3-Clause** for builder-ide, matching infinigen-thor and the
provenance rules in the README; (b) MIT, matching the WHY kernel and modern
practice; (c) Apache-2.0, for the explicit patent grant; (d) keep it
undecided. **Recommendation: (a) BSD-3.** It is the licence the whole corpus
already uses, it is the most permissive-in-practice of the three, and it lets
us take and re-license Infinigen's BSD-3 fork without friction. It does **not**
change the third-party rules: each dependency keeps its own licence, and the
scheduler stamps it per weights revision. **If you don't decide:** the repos
stay public with no licence, which means **nobody may legally reuse anything
we write** — including anyone we might want to attract later. This is the one
item on the sheet with a silent cost.

### B5. Contacting the maquette author ⏳ *decide by Nov 21*
**Context:** someone else has already built a prototype of our builders layer
— an LLM writing Blender scripts against a closed catalog of factories, a
work-order queue, a checkpoint mechanism, and an LOD bake for a browser
client. It is BSD-3, so **we may take the code without asking**. The fork's
last push was 2026-06-12, it has 0 stars, and the companion repo holding the
MCP server and the viewer is **not publicly reachable** — so the most
interesting half may be private, discontinued, or simply unpublished. We have
read everything that is public; we cannot read that. **Options:** (a) **send
one short, specific, technical note** asking whether the companion repo is
available and whether the catalog-guide filter was a deliberate design; (b)
do not contact him and rely on the code we can read; (c) a broader
collaboration pitch. **Recommendation: (a).** Frame it as *"we studied your
maquette pipeline and borrowed the guide idea"* — not a rescue pitch (the fork
has 0 stars and a stale changelog) and not a collaboration proposal yet. One
question, no attachments, no ask. **What not to do:** don't fork, star, or
open an issue to wake it up — a star on a 0-star fork is noise. **If you don't
decide:** (b) stands and we lose the one thing we cannot read by reading.

### B6. The 5 GbE cable ⏳ *decide by Nov 7*
**Context:** the Thor's 5 GbE RJ45 port has no cable, so every byte moves on
**2.4 GHz Wi-Fi** (PHY 229/207 Mbps, RTT 1.6–7.6 ms). The 4× 25 GbE cage is
real silicon with nothing in it. **Options:** plug the cable / stay on Wi-Fi.
**Recommendation: plug it.** One cable, driver verified, it costs a minute of
your hands. The loads do not need it — recipe state is kilobytes — but every
video-class moment (the peek's clips, the morning filmstrip at 60 fps)
competes with Wi-Fi until it does. **If you don't decide:** Wi-Fi stays, and
the filmstrip and clip channel carry a quality risk we will have to measure
and absorb.

### B7. Re-formatting the external drive as ext4 ⏳ *decide by Nov 7*
**Context:** the 1.9 TB cold shelf is **offline**. It is mounted NTFS through
fuseblk, and it wedged mid-write under load and D-stated a run for over 30
minutes; `fuse`, `ntfs3` and `ntfs-3g` mounts all hang, and two processes are
stuck in `D` state, unkillable, because a task in `D` cannot be signalled.
Everything runtime has already moved to the internal NVMe (343 GB free). The
Blender source tree and the original wheel are parked on it. **Options:**
(a) **physical replug, then re-format as ext4** and use it strictly for cold
caches and artefacts; (b) replug and keep NTFS; (c) leave it off and buy
more NVMe. **Recommendation: (a).** The NTFS-over-fuseblk combination is a
repeat-offender failure mode that has already cost us a run, and ext4 is what
the box expects. This destroys the data on the drive — we will move anything
we need to NVMe first. **If you don't decide:** the shelf stays offline, the
box stays on 343 GB of NVMe, and every model weight and cold cache competes
with the renders.

---

### Carried over from draft 1 and now closed (no decision needed)

- **The prop stack.** TRELLIS.2 via ComfyUI (MIT code and weights), TripoSR as
  the baseline, textures via TRELLIS.2's shape-conditioned texturing, behind a
  thin HTTP service. The alternative (modly + TripoSG) brings a Tencent licence
  and two CUDA source builds; TRELLIS.2 brings neither, and it is **already
  measured on this box**: 512³ in 101 s, 1024³ in 194 s.
- **The 2.4 GHz link and the 4× 25 GbE cage** — the cage is empty, the port
  needs a cable (B6).
- **The local model lane** — folded into B2; it is priced as residency.
- **The Orin** — a non-goal for now; the core is Thor-only and single-writer,
  and `CLAUDE.md` says to ask before using it. Revisit at M3 if a measured
  CPU-lane backlog appears.
- **Cold start: mechanism or number of nights** — a **mechanism**, already
  built (questions and guess-confidence decay per builder per reason code at
  two observations), and the melt week measures the 6 → 0 decay from the
  ledger alone.
- **May the pre-flight act when the lane is busy** — **propose only**. The
  owner's bar, the owner's start; the sole exceptions are the safety rails,
  which act without asking, exactly as the trust report specifies.
- **The Companion's memory of Magnus's chip requests** — count them, scoped,
  after ratification; they never reweight Casey's builders.
- **Character motion** — procedural, recipe-authored walk cycles; no
  generated motion in shipped paths (the data licence flows into shipped
  outputs).
- **The Critic's model, and when** — scripted checks now (`verdict@scripted`
  on the face), a vision model chosen from the calibration numbers at M2/M3.
- **Public GitHub repos** — done; both repos are already public.

---

*Sources: `docs/plan.md` (draft 2) · `docs/understanding.md` §2.5–2.7, §3.1,
§4.17 · `docs/research/ig2-procfunc.md` · `docs/research/maquette.md` ·
`docs/research/cogeco.md` · `docs/research/forks.md` ·
`docs/research/spike-phase1.md` · `docs/lab/exp-nvme-bandwidth.md` ·
`docs/lab/exp-fp8-tensorcores.md` · `docs/lab/exp-warp-terrain-port.md` ·
`INTEGRATION.md` · `CLAUDE.md`. Every recommendation here is the team's, with
its source named; none of it needs a new experiment to answer.*
