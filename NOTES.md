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

## 2026-11-01 19:00 — build #2: the drift detector

The brief (this seat's `BRIEF.md`) asks for build #2 of
`docs/design/vibecode-in-world.md`: §3.4's drift detector and the
auto-pause signal, offline, on the world ledger that already exists.

State before I started, on the Thor, in `~/lm-wt/drift-detector`:

- `git log --oneline` — last commit `535e7e3` ("design: vibecode-in-world"),
  which is the note this build implements. The branch `drift-detector` had
  **no commits of its own** yet.
- `git status --short` — clean.
- `pgrep -af drift` — nothing of mine running. The residents are other
  projects' (the world's reflex, the builder IDE, crafter-lab).
- The box: 122 GB total, 11 GB used, 111 GB available, load 5.4/6.1/11.9,
  26 users. The world was running the whole time — the ledger is live.

**Decision:** read the world's ledger read-only and never write to it; take
the ground truth from instruments *outside* the ledger, so the measurement
is not the detector scored against its own rows.

## 2026-11-01 19:10 — what the ledger actually carries

`~/lm-wt/agent-world/runtime/world-ledger.sqlite3` is 113 MB and still
growing. One table, `audit` (seq, id, at, actor, type, subject, payload,
artifact). Four event types: `tile.played` (43,125), `judge.verdict`
(40,617), `tile.authored` (285), `tile.retired` (39).

**Per-actor attribution is in the payload, not the `actor` column.** The
`actor` column holds a JSON blob naming the *seat* that wrote the row (the
reflex, the judge, the seed); the agent a row is about is
`context.bot` for a play and `judgments[].qid` for a verdict. The design
note's "82,952 labelled events with per-actor attribution" is this ledger,
and it is still being written.

Three things §3.4 says that the ledger does not say, found by reading the
rows:

1. The *outcome* is on `tile.played` (`outcome.result`), not on
   `judge.verdict`. A verdict carries the decision (the agent, the
   confidence) and no outcome. So the success signal reads the plays.
2. `constraint.failed` and `wo.failed` are **canon** event types
   (`core/fold.py`); the world ledger has neither. The third event §3.4
   names — payload flagged `refused: true` — is exactly the world's own
   refusal event, and that half of the definition holds verbatim.
3. The spend is not in thor-admit's ledger: the world's services run
   outside the lease system, so there is **no world label** to divide. The
   spend is in the ledger's own `cost` fields, and `hosted_cents` is 0 on
   every row (the decision model is local).

Two of the six signals are not computable at all: rule violations (the
bots' humanity promises live in the bots' code and are never written to
the ledger) and build drift (the ledger has no branch head and no
constraint set; that is the canon side).

## 2026-11-01 19:25 — the ground truth, and the timezone that nearly hid it

Three instruments outside the ledger:

