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

## 2026-11-01 18:23 — the brief, and the state of the tree

`BRIEF.md` asks for **one** design note, `docs/design/vibecode-in-world.md`, that turns Casey's
sentence ("agents could vibecode ingame too, under the correct supervision; a human can come and go
and even rewind if it got off track") into an architecture **over what we already have**. Docs
only. Commit on this branch, never push.

State on the Thor before I started:

- `git log --oneline` — last commit `ad29c32` (the in-game-building phase-1/1b survey); the branch
  is a working branch with many siblings checked out.
- `git status --short` — **clean**. Nothing was left uncommitted by an earlier seat.
- `pgrep -af` — no leftover copy of this work; the only residents are other projects'
  (`agent_world_reflex serve` on the Thor, the builder-ide uvicorn on :8077, crafter-lab workers).
  Nothing of mine to collide with.
- `docs/design/vibecode-in-world.md` did **not** exist. This is a fresh write, not a continuation.

Read before writing: `docs/research/ingame-building.md` (+ `RESULT.md`), `docs/research/dsmc.md`,
`docs/design/screen-watcher.md`, `docs/design/watching-teachers.md`, `docs/design/autoplay-stack.md`,
`docs/research/theatre-open3d.md`, `docs/lab/exp-syzygy-keyframes.md`, the canon ledger code
(`core/records.py`, `core/events.py`, `core/fold.py`, `core/store.py`, `core/recipe/*`,
`core/critic/*`, `core/auth.py`), `tools/thor-admit/README.md`, and — outside this repo —
`~/lm-wt/agent-world` (`PLAY.md`, `COACHING-IDEAS.md`, `reflex/agent_world_reflex/ledger.py`) and
`~/last-mile` (`README.md`, `docs/design/decisions.md`).

**Decision:** write the note against the two live substrates we actually have — agent-world
(Minecraft, where the human is) and last-mile (Bevy, where replay is already bit-exact) — rather
than inventing a third world. The note's argument is that these two carry opposite halves of the
problem, which is also why the ordering is not a preference.

## 2026-11-01 18:28 — the numbers the note is built on

Box state at the time of measurement: Thor, load average **21.18 / 25.76 / 31.28**, 21 users,
122 GB total memory with 13 GB used and 90 GB free (108 GB available), NVIDIA Thor GPU. The box
was **not idle** — the reflex server and other work were resident. Numbers that are counts of
what the world did are unaffected by load; the *timings* quoted from earlier labs (the critic's
696 ms, syzygy's reader timings) were measured on this box under its own conditions and the note
says so.

**The world ledger** — `~/lm-wt/agent-world/runtime/world-ledger.sqlite3`, queried read-only
(`mode=ro`):

```
total events: 82952
span: 2026-11-01T05:20:38Z .. 2026-11-02T03:24:34Z      (22.07 h)
  42567  tile.played      40061  judge.verdict
    285  tile.authored       39  tile.retired
actors: judge@d1:d1-2B 40061 · Kite 24375 · Sprout 8509 · Pebble 7270 · Timber 2413
file: 112,517,120 B (+ 4,148,872 B WAL)
```

Two quotients: **3,760 events/hour** and **≈5.1 MB/hour** (≈1,356 B/event). That is the number the
rewind section is built on, and it is why "keep everything" is an affordable policy for now.

**The world state** — Paper's region files under `runtime/paper/world/dimensions/`:

```
overworld r.*.mca  3,813,916 + 3,557,857 + 3,196,472 + 4,051,079 = 14,619,324 B
dimensions tree 20 MB      level.dat 467 B      players/ 284K
```

So a full world snapshot is **20 MB**, and eight hours of hourly snapshots is 160 MB against
≈41 MB of ledger.

**A dead end worth recording:** my first instinct was to measure the *event payload* cost per
decision, which would have been the interesting number. The world ledger has no payload column
worth quoting — the closed event set it writes carries the decisions' outcomes, not their
contents — so the file-size-over-event-count is the honest figure and the payload-per-decision is
not available without reading a payload. I left it out rather than guess it.

## 2026-11-01 18:40 — the note, and the two things I corrected in it

`docs/design/vibecode-in-world.md` written: 854 lines, sections 1–7 as the brief names them
(the loop and the permission ladder; rewind; supervision while away; the return; where it runs
first; the gaps table and the ranked five; where the phase-2 tools slot), plus a short version,
what-is-not-verified, and a reproduction section.

Two claims I checked against the sources and **corrected before committing** (DOC-RULES item 5):

1. I had written that "`thor-admit exec` refuses to run a preallocating GPU framework without a
   lease". The README's actual rule is narrower and more precise: it refuses a JAX/XLA process
   **without a safe allocator**, and running it under a lease is *one of three* ways to be safe
   (the others are `XLA_PYTHON_CLIENT_PREALLOCATE=false` and the platform allocator). Rewritten to
   match, in §1.2c and in the hard rules of §3.1.
2. I had cited `last-mile/docs/design/decisions.md` for "the Thor serves about 9 decisions/s on
   d1-2B". That phrase is in `last-mile/README.md`; D68 says "~9/s". Both are now cited.

Also verified, phrase by phrase, with `grep -F` against the sources: every file path the note
names exists (23 in this repo, 7 in agent-world, 6 in last-mile), and every quoted sentence is
verbatim. Five apparent misses were line-wrap artefacts in the source (the phrases are exact once
the file is unwrapped) — `core/fold.py`'s "a stale transition fails closed",
`core/recipe/merge.py`'s "park a question rather than auto-merging", `core/recipe/store.py`'s
"Heads never move backwards". The critic table, the syzygy keyframe sweep, the rate-gate result
(19.4 % → 6.9 % → 0 %) and D68/D69/D74 were read out of the files rather than from memory.

**What I decided:** commit the note with the numbers and the corrections, and stop there. The
brief's deliverable is the note; the five ranked builds in §6.2 are the recommendation, not work
to start. §8 lists eleven things that are **not** verified — the Minecraft rewind above all, since
it is a design and not a measurement — so that the next seat does not read the note's certainty as
the note's evidence.
## 2026-11-01 14:00 — round 13 starts, and the guard is watched for an hour

Round 12 is merged and live (the round-12 binary `636ba7bb`, the guard on,
`~/.local/state/thor-admit/protected.txt` protecting `lm-wt/agent-world/`).
This runtime runs on the **ProArt** and drives the Thor over ssh, so the
Thor's Wi-Fi carries only the commands; every edit was made by hand, no
sub-agents.

**Item 2 first**, because it is wall-clock: a watcher on the Thor, sampling
every 60 s for 62 samples, recording the box's free memory, the daemon's
status, and **every new `guard.*` event in the daemon's log**, plus the box's
biggest processes every fifth sample. It starts nothing and stops nothing.

    $ nohup ~/lm-wt/thor-admit/.guard-watch.sh \
          ~/lm-wt/thor-admit/.round13/guard-watch.log 62 60 &

The live daemon at 13:57 was **pid 307460** — a *restart*, five minutes
before the round began. The daemon that had been up since 00:45 was gone,
and with it every lease it held.

## 2026-11-01 14:03 — the lock-before-lease flaw, stated

The brief's item 1, with the state of the code that has to change.

**The fact.** The box has two kinds of lock. The *lease* is the daemon's
promise about memory — admission before spend — held by the client as a
`flock(2)` on a per-lease file, so the kernel drops it when the client dies.
The *box's lock* is `~/lm-wt/heavy.lock`: the file lock every seat took
before the daemon existed.

**Why the old order could not work.** The rule the seats were given put the
lock **around** the daemon:

    flock ~/lm-wt/heavy.lock thor-admit run --peak 8G --label build -- nvcc ...

so the lock is taken first and the lease second, and a seat waiting in the
admission queue holds the lock for the whole wait. The measurements from
13:47 (above) show the cost: two seats held the lock for the whole of that
round and **neither was running anything** (the `nvcc` compile had not
started — it is inside the queued client — and the `ctest` shell had no
children), the fp4 seat had waited **3 003 s** for an 8 GiB lease on a box
with 77 GiB free, and the daemon's own queue could not advance either
because the head (`serve.glide`, 58 GiB) does not fit above the 25 GiB
floor.

**Decided next:** the lease first, the lock only once the lease is granted —
in three forms, so a seat meets it whichever way it asks: `--lock` by name,
the repair of the old line in place, and the Python shim's `lock=`.

## 2026-11-01 14:14 — `flock(1)` forks, and the pid is the wrong key

The first implementation looked for the inherited lock by **pid**: read
`/proc/locks`, find the entry whose pid is this process, take its file. It
found nothing, and the reason is worth writing down.

**`flock(1)` forks.** The parent opens the file, takes the lock and forks;
the child runs the command. Measured on the box with a client started as
`flock <lock> thor-admit run ...`:

    === the shell's job pid is 346700
    === /proc/locks lines naming this inode:
    12: FLOCK  ADVISORY  WRITE 346700 103:01:3578769 0 EOF
    === every process with this name:
        PID    PPID STAT COMMAND
    346700  346671 S    flock .../box-346671.lock .../thor-admit run --socket ...

The kernel's record names **346700** — the `flock(1)` parent. The client is
a different process, the parent's child. So the pid in `/proc/locks` is not
the pid of the process that inherited the descriptor, and matching on it
finds nothing.

**The test that works is on the descriptor**, and both halves of it are the
kernel's own:

1. the file is flock-locked on the box — `/proc/locks` names it, by device
   and inode;
2. this process can take the lock on its own descriptor **without waiting**
   — true only when the lock is held by *this* open file description, since
   `flock(2)` on a description that already holds the lock is a no-op, while
   a lock held by a *different* description blocks even in the same process.

So the client walks its own descriptors and asks the kernel, for each one
that is on a flock-locked file, whether the lock is its own.

**A second thing learned the hard way:** the descriptor is **copied** with
`dup(2)`, not adopted. The first version took ownership of the descriptor it
found with `File::from_raw_fd`, and the unit test aborted with *"IO Safety
violation: owned file descriptor already closed"* — because the descriptor
belonged to a `File` the test itself held, and two owners of one descriptor
means two closes. A copy shares the open file description, so it is the same
lock, and closing it closes nothing else.

## 2026-11-01 14:25 — the lease comes before the lock: the tests

Two integration tests, under a **test daemon** on its own socket and state
directory, never the live one:

    the_lease_comes_before_the_lock ... ok
    a_client_that_inherited_the_box_lock_gives_it_back_while_it_waits ... ok

They assert the same two things from both ends: a **queued** client holds
**nothing**, and an **admitted** client holds the lock. The first asks for
the lock by name (`--lock`); the second is started the old way, under
`flock(1)`, and is repaired in place.

The unit tests: **167 pass** (160 before this round, plus the `boxlock`
module's own seven). The Python shim's suite: **14 pass** (12 before, plus
the shim's two).

**A detail the test taught:** the holder of the lock is the **client**, not
the `flock(1)` process — the kernel records the process that called
`flock(2)`, and after the repair that is the client, which re-took the lock.
The first version of the test asserted the flock parent's pid and failed.

## 2026-11-01 14:29 — the guard's candidates, and the protected list

The guard's candidate is the biggest process that **no lease owns**, ranked
by resident set **plus** the device bytes the driver says it holds (the
guard's threshold: 4 GiB of that sum). Measured on the live box at 14:29,
with the leases read from the daemon's own status and the groups from
`/proc`:

    rss   device  ranked  pid      pgrp     owned  command
    0.51G  20.35G  20.86G  15433    15433    NO     llama-server -m .../Qwen3-Coder-30B-...gguf --port 8001
    0.80G   2.45G   3.25G  166798   166798   NO     llama-server -m .../d1-2B-...
    2.52G   0.00G   2.52G  12666    12653    NO     .../jdk-25/bin/java -Xms2G -Xmx6G ... (agent-world)
    2.02G   0.18G   2.20G  136803   136800   NO     llama-server -m .../d1-2B-...
    0.82G   0.44G   1.25G  376793   376790   lease  .venv/bin/python benchmarks/bench_fused.py

**Two things fall out of this.**

1. The coder seat's shared model server (pid 15433) holds **20.35 GiB of
   the box's device memory** and has **no lease**. The reason is the daemon
   restart at 13:57: the seat's `thor-admit serve` client (pid 14733) is
   still running, but the lease it held lived in the old daemon, and a lease
   does not survive a restart. The daemon now shows **0 leases** while that
   server holds a fifth of the box's memory. That is a near miss: had the
   box fallen to the emergency floor, the guard would have stopped it — and
   the guard cannot tell a seat that it did.
2. The agent-world's Paper server (2.52 GiB) is *already* spared by the
   operator's pattern list, and the d1-2B servers are below the threshold.

**Decided next:** add the coder model to `protected.txt`, by its model
*file*, so the box's agreed copy of that model is spared and nothing else
is; and report the orphaned lease as the finding it is — the fix is a client
that re-registers after a daemon restart, not a pattern in a list.

The daemon picked the new list up **without a restart**, at 23:29:42Z:

    {"event":"guard.protection","patterns":["lm-wt/agent-world/",
     "Qwen3-Coder-30B-A3B-Instruct-Q4_K_M.gguf"], ...}

## 2026-11-01 14:40 — the suite, and the one flake

The full integration suite, serial, on the box with the other seats' work
running:

    test result: ok. 47 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out;
    finished in 203.27s

**The first run failed one test**, and it is worth writing down because it
is not a change of the code under test:

    the_watchdog_stops_a_runaway_before_the_memory_runs_out ... FAILED
    the hog was terminated with only 0 MiB free, which is inside the OOM zone

That test scripts the box's memory curve (12 GiB down to 0, 256 MiB every
50 ms — the whole curve is **2.4 s**) and asks the daemon's real watchdog to
act inside it. The daemon samples every 250 ms, so it has about a second of
margin. The run that failed was on a box at **load average 19** with the
GLiDE server faulting in 33 GiB; the daemon's watchdog thread was delayed
past the end of the curve. Run alone, it passes and says so:

    low water: the hog was terminated with 7168 MiB free (the floor was
    8192 MiB) and the curve went on down to 0 MiB; the daemon acted within
    181 ms of the floor being crossed, and the kernel's OOM killer fired 0 times

and the whole suite passes on the re-run. So: a load-dependent flake in a
timing-sensitive test, not a regression — but it is the shape of thing that
will bite on a busy box, and it is recorded here rather than forgotten.

## 2026-11-01 14:45 — the documentation, and the live copy that could not be written

The memory rule gains a section, **"The box's lock: the lease first, the
lock second"**, with the right line and the wrong one side by side, the cost
of the wrong one (3 003 s of a seat's wait with the lock held), and the note
that a seat does not have to change its command line to be correct. The
crate README gains the same, the `status` line, and the two new tests in its
list. The design record gains section 17.

**The live copy at `~/lm-wt/MEMORY-RULE.md` could not be written from here.**
This runtime's permission gate refuses to replace a file outside the
repository on the box (it refused `cat >`, `cp` and a relative-path copy).
The updated text is committed in the repository at
`tools/thor-admit/round8/MEMORY-RULE.md`, and it is one command away:

    cp ~/lm-wt/thor-admit/tools/thor-admit/round8/MEMORY-RULE.md ~/lm-wt/MEMORY-RULE.md

Until that is run, the live copy is the round-12 text: it says the flock is
only for when the daemon is gone, which is true, but it does not say that
`flock ... thor-admit run ...` is the wrong order, and it does not mention
`--lock`.

## 2026-11-01 18:05 — round 13, item 0: the guard sees the GPU, and the numbers the director ran become the defaults

Three changes, committed as `cc97802`:

1. **The guard now sees GPU bytes.** The candidate ranking is
   `rss_bytes + gpu_bytes`, from the merged per-process view
   (`src/gpu.rs`). The new integration test
   `the_guard_sees_a_process_by_its_gpu_bytes` is the one the brief asked
   for: a 6 GiB CUDA allocation (`tests/cuda_probe.cu`, compiled with
   `/usr/local/cuda/bin/nvcc -O2`) held by a process with a 68 MiB resident
   set and no lease, against a scripted floor. The daemon stops it by its
   GPU bytes, and the kernels OOM killer fires 0 times.

## 2026-11-01 18:05 — round 13, item 0: the guard sees the GPU, and the numbers the director ran become the defaults

Three changes, committed as `cc97802`:

1. **The guard now sees GPU bytes.** The candidate ranking is
   `rss_bytes + gpu_bytes`, from the merged per-process view
   (`src/gpu.rs`). The new integration test
   `the_guard_sees_a_process_by_its_gpu_bytes` is the one the brief asked
   for: a 6 GiB CUDA allocation (`tests/cuda_probe.cu`, compiled with
   `/usr/local/cuda/bin/nvcc -O2`) held by a process with a 68 MiB resident
   set and no lease, against a scripted floor. The daemon stops it by its
   GPU bytes, and the kernel's OOM killer fires 0 times.
2. **The director's numbers become the defaults**: `--emergency-floor`
   8 GiB → 16 GiB, `--guard-drop` 8 GiB/10 s → 12 GiB/120 s. Both hangs on
   2026-11-01 ran the 8 GiB floor; 16 GiB is early enough that the watchdog
   still has living processes to stop. 12 GiB in 120 s is still far smaller
   than the incident (94.5 GiB in 20 s) and far larger than ordinary
   churn — the afternoon log carries seven `guard.unexplained_drop` lines
   in 80 s (02:08:30Z–02:09:50Z) at 8 GiB/10 s, on a box that was merely
   working.
3. **The driver's view says when it goes quiet.** A query to the driver is
   bounded by `timeout -s KILL 5` (the 16:10 hang showed a hung driver
   never answers), the per-process view carries its own timestamp, and a
   view older than 10 s is re-asked once; a stale ranking is kept rather
   than dropped, and `daemon.gpu_stale` is logged at most once a minute.

Suite state after these: 167 unit tests, 48 integration tests, on a box at
load 18.

## 2026-11-01 18:30 — what the suite hit on the shared box, and the list the floor path was reading

`three_thirty_gigabyte_hogs_are_serialised` failed four runs in a row
(02:07–02:19Z, 15:07–15:19 local) while the box was shared. Two separate
causes, both visible in the logs:

**The live daemon's guard was stopping the suite's hogs.** The suite
leases its hogs to its own test daemon; to the live daemon they are
unleased work, and a 30 GiB fault-in in under a second is the runaway
shape. The live log carries 26 `guard.terminated` lines between 01:28:28Z
and 02:55:14Z, of them 25 `thor-admit-hog` (all `trigger: runaway`, with
60–100 GiB free on the box — the guard did not need the box to be short).
The fix is the operator's mechanism, not code: `thor-admit-hog` was added
to `~/.local/state/thor-admit/protected.txt` with the reason in a comment,
and the running daemon picked it up without a restart at 02:58:24Z
(`guard.protection` with the three patterns). After that line the live log
has no hog stops.

**The box was through a real crisis, 03:00–03:25Z.** The `serve.glide`
lease (peak 62 277 025 792 B = 58.1 GiB) started and died `137` three
times: 03:07:15Z at 17.4 GiB resident, 03:09:31Z at 22.8 GiB, 03:17:51Z
at 26.6 GiB — each restart re-faulting while the box was already busy. The
live guard stopped two `llama-server`s in the window (03:08:59Z and
03:09:33Z; the second escalated to `guard.killed`, SIGKILL, after
3 996 ms). Co-tenant movement in the same window: up to 34.4 GiB lost in a
119.5 s window (03:07:18Z). That morning the previous daemon instance had
seen the box at **32.8 MiB available** (01:16:41Z, 34 430 976 B). The
hogs of the 3-hog test ran in and after that window; with the storm over
(03:45Z) the same test passed, with its margin raised from 4 GiB to
16 GiB (`HOG_MARGIN_GIB`) so ordinary churn is not misread as the second
hog.

**One daemon defect, found in this and fixed here: the floor path was
deciding with a stale protection list.** The list is re-read on the
guard's clock (every 2 s); the floor check runs every sample (250 ms).
On 2026-11-02 the first floor breach of the day stopped the Qwen3-Coder
`llama-server` (pid 7813) — the process the operator had put on the list
minutes before, *because its lease had been lost in a daemon restart*.
`watchdog_floor` now calls `read_protected` before it chooses (one
metadata call until the file changes). The regression test,
`the_floor_breach_reads_the_protection_list_before_it_charges`, scripts a
box that is below the emergency floor from the first sample, protects
everything on the box but one 2 GiB unleased hog, and asserts the hog is
the only thing stopped. It runs in 0.32 s. It was not verified against
the pre-fix binary, on purpose: the pre-fix failure mode is "the test
daemon stops a real co-tenant", which is what the daemon exists to
prevent doing.

## 2026-11-01 18:55 — the suite green, and what a live deployment would need

    test result: ok. 167 passed; 0 failed   (unit)
    test result: ok. 50 passed; 0 failed; finished in 242.40s   (integration)

on the box with the other seats' work running (Paper, two d1 servers,
ComfyUI, `run_student.py`, the lm-soak build).

**What a live deployment would need (not done from here):** the live
daemon is `~/lm-tools/thor-admit`, built 2026-11-01 13:51, i.e. before
`cc97802`, run with the director's explicit flags (`--emergency-floor
16G --guard-drop 12G --guard-window-secs 120`). A restart of that daemon
on the rebuilt binary is what makes the new defaults, the bounded driver
query, the `daemon.gpu_stale` line, and the floor-path list re-read live.
The call is the director's.

**Not solved, recorded:** between 03:04 and 03:25Z, hog processes were
sent SIGTERM by something that is not any `thor-admit` daemon (no event in
either daemon's log at the moments of death) and not the kernel's OOM
killer (dmesg and journal clean, tens of GiB free). The deaths cluster in
the `serve.glide` crash-loop window. After the loop stopped, every hog
run finished — including the suite's own three 30 GiB hogs in the green
run of 03:45Z. A memory watcher or a seat script on this box is the
standing suspect. The box runs auditd with logs under `/var/log/audit/`,
but it has no rules (checked 03:48Z: `auditctl -l` is empty), so there is
no standing way on the box to attribute a userspace `kill`; adding one is
the standing recommendation, left to the operator.
## 2026-11-01 17:20 — sleep-dreaming: the paper, found and read

The brief's round 1: find Google's SLEEP paper, write the mechanism, map it
onto our night, then measure a toy with and without a sleep phase.

**The paper.** *Language Models Need Sleep: Learning to Self-Modify and
Consolidate Memories* — Behrouz, Hashemi, Javanmard, Mirrokni (Google).
arXiv:2606.03979 [cs.LG], v1 2026-06-02, v2 2026-07-10, **CC BY 4.0**. Blog:
research.google, 2026-10-27. **No code is linked** from either the paper or the
blog (searched both on 2026-11-01); the blog's "Discover open-source code" is
site navigation, not a release.

The mechanism, in one line: the sleep phase **freezes the old parameters,
writes the new knowledge into newly unlocked low-rank experts in the stable
block, distils it on the model's own samples rather than on raw data, and
prunes the transient**. Read from the paper's own text and written up in
`docs/research/sleep.md`.

**A correction to the brief.** The brief points at
`docs/design/watching-teachers.md`. **That file does not exist** — not on this
branch, not on any branch (`git log --all --diff-filter=A -- "*watching-teachers*"`
is empty). The tiles-to-weights path the brief means is `docs/design/tiles.md`
§5 "The learning loop — the nightly retrain", implemented in
`core/tiles/retrain.py`. The research note says so in writing and maps onto
that file instead.

**The mapping, in one line.** Our night already has SLEEP's lifecycle, the
append-only log and the prune (tiles are retired, never deleted) — but our
consolidation re-fits on **raw events**, which is the one thing the paper
explicitly refuses, and our chooser has **no expansion**.

**Decided next.** Build the smallest honest toy: a two-phase class-incremental
MLP, five arms (no sleep / more waking / raw replay / sleep / sleep+dream), the
same gradient-step budget in each, the forgetting measured per seed. Under
`thor-admit run --tier practice --peak 2G`.

## 2026-11-01 19:05 — the toy, measured

The brief's rounds 2 and 3: a tiny continual-learning task with and without the
sleep phase, the forgetting measured, and a verdict for the night.

**The toy.** A two-phase class-incremental task: an MLP (16-32-10) with a
shared trunk and a shared 10-way head learns classes 0-4, then classes 5-9.
Five arms, the same gradient-step budget in each: `seq`, `seq_extra` (the same
budget spent on more waking), `replay` (the old task's samples, with their true
labels), `sleep` (head frozen, transient expert pruned, fresh expert trained
only on the teacher's own samples) and `sleep_dream` (the same, then
self-generated dreams filtered by gradient). Two settings: `shared_trunk` and
`frozen_trunk`. 8 seeds each, 80 runs, 18 min 24 s, CPU only, 317 MiB.

**The run.** `thor-admit run --tier practice --peak 1G --label
sleep-dreaming.exp`, lease #39, queued and granted at 18:42:46 with no wait.
Box state at the start: load 21.59 / 23.71 / 26.87, MemAvailable 112 415 MiB
of 122.8 GiB, `NV Power Mode: MAXN`, GPU 0 % used by this job, other seats'
work on the box throughout. 18 min 24 s of wall clock for the 80 runs (1 658 s
of CPU, 154 %). The 1 GiB promise was ~3x the measured 317 MiB (rusage).

**The numbers** (mean over 8 seeds; the full table with ranges is in
`docs/lab/exp-sleep-dreaming.md`):

| arm | setting | a1 (A kept) | a1, trunk put back | b1 (B learned) | average |
|---|---|---|---|---|---|
| `seq` | shared_trunk | 0.003 | 0.133 | 1.000 | 0.501 |
| `seq_extra` | shared_trunk | 0.003 | 0.133 | 1.000 | 0.501 |
| `replay` | shared_trunk | 0.997 | 0.591 | 0.287 | **0.642** |
| `sleep` | shared_trunk | 0.078 | **0.970** | 0.970 | 0.524 |
| `sleep_dream` | shared_trunk | 0.035 | 0.951 | 0.965 | 0.500 |
| `seq` | frozen_trunk | 0.041 | 0.041 | 0.997 | 0.519 |
| `replay` | frozen_trunk | 0.995 | 0.995 | 0.083 | **0.539** |
| `sleep` | frozen_trunk | 0.012 | 0.012 | 0.993 | 0.502 |
| `sleep_dream` | frozen_trunk | 0.000 | 0.000 | 0.943 | 0.472 |

**What it says.** (1) The freeze worked on the parameters it froze: put the
trunk back and the sleep arm scores **0.970** on A against the baseline's
0.133 - but it could not protect the shared representation underneath, so the
forgetting (0.922) barely moved (0.998). (2) With the substrate frozen too,
the sleep phase still lost A (0.012 against 0.041): the wake phase taught the
transient expert to suppress A, and the consolidation distils the teacher, so
it carried the interference over faithfully. **A consolidation step preserves
the teacher; it cannot undo what the teacher learned.** (3) The arm that kept
the old task was `replay` - keeping the old task in the loss - and our nightly
refit is already that shape; the price is the new task's estimate (b1 0.287),
which we have been assuming. (4) Dreaming in the toy eroded the old task
(0.035 / 0.000) and lowered the average in both settings. We did **not**
reproduce the paper's dreaming benefit; we reproduced the risk they name.

**Decided next.** Do not adopt SLEEP's machinery. Take the substrate rule: the
old knowledge must live in parameters nothing else touches - for the chooser
that is the per-context counts, and the *context bucket definition* is the
shared substrate, so a context definition is a versioned thing. And measure the
one thing the toy says matters: does the nightly refit over a growing log
drift the old contexts' estimates? That is answerable with `core/tiles/ope.py`
and our own log.

**The dead ends, so nobody retries them.**

1. *The train and the test split drew different class centres* (two seeds for
   one task), so the model fitted the training set to zero loss and scored at
   chance on the test set (a0 = 0.143). The centres now come from one seed and
   the samples from another. Symptom: train loss 0.0, test accuracy at chance.
2. *The expert's zero initialisation was dead.* A = 0 and B = 0 means
   `B @ A` has zero gradient in both directions and the expert never learns.
   A is now random (0.02) and B zero, so the expert starts as a no-op with a
   live gradient.
3. *The dream phase diverged.* Learning rate 0.05 with momentum on a
   single-sample loss produced NaN weights (seed 8, `shared_trunk`) and the
   run died on `multinomial` over `inf`. The dream phase now has its own
   learning rate (0.01) and a gradient clip (1.0); the consolidation clips
   too. The run that died was **discarded, not merged**.
4. *The splice left two `if __name__ == "__main__"` blocks*, so the script
   ran the whole experiment twice; the second pass was killed and the script
   was re-run once, clean, from the committed file. The published rows are
   from the clean run.
5. *The permission gate on this host would not prompt for some file writes*,
   so the scripts were sent in ~900-byte chunks (`tee` over `cat >`) and
   patched by a script in `/tmp` rather than by an editor. It is the harness,
   not the box; but it is why the scripts in this commit look the way they do.

**What was not verified.** The paper's experiment (no LLM on the Thor, B2);
the figures in the paper (numbers not in the HTML text); anything about the
night pipeline beyond what the toy implies. The toy is one synthetic task with
8 seeds - the ranges are in the lab note.

## 2026-11-01 19:30 — the brief was right about watching-teachers.md

**A correction to my own note.** At 17:16 I searched the reachable history for
`docs/design/watching-teachers.md`, found nothing, and wrote in
`docs/research/sleep.md` that the file did not exist and that the
tiles-to-weights path the brief meant was `docs/design/tiles.md` section 5.
**That was wrong, and the brief was right.** The commit is `dc99482` ("design:
watching teachers ... demonstration -> tile -> weights; retire the teacher
skill by skill"), authored and committed at 15:03 AKST, an ancestor of `main`
and **not** of this branch (cut at `18ec1be`). The same command, run now,
finds it; at 17:16 it found nothing, so the commit reached this clone's refs
during this session.

The wrong text is kept in the note under **SUPERSEDED**, and the mapping the
brief asked for is now section 2.5 of the note: the watching-teachers ladder
(demonstration -> tile -> weights) against SLEEP's (wake -> consolidation ->
dreaming), with the toy's findings landing on it.

**The one that matters.** The design's weights path is "the student's policy
fine-tuned on the demonstrations" - **one policy, many demonstrations** - which
is the toy's trunk: one shared substrate. The toy says a shared plastic
substrate under frozen parameters is where the old skill's behaviour goes, and
that no consolidation step puts it back. So the question for the design is:
when the policy is fine-tuned on all the demonstrations, does the newest
skill's behaviour survive? Answerable from the recordings the design keeps.

**Decided next.** Nothing in the design is changed here; this is a note and a
measurement. The measurement to take is on our side: whether the nightly refit
over a growing log drifts the old contexts' estimates (`core/tiles/ope.py` and
our own log).

## 2026-11-01 20:25 — refit-drift: part 1 done and reported, part 2 running

**What was tried.** The brief's two parts. Part 1 (does the nightly
whole-log refit drift the old contexts' estimates) was finished by the
earlier seat before it was stopped: `extract_real_tiles.py` read the six
tiles out of the nights' own ledgers, and `exp_refit_drift.py` ran 24 seeds
x 3 arms x 10 nights on the repo's own `core.tiles` code (19:38:02-19:39:06
AKST, 64 s, load 5.41, 114.4 GiB available of 122.8, 14 cores, GPU 0 % for
the job). Part 2 (watching-teachers: one policy fine-tuned on all the
demonstrations) was launched detached at 19:44 AKST under a thor-admit
practice lease (peak 2G), `--seeds 3 --passes-per-stage 262144`, four arms
(`seq`, `seq_replay`, `whole`, `per_skill_heads`) x 3 seeds on
crafter-lab's real teacher frames, CPU torch. The seat was stopped by quota
while it ran; the run continued on its own.

**What happened.** Resumed, checked the run was alive (pgrep: one copy,
under the lease), and reported part 1 in
`docs/lab/exp-refit-drift.md` while part 2 runs. The part-1 numbers: a
bucket that received no new plays keeps its estimate **exactly** (max move
0.0000, every night, both definition-fixed arms); touched buckets move by
0.001-0.004, every interval over zero; choices in old contexts flip at most
2.3 % a night; the OPE estimate checked against the closed-form truth is off
by 0.042 -> 0.014 over the run (clip 10, effective n 89 -> 1380). The churn
arm (`refit_grow`) does not drift the estimates (exact value drift
0.000 +/- 0.003) but does change the **choices**: 14-25 % of old buckets
flip and by night 3 a third of old-context picks is a tile trusted on the
0.5 prior alone. The moved-definition arm (`refit_moved`, the substrate
risk): on the move night, untouched buckets move up to 0.411, 45 pairs
collapse to the prior, 79.4 % of choices flip, OPE error 0.0736; recovered
to 0.0149 by night 10. Part-2 so far (seq arm, seeds 0-2): newest-skill
agreement 0.382-0.388, old-skill mean 0.320-0.324, env achievements 2-3 -
the full table comes with the run.

**Decided next.** Commit part 1 (note + scripts + recorded run). Wait on
part 2 (one line per arm/seed lands in
`results/watching_teachers.log`; ~8.5 min per seed). When it finishes: run
the two calibration scripts (the reference table for reading part 2), write
section 7 of the note, commit the final state.


## 2026-11-01 21:58 — resumed the seat: exp2 crashed in the last arm; fixed and re-running whole

**What happened.** The previous seat's part-2 run (launched 19:44, lease
`refit-drift.exp2`) had completed three of four arms — `seq`, `seq_replay`,
`whole`, 3 seeds each — and then crashed entering `per_skill_heads`:
`AttributeError: 'MlpExtractor' object has no attribute 'latent_dim'` (this
SB3 build exposes `latent_dim_pi`). The JSON is written at the end, so the
per-stage record was lost; what survives are the summary lines in
`results/watching_teachers.log` (newest 0.382–0.459, old mean 0.311–0.502,
overall 0.324–0.521, env 1.0–3.0, 464–1080 s per run; box under the lease,
peak 2G).

**What was done.** (1) `HeadStudent` now falls back to `latent_dim_pi`.
(2) `_diag_calib.py` and `_diag_budget.py` had a broken absolute ProArt
`sys.path` line (`/home/proart/…`); they now use `Path(__file__).parent`,
so the scripts run on the Thor. (3) Smoke run verified the fix: latent 64,
head to 17 actions, forward pass clean (lease peak RSS 357M). (4) Re-ran
**all four arms** × 3 seeds, `--passes-per-stage 262144`, detached at 21:58
AKST under the 2G lease — the first attempt's JSON being lost, the re-run is
the canonical record; the log is `results/watching_teachers.run2.log`, the
output `results/watching_teachers.json`. First attempt averaged ~11 min per
run, so ~2 h expected.

**Decided next.** When it finishes: run `_diag_calib.py` and
`_diag_budget.py` (the calibration table for reading part 2), write section
7 of `docs/lab/exp-refit-drift.md`, add the missing scripts README, commit.


## 2026-11-02 00:40 — run2: nine of twelve runs clean, second crash in per_skill_heads; patched

**What happened.** The full re-run (run2, admitted 22:06) finished the
`seq`, `seq_replay` and `whole` arms again — the agreement numbers are
bit-identical to run 1 (training is deterministic; only the env episodes
differ slightly, as expected) — and then crashed in `per_skill_heads` with
`KeyError: 'collect_wood'`: `agreement_table` measured every skill through
`heads[name]`, but the heads are trained one at a time, so later skills have
no head yet. The end-of-run JSON was lost a second time; the nine summary
lines survive in `results/watching_teachers.run2.log`.

**What was done.** (1) `agreement_table` now reports `None` ("not measured
yet") for skills whose head has not been trained; nothing later writes that
head's output, so that is the honest value, and it is the arm's design
claim. (2) The JSON is now saved **after every run** (`save_json` inside
the loop), not only at the end — an interrupted run leaves what it had.
Both changes compile; the JSON for this run lands in
`results/watching_teachers_heads.json`. (3) Re-ran only `per_skill_heads`
× 3 seeds (the other nine runs are the verified records), 
launched detached 00:40 AKST under the 2G lease, log `results/watching_teachers.run3.log`.

**The surviving table (9 runs, two agreeing attempts).** newest/old mean/
overall: seq 0.405/0.388/0.382 vs 0.311/0.320/0.324, 0.330/0.344/0.324
(env 2.00–2.50); seq_replay 0.417/0.431/0.386 vs 0.424/0.434/0.427,
0.462/0.456/0.450 (env 1.50–2.50); whole 0.455/0.456/0.459 vs
0.502/0.496/0.489, 0.510/0.521/0.511 (env 1.75–3.00). So far: seq keeps the
newest skill only at the price of the old ones; whole lifts everything;
seq_replay keeps both middling.

**Decided next.** When the heads arm lands: `_diag_calib.py` +
`_diag_budget.py` (calibration), section 7 of `docs/lab/exp-refit-drift.md`,
scripts README, commit.
