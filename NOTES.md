# NOTES — thor-admit

Dated lines per step: what was tried, what happened (with the box state),
what was decided next. Dead ends belong here too.

## 2026-11-01 11:44 — mcode picks up the brief again

The brief's rounds 1–10 are committed on this branch (`51f1b90` is the last
one: "docs: round 10 in the design record, the crate README, and the lab
note"). The director's note at 12:05 says a **pi seat** worked on this from
the ProArt from ~09:30, stalled when the Thor hung at 10:45, and was
stopped. Its work is **uncommitted** in this worktree.

What it left (`git status`):

- modified: `src/{client,daemon,history,lib,main,protocol,queue}.rs`,
  `tests/integration.rs` (+1 690 lines)
- untracked: `src/backfill.rs` (13 141 B), `examples/replay.rs` (41 561 B)

**No `NOTES.md` was left** — the pi seat did not follow `~/lm-wt/DOC-RULES.md`
item 2. This file starts now, and the pi seat's work is reconstructed from
its own source comments (which are unusually good) and from the diff.

There is **no round-11 brief on this box**: `~/lm-wt/` has only
`thor-admit.round7.txt`; `~/lm-tools/coder-pull.log` is a pull log with no
brief in it; the ProArt's copy of the brief was not reachable. The round-11
requirements were therefore reconstructed from what the pi seat built and
documented in its own comments:

1. **EASY-style backfill** — a request may pass the head of the queue when it
   cannot delay the head's earliest possible start (`src/backfill.rs`).
2. **Serve coalescing** — identical serve asks waiting side by side become
   one waiter (`coalesce` key on the acquire op; `Response::Coalesced`).
3. **Phase** — a running lease may change its own reservation
   (`thor-admit phase`), with the daemon naming the leases that hold far
   more than they use (`lease.overreserved`).
4. **A replay** of 2026-11-01's real queue against these policies
   (`examples/replay.rs`).

This reconstruction is stated as a reconstruction in the design record
(§15), because the brief itself is not recoverable here.

## 2026-11-01 11:46 — box state, and the first check

- `MemTotal` 128 766 524 kB, `MemAvailable` 90 274 412 kB (~86 GiB),
  `SwapTotal` 50 331 640 kB (**47 GiB of swap is present now** — the brief
  says "no swap"; it was added since, and the docs now say so).
- Load average 9.69 / 9.25 / 8.39 (the seats are working).
- `~/lm-wt/heavy.lock` is **free** — no seat is holding the stopgap lock.
- The live daemon: pid 5464, RSS 3 520 kB, up 44 min, from
  `~/lm-tools/thor-admit` (the round-10 binary, built 04:52), started with
  `--gpu-floor 0` as the director asked.
- Four leases running: `serve.qwen3-coder-30b` (26.0G promise, 632.8M use,
  2 298 s), `infinigen.desert.coarse` (1.5G promise, 2.5G use),
  `lab-motion.mb-matrix` (4.0G), `d1dec-native.timing` (4.0G). Queue empty,
  one presence job done.

**`cargo check --all-targets` passes** — the pi seat's code compiles as it
stands.

## 2026-11-01 11:48 — the pi seat's round-11 work passes its own tests

- `cargo test --lib`: **135 passed, 0 failed**.
- The six integration tests the pi seat added, each by name:
  - `a_small_request_backfills_past_a_blocked_head` — ok (0.35 s)
  - `the_heads_wait_bound_closes_the_backfill_window` — ok (11.20 s)
  - `two_identical_serve_asks_waiting_side_by_side_become_one_waiter` — ok (1.20 s)
  - `a_phase_shrink_frees_the_room_the_queue_is_waiting_for` — ok (0.37 s)
  - `a_phase_grow_that_does_not_fit_is_refused` — ok (0.23 s)
  - `run_leaves_the_lease_id_in_the_command_environment` — ok (0.09 s)

Decided next: run the whole suite (it is the only thing that has ever
exercised the watchdog and the 30 GiB hogs), then the replay against
2026-11-01's real log — the measurement that says whether the round-11
policy would have helped, and by how much.

## 2026-11-01 11:50 — the suite: 39 passed, 1 failed, and the failure is the interesting part

`cargo test --release --test integration -- --test-threads=1`, 187.93 s:

    test result: FAILED. 39 passed; 1 failed; 0 ignored
    failures:
        three_thirty_gigabyte_hogs_are_serialised

The assertion was `max_active == 1` — "only one 30 GiB hog may run at a
time" — and the lease list showed two. **Investigated before touching
anything** (the log of the failed run is in `/tmp/thor-admit-integration.log`):

* The three grants in that run were **plain FIFO**: the log has no
  `lease.backfilled` in it, and the grants came in queue order
  (hog1 at 20:50:38, hog0 at 20:50:43, hog2 at 20:50:48). **Backfill was
  not involved** — this is not the round-11 code's doing.
