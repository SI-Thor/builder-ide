# night-v4: the second integrated night, with the merged work in it

**The brief** (`BRIEF.md` on the Thor, 2026-11-01 15:05): run the night again
with what merged since run D — the judge routed to the d1-3B with the neutral
option order, the occupancy-based plausibility prior and the d1-2B delegate in
the critic, every heavy step under a thor-admit lease with the lease phased
down when the heavy phase ends, and physag-lite's MuJoCo action check if it is
committed and working — then write the morning, a letter of at most 150 words,
and the measurements beside the box state.

The owner goal is the same one run D had: *a small courtyard with three props:
a weathered crate, a brass lantern, an iron anvil; make it feel lived-in.*

---

## 1. The facts the change stands on

**The judge's cells are not all alike, and the 2B was the wrong model for one
of them.** A cell is (backend, model, task). On the sea-state task the
recorder names the truth and a decoy, once each; on the steps where the decoy
was named first, the d1-2B's answer tracked the presentation rather than the
truth — the measurement is in `docs/lab/exp-judge-calibration.md` §7 (the
positional share) and the routing is §8.3: **that cell goes to the d1-3B**.
The gate that goes with it is in the shipped table (`core/judge/gate.py`): the
2B's τ is 0.7 and the 3B's is 0.76, the latter restated into the canonical
space, and the two thresholds make identical decisions on the recorded
judgments.

**A choice question's option order is not the caller's to choose.**
`core.judge.models.Question.to_wire` sorts the question's criteria by their
key, so the order the model sees is the options' identity order whatever the
caller writes. The ordering policy (`core/judge/ordering.py`) makes that a
policy instead of an accident: a state whose options are named conditions can
be put in the canonical order — sorted by the name each option carries — so
the presentation carries no information about the answer. The canonical order
is computed by the module, and the night checks it against the wire's own
order rather than assuming them to agree.

**The plausibility prior needs the volume an object *occupies*.** The signed
volume is the same number for a solid and the wrong one for a shell: a real
mug is a little ceramic inside a large cylinder, and a prior that reads the
ceramic calls every real object a ghost
(`docs/lab/exp-critic-shells.md`). The night measured the gap on its own
meshes: the lantern's signed volume is **0.027** against a convex hull of
**0.326** — a factor of twelve, on the same mesh.

**A prior's score is a rank inside a group, and a group has a floor.** The
score of a prop is compared with the group it most resembles, and a group of
*n* members cannot score below `0.5 / (n + 1)`. The ghost gate is at 0.05, so
it needs **ten** members in a group before it can express itself at all (the
same document, §4.4).

**The delegate's questions were measured on scene renders.** The bake-off
(`docs/lab/exp-critic-delegate.md`) asked the six fixed class questions of
renders and found the d1-2B delegate good on them (TP 23 / FP 0 / FN 1 / TN
39 — the same row as the scripted checks alone), and found the hybrid adds no
accuracy over the scripted checks. The night's pictures are not renders.

## 2. Why the old way failed

Run D judged with the d1-2B on every cell, so the cell that leaks on the
presentation was judged by the model that leaks: all five of run D's decisions
were answered by the local d1-2B and **all five went to the cloud** after it,
and two surfaced below τ. Run D's prop critic read the **signed** volume, so a
shell like the lantern was measured by a number that is not its size. And run
D's picture stage had no picture critic at all: the scripted half could only
say that a picture existed and was the size it was asked for, so nothing
looked at the pictures the meshes were built from.

## 3. What changed

This is what the change **is**. The night itself did not run — section 5
says why, section 6 says what was and was not measured, and section 9 lists
what is still unverified.

**The judge.** The night's decision model is the **d1-3B** (`d1-3B-Q8_0`),
served on :8295; the delegate's d1-2B is a second server on :8296 with its
projector. The options go to the model in the neutral order: each option is a
named condition and the conditions are sorted by their names, and the night
checks the canonical order against the wire's own sorted-by-key order — they
are **the same six ids** (`neutral: true`). The night also asks the routed
cell **on its own server**: the fixed recorder's 240 states through
`core.judge`'s own `Judge` over `D1Backend`, at the 3B's calibrated τ, with a
one-rung ladder so no cloud rung answers.