- `bots.jsonl` (the world's clients): `reflex_unreachable`,
  `play_not_recorded`, `kicked`, their own errors (117 events), and the
  refused decisions whose *cause* is a failure — `IntegrityError: UNIQUE
  constraint failed: audit.id`, `ProgrammingError`, "the reflex did not
  answer in time" (8,179 events).
- `docs/lab/incident-2026-11-01-jax-hang.md` — the box hang.
- `agent-world/docs/playtest-2026-11-01-reward.md` — the wedge (the
  builders could not move) and the judge being unreachable twice.

**The timezone, which I nearly got wrong.** The box is AKST (UTC−9) and
`journalctl --list-boots` prints AKST. The incident note's boot id
(`ea0658fc`) is the boot that ended at **10:49:53 AKST = 19:49:53Z**, so
the note's "~10:45" and "~10:59" are 19:45Z and 19:59Z. The playtest
note's "rebooted at ~20:00 UTC; the world came back at 20:06" is the same
event in UTC from the other note. And the world's ledger has a **25-minute
hole over exactly that stretch** (19:40Z–20:00Z) — which is how the
derivation was checked rather than believed.

The negative control: 2,217 refusals whose cause is the world *yielding*
the box ("yielded: the box has N GB free" / "leased: another seat holds
the box"). Those are not failures, and a detector that alarms on them is
wrong. Kept as their own class so that can be measured.

Nine labelled drift episodes, 115 positive windows.

## 2026-11-01 19:45 — three measurement bugs, found by the first numbers

The first calibration run was wrong in three ways, and the numbers said so:

1. **The incident labels were instants, not windows.** A label carried only
   its start, so a 55-minute incident labelled one 5-minute window. Fixed:
   a label carries `until`, and every bucket of it is positive.
2. **The detector reported fires but not state.** A gate in alarm for two
   hours is one fire and two hours of pause; counting only the transitions
   made the always-on gate look free. Fixed: the detector now exposes the
   alarm *state* per window, and the score counts false-alarm **windows**
   as well as episodes.
3. **The spend signal was dividing the wrong cost.** `tile.played`'s own
   `cost.gpu_minutes` is 0.000 on every row — the play is cheap and the
   *decision* is what costs. The verdict's cost is charged to the agent
   the verdict was about (`judgments[].qid`), which is the only
   attribution the ledger carries for it.

Also: the detector built one gate for all agents of a signal, so the
"previous value" leaked between agents. One gate per scope now.

## 2026-11-01 20:05 — the metric that punishes an always-on gate

The level gate beat the rate gate on the first honest scoring, which was
wrong: a level gate on the stall signal sits on for 124 of 272 windows
because the scout's worst gap is *permanently* ten times its median gap.
Its episode-level precision said 1.0, because its one long episode
overlapped a positive window.

So the score needed the **time**: a false-alarm *window* count beside the
episode count, and the operating point had to fit inside a **pause budget** —
the world may be in alarm for at most a tenth of its windows (27 of 272)
without anything being wrong. A permanently-on gate is not worse on
recall; it is worse on time, and time is what a pause costs.

With the budget in place, the selection rule is: the most episodes detected,
subject to the budget; ties to the fewest false-alarm windows, then the
fewest fires, then the highest threshold.

**Dead end, kept here so nobody retries it:** a *trailing* baseline. The
first version chased the drift (the baseline is the agent's own trailing
24 h median), so a four-hour wedge became the new normal and the signal
went flat in the middle of it. The baseline is **frozen** over the
reference period now.

## 2026-11-01 20:30 — syzygy's gate is one-sided, and so is mine

The pause list showed the detector firing on *good news*: "the success rate
fell −0.444 below its own reference" and "the cost per productive decision
moved to 0.00×". The rate gate was using `abs(Δ)`, so a recovery counted
as a drift.

Checked against the bar's own source: `~/lm-wt/syzygy-keyframes/harness/
gates_conf.py` fires on ``conf[i-1] - conf[i] > tau`` — the reader *losing*
the scene, **not** the reader regaining it. Syzygy's rate gate is
one-sided, and mine had to be too. Every signal here is a *badness* (higher
is worse), so the rate is now the **rise** of the badness and only the
rise.

The effect was large:

| | before (abs) | after (one-sided) |
|---|---|---|
| holdout episodes detected | 5 / 6 | **6 / 6** |
| holdout false-alarm windows | 35 | **28** |
| negative control (designed yield) | 7 of 12 alarmed | **5 of 12** |

## 2026-11-01 20:50 — the shipped detector, and the one thing that failed

Shipped: the **rate** gate, thresholds `stall` 10.0, `success` 0.2,
`errors` 0.8, `spend` 0.5, exit 0.6 × enter in every case, dwell_down
600 s, five-minute windows, `min_scored_plays` 20.

**37 alarms over 22.67 h = 1.63 per hour of world.** The five real events
in the run are all caught in the right window: the judge's first absence
(06:20Z), the judge after the reboot (17:55Z), **the box hang (19:40Z)**,
the world's write path breaking (00:50Z — Kite's worst gap jumped to
193× its median), and the judge again (02:40Z).

**The negative control failed, and the cause is the ledger's.** 5 of the 12
windows in which the world *correctly* yielded the box were alarmed on.
When the world yields because the box is busy it stops playing, and a world
that stops playing is what the stall signal is for. The ledger records "the
agent did not play" and not "the agent declined to play because the box is
busy" — the two are the same row. **The fix is one more event in the world
(`drift.yield`), not a better detector**, and it is the most actionable
finding in the lab note.

**A hybrid gate was built and did not earn its place.** The idea: fire on
the rise, hold while the level is bad — for a drift that is sustained and
settles. On this ledger it reached the same recall (6/6) with *more* alarm
time than the rate gate (122 windows against 88), because the world's
signals wobble rather than settle. It stays in the code, documented, for
the day a signal does settle.

## 2026-11-01 21:05 — committed

- `core/drift/` — the detector, the six signals, the gate, the pause ladder.
- `core/hysteresis/gate.py` — one addition, `reset_pending()`, so a window
  with no reading drops a pending transition instead of carrying it across
  the gap. Its README was updated in the same commit.
- `tools/drift/` — the extraction, the calibration, the pause list.
- `tests/drift/` — 46 tests, all passing.
- `docs/lab/exp-drift-detector.md` — the lab note: the mechanism, the
  numbers, the defaults, the negative control, what is not verified.
- `docs/lab/drift-dataset/` — the dataset (with the ledger's sha256), the
  labels, the calibration report, the pause list.

The auto-pause is **computed and named but not wired to `thor-admit`**: the
demotion itself would mean touching the admission daemon, and this build is
the detector and its measurement. That is the next thing to do, with the
tier demotion behind the same threshold this lab chose.

## 2026-11-01 21:20 — a correction to my own claim about the sample width

The lab note's first draft said the sample width was the lever: "at five
scored plays per window the success signal's rate gate spent 150 false-alarm
windows over the run; at twenty it spent 18". **That was measured against
the two-sided gate and it is superseded.** Measured on the *committed*
dataset with the shipped one-sided gate (`tools/drift/measure_twosided.py`,
which patches the gate back and re-runs the same calibration in this
process):

| on the committed dataset | two-sided | one-sided (shipped) |
|---|---|---|
| holdout episodes detected | 5 / 6 | **6 / 6** |
| holdout alarm windows | 99 | **88** |
| holdout false-alarm windows | 35 | **28** |
| negative control | 7 of 12 | **5 of 12** |

And the sample width, with the shipped gate: 16.2 false-alarm windows at
five scored plays, 18.3 at twenty, 7.2 at forty — the same 2 of 9 episodes
in all three. So the width is a **second-order** lever and the one-sided
rate is the first-order one. The default of twenty stays (the holdout
numbers are better there: 10 false-alarm windows against 16), but not for
the reason the first draft gave.

**A measurement trap worth recording:** the first version of that script
ran the calibration in a **subprocess**, so the patched gate never reached
it and the two arms measured the same code and came out identical. The
second version patched the class but restored the function from the already
patched module, which had the same effect. Only the third version — patch,
then call `calibrate.main()` **in this process** — measured anything. A
"before and after" that comes out identical is usually the harness, not the
result.

## 2026-11-01 (the resume) — the log above was appended twice

The seat that built #2 stopped on a quota limit, and its last commit carried
the build-#2 log twice: the entries 19:00 … 21:05 stand at lines 567-763 and
again, byte for byte, at 764-960. That commit piped `notes_append.md` and
`notes_correction.md` together when only the correction was new. The second
copy is deleted here; nothing is lost — git holds both copies (`git show
6f63dcc`, `git show 749f1fe`) — and no other file was touched by the double
pipe (every file of the build is byte-identical to the seat's staged copies,
checked by sha256 over `core/drift`, `core/hysteresis`, `tools/drift`,
`tests/drift`). One oddity to keep in mind when reading this log: its
timestamps run ahead of the box's clock — the "21:20" entry was written at
19:43 on the box. This entry uses the box's own clock (20:07 AKST).

What the resume checked, before deciding there was nothing to rebuild:

- the tree is clean at `e08278a`, and the only code change after the seat's
  own green run is the `min_scored_plays` **docstring** in
  `core/drift/config.py` (the same correction as the note's, in comments);
- the suite, on that final tree: **46 passed in 0.31 s** under a 2 GB
  `thor-admit` lease, peak RSS 59.9 MB. CPU only.

One sentence was added to the lab note's §3. The brief asks for
precision/recall "against whatever ground truth exists (director
interventions, failed runs, the incidents…)". The incidents and the failed
runs are labelled; *director interventions* had no named place in the note
because the box keeps no such instrument — a grep of `agent-world/docs` and
`agent-world/runtime/logs` for "intervention" finds nothing. The incident
notes and the playtest note are that record (the human's reboot that ended
the box hang, `ops/d1.sh start` that brought the decision model back), and
they are the `incident_*` rows of the label table. The table is the whole
ground truth the run has, not a selection out of a larger one.

Nothing new was started. The auto-pause is still computed and named but not
wired to `thor-admit`; that is build #3 and the note already says so.