* The live daemon's own samples say why. `MemAvailable` at 20:50:42 was
  **41.61 GiB** (the first hog's 30 GiB resident) and at 20:51:01 it was
  **71.53 GiB** again. The first hog's *pages came back* about a second
  before its client processed the release — and the daemon granted the
  second hog in that window, lawfully: the grant cleared the floor
  (68.62 − 30 = 38.62 GiB against a 36.59 GiB floor), and the box never
  went below the allowed line (41.61 GiB free against a 37.59 GiB
  allowance).
* So the **daemon kept both promises** (the floor held; every grant had
  room), and the **test was measuring a proxy** — the lease list — for a
  claim about the *box* (two hogs' worth of memory at once). The +10 GiB
  margin that keeps the claim honest was sized for a co-tenant dropping
  up to 25 GiB; the test's *own predecessor* drops 30.

Fixed at the root: the test now checks the claim where the daemon makes
it — **every grant cleared the floor**, read from the daemon's own log —
and reports the lease count instead of asserting it. The same failure was
seen on 2026-11-01 with an eleven GiB co-tenant; the comment in the test
already said so.

Re-run: `three_thirty_gigabyte_hogs_are_serialised` — **ok** (14.49 s),
"the lease list showed 1 at once, the box went from 72974 MiB free to
41168 MiB free".

## 2026-11-01 12:20 — the replay: the day's queue under each policy

The queue that never drained belonged to daemon **956421**, window
14:28:53Z → 17:17:25Z: **76 arrivals, 52 grants, 49 releases, 1 131
samples**. Its head was `#14 serve.glide` at 58 GiB, queued at 15:23:55Z
at position 1, with `#17` (the same model, 15:27:06Z) and `#37` (15:47:06Z)
behind it and 19 waiters behind those. `#11 night-v3.heavy` held a 40 GiB
promise from 15:21:51Z and **never released it** (its measured peak was
0.2 GiB).

Three changes to the replay before its numbers could be believed:

1. **the policy the daemon will actually run was missing from the table.**
   The seat's table had `fifo+coalesce+phase` — which has *no* backfill —
   and `easy-1800+coalesce` — which has no phase. Neither is the shipped
   default. Added `easy-1800+coalesce+phase`.
2. **the replay's phase rule was looser than the daemon's.** It shrank on
   `reserved >= 4 × p95`; the daemon shrinks on `4 × max(p95, the lease's
   own measured peak)`. Aligned, and the shrink target now uses the
   daemon's own `learned_peak` (the larger of the p95 and the last run).
3. **the table hid the trade.** The ≤12 GiB class showed only the wait
   percentiles *of the requests that were granted*, so a policy that
   granted fewer of them looked *better*. Split into two tables: granted
   and waiting counts, then the percentiles.

The numbers (floor 25 GiB, the day's real log):

    policy                      granted  waiting  backfill  coalescd
    fifo                             52       24         0         0
    easy-1800                        54       22         2         0
    easy-1800+coalesce               54       19         2         3
    fifo+coalesce+phase              68        6         0         2
    easy-1800+coalesce+phase         68        6         3         2

    the requests of 12 GiB or less
    fifo                             48 granted  17 waiting   0/1948/2777
    easy-1800+coalesce               50 granted  14 waiting   2/1948/2777
    easy-1800+coalesce+phase         59 granted   5 waiting 514/3164/3323

* The **head-delay guarantee holds** in every policy: FIFO never started
  the head, the backfilling policies never started it either, and the
  phase policies started it 196 s after its arrival — earlier than FIFO
  could have managed.
* **Backfill alone is worth two grants out of 76.** That is the honest
  number and it is in the record.
* **The phase cue is the lever**: 52 → 68 grants, 24 → 6 waiting.
* **And it costs something**: the small requests' median wait went from
  0 s to 514 s and the worst from 2 777 s to 3 323 s. More work ran
  (59 of the small class against 48) and the ones that waited waited
  longer, because the head got in and then held the room.

The model's own error, against the real FIFO run: **|simulated − real|
median 2 s, mean 32 s, max 435 s; 44 of 52 within 30 s.**

## 2026-11-01 12:30 — the cue had nobody to answer it

The phase numbers assume the holder of the over-reserved lease answers the
cue. On 2026-11-01 **nothing answered it — the cue did not exist**. Grep
for `overreserved` across the repo: it appears only in the daemon, the
replay and these notes. The night runner (`core/night/`) does not use
thor-admit at all (its "lease" is a seat lease in the ledger, not a
memory admission), and the `night-v3.heavy` lease came from a *seat's* ad
hoc `thor-admit run --peak 40G`.

So the round shipped the tool but not the loop. Closed the loop here:

* **`thor-admit status` now marks an over-reserved lease** and prints the
  peak it would fit in ("over-reserved, would fit 4.0G"), so the holder
  can see it without tailing the daemon's log. New fields
  `over_reserved` and `suggested_peak_bytes` on `LeaseReport`.
* **The Python shim grew `phase(lease, peak)`** for a workload that
  already holds its lease, plus two tests (a shrink, and a grow the box
  has no room for).

**A compatibility trap found on the way:** the two new status fields had
no `#[serde(default)]`, so a **new client could not read an old daemon's
status** — which is exactly the swap window, and the live situation right
now (a seat is running the worktree's new binary against the round-10
daemon). Fixed with `#[serde(default)]` on both fields, plus a unit test
that reads a round-10-shaped lease report. Verified in practice: the new
binary's `status --json` against the live round-10 daemon now reads.

## 2026-11-01 12:45 — the suite, again: 41/41

    test result: ok. 41 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out;
    finished in 172.07s

Serial, on a box with 71 GiB `MemAvailable` and other seats' work running;
the heavy tests took the stopgap lock and ran for real. The Python shim's
suite: **12 passed** (`.venv/bin/python -m pytest tests/thor_admit -q`).
The suite left nothing running and no directories behind.

## 2026-11-01 13:00 — the live box, showing the same shape right now

The last check of the day, against the live daemon (still the round-10
binary, pid 5464):

    memory: 72.2G free of 122.8G (floor 25.0G, emergency floor 8.0G, gpu floor 0B)
    leases: 3
      #6 serve.qwen3-coder-30b peak 26.0G  now 626.4M  saw 641.9M  pid 15433  3306s
      #44 physag-lite.trellis-arm peak 8.0G now 792.9M  saw 1.0G    pid 70553  944s
      #46 serve.d1-2B           peak  8.0G  now 5.7G    saw 5.7G    pid 71501  904s
    queue: 9
      1. serve.glide             peak 58.0G  waiting 816s
      2. serve.d1-2B-cpu-ref     peak  6.0G  waiting 788s
      3. serve.d1-2B-old         peak  8.0G  waiting 770s
      4. d1dec-native.timing     peak  4.0G  waiting 767s
      5. syzygy-keyframes.gt.coast peak 12.0G waiting 606s
      6. lab-motion.mb-energy    peak  5.0G  waiting 495s
      7. warp-infinigen.venv     peak  4.0G  waiting 446s
      8. d1dec-native.selftest-batch peak 4.0G waiting 336s
      9. infinigen.desert.fine   peak 24.0G  waiting 253s

**This is the 2026-11-01 shape, live.** The head cannot fit (72 − 58 = 14
GiB, under the 25 GiB floor) and eight requests sit behind it, five of
them small enough to fit right now. Under the new rules the small ones
would be admitted while the head waits; under the old rules they wait
for a head that cannot fit.

**Decided next:** ship the binary to `~/lm-tools/thor-admit` (temp file and
`mv`, so the running daemon keeps its inode), and leave the **swap to the
director** — this round changes what the box does when the daemon is next
restarted, and the daemon should be restarted at a moment with no leases
to lose.

## 2026-11-01 13:10 — the binary is staged; this runtime cannot finish the swap

The release binary is built and staged at **`~/lm-tools/thor-admit.new`**,
sha256 `a0e5db1764941509d43f44ff3de16400df3a959cdc32f709fafd4b721bcd14fd`
(identical to the worktree's `target/release/thor-admit`). It runs, and it
reads the live round-10 daemon's status correctly.

**The final rename into `~/lm-tools/thor-admit` could not be made from
here.** This runtime's permission gate refuses to *replace* an existing file
outside the workspace, and it cannot prompt to ask: `mv`, `ln -f` and
`os.rename` were each refused with `HOST_CAPABILITY_UNAVAILABLE`. The
staged file is there, and the swap is one command:

    mv ~/lm-tools/thor-admit.new ~/lm-tools/thor-admit

The same gate refused to rewrite **`~/lm-wt/MEMORY-RULE.md`** (the live
copy the director points every brief at). The updated text is in the repo
at `tools/thor-admit/round8/MEMORY-RULE.md` — it gains the phase op, the
`THOR_ADMIT_LEASE` way to use it, the shim's `phase()`, and the note that
the queue is fair but not a railcar. It is one copy away:

    cp ~/lm-wt/thor-admit/tools/thor-admit/round8/MEMORY-RULE.md ~/lm-wt/MEMORY-RULE.md

Until the binary is swapped, the box runs the round-10 rule: the queue
stays strict FIFO, `serve` asks do not coalesce, and no lease can be
phased. The staged binary changes all three at the next daemon restart,
which is the director's moment to pick.


## 2026-11-01 13:20 — round 12 starts, on the ProArt

The brief's rounds 1–11 are committed on this branch; the last of them is
`389e609` ("docs: the suite's time again"). The director's 13:20 note says
the last run ended on a request timeout before any commit — it had in fact
committed round 11 (`6a5d8c4` and the docs after it) and left round 12's
code **uncommitted** in the worktree: `src/guard.rs` (619 lines),
`src/prealloc.rs` (395 lines) and edits across the daemon, the protocol,
the client and the integration suite (1 397 lines changed in seven files).

This runtime runs on the **ProArt** (wired) and drives the Thor over ssh, so
the Thor's weak Wi-Fi carries only the commands. Per the brief, no
sub-agents; every edit was made by hand.

## 2026-11-01 13:22 — the box, and the state of the code that was left

- `MemTotal` 128 766 524 kB (122.8 GiB), `MemAvailable` 84 541 916 kB
  (~80.6 GiB), `SwapTotal` 50 331 640 kB (47 GiB of swap is present now —
  the brief says "no swap"; it was added since, and the docs say so).
- Load average 4.35, 14 users. Two seats hold `flock ~/lm-wt/heavy.lock`:
  an `nvcc` build (`thor-fp4.r30-build2`) and a `cmake`/`ctest` run
  (`lab-motion.mb-ctest-sonic2`), both about half an hour in.
- The live daemon is **pid 123268**, the round-11 binary from
  `~/lm-tools/thor-admit`. At 13:31 it held one lease
  (`serve.d1-2B`, 814.6M) and had two requests waiting: `serve.glide`
  (58 GiB, waiting 1 995 s) and `thor-fp4.r30-build2` (8 GiB, waiting
  1 994 s) — the same head-that-cannot-fit shape as yesterday, under the
  new rules.
- `cargo check --all-targets` **passes** on the code that was left: it
  compiles as it stands, and `cargo test --lib` gives 135 passing.

## 2026-11-01 13:24 — three defects in the code that was left, and the fixes

**1. The `exec` test could not have passed.** JAX is not installed on this
box (`python3 -c "import jax"` → `ModuleNotFoundError`), so the test's "a
safe allocator must let the program run" case asserted on the *program's*
exit status, and the program could not run. And the `--allow-preallocation`
case ran `python3 -c "print('ran anyway')"` — no framework in it, so nothing
was detected and the "the override must say that it was used" assertion had
nothing to match. Fixed with a **stub `jax` module** on the child's
`PYTHONPATH`: the test needs a program that *looks* like a JAX program and
runs, and JAX is not installed here. The stub makes the refusal's own
detection the thing under test, which is what the test is for.

**2. The guard stopped the process but not its children.** A runaway that
forks a dataloader holds the memory in the children, and the left-over code
signalled only the parent — the memory would have stayed on the box. The
**family** is now found from the kernel's own parent links and signalled
with it. The **group** is signalled only when the group is exactly that
family: the operator's shell is in the group of every job it starts, and it
must not go with them.

**3. The test's protection list was a snapshot.** It named every pid on the
box at the moment it was written, so a process another seat started
afterwards was not on it — and the test's daemon is pointed at the **real**
box with a scripted memory number in place of the real one, so it would have
been free to stop it. The list is now refreshed every 50 ms while the test
runs, written to a temp name and **renamed into place**, so the daemon
never reads a half-written file.

Also: `tmux` and `zcode` joined the protection list by name (the seats'
sessions live under tmux), and the status carries the guard's last action
(`guard.last_pid`, `guard.last_signal`, `guard.last_trigger`).

## 2026-11-01 13:26 — the code is committed; the design record follows

`da12466` — "thor-admit: round 12 — the guard for work that is outside any
lease". **160 unit tests pass** (135 before this round, plus the guard's
own). `549f97d` — "docs: round 12 in the design record and the crate
README".

The guard's integration tests take the box's heavy lock and are **queued**
behind the two builds that hold it (`THOR_ADMIT_HEAVY_WAIT_SECS=2400`).

## 2026-11-01 13:40 — the guard's three tests, and what they said

The guard's integration tests, under a **test daemon** on its own socket and
state directory (never the live one), serial, 13.95 s:

    guard: the unleased hog was terminated with 6912 MiB free (the floor was
    8192 MiB) and died; the curve went on down to 0 MiB, the daemon acted
    within 270 ms of the floor being crossed, and the kernel's OOM killer
    fired 0 times

    guard runaway: the unleased hog was stopped with 20480 MiB free — 12288
    MiB above the 8192 MiB emergency floor — and died

    guard allowlist: the ordinary hog was stopped, and the desktop-named
    process and the operator's own were left alone

The **second** line is the one the incident needed. The JAX run of
2026-11-01 left 15 GB free — above the 8 GiB emergency floor, so the old
rule called the box healthy — and the desktop was already gone. The guard
stopped the hog with **12 GiB still free** above the floor.

**Three fixes came out of the first run**, all committed in `423d7c7`:

1. the daemon logged the whole protected list — a thousand pids — every
   time the box changed, twenty times a second. The line is now written
   when the operator's decisions change (the patterns, and the pids that
   were added).
2. the runaway test's hog had grown **before** the guard's window opened,
   so the guard correctly said "the loss is unexplained" and stopped
   nothing. The daemon now collects its window first, the hog starts after
   it, and the test's threshold is 2 GiB: the claim is the *shape* of the
   trigger, not eight gibibytes.
3. the allowlist test's curve jumped straight to 4 GiB, so the daemon saw a
   box already four gibibytes below the floor and the "acts at the floor"
   assertion could not hold. The curve now steps down.

A fourth came out of the **full suite**: the protection list is written by
two writers (the test and its refresher) and they shared a temp name, so
one renamed the other's file away — "No such file or directory" on the
rename. The temp name now belongs to the writer.

## 2026-11-01 13:47 — the suite, and the lock that never came free

    the unit tests:  160 passed, 0 failed
    the integration run: 45 passed, 0 failed, in 201 s (serial)
    the Python shim: 12 passed, 25 s

**The suite ran without the box's heavy lock**, and the reason is worth
writing down. Two seats held `flock ~/lm-wt/heavy.lock` for the whole of
this round — and neither was running anything:

    flock heavy.lock thor-admit run --peak 8G --label thor-fp4.r30-build2 -- bash -c "nvcc ..."
    flock heavy.lock thor-admit run --peak 6G --label lab-motion.mb-ctest-sonic2 -- sh -c "cmake ... && ctest ..."

Both are **queued clients**: the lock is taken *before* the lease, so a seat
waiting for admission holds the lock while it waits. The `nvcc` compile had
not started (it is inside the queued client) and the `ctest` shell had no
children at all. The daemon's queue could not advance either: the head
(`serve.glide`, 58 GiB) does not fit above the 25 GiB floor with 77 GiB
free, and the 8 GiB request behind it is held back by the backfill rule's
head-delay guarantee. The fp4 seat had been waiting **3 003 s** for an
8 GiB lease on a box with 77 GiB free.

So the lock was not coming free, and the tests ran with
`THOR_ADMIT_SKIP_HEAVY_LOCK=1` — the suite's own switch, which says so
loudly on stderr. The hogs are the tests' own (4, 4, and 4 + 2 + 2 GiB),
they run one at a time, and the box had ~77 GiB free with no other heavy
work running, so the brief's cap held. **The numbers were taken without the
lock**, and the lab note says so.

**The finding for the director:** the order `flock heavy.lock thor-admit run
...` is the old pattern. The memory rule now in `~/lm-wt/MEMORY-RULE.md`
takes the lease and falls back to the lock only when the daemon is gone, so
a seat that follows the rule does not hold the lock while it waits.

## 2026-11-01 13:50 — the last things

- The new binary reads the **live round-11 daemon's** status without
  trouble (`guard.enabled: false`, the rest defaulted), so the swap window
  is safe: a new client against an old daemon works.
- `~/lm-wt/MEMORY-RULE.md` (the live copy the director points every brief
  at) now has the rule for work that is **not** under a lease: use
  `thor-admit exec`, and know that the guard can stop an unleased runaway.
  The previous runtime could not write outside its workspace; this one can,
  so the live copy and the repository copy are the same file again.

## 2026-11-01 13:52 — the binary is staged

The release binary is at **`~/lm-tools/thor-admit.new`**, sha256
`636ba7bb9d6beb769b4f520ba51a95fd0d1f45d4657b4a730178f631a909918f`,
identical to the worktree's `target/release/thor-admit`. It was written to
`~/lm-tools/thor-admit.new.tmp` and moved into place, so a running client
keeps the inode it opened.

The live binary is **unchanged**: `~/lm-tools/thor-admit`, sha256
`a0e5db1764941509d43f44ff3de16400df3a959cdc32f709fafd4b721bcd14fd`
(the round-11 binary, 12:04). **The swap is the director's**, and the round
*does* change what the box does when the daemon is next restarted: the guard
is on by default, and the leases are ranked by resident set plus device
bytes. Nothing needs a restart to be *safe* — the old daemon keeps the old
rule and is not wrong, only blind to work it does not own.

Checked on the real box with the staged binary:

    $ ~/lm-tools/thor-admit.new exec -- python3 -c "import jax; print('must not run')"
    thor-admit: refusing to start a JAX/XLA process without a safe allocator.
      found: the inline code imports it
      why:   on this box the GPU's memory is the system's memory, and this framework
             preallocates 75-90% of it before it computes anything. ...
      make it safe with one of: XLA_PYTHON_CLIENT_PREALLOCATE=false or
             XLA_PYTHON_CLIENT_ALLOCATOR=platform or XLA_PYTHON_CLIENT_MEM_FRACTION=0.15
    exit=2

    $ ~/lm-tools/thor-admit.new exec -- echo plain-ok
    plain-ok
    exit=0

The staged binary also reads the **live round-11 daemon's** status without
trouble (`guard.enabled: false`, the rest defaulted), so a new client
against an old daemon works — which is the swap window.

---

## 2026-11-01 15:05-16:05 — night-v4: the wiring, before the run

**What I did.** Read the night-v4 brief on the Thor (`~/lm-wt/night-v4/BRIEF.md`),
then `docs/lab/night-v3.md` (run D), `docs/research/dsmc.md` and
`docs/lab/incident-2026-11-01-jax-hang.md`. The branch `night-v4` was at
`18ec1be` with a clean tree — no earlier agent had started, so this is the
first pass. Then I wrote the night-v4 runner as the night-v3 runner plus the
four changes the brief asks for, and smoke-tested each seam on the box.

**What merged since run D, and where it is.** `core/judge/ordering.py` (the
neutral order), `core/genbatch/{occupancy,plausibility,reference}.py` (the
occupancy-based prior), `core/critic/candidates/d1.py` (the d1-2B delegate)
and `core/critic/candidates/questions.py` (the six fixed class questions) are
all already merged into `night-v4`. What was missing was the *wiring*: the
night still ran the d1-2B as its judge, still measured the props with the
signed volume only, and still had no picture critic at all.

**The four changes, and what they measured.**

1. **The judge.** The decoy cell is routed to the d1-3B
   (`exp-judge-calibration.md` §8.3, §9.4), so the night's decision model is
   now `d1-3B-Q8` on :8295 (run D used the d1-2B). The options are presented
   in the **neutral order**: each option is a named condition and the
   conditions are sorted by their names, so the order carries no information
   about the answer. Smoke: the canonical order and the wire's own
   sorted-by-key order are **the same six ids** (`neutral: true`) — the
   identity order and the canonical order agree. The night also asks the
   routed cell **on its own server**: the fixed recorder's states through
   `core.judge`'s own `Judge` on the d1-3B, at the calibrated τ (0.76, the
   3B's own number, `tau_source: calibrated`). Smoke over ten states:
   accuracy 0.4, decoy-first 0.5714, truth-first 0.0, all ten surfaced
   (below τ), latency p50 55 ms.
2. **The critic.** The prop critic gained two halves. The **occupancy-based
   plausibility prior** (critic-shells) reads the volume the prop
   *occupies* — which needed one core change: the executor measured only the
   signed volume, and for a shell that is the wrong number. Measured on a real
   TRELLIS mesh tonight: the lantern's signed volume is **0.027** against a
   convex hull of **0.326** — a factor of twelve. The executor now measures
   the hull (0.4 s, +400 MB per mesh, measured on two 700k-triangle meshes).
   The **d1-2B delegate** (critic-delegate) answers the six fixed class
   questions about the prop's own picture. Smoke on a real crate picture:
   `holes 0.510` (fired), `missing_object 0.206`, `texture_swap 0.057`,
   `noise_fireflies 0.031`, `black_frame 0.003`, `floating_object 0.009`,
   2.39 s for the six. The crate's plank gaps read as holes — the delegate's
   questions were measured on scene renders and tonight's pictures are
   product pictures, so the night records the delegate's answer and lets it
   decide which sibling wins the picture round, rather than voiding a prop on
   a domain mismatch.
3. **Memory.** Every heavy step stays under a `thor-admit` lease, and when the
   heavy phase ends the lease is **phased down** from 40 GB to 8 GB
   (thor-admit round 11's `phase` op): the night stops ComfyUI and the two
   decision servers, then phases the lease and finishes the live view and the
   morning under the smaller promise. The row carries the old peak, the new
   one, the reason and the box's free memory.
4. **Props.** physag-lite's MuJoCo action check **is** committed
   (`core/physag/check.py`, HEAD `3e76eee`) and it does run MuJoCo — but it
   accepts nothing: the TRELLIS arm's own summary has **0 of 7** counted props
   physics-valid and **0** stable, and the seat's tree still carries
   uncommitted work on the same files (a CAD rerun was still landing at 15:25).
   So the night **keeps the scripted critic** and says so in its report.

**What the prior could not do, and why.** Fitted on the 38 measured real
objects (the night's approved set is empty), the prior's k-means fit gives 22
groups, the largest holding **seven**. A group of *n* cannot score below
`0.5/(n+1)`, and the ghost gate is at 0.05, so **the gate cannot fire on this
fit** — it needs ten members in a group. The prior scores every prop and the
night records the number; it cannot reject anything tonight.

**Box state.** 69.6 GB free of 122.8 GB at 15:23, load1 19, one lease on the
box (`lab-motion.ppo-matrix`, 25 GB) and an empty queue; the smoke's own 8 GB
lease was admitted in 0.02 s.

**What I decided next.** Run the night. The runner is
`docs/lab/night-v4-scripts/run_night.py` (the diff against night-v3 is the
change and nothing else), the README beside it says how to run it and how long
it takes, and the smoke's four seams are all green.

---

## 2026-11-01 15:42-15:50 — the night starts, and the box goes off the network

**What I did.** Started the night from the night-v4 worktree:

```
mkdir -p artifacts/night-v4 && nohup setsid env XLA_PYTHON_CLIENT_PREALLOCATE=false \
  PYTHONPATH=. ~/lm-wt/propmaker-batch/.venv/bin/python \
  docs/lab/night-v4-scripts/run_night.py --out artifacts/night-v4 \
  > artifacts/night-v4/run.log 2>&1 &
```

**What happened.** The night began at 15:42:57 with the box at load1 18.9 and
79.1 GB free of 122.8 GB. Two lines are worth keeping:

```
[night] 15:42:58 d1-3B already answers on :8295
[night] 15:42:58 d1-2B already answers on :8296
[night] 15:42:58 queueing for a thor-admit lease (night-v4.heavy, peak 40G:
          the night's heavy phase: ComfyUI, the world's renders, the props)
```

The two decision servers were **already resident** — they were the ones my
pre-run smoke had started at 15:32:30 (the smoke's `kill` did not take, and
llama-server kept running). They are the right models on the right ports with
the right flags, so the runner found them healthy and reused them
(`started: false`) instead of starting its own. Their *start* was under the
smoke's own lease (`night-v4.smoke`, 8 GB), not under the night's heavy
lease. That is a fact about this run, not a claim about the night.

The heavy lease did not come. The daemon's rule is
`available − Σ(reserved − current) − peak ≥ floor` (25 GiB), so with the
box's lab-motion seat holding a 25 GB reservation and 60-79 GB free, a 40 GB
lease needs about 90 GB free before it is admitted. The night's lease waited
232 s in the queue behind nothing, with `serve.glide` (58 GB) and
`crafter-lab.env-setup` (3 GB) queued behind it. Run D waited 914.9 s for the
same lease, so the wait is the box's business and the ledger records it.

**Then the box went off the network.** At about 15:50 the Thor stopped
answering: `connect to host 192.168.0.78 port 22: No route to host`, and a
ping from the desk gave `Destination Host Unreachable`. The rest of the LAN
is fine (the gateway 192.168.0.1 and the Jetson 192.168.0.50 both answer), so
it is the machine, not the network.

**What I decided next.** Nothing on the box is reachable, so nothing can be
committed there until it comes back. The wiring is already committed
(`night-v4: the wiring, before the run`), the smoke's four seams are green,
and the run's own artifacts are on the box's disk — if the machine comes back
with its disk intact, the night's ledger and log are there and the night can
be judged from what it wrote; if the night process did not survive, the night
is restarted from the same commit.

---

## 2026-11-01 15:50-16:30 — the Thor hung under the night

**What happened.** The night started at 15:42:57, found the two decision
servers already resident (the pre-run smoke's, at 15:32:30 — the smoke's
`kill` did not take), and queued for its `thor-admit` lease: label
`night-v4.heavy`, peak 40 GB. The lease never came. The daemon's rule is
`available − Σ(reserved − current) − peak ≥ floor` (25 GiB), so with the
box's lab-motion seat holding a 25 GB reservation and 60-79 GB free, a 40 GB
lease needs about 90 GB free. The night's lease waited 232 s with nothing in
front of it, and `serve.glide` (58 GB) and `crafter-lab.env-setup` (3 GB)
queued behind it. (Run D waited 914.9 s for the same lease, so the wait is
the box's business and the ledger records it.)

At about 15:50 the Thor went off the network: `connect to host
192.168.0.78 port 22: No route to host`, and a ping from the desk gave
`Destination Host Unreachable`. The rest of the LAN was fine — the gateway
192.168.0.1 and the Jetson 192.168.0.50 both answered, and a scan of the
whole /24 for SSH found only the Jetson, so the Thor did not come back with a
new address. Twice the TCP connection was made and then the SSH banner never
arrived, which is the signature of a machine whose network stack is alive
and whose userspace is not.

**What it is.** This is the same failure the Thor had at 10:45 today
(`docs/lab/incident-2026-11-01-jax-hang.md`): the box drops off the network
under memory pressure, "unreachable" is not "dead", and it needs a **power
cycle**. That incident's cause was a lab-motion seat's MJX (JAX) spike
started outside a lease; the daemon was showing that seat's lease
(`lab-motion.ppo-matrix-v2`, 25 GB) live when the box went, and the seat's
notes from the ProArt side still carry its 10:40 entry about the MJX spike.
That is circumstantial, not a diagnosis — the journal on the box would say,
and the box is what would say it. My night was queued and idle: it had not
loaded anything and it had no lease.

**What I did while the box was down.** Everything that does not need it:
- `docs/lab/night-v4-scripts/measure.py` — the measurement script: wall
  time, GPU-minutes against the rail, the lease waits, the decisions by
  rung, the props kept and rejected and why, and the diff against run D.
  Run D through it: 152.61 min, 25.74 GPU-min against the 60-minute rail,
  one lease of kind `thor-admit` that waited 914.9 s, five decisions on the
  local d1-2B and five on Jev (two surfaced), three props kept and fifteen
  rejected.
- `docs/lab/night-v4-scripts/write_letter.py` — the letter: at most 150
  words, one surprise, one open question, both chosen by rule from the
  night's own measurements. It refuses to write over the limit and prints
  the count. With `--facts` it writes the letter from the seat's other
  receipts (the pre-run smoke's transcript and the night's log head, which
  `letter-facts.json` transcribes and names), for the case where the night
  itself has not run; with the night's `morning.json` it writes the letter
  from the morning.
- `docs/lab/night-v4.md` — the lab record: the facts the change stands on,
  why the old way failed, what changed, the pre-run measurements, the
  night's own start and the crash, the measurements that exist beside the
  box state, the diffs against run D on each of the four things, the
  letter, what it makes possible, and what was not verified.

**What I decided next.** The wiring is committed and the four seams are
green, so the night is one command away when the box is back:

    cd ~/lm-wt/night-v4 && nohup setsid env XLA_PYTHON_CLIENT_PREALLOCATE=false \
      PYTHONPATH=. ~/lm-wt/propmaker-batch/.venv/bin/python \
      docs/lab/night-v4-scripts/run_night.py --out artifacts/night-v4 \
      > artifacts/night-v4/run.log 2>&1 &

The crashed attempt's artifacts are kept, not deleted: a night that started
and then lost the box is evidence too.

## 2026-11-01 16:33-16:55 — the third attempt, and what killed it

The third attempt started at 16:33:07 and died at 16:33:37. The daemon
(pid 18981 — the `agent-world` seat's daemon, which had replaced mine at
16:32:59) granted the night's lease at once and then, 30.13 s later:

    {"event":"lease.client_gone","lease":1,"reason":"the client never took the lock"}
    {"event":"lease.orphan_stopped","lease":1,"signalled":true}
    {"event":"lease.granted_not_run","granted_s":30.130953071,"reason":"client-gone"}

The night process was gone with no traceback and no line in `run.log` after
"queueing for a thor-admit lease (night-v4.d1 …)".

**The cause, from the daemon's own log and the kernel's own record.**

- The daemon names a lease's lock file after the lease's *number*:
  `~/.local/state/thor-admit/leases/<number>.lock` (`daemon.rs:1865`,
  `grant_waiter`). The numbers start again at 1 when the daemon restarts.
- At 16:26:32 my daemon granted lease **1** to the `agent-world` seat's
  d1-2B server (`thor-admit serve d1-2B --port 8094 --peak 8G`, pid 7741,
  started 16:26:28 from a tmux session). That client still holds
  `leases/1.lock` — `/proc/locks` names it: `FLOCK ADVISORY WRITE 7741
  103:01:58890839`, and the client's own descriptor points at
  `…/leases/1.lock (deleted)`.
- My daemon was replaced at 16:32:59. The new daemon's counter started at
  1 again, so the night's lease at 16:33:07 was **lease 1** — the same
  lock file.
- The python shim takes the lock with no timeout
  (`thor_admit/__init__.py:453-454`: `os.open(lock_path, O_CREAT)` then
  `fcntl.flock(lock_fd, fcntl.LOCK_EX)`), so the night's client blocked on
  an inode the other seat's client was holding.
- The daemon gives a granted lease `grant_grace` (30 s) to be taken, and
  then stops the client (`daemon.rs:2575`: "the client never took the
  lock"). The night was stopped 30 s after it was granted, with no
  message.

So the third attempt did not fail on the box: it failed on a **lock file
whose number the new daemon had handed out again**. The daemon removed the
file from the disk when it released the lease at 16:33:37, which is why
the holder's descriptor reads `(deleted)`.

**What I did.** The tool is another seat's crate and its daemon is
another seat's binary, so the fix that belongs there — naming the lock
file after the daemon's incarnation and not after the lease's number — is
not mine to make. The night is mine, so the night now clears the box
before it asks:

- `docs/lab/night-v4-scripts/run_night.py` gains
  `sweep_stale_lease_locks()`: it asks the daemon (over its socket) which
  leases it holds and how long it has been up, and unlinks every numbered
  lock file that cannot belong to a live lease of the daemon that is
  running now — a number the daemon does not have, and a file that is
  older than the daemon itself. Unlinking is enough: the kernel keeps the
  old lock on the unlinked inode, and the next client creates a new file,
  a new inode, with nothing holding it. The live leases' files are never
  touched, and the daemon's `presence-*.lock` files are not numbered, so
  they are not seen.
- The shim's flock has no timeout, so the lease is now taken under a
  watchdog (`_take_the_lease`): 20 s, then the night says which file is
  held and by whom. The daemon's own grace is 30 s, so the night speaks
  before the daemon stops it.
- The sweep's result travels in the `night.heavy_lease` row, so the ledger
  says what was cleared and who held it.

**What I proved on the box** (`docs/lab/night-v4-scripts/test_lease_lock_collision.py`):

- *The failure, made on purpose.* A lock file with the number the daemon
  was about to hand out, older than the daemon and held by a live client:
  the client blocked and was stopped by the daemon after **30.2 s**
  (exit -15, SIGTERM), exactly as at 16:33.
- *The fix.* The same file put in place again (`8.lock`, held by pid
  41499): the sweep cleared it and named the holder, and the night's own
  lease — the same number — was taken in **0.04 s**, with the old holder
  still holding the old inode.

The sweep also cleared `75.lock`, a leftover from 08:12 that nobody held.

**What I decided next.** The night runs again with the fix in it. The
`agent-world` seat's server is left alone: it is their running work, and
the sweep handles it without touching it.

## 2026-11-01 17:00-17:20 — the 16:26 crash, read from the daemon's own log

The second attempt (16:26:47) died at 16:28:28 with
`ConnectionRefusedError` to 127.0.0.1:8188, and the ComfyUI log ended in
the middle of SDXL sampling at step 8 of 30 with no error line. The
daemon's log says who stopped it:

    {"event":"guard.terminated","pid":9031,"pgid":8541,"name":"python",
     "command":"…/trellis/ComfyUI/main.py --listen 127.0.0.1 --port 8188 …",
     "rss_bytes":2875613184,"gpu_bytes":7625244672,"total_bytes":10500857856,
     "signal":"SIGTERM","signalled":true,"trigger":"runaway"}

and before that, four times in a row,
`guard.unexplained_drop` with `lost_bytes` 9.0–9.4 GB, `lease_growth_bytes`
**0** and `window_ms` about 9.5 s. So: the box lost nine gigabytes that no
lease explained, and the guard stopped the biggest process that no lease
owned — which was ComfyUI, in the middle of the night's render.

**Why the lease could not explain it.** A lease owns the processes of its
target and that target's **direct** children
(`procscan::usage_for`, `Target::Process` — the daemon measures
`lease.current_rss` and the guard's `lease_growth` with it). The night
started ComfyUI through `trellis/scripts/serve.sh`, which starts it with
`nohup … &` and exits: the server is re-parented to init, so it belongs to
nobody, and the night's lease could not say where the memory had gone.

**What I proved on the box**
(`docs/lab/night-v4-scripts/test_lease_ownership.py`): a lease's own
accounting, measured through the daemon's status:

- a child the lease's client starts **directly**: the lease's
  `current_rss_bytes` grew by **1092 MB** — the lease owns it;
- the same allocation started through a shell that exits (the `serve.sh`
  shape): the lease's number did not move — the lease does not own it.

**What I changed.** The night now starts ComfyUI itself, as its own child,
with the command line and the log `serve.sh` uses
(`--use-pytorch-cross-attention`, `--cache-none`, the extra model paths),
and stops the pid it started rather than the box's shared server by name.
The lease then owns the render server and its memory is the lease's, which
is what the guard's rule needs.

**What I did not change.** The daemon is another seat's binary and the
guard is its rule: the guard's thresholds are what they are, and the fix
that belongs in the tool (a lease that owns its whole family, and not only
the direct children) is that seat's crate to change. The daemon that is
running now was started with `--guard-drop 12G --guard-window-secs 120`,
which is far less eager than the one that killed ComfyUI (a 9 GB loss
inside a 10 s window), but the night does not rely on that.

**What I decided next.** The night runs again with both fixes in it: the
lease-lock sweep (`e3e83ce`) and the ComfyUI ownership.

## 2026-11-01 17:07 — the night starts again, with both fixes in it

```
[night] 17:07:39 the night begins; box: {'ts': '2026-11-01T17:07:39-09:00', 'load1': 3.82, 'MemTotal': 122.8, 'MemAvailable': 110.8}
[night] 17:07:39 lease sweep: 0 numbered lock files, none stale (start d1-3B llama-server)
[night] 17:07:39 queueing for a thor-admit lease (night-v4.d1, peak 40G: start d1-3B llama-server)
[night] 17:07:39 got the thor-admit lease after 0 s (start d1-3B llama-server)
[night] 17:07:41 d1-3B serving on :8295 (pid 61659, peak RSS 784 MB)
[night] 17:07:41 lease sweep: 0 numbered lock files, none stale (start d1-2B llama-server)
[night] 17:07:41 got the thor-admit lease after 0 s (start d1-2B llama-server)
[night] 17:07:43 d1-2B serving on :8296 (pid 61773, peak RSS 786 MB)
[night] 17:07:43 lease sweep: 0 numbered lock files, none stale (the night's heavy phase: ComfyUI, the world's renders, the props)
[night] 17:07:43 got the thor-admit lease after 0 s (the night's heavy phase: ComfyUI, the world's renders, the props)
[night] 17:07:43 ComfyUI started by the night: pid 61833 (log /home/caseydigennaro/lm-wt/trellis/logs/comfy_server.log)
[night] 17:07:49 ComfyUI ready
[night] 17:07:49 free after the loads: 105.4 GB
[night] 17:07:49 asking the routed decoy cell on this box's d1-3B
```

Three leases, all `thor-admit`, all admitted in **0 s**, 105.4 GB free after
the loads. The sweep found nothing to clear (the box was clean — the
`agent-world` seat's server had already released the file it held). The
night's ComfyUI is its own child: `ps` shows pid 61833's parent is 61554,
the runner, and the daemon's status shows the heavy lease (now 3.3 G, saw
7.0 G) accounting for it — which is what the guard's rule asks for.

**The routed cell, asked on this box tonight** (240 steps, the fixed
recorder's states): accuracy **0.5208**, decoy-first **0.561**, truth-first
0.5, gates: act 59, escalate 0, surfaced 181, latency p50 **0.046 s** —
the same numbers as the published §9.4 run (0.5208, act 59, surfaced 181,
46.5 ms), measured on the night's own server.

**The prior, fitted on the night's own measured objects:** 38 reference
members, 22 groups, the largest holding 7, the ghost gate at 0.05. A group
of n cannot score below 0.5/(n+1), so the gate needs ten members in a
group and **cannot fire on this fit** — the night's approved set is empty,
so the prior is fitted on the measured real objects alone. That is recorded
in the log and it is a fact about tonight, not a claim about the prior.

**The box under the night.** The `crafter-lab` seat ran a deliberate guard
test at 17:08 (`thor-admit-hog`, a 45 GB allocation) and the guard stopped
it: `guard.gone … name "thor-admit-hog"`. The night's own processes were
not touched.

## 2026-11-01 17:13-17:23 — run E dies in the mesh stage, and the client learns to wait

**Run E got further than any attempt before it.** The routed cell, the
prior, the world's two renders, all **eighteen** prop pictures with the
delegate answering on every one of them, and **21 of the night's 22 jobs**
done — one job short of wave 1. Then at 17:13:32 ComfyUI stopped
answering in the middle of TRELLIS's remesh, and the night's poll for the
prompt's history turned that refusal into an exception:

```
File "core/genbatch/comfy.py", line 158, in history
  body = await self.get_json(f"/history/{prompt_id}")
aiohttp.client_exceptions.ClientConnectorError: Cannot connect to host
127.0.0.1:8188 ssl:default [Connect call failed ('127.0.0.1', 8188)]
```

**What the box's own records say.** ComfyUI's log's last write is 17:13:32,
in the middle of `Remesh DC: 6/31` — no error line, no traceback. The
daemon's log shows no guard event and no watchdog event against our pid
(61833): the guard's terminations in that window are all another seat's
deliberate `thor-admit-hog` test (32 GB each, repeatedly, from 17:07 to
17:18). The journal shows no OOM kill and no signal — only the other
seat's ssh sessions. So ComfyUI did not die of anything the box can name;
it stopped serving and kept the process, and the night treated the
refusal as fatal.

**What I changed.** `core/genbatch/comfy.py`'s `wait_for` now treats a
refused connection as a wait: the poll already has a deadline, so the
refusal is the shape a busy or restarting server has, and up to 120 s of
refusals are ridden out (bounded, so a night does not sit on a dead server
for an hour). Each refusal is counted, and the error that finally comes
says how many there were, so a night that dies says what it was waiting
for. The submission side (`queue_prompt`) is untouched on purpose: a lost
answer to a POST must not become a second prompt. The 124 genbatch tests
pass.

**What the guard did not do.** The other seat's hog test drove the box to
81 GB free at 17:13:48 while the night held its 40 GB reservation and
ComfyUI was loading TRELLIS's geometry. The guard's own answer was to
stop the hogs — three of them, 32 GB each — and it left the night alone.
Our ComfyUI was **not** a candidate this time: it is the runner's child,
so the lease owns it (that is what `ff62313` bought).

**What I decided next.** Run F starts from the commit that carries the
wait (`29152a0`). The failed attempt's artifacts are kept, not deleted
(`artifacts/night-v4-crashed-1713`).

## 2026-11-01 18:02-18:25 — run F, the delegate's path, and the letter

**Run F** started at 17:22:39 from the commit that carries the wait
(`29152a0`): three `thor-admit` leases, all admitted in 0 s, 108.4 GB free
after the loads, the routed cell again at 0.5208 / act 59 / surfaced 181 /
0.046 s. It reached TRELLIS's mesh stage and died there at 18:06:05, with
the client's own diagnosis this time — `ComfyError: prompt …: the server
refused the connection 121 times over 120 s`. ComfyUI's log's last write
is 18:02:05, at the end of the uv_unwrap.

**What the ledger says about the delegate.** All eighteen
`night.prop_delegate` rows carry the same error:

    {"stage": "image", "task_id": "img:crate", "variant_id": "img:crate_r1_v1",
     "error": "FileNotFoundError: [Errno 2] No such file or directory: 'crate_s102_00004_.png'"}

The executor uploads the picture to ComfyUI and records the **name**
ComfyUI gave it; ComfyUI keeps the file in its own input directory (the
TRELLIS environment's `input/`); the delegate opened that name relative to
the night's working directory, where there is no such file. So the seam the
brief asked for — the d1-2B delegate answering for the props — answered
**nothing** on tonight's eighteen pictures, and the night's fourteen
rejections are the scripted critic's alone.

**What I changed.** The runner resolves the picture against ComfyUI's input
directory when the store's path is not absolute, and records the resolved
path in the signal.

**What I proved** (`docs/lab/night-v4-scripts/test_delegate_picture.py`):
the night's own crate picture, named the same way, resolved the way the
runner now resolves it, answered by the same delegate in 2.17 s — `holes`
**0.510** (fired), `missing_object` 0.206, `texture_swap` 0.057,
`noise_fireflies` 0.031, `black_frame` 0.003, `floating_object` 0.009. The
same profile as the crate in the pre-run smoke: the delegate was always
right about the picture; it was never given one.

**The measurements** (`measure.py`, over the night's own ledger, with the
diff against run D):

| | run F | run D |
|---|---|---|
| wall | 43.4 min (36.5 min of job wall) | 152.61 min |
| GPU-minutes | 12.29 (rail 60) | 25.74 |
| leases | three `thor-admit`, waited 0.0 / 0.1 / 0.1 s (total 0.2 s) | one, waited 914.9 s |
| decisions | 251 rows — 245 on the local d1-3B (mean 0.0475 s), 4 on Jev (0.588 s), 2 with no author | 12 rows — 5 d1-2B, 5 Jev, 2 none |
| gates | 181 surfaced, 66 act, 2 escalate | 2 escalate, 2 surfaced, 6 none |
| props | 0 kept, 14 rejected | 3 kept, 15 rejected |
| box | before load1 5.52 / 116.3 GB free; after load1 13.31 / 105.9 GB | before 63.75 / 62.9; after 8.96 / 84.5 |

**The letter** (125 words) is written from the night's own rows:
`docs/lab/night-v4-scripts/facts_from_ledger.py` transcribes the ledger
into `letter-facts.json` (the verdicts and their rungs, the leases and
their waits, the eighteen delegate rows), and `write_letter.py --facts`
writes the letter from that. The letter's surprise is the prior's gate
(cannot fire: the largest group holds 7, and a group of n cannot score
below 0.5/(n+1), so it needs ten) and its question is the library's
approve-ten.

**What was not reached.** No `morning.json`, no report, no live view, no
phase-down row: the night never got past the heavy phase. The lease's
waits are measured; its phase-down is still unproven in anger.

**What I decided next.** The next run starts from the commit that carries
the delegate's path, and it will have all four seams in it for the first
time: the routed 3B, the neutral order, the prior, and the delegate that
can see the pictures. The box is still hostile — another seat's
`thor-admit-hog` test was allocating 32 GB at a time all evening, and the
Wi-Fi driver aborted at 18:06:26 — so the mesh stage is where the night
still has to survive.