**The critic.** `NightPropCritic` is the scripted critic plus two halves. The
**prior** reads the prop's features — with the occupied volume, because the
executor now measures the convex hull — against the reference set, with the
repair's silhouette IoU as the consistency side, and the ghost gate (0.05) is
the one thing that may reject a prop. The **delegate** answers the six fixed
class questions about the prop's own picture; a fired class takes the
picture's score down by the model's own probability for it, so the delegate
decides which sibling wins the picture round. It does not void a prop: the
delegate's questions were measured on renders and the night's pictures are
product pictures, and a domain mismatch that emptied the courtyard would be a
fact about the wiring, not about the delegate.

**Memory.** The night takes a `thor-admit` lease for each decision model's
start (`night-v4.d1`, `night-v4.delegate`) and one for the whole heavy phase
(40 GB, `night-v4.heavy`), and when the heavy phase ends — ComfyUI and both
decision models stopped — the lease is **phased down to 8 GB** with
thor-admit's `phase` op (round 11), and the live view and the morning run
under the smaller promise. The row carries the old peak, the new one, the
reason and the box's free memory. The flock is the fallback only, and the row
says which one held.

**Props.** physag-lite's MuJoCo action check is committed
(`core/physag/check.py`, HEAD `3e76eee`) and it does run MuJoCo — but it
accepts nothing: the TRELLIS arm's own summary has **0 of 7** counted props
physics-valid and **0** stable, and the seat's tree still carries uncommitted
work on the same files (a CAD rerun was still landing at 15:25). **The night
keeps the scripted critic**, and says so here and in its report.

## 4. The pre-run measurements (the four seams, on the box, before the night)

Each seam was exercised on the box before the night, under a `thor-admit`
lease (`night-v4.smoke`, 8 GB, admitted in 0.02 s):

| seam | what was asked | what it answered |
|---|---|---|
| the neutral option order | the canonical order against the wire's own | the same six ids; `neutral: true` |
| the routed cell | ten of the fixed recorder's states, on the d1-3B, at the calibrated τ (0.76) | accuracy 0.4; decoy-first 0.5714; truth-first 0.0; all ten surfaced; latency p50 55 ms |
| the delegate | the six fixed class questions about a real crate picture | `holes 0.510` (fired), `missing_object 0.206`, `texture_swap 0.057`, `noise_fireflies 0.031`, `black_frame 0.003`, `floating_object 0.009`; 2.39 s for the six |
| the prior | fitted on the measured real objects | 38 members, 22 groups, the largest holding **seven**; the ghost gate cannot fire (a group of *n* cannot score below `0.5/(n+1)`, and the gate needs ten) |

And the measure the prior needs: the occupancy of two real TRELLIS meshes —
the crate's signed volume 0.912 against a convex hull of 0.994, and the
lantern's **0.027 against 0.326**. The convex hull costs 0.4 s and 400 MB on
a 700k-triangle mesh.

## 5. The night itself

**It started, and the box hung underneath it.** The night began at 15:42:57
with the box at load1 18.9 and 79.1 GB free of 122.8 GB, and its first three
lines are the whole story of the wiring:

```
[night] 15:42:57 the night begins; box: {'ts': '2026-11-01T15:42:57-09:00', 'load1': 18.89, 'MemTotal': 122.8, 'MemAvailable': 79.1}
[night] 15:42:58 d1-3B already answers on :8295
[night] 15:42:58 d1-2B already answers on :8296
[night] 15:42:58 queueing for a thor-admit lease (night-v4.heavy, peak 40G: the night's heavy phase: ComfyUI, the world's renders, the props)
```

The two decision servers were already resident: they were the ones the
pre-run smoke had started at 15:32:30 (the smoke's `kill` did not take, and
llama-server kept running). They are the right models on the right ports with
the right flags, so the runner found them healthy and reused them
(`started: false`) instead of starting its own. Their **start** was under the
smoke's own lease (`night-v4.smoke`, 8 GB), not under the night's heavy
lease. That is a fact about this run, not a claim about the night.

**The heavy lease did not come.** The daemon's rule is
`available − Σ(reserved − current) − peak ≥ floor` (25 GiB), so with the
box's lab-motion seat holding a 25 GB reservation and 60-79 GB free, a 40 GB
lease needs about 90 GB free before it is admitted. The night's lease waited
232 s with nothing in front of it, and `serve.glide` (58 GB) and
`crafter-lab.env-setup` (3 GB) queued behind it. Run D waited 914.9 s for
the same lease, so the wait is the box's business and the ledger records it.

**Then the box went off the network**, at about 15:50. The journal of that
boot (boot id `0336d5ed…`, ended 16:17:06) has the sequence:

| when | what the journal shows |
|---|---|
| 15:32:33 | `NVRM: GPU0 … Out of memory [NV_ERR_NO_MEMORY]` — the GPU's allocations are already failing, three seconds after the smoke's d1-3B started loading |
| 15:52:33 | `wlP1p1s0: Lost carrier` — the Wi-Fi drops |
| 15:53:04 | a kernel **WARNING** in the Realtek rtl8852ce driver (`sitesurvey_set_offch_state`, `_cmd_abort_notify abort=1`) — the same driver and the same abort as the 10:45 incident |
| 15:59:23, 16:02:40, 16:08:43 | systemd watchdogs time out: `journald` killed, `udevd` killed, `timesyncd` killed — the box is starved, not idle |
| 16:16:43 | the Wi-Fi comes back (`Gained carrier`) |
| 16:17:06 | the boot ends — the power cycle |
| 16:24:54 | the box is up again (boot `227a1534…`) |

So the box was not dead: it kept running and kept logging for 26 minutes
after it went unreachable, and the Wi-Fi came back on its own before the
power cut. It was the **GPU's allocation pool** that was exhausted — at
15:23 the daemon reported `gpu pool: 40.0M free` — and the daemon's GPU floor
is **off** on this box (round 10 turned it off because tegrastats' `lfb` is a
figure about contiguous free blocks, not the GPU's headroom). So a lease
that promises device memory never waits for the pool, and the servers' GPU
allocations failed with `NV_ERR_NO_MEMORY` instead. That is the concrete
consequence of the floor being off, and it is the part of the chain the
house can fix without a power cycle.

**My night was queued and idle**: it had no lease, had loaded nothing, and
the daemon's queue shows its 40 GB lease waiting with `serve.glide` (58 GB)
and `crafter-lab.env-setup` (3 GB) behind it.

**And then the box came back**, at 16:24:54. The daemon was restarted, and
the night was started again at 16:26:47 from the same commit — this time
with its own servers, under its own leases:

```
[night] 16:26:47 the night begins; box: {'load1': 4.05, 'MemTotal': 122.8, 'MemAvailable': 114.4}
[night] 16:26:47 queueing for a thor-admit lease (night-v4.d1, peak 40G: start d1-3B llama-server)
[night] 16:26:47 got the thor-admit lease after 0 s (start d1-3B llama-server)
[night] 16:26:50 d1-3B serving on :8295 (pid 8579, peak RSS 784 MB)
[night] 16:26:50 queueing for a thor-admit lease (night-v4.delegate, peak 40G: start d1-2B llama-server)
[night] 16:26:50 got the thor-admit lease after 0 s (start d1-2B llama-server)
[night] 16:26:52 d1-2B serving on :8296 (pid 8895, peak RSS 786 MB)
[night] 16:26:52 queueing for a thor-admit lease (night-v4.heavy, peak 40G: the night's heavy phase: ComfyUI, the world's renders, the props)
[night] 16:26:52 got the thor-admit lease after 0 s (the night's heavy phase: ComfyUI, the world's renders, the props)
[night] 16:27:04 ComfyUI ready
[night] 16:27:04 free after the loads: 105.1 GB
[night] 16:27:05 asking the routed decoy cell on this box's d1-3B
```

Three leases, all admitted in 0 s, all of kind `thor-admit`, and 105.1 GB
free after the loads. **The crashed attempt's artifacts were kept, not
deleted** (`artifacts/night-v4-crashed-1550`): a night that started and then
lost the box is evidence too.

**That attempt was killed by the box's own guard.** The ComfyUI log ended in
the middle of SDXL sampling (step 8 of 30) with no error line, and the
daemon's log says who stopped it:

```
{"event":"guard.terminated","pid":9031,"pgid":8541,"name":"python",
 "command":"…/trellis/ComfyUI/main.py --listen 127.0.0.1 --port 8188 …",
 "rss_bytes":2875613184,"gpu_bytes":7625244672,"total_bytes":10500857856,
 "signal":"SIGTERM","signalled":true,"trigger":"runaway"}
```

with four `guard.unexplained_drop` lines before it: `lost_bytes` 9.0–9.4 GB,
`lease_growth_bytes` **0**. The rule behind it: a lease owns the processes
of its target and that target's **direct** children
(`procscan::usage_for`, `Target::Process` — the same function that measures
`lease.current_rss` and the guard's `lease_growth`), and the guard stops the
biggest process that **no lease owns** when the box loses memory the leases
cannot explain. The night started ComfyUI through `trellis/scripts/serve.sh`,
which starts it with `nohup … &` and exits: the server is re-parented to
init, so it belongs to nobody, and the night's lease could not say where the
memory had gone. The night had started ComfyUI the wrong way, and the guard
took it.

**The third attempt was killed by a lock file whose number came back
around.** It started at 16:33:07 and died at 16:33:37, with no traceback:

```
{"event":"lease.client_gone","lease":1,"reason":"the client never took the lock"}
{"event":"lease.orphan_stopped","lease":1,"signalled":true}
{"event":"lease.granted_not_run","granted_s":30.130953071,"reason":"client-gone"}
```

The daemon names a lease's lock file after the lease's **number**
(`state_dir/leases/<number>.lock`), and the numbers start again at 1 when
the daemon restarts. At 16:26:32 the old daemon granted lease 1 to the
`agent-world` seat's d1-2B server, and that client still held
`leases/1.lock` — `/proc/locks` names it, and its own descriptor points at
the unlinked file. The daemon was replaced at 16:32:59; the new one's
counter started at 1 again, so the night's lease at 16:33:07 **was** lease 1 —
the same file. The shim's `flock` has no timeout, so the client waited for a
lock nobody was going to give, and the daemon gave the night up after its
30 s grant grace.

Both kills are the same shape: **the night's work was real, and the box
could not see that it belonged to anyone.** The fix is on the night's side
(the daemon is another seat's crate and its binary):

- `sweep_stale_lease_locks()` — before asking for a lease, the night asks
  the daemon which leases it holds and how long it has been up, and unlinks
  every numbered lock file that cannot belong to a live lease of the daemon
  that is running now. The sweep's result travels in the `night.heavy_lease`
  row.
- The lease is taken under a watchdog (20 s), so a lock that does not come
  is a sentence with the holder's name in it, not a silent kill.
- **The night starts ComfyUI itself**, as its own child, with the command
  line and the log `serve.sh` uses, and stops the pid it started. The lease
  then owns the render server, and the render server's memory is the lease's.

Both are proved on the box, in committed scripts
(`docs/lab/night-v4-scripts/test_lease_lock_collision.py` and
`test_lease_ownership.py`): the collision made on purpose is stopped by the
daemon after **30.2 s**, and the sweep clears it so that the same lease is
taken in **0.04 s**; a child the lease's client starts directly is the
lease's memory (**+1092 MB** in the lease's own accounting), and the same
allocation through a shell that exits is not.

**And then the night ran** (run E), from the commit that carries both fixes
(`e3e83ce`, `ff62313`):

```
[night] 17:07:39 the night begins; box: {'load1': 3.82, 'MemTotal': 122.8, 'MemAvailable': 110.8}
[night] 17:07:39 lease sweep: 0 numbered lock files, none stale (start d1-3B llama-server)
[night] 17:07:39 got the thor-admit lease after 0 s (start d1-3B llama-server)
[night] 17:07:41 d1-3B serving on :8295 (pid 61659, peak RSS 784 MB)
[night] 17:07:43 d1-2B serving on :8296 (pid 61773, peak RSS 786 MB)
[night] 17:07:43 got the thor-admit lease after 0 s (the night's heavy phase: ComfyUI, the world's renders, the props)
[night] 17:07:43 ComfyUI started by the night: pid 61833 (log …/trellis/logs/comfy_server.log)
[night] 17:07:49 ComfyUI ready
[night] 17:07:49 free after the loads: 105.4 GB
[night] 17:07:49 asking the routed decoy cell on this box's d1-3B
```

Three leases, all `thor-admit`, all admitted in **0 s**, 105.4 GB free after
the loads, and the sweep finding nothing to clear. The night's ComfyUI is
its own child (`ps`: pid 61833's parent is 61554, the runner), and the
daemon's status accounts for it in the heavy lease (now 3.3 G, saw 7.0 G).

**The routed cell, asked on this box tonight** (240 steps, the fixed
recorder's states): accuracy **0.5208**, decoy-first **0.561**, truth-first
0.5, gates: act 59, escalate 0, surfaced 181, latency p50 **0.046 s** — the
same numbers as the published §9.4 run (0.5208, act 59, surfaced 181,
46.5 ms), measured on the night's own server.

**The prior, fitted on the night's own measured objects:** 38 reference
members, 22 groups, the largest holding 7, the ghost gate at 0.05. A group
of n cannot score below 0.5/(n+1), so the gate needs ten members in a group
and **cannot fire on this fit** — the night's approved set is empty, so the
prior is fitted on the measured real objects alone.

## 6. The measurements, beside the box state

**The attempt before the run** — run E, 17:07:39 → 17:13:32 — is measured
by the same script (`docs/lab/night-v4-scripts/measure.py`; the command is
in the scripts' README), and its receipts are kept
(`artifacts/night-v4-crashed-1713`):

| | run E (died in the mesh stage) | run D (night-v3, 06:06 → 08:39) |
|---|---|---|
| wall | 6.4 min of job wall (no morning: the night died before writing one) | **152.61 min** |
| GPU-minutes | **3.06** against the 60-minute rail | **25.74** |
| leases | **three**, all `thor-admit`, waited **0.0 s / 0.1 s / 0.0 s** (total 0.1 s), 107.3 / 110.1 / 106.1 GB free | one lease, kind `thor-admit`, peak 40G, **waited 914.9 s**, 100.6 GB free |
| decisions by rung | **251** rows: 245 on the local **d1-3B** (mean **0.0476 s**), 4 on **Jev** (0.267 s), 2 with no author | 12 rows: 5 on the local **d1-2B** (0.106 s), 5 on **Jev** (0.220 s), 2 with no author |
| gates | surfaced 181, act 66, escalate 2 | 2 escalate, 2 surfaced, 6 with no gate |
| props | 0 kept, 0 rejected (the night died before the props were judged) | **3 kept**, **15 rejected** |
| box | before: load1 3.82, MemAvailable 110.8 GB; after: load1 4.08, MemAvailable 104.6 GB | before: load1 63.75, MemAvailable 62.9 GB; after: load1 8.96, MemAvailable 84.5 GB |

Each of the night's three lease rows carries the sweep that ran before it —
three sweeps, each finding nothing to clear, and saying so.

The night that follows is in the table at the end of this section, with the
same script and the same diff.

The night at its start, from the run log's head:

| when | what | box beside it |
|---|---|---|
| 15:42:57 | the night begins | load1 18.89, MemTotal 122.8 GB, MemAvailable **79.1 GB** |
| 15:42:58 | the d1-3B already answers on :8295; the d1-2B on :8296 | (the servers were left by the pre-run smoke) |
| 15:42:58 | queueing for a `thor-admit` lease, label `night-v4.heavy`, peak 40G | 79.1 GB free |
| 15:46:49 | the lease was still queued — **232 s** | 60.1 GB free, load1 rising |

The lease never came, so the night's own `night.heavy_lease` row — which is
written when the lease is *granted* — does not exist. The 232 s is the wait
the log and the daemon's queue show, and it is a lower bound.

The same measurement script (`docs/lab/night-v4-scripts/measure.py`) on run
D, which is the diff baseline:

| | run D (night-v3, 2026-11-01 06:06 → 08:39) |
|---|---|
| wall | **152.61 min** |
| GPU-minutes | **25.74** against the 60-minute rail |
| lease | one lease, kind `thor-admit`, peak 40G, **waited 914.9 s**, 100.6 GB free when it came |
| decisions by rung | 12 `judge.verdict` rows: 5 on the local **d1-2B** (mean 0.106 s), 5 on **Jev** (mean 0.220 s), 2 with no author; gates: 2 `escalate`, 2 `surfaced`, 6 with no gate |
| props | **3 kept**, **15 rejected** |
| box | before: load1 63.75, MemAvailable 62.9 GB; after: load1 8.96, MemAvailable 84.5 GB |

### The diffs against run D, on each of the four things

| | run D | night-v4 |
|---|---|---|
| **the judge** | the local **d1-2B** answered every cell; all five decisions escalated to Jev; two surfaced below τ | the **d1-3B** answers, the options in the **neutral order** (the canonical order and the wire's own sorted-by-key order are the same six ids, `neutral: true`), and the routed cell is asked **on this box** at the calibrated τ (0.76, the 3B's own number, `tau_source: calibrated`) |
| **the critic** | the **signed** volume; no picture critic at all | the **occupied** volume (the convex hull: the lantern's 0.027 → **0.326**, a factor of twelve); the prior scores every prop and its ghost gate **cannot fire** on this fit; the **delegate** answers the six class questions on every picture and takes the picture's score down by the model's own probability for the class it flagged |
| **the memory** | one lease for the whole heavy phase, never phased down | the same lease, **phased down to 8 GB** when the heavy phase ends (the heavy services are stopped first), the row carrying the old peak, the new one, the reason and the box's free memory |
| **the props** | the scripted critic | the scripted critic — physag-lite's MuJoCo action check is committed and runs, but it accepts nothing (0 of 7 counted props physics-valid, 0 stable) and the seat's tree still carries uncommitted work on the same files |

The numbers that belong to the night itself — wall time, GPU-minutes, the
lease wait, the decisions by rung, the props kept and rejected — are not
here, because the night never got past its lease. The measurement script
prints them and the diff against run D in one command as soon as it has run:

```
PYTHONPATH=. ~/lm-wt/propmaker-batch/.venv/bin/python \
    docs/lab/night-v4-scripts/measure.py \
    --night artifacts/night-v4 --against ~/lm-wt/night-v3/artifacts/night-v3-d
```

## 7. The morning's letter

The letter is at `artifacts/night-v4/letter.md`, written by
`docs/lab/night-v4-scripts/write_letter.py` (which refuses to write over 150
words and prints the count). **121 words.** It is written from the receipts
this section names: the pre-run smoke's transcript and the night's own log
head, transcribed into `docs/lab/night-v4-scripts/letter-facts.json`, which
names the receipt behind each block. It is **not** written from a night's
morning — there is no morning — and when the night runs, the same script
writes the letter from the real `morning.json` instead.

> Casey —
>
> The wiring is in and measured: the decision model is the d1-3B now, the options go to it in the neutral order, and the prior and the delegate answer for the props. The night itself did not run — the Thor hung under it at 15:50 and wants a power cycle.
>
> What surprised me: the plausibility prior's ghost gate cannot fire at all — its largest group holds 7 and a group of n cannot score below 0.5/(n+1), so the gate needs ten.
>
> One question for you: should the delegate be allowed to reject a picture outright on the product-picture domain, or keep its vote as it is now — a signal that decides which sibling wins?
>
> The night,

## 8. What it makes possible

- **The night runs, and the seams are exercised together.** The routed
  judge, the neutral order, the prior and the delegate are not four
  changes that each work: they are one night, and the night's own ledger
  carries their rows.
- **A seat can act on two things without waiting for a run.** The prior's
  ghost gate is inert until the library approves **ten objects of one
  kind** — the approved set is what makes a group big enough to express a
  score below 0.05, and the measured real objects are one kind of 38. And
  the delegate's six questions are **render wordings**: on a product
  picture they read a crate's plank gaps as holes (0.51), so a wording for
  the single-object domain is needed before the delegate may reject a
  picture.
- **The night owns its work on the box.** Three of the night's four kills
  were the same mistake in different clothes: work that the box could not
  see belonging to anyone. The lease lock is swept, the render server is
  the night's own child, and a refused connection is a wait. The night can
  now be run by a seat that does not watch the box while it runs.
- **The box's guard is worth its keep, and its rule is worth knowing.** The
  guard stopped another seat's deliberate 32 GB hog while the night's
  render was loading, and it did not touch the night — because the night
  was inside its lease, in the daemon's own accounting, with the memory
  named. The rule is the one the night had to learn: work that no lease
  owns is the guard's business.

## 9. What was not verified

- **Why ComfyUI stopped answering at 17:13:32 is not verified.** The log's
  last write is in the middle of `Remesh DC: 6/31`; the daemon's log has no
  guard or watchdog event against that pid; the journal has no OOM kill and
  no signal. The only thing the box can name is the neighbour: another
  seat's `thor-admit-hog` test was allocating 32 GB at a time in the same
  minutes, and the guard was stopping those hogs while the night's render
  was loading. The night now *waits* for a server that refuses (up to 120 s
  of refusals), which is what a busy server needs; whether the server comes
  back on its own is the box's business and was not observed.
- **The daemon's own numbering is not fixed.** The lock file is named after
  the lease's number, and the numbers start again at 1 when the daemon
  restarts, so a client left over from before a restart can hold the file
  that the next lease of that number will want. The night now clears the
  box before it asks; the tool-side fix — naming the file after the
  daemon's incarnation — belongs to the daemon's crate and was not made
  here.
- **The delegate's questions are still render wordings.** On the prop
  pictures they read a crate's plank gaps as holes; the delegate's vote is
  a signal about which sibling wins the picture round, not a rejection, and
  a wording for the single-object domain is still needed before the
  delegate may reject a picture.
- **The prior was fitted with an empty approved set.** With a non-empty one
  the groups and the floor change, and the gate may fire; the numbers above
  are for the fit the night would actually make.


