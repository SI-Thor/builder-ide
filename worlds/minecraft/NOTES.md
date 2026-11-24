# NOTES — agent-world desk, 2026-11-01 (the reward playtest)

One line per step: what I tried, what happened (the numbers, with the box
state), what I decided next. The box: the Thor, aarch64, 122 GB; the box
**rebooted at ~20:00 UTC today** (42 min uptime when I connected at
20:41 UTC), the world came back at 20:06 UTC; another seat was running a
generation sweep and two zcode seats ran throughout; free memory 45–86 GB.

## The finding, and the chain under it

- 20:47 — Status page: `skill_4c16c6547b52` (scout.sight, "survey the
  ground around") at **reward 0.5, mean 0.5, on all 18,066 plays**, day
  and night. Wrote `ops/reward-audit.py` (committed beside this note) and
  audited every family: the sight skill is the only *constant-high*, and
  two gatherer.wood skills are constant at 1.0 on small counts (7, 37
  plays — real wins, not a defect). The bigger finding: **in the last
  two hours every other skill was constant at 0.0** — 1,855 plays, zero
  wins across all four builders. The last win in the ledger was 17:22Z.
- 20:49 — Read the reward chain: `bots/src/agent.js` `measure()` scores
  predictions `inventory_delta`/`block_placed`/`block_broken`/`moved_to`
  as 1/0; a skill with `predict.kind = "none"` records **partial** with
  `score: null`; `reflex/agent_world_reflex/models.py` `PlayRecord.reward`
  mapped `{win: 1.0, partial: 0.5, lose: 0.0}` — **"we could not measure
  this" became "this wins half the time"**, a fabricated constant, and a
  high one: higher than any working gatherer's true rate (0.28–0.33).
  The sight skill's prediction is `kind: "none"` by design (a survey
  changes nothing the measures can see), so every one of its plays scored
  exactly 0.5. That is the brief's constant.
- Decision: a partial is **not half a win**; it is no measurement. Fix at
  the source: `reward` returns `None` for a partial, and the chooser's
  `update`/`fit` skip `None`-reward records. Test: `tests/test_reward.py`
  — 6 checks FAIL against the old code (e.g. "got 0.5, want None"; the
  old arithmetic also blended one real win with five phantom partials
  into 4/7 ≈ 0.571), all pass against the new one.

## Why every family was constant at 0 (the second disease)

- 20:33–21:00 — The all-lose streak had its own cause. Probes (bots/
  probe-wedge.js, probe-spots.js and five throwaways, deleted):
  - Pebble stood **in water in a cave at (3, 27, −2)**, 48 blocks under
    the depot, since ~16:00Z; every "walk home" timed out at 20 s with
    **zero displacement**.
  - Kite's walk-east had never once moved it: 238 plays, all "the walk
    took too long", all day.
  - A **fresh probe bot** also could not move: raw controls covered
    0.02 blocks in 3 s at the depot plateau; the world border was fine
    (59999968 blocks wide); no mobs stood on anyone; chunks were loaded;
    health and food were 20.
  - A **server-side teleport** freed the same client instantly (it then
    walked 6 blocks east in 3 s). The freeze is spot-local: the bots
    stand wedged against cobble faces — much of it the cobble lines the
    community itself laid while building the wall.
  - The mechanism (probe-wedge.js): under input, mineflayer's physics
    reports the wedged bot **off the ground**, and a jump needs
    `onGround` — so it can never step or jump out, and the pathfinder's
    follower cannot make its first move, so `goto` hangs with no error.
    probe-wedge.js: 58 s on a planner goto, zero movement.
  - Also the judge was dead twice over: after the reboot another seat's
    `serve.d1-2B-old` held the lease on port 8143 while the reflex asked
    8094; then, when the reflex joined it, **480 of 486 asks failed in
    3 ms** — that server answers `/health` but not `/v1/systemone`.
- Decision: three source fixes besides the reward.
  1. `bots/src/api.js` `gotoNear`: a stall watcher (no net progress for
     3.2 s) now buys one nudge — back off, sidestep, stop the planner,
     retry from a clean standstill; after two nudges the walk fails fast
     ("the walk could not start") instead of grinding its whole clock;
     the budget grows 1.5 s per block beyond twelve for far walks.
     Test: `bots/test/goto-near.test.js` with a stub bot that wedges —
     both tests FAIL against the old code (20 s grinds), pass against
     the new (fail in 16.5 s having moved; arrive in 2.4 s).
  2. `reflex/agent_world_reflex/decision.py`: the port is discovered —
     configured port first, then any admission lease serving the model,
     and a candidate counts only if it answers a real `/v1/systemone`
     probe (green `/health` is not enough). Canonical `serve.d1-2B`
     before variants. Test: `tests/test_d1_port.py` (5 checks).
  3. `ops/d1.sh start` brought the world's own d1-2B up on 8094 under
     the admission daemon; the reflex then ran 18 asks with 0 failures,
     mean 51 ms.
- World-ops: the four builders were teleported out of their wedged and
  barren spots (the same tool the docs record from this morning):
  Pebble into the stone quarry pit (0, 66, −8) — surface stone near the
  depot was mined out or is wall cobblestone, which the gatherer's
  search rightly does not count; Sprout to the grass field (−12, 77,
  −20); Timber to the depot edge (5, 72, −12); Kite to open ground
  (16, 71, −20). Probes graded the spots first (probe-spots.js).
- Restarted only the windows whose code changed: viewer, reflex, bots,
  and started d1. **Paper was not stopped.**

## The viewer's NaN errors (brief item 3)

- 20:52–21:10 — Reproduced with `~/lm-tools/playwright/probe.mjs`: **12**
  "computeBoundingSphere(): Computed radius is NaN" console errors per
  load (the director counted ~6). Not entities from the model file: a
  WebSocket-correlated probe showed every NaN fired **before any entity
  spawned**. A temporary patch of the served bundle
  (`ops/patch-bundle-diag.py`, diagnosis only) printed the geometry:
  twelve of them, each **24 positions / 36 indices — one box** — each
  with NaN at position index 1 (a NaN y). That is prismarine-viewer's
  fallback for a **name-less entity**: `BoxGeometry(entity.width,
  entity.height, entity.width)` with undefined width and height. The
  server's `drawable()` forwarded name-less entities because its first
  branch read `!entity.name` as "a departure or a move". 26.1 has
  entities the viewer's 1.21.4 tables do not name.
- Fix: `viewer/src/server.js` `drawable()` leaves name-less entities out
  — the rule the docs already state for model-less mobs, now applied to
  the case that actually produced NaN. Correction in writing: the check
  had been **excusing** the NaN warnings as an empty-section artifact of
  three.js; that was wrong (empty sections have 0 positions, these had
  24), and `ops/check-views.mjs` now fails on *any* console error.
- Verified: `ops/check-views.sh` — all three pages pass, the 3D view's
  line is `ok no console errors`; `probe.mjs` prints no console.error;
  the screenshot shows terrain, a builder, the strip.
- The probe whitelist: `Probe8` added to `ops/world/whitelist.txt` and
  via the console (the probes are the world's own eyes; Probe5 was
  already listed).

## Dead ends, so nobody retries them

- `/data get entity Kite` from the Paper console: "No entity was found"
  — Paper's data command does not read players. Positions came from a
  mineflayer probe instead.
- "The Thor rebooted" as the cause of the freeze: wrong — movement died
  ~16:00Z, before the reboot; the binaries and node_modules are
  unchanged since Oct 31 21:23.
- "A mob parked on the bot" (server pushes overlapping entities): wrong
  — the nearest mob to the frozen spawn was a bat 28 blocks away in a
  cave.
- "A collapsed world border": wrong — 59999968 blocks wide.
- `thor-admit serve d1-2B --port 8094 -- /bin/true` (probing the handoff
  behaviour): the daemon keyed on the command and started a server on
  8094 supervising `/bin/true`; my timeout killed it and no stale lease
  remained (checked `thor-admit status`). Do not probe serve with a
  command that is not the real model server.
- `movements.canSwim` does not exist in the installed
  mineflayer-pathfinder 2.4.5; water is already pathable there
  (`liquidCost`). Pebble could not walk home because the walk could not
  start, not because water is forbidden.

## State at the end of the hour (filled in below)

See `docs/playtest-2026-11-01-reward.md` for the numbers of the one-hour
re-run.

## The hour, measured (22:53 UTC)

- The window 21:53–22:53 UTC: farmer.ground 270 of 271 wins,
  gatherer.stone 164 of 165, scout.ground 20 plays with rewards
  {0.0, 1.0} — its first win ever ("moved 25.2 blocks (wanted 20)",
  22:03:26Z) — and the survey's 1,564 plays all unscored. Judge
  1,828 calls, 0 failures, mean 58.4 ms, on the world's own serve
  (port 8094). Estimates moved on evidence: farmer.ground night
  0.005 → 0.251, gatherer.stone night 0.282 → 0.361.
- Still broken, on purpose of the design: builder.wall 19 plays, 0
  wins ("the wall could not grow" — a placement problem for the
  mediator), and the scout walks lose 19 of 20 in the forest.
- The playtest note with the whole story:
  docs/playtest-2026-11-01-reward.md.

## 2026-11-01, the playable round (Casey 13:40: "playable with the agents live")

- Started 14:19 UTC from the desk brief. The world was already up
  (paper 26.1.2-74, viewer, reflex, four builders, d1 on 8094), the
  tree clean at 3219f47. Killed a leftover hung `node --test
  bots/test/goto-near.test.js` (2 h 06 in --test-timeout=0; it passes
  cleanly in 23 s when actually run, so the hang was the run, not the
  code).
- Built the no-grief ledger (bots/src/humanity.js): a block that
  appears within 6 blocks of a person is theirs; no mining it, no
  mining within 4 blocks of it, no building within 8 unless the person
  said "help me build" (a 10-minute invite); a chest a person placed
  is never opened; players are never attacked. The pathfinder's
  safeToBreak is held to the same rule, so a planned path cannot dig
  through a house either. 14 offline tests pin the rules
  (bots/test/no-grief.test.js, all pass, 81 ms).
- Next: the command table and the duties, then restart reflex+bots
  (service.py gains a family= filter so "gather wood" is the chooser's
  wood family, not a model parsing words), then the probes.

- 15:00 UTC: the crew restarted with the command layer live; the join
  proof passed end to end (TestHuman9: join 0.4 s, greeting 1062 ms,
  moved 9 blocks, chat, broke coarse_dirt, placed it back; the dig
  needed look-first/verify-after — the same lesson as the api's).
  Privacy checked by grep: 0 marked free-text lines in bots.jsonl.
  Say-lines verified through /events to the voices page; check-views
  passes all three pages.
- The command battery found four faults, all fixed (commits e702bdd,
  40e6548, later): duties died instantly (expires was a duration read
  as a timestamp); nearest-routing never fired (a player's position is
  on the entity, not the player list); a paper restart re-armed the
  whitelist at the door (now AW_PLAYTEST=1 keeps it open, said out
  loud at every start); the follow re-planned walks to old positions
  (now GoalFollow holds the person's entity).
- Bedrock, measured: Geyser shipped with transport "nethernet" (WebRTC
  only) so RakNet never answered; set to "both". ViaVersion 5.12.3
  installed (Geyser 2.12.1 targets MC 26.3, the world runs 26.1.2).
  bedrock-protocol 3.59.0 joins the door and is refused: "Please log
  into Xbox" under auth-type online/offline/floodgate, reload and two
  restarts. Anonymous Bedrock is not a thing in this Geyser; signed-in
  devices are the path, and that path is untested here (no device).
- gatherer.wood v11 seeded (searches 96 blocks, steps 24 on failure):
  the night's chopping cleared the spawn forest and v10 searched 24.
  The gather duty now retries from new ground before giving up.
- 01:0x UTC: **the Thor dropped off the LAN mid-run** (ping 100%
  loss from the ProArt while the Orin answers; the box was load ~11,
  86 GB free). Everything since is staged locally. When it returns:
  run the final battery, the grief probe, ops/steady.sh 30, fill the
  playtest note's placeholders, commit.

- 02:33 UTC: the power cut's real wound found and healed: the box died
  between builder-ide's ledger INSERT(id='') and its UPDATE, leaving
  one audit row with an empty id that every later insert of the
  placeholder collided with ("UNIQUE constraint failed: audit.id" on
  every play). One UPDATE healed it; the log of record (bots.jsonl)
  refolded unchanged (41,357 plays). The reflex reloaded, the crew
  rejoined on their own.
- The follow, cracked: mineflayer-pathfinder's GoalFollow with the
  work movements (dig on, parkour off) stalls a few blocks from a
  moving target and never closes (FollowerM2: 13.9 → 8.0 forever);
  with walking movements it closes to 1.3 (FollowerX). And even with
  walking movements, a wedged bot computes paths ("success" every 4 s)
  and never makes the first move — probe-follow, FollowerF2 at 11.6
  blocks. Fixes: a follow now walks with its own movements (no
  digging), and the follow duty watches its own progress and nudges
  itself loose the way gotoNear always has.
- "stop" is now visible: the crew holds still five seconds,
  re-releasing the planner every tick, before taking up its own work.
- gatherer.wood v12 seeded: four 36-block walks, searching after each,
  before admitting there is no tree (the spawn forest is gone; v11
  searched 96 blocks from where it stood and failed three times in one
  battery — a gatherer must go where wood is).
- The last battery (04:26 UTC): what-doing ok, addressed ok, stop ok
  (ack 400 ms, they let go), follow and come ok when the crew is near,
  failing honestly from 35+ blocks of rough ground; gather-wood running
  v12 as this is written. The full table and every earlier run's
  numbers are in docs/playtest-2026-11-02-playable.md.
- 06:0x UTC: the endgame numbers. The grief proof complete under the
  rule: TestHumanH placed 2 coarse_dirt with Timber working 4 blocks
  away, the ledger recorded both placements as they landed, and both
  stood after the watch (2 of 2; an earlier run held 2 of 2 at crew
  distance 13-35). The steady half hour: 62 samples, TPS 63/63 >= 19.5
  (min 19.9, median 20.0, reconstructed from paper.log by
  ops/tps-window.sh), MemAvailable min 78.9 GB, d1 running mean
  3.7 -> 6.0 ms (single-digit under a person plus my probes, load
  13-28). The playtest note docs/playtest-2026-11-02-playable.md holds
  the tables and the honest limits (carry-on unwitnessed, the depot
  pile race, the deforested spawn, the pit-stranded crew — the
  mediator's list).


## 2026-11-02, the community round (Casey 2026-11-01: "leave and have the community developing while you are gone")

- 06:19 UTC — The box was up 4:53 h (load 22–29, another seat's
  voyager-port sandbox under thor-admit; 88 GB free). Paper, viewer,
  reflex and the four builders were already running — but **d1 was
  down**: the reflex's every model call had failed since its start
  (634/634 at 2.5 ms). `ops/d1.sh start` brought it up on 8094; 29
  calls later only 2 failures (the race at startup), then clean.
  TPS 20.0/20.0/20.0, crew + Watcher in the world.
- Built the community loop, all offline-tested (31 new checks, the
  full suite 48/48 in 21 s): the **board** (`bots/src/board.js`, an
  append-only event log `runtime/logs/board.jsonl` replayed into
  state, snapshot `runtime/board.json`, the manifest fingerprint), the
  **validator** (`bots/src/validator.js` — a local rule table with
  builder-ide core/precedent's exact interface, since that repo is not
  merged here; every project proposal and every structural edit passes
  it), the **council** (`bots/src/council.js` — deterministic order of
  need: chest, forest, farm, path, shelter; a DeepInfra model may
  *propose* when the needs are met, never decide), the **world look**
  (`bots/src/worldlook.js` — the council's eyes, honest about unloaded
  chunks) and the **executors** (`bots/src/projects.js` — idempotent
  plan-walkers per role; the scout tests finished work and files
  issues; the gatherer supplies materials to sites).
- The playtest's known failures, fixed at the source: the **depot
  pile race** (leave_at_depot/take_from_depot now use the depot chest
  first — placed by the depot-chest project, the council's first
  need), **depth-minding** (api.dig refuses below y=48 — the planner
  may still dig upward to escape a pit; skill g14 "surface stone"
  seeded as gatherer.stone v9, searching y≥50), and the **gone
  forest** (a replant project: saplings from leaves, planted on the
  plan; scope 8 spots).
- Humans: the greeting now says what the community is building
  (board.headline()) and offers a hand in it; new commands
  `what are you building?`, `build a farm`, `plant trees`,
  `build a chest`, `build a shelter` — a person's request becomes a
  proposal through the same validator (a deny is said plainly).

- 06:41–07:47 UTC — The loop's first live hour, and what it taught:
  the world held TPS 20.0 while the council proposed, the validator
  denied, and the crew worked. Six faults found and fixed (commit
  follows): the blanket keep-out handed a departed visitor's two
  blocks a veto over the whole depot (site searches exclude that
  ground now; the coarse deny fires only on a block inside the
  site; denied kinds cool 30 min); the chest scope floated a block
  and billed a finished chest; the library gather skills drop
  everything at the depot so a supply run through them carried
  nothing (the supply fetch gathers straight into the bag);
  oak/spruce is one family to a delivery; "mined" is not "holding"
  (the hillside spruces are a climb the planner refuses — walk
  first, dig only where you stand, `exclude` the refusals); and the
  pit still owned all four builders (Pebble y=8, Timber y=48, Kite
  y=32, Sprout y=64 — lifted by console tp; the pathfinder now holds
  the y=48 floor too, with an escape clause for a builder already
  deep).
- 07:43 UTC — **the drift detector's first live hold**: Pebble's
  success-rate signal fired, the watcher wrote the soft hold to the
  pause file, the reflex refused its asks ("paused: drift pause
  (soft)"), and — once the bots learned to read the pause file too —
  Pebble held its own work with a `drift_hold` note. The whole of
  §3.5's soft level, live and unattended.
- The watchers are detached: `ops/drift-watch.sh` (one window every
  5 min, soft enforced, tier/hard dry-run) and
  `ops/community-watch.sh` (a sample a minute into
  runtime/logs/community-20261102.csv, hourly rollups).
- An honest correction (DOC-RULES 5): the playtest note's "the
  deforested spawn" stands for oak — but the world is not woodless;
  two mature spruces stand 6 blocks from the depot (506 log blocks
  within 96, probe-wood.js). The first probe read "no wood" by
  scanning before its chunks settled, and the level-bound search
  could not see trunks 8 blocks up a hill. Both lessons are in the
  g15 seed's provenance.

- 09:30 UTC — Picked up mid-diagnosis (the seat stopped with api.js's
  nearest-first ordering and worldlook's farm-plot ring uncommitted and
  undeployed). probe-farmland vindicated the look: `farmlandNear`
  answered **no** honestly (0 farmland in 56 blocks, registry id 208);
  the farm need was real and the proposal was dying at `farmPlot` —
  every candidate centre sat on the keep-out ground. Deployed both
  fixes (suite 50/50 in 21 s): at 09:32:45 the council proposed
  **b044** with its site on the ring at (-10, 0), the validator
  allowed it, and the farmer took it up. The ring works.
- 09:43–09:49 — Pebble, back from the 09:13 soft hold's TTL, hunted
  blind: "no tree within reach of the depot", every 11 s. The facts
  (probe-crew-wood.js, new): Pebble/Timber/Kite stand in the depot
  gully at **y=61–62**; every standing log sits at **y=64–73** (the
  terraces) with the spruce canopy at y=83–86 — cd0a7f9's
  `max_y: feet+2` window contained **zero** logs. The community
  starved on a window. Widened the band to **feet+12** (a terrace or
  two up, never the canopy; the nearest-first ordering tries the
  gully-edge logs long before any climb). Suite 50/50.
- 09:49:06 — before the patched hunt ever ran, the watcher enforced a
  fresh soft hold on Pebble (success signal, TTL 30 min → lapses
  10:19). Read the fold to know if the loop converges: a held bot's
  asks are recorded as **yields, not scored plays** (service.py: "a
  held bot is a yield, not a failure"), and `partial` steps are
  unscored — so a hold does not depress the success rate by itself;
  the pool recovers when real wins return. Watching the 10:19 lapse
  with the patched hunt behind it.

- 10:26–10:58 — the doom loop named and broken. The watcher held
  Pebble again at 10:24, one window after the 10:19 TTL lapse — for
  the silence the 09:49 hold itself had made (the stall lookback is 15
  min, the TTL 30: a lapsed hold always re-trips). And the fold read
  again: refusals are yields, not scored plays, so Pebble's pool of
  wins sat empty all morning — every project play scored 'partial'
  (predict kind none). Two changes: **the watcher does not enforce a
  soft hold on an agent that played in the window** (plays or a
  drift.yield explain it; ops/drift-watch.py, "soft hold not
  enforced" — live from 10:31), and **a duty may carry its own
  result** — a supply step that mined, staged, or delivered is a won
  play (agent.js honors result.result; the hunt and the fetches say
  win).
- 10:54–11:19 — the walk itself, dissected with the repo's own
  gotoNear driven from probes (probe-walkstate.js, probe-path.js):
  the follower sticks at a 1-up step reporting moving=true with zero
  displacement until a nudge frees it (a lone probe needed two, then
  arrived in 13.2 s); the crew's walks died at three nudges. Five
  now (the wedged-walk test's bound honestly re-measured: ~23 s
  against a 20 s budget). A dig under way counts as progress in the
  stall watcher. The hunt's walk aims at dig range (3), not
  adjacency (2) — a GoalNear(2) into an embedded log searches
  forever. The refusals are remembered ten minutes (HUNT_MEMORY):
  the five nearest candidates to the gully floor were three keep-out
  refusals and two walk failures, re-bought every step, the sixth
  candidate — the nearest ALLOWED log — never reached.
- 11:19 — Pebble lifted by console tp to the farm site (-10,70,0):
  **four spruce logs mined** (result win) — the hunt works from
  terrace ground. But "mined" was not "held": collectAt gave up when
  the walk to the block's own cell failed, never chasing the drop
  (it now breaks to collectEntity). Two logs each went to b037/b044
  as tosses at 11:26 — and **despawned** (5-min item life) before
  any owner stepped over them: the board said "staged", the world
  held nothing. board-unstage.js re-opens a lied-to project; the
  delivery now walks to distance 1 before the toss; the owners
  pickup_near their site before waiting.
- Not yet true: a chest placed, a hoe crafted, a farm planted. The
  chain that remains: Pebble's walks fail from the gully floor (the
  restart put it back there; the tp does not survive a restart), and
  the 5-minute despawn races the owners' 13–45 s project-step
  cadence — the library gather drops logs in the pile, Timber takes
  them only if its project step is chosen inside the window. The
  depot chest (b037) is the fix for its own delivery problem; it has
  not closed yet.

- 12:13–13:03 — the chain closed, one block at a time. The deliveries
  kept dying at the toss: the toss landed neither at the site nor the
  pile (the delivery walk's distance-1 goal exploded like the hunt's
  distance-2; now distance 2 with a pile fallback, and the outcome
  says where it landed). Pebble disconnected at two delivery moments
  (12:13:20, 12:30:04 — "lost connection: Disconnected" in paper.log
  at exactly the materials events; unexplained, open). Then the sight:
  **a dropped item is type "other", name "item"** — the kind lives in
  metadata nobody read (probe-drop-fields.js). Every item look was
  blind: the pile look never walked its ring, pickup_near saw nothing.
  Then the bench: "no recipe for chest" — recipesFor needs a crafting
  table; api.craft finds one within 16, ensureBench crafts and places
  one when the world has none. Then the wiring: **sendToTest had no
  caller** — done projects could never reach the scout's walk (done
  stayed 0 all day for this reason alone, wood aside).
- 12:47–12:53 — two operator seeds, honestly owed and recorded: the
  console gave Timber one chest and Sprout two oak logs (the supply
  chain's despawned tosses had eaten three real deliveries' worth of
  wood); Timber placed the chest from beside the site (tp -4 68 -5,
  after six placement timeouts from the gully floor).
- 13:02:35 → 13:02:59 — **b037 done**: Timber's step said done, the
  service handed it to the tester, Kite walked it and passed it. The
  first completed project of the community round, 6.5 h in. The board:
  done 1, active 1 (b044 farm — Sprout splitting logs for the hoe at
  12:49; the seeds are its open want). The depot has a chest:
  leave_at_depot/take_from_depot now have a durable handoff surface.

- 13:10–13:50 — the run settles. The farm (b044) holds the hoe and the
  bench; Sprout and Pebble grind short_grass for the 14 wheat seeds
  ("grass broken, no seeds yet", one break ~36 s, a seed an eighth of
  the time — the honest pace of it). The chest stands at the depot;
  the board: done 1, active 1. TPS 20.0 every sample of the day
  (240/240 ≥ 19.5 by the 12:40 rollup), MemAvailable min 69.7 GB,
  zero soft holds enforced since 10:31 (31 exemptions), grief 0 (the
  visitor's two blocks stand, no new player builds). The day's doc is
  docs/playtest-community-2026-11-02.md; the round's commits run
  14ce3f6 → 6f4134e. Left for the next seat: the gully (walks from
  its floor still cannot climb out; restarts put the gatherer back),
  Pebble's delivery-moment disconnects (12:13:20, 12:30:04,
  unexplained), the farm bill's bench under-count (bills one log, the
  hoe-and-bench need eight planks), the drift gate's "success rose"
  semantics, and the replant proposal when the terrace singles run
  out. The world runs on: paper, bots, reflex, d1, drift-watch,
  community-watch, all detached.

- 14:00–14:40 — day two, the five CONTINUE priorities, four fixed and
  the fifth turned over to the crew. **(1) The "Pebble disconnects"
  were never a world fault**: every mystery disconnect (paper.log
  local 03:13:20, 03:23:31, 03:30:04, 03:42:09, 04:00:03, 04:26:41 —
  UTC 12:13–13:26) has **all four bots leaving the same second** and a
  staggered rejoin ~10 s later, with ProbeD/W/G connections between:
  those were the previous seat's own `ops/bots.sh restart` calls while
  patching delivery code (tmux kill-window is a SIGHUP; the graceful
  quit path never ran). `cmd_stop` now SIGTERMs the window's leaves
  first (`bot.quit('the world is resting')`), then kills the window;
  the orphan reflex from the 09:36 restart (no port, PID 2834293) is
  killed. **(2)** the drift success signal is one-sided at the source
  (drift-pause 4baf697, floored at zero — the signed form let the rate
  gate fire on a rise from far-above-reference to slightly-above-it,
  Pebble 06:45); the watcher restarted onto it at 13:59 and its first
  window read "nothing in alarm" where the five minutes before planned
  a Pebble success hold. **(3)** bills count the bench: CRAFTED_FROM
  gains `crafting_table` (4 planks = 1 log), `benchNear` mirrors the
  craft-time 16, and depot-chest/farm bills add the bench only when
  the site has none (rawBill: chest+bench 3 logs; hoe+bench+14 seeds
  2 logs + seeds). **(4)** seeds by the patch: `gatherSeeds` breaks a
  90 s run per step at reach 48 — the old one-break-per-step cadence
  (~36 s a break) put 14 seeds at more than an hour. **(5)** the gully
  itself: a `ramp` project kind that carves the way out — each step a
  cell dug down to the standing level and finished with scoped
  cobble, terraform, not construction (a place-only plan cannot cross
  the 4-high mossy wall; probe-column.js read the wall, the floating
  lip at y66, and the crew floor y61-64). `surfaceAt` now skips ALL
  leaves — spruce canopy counted as ground made the spawn slope a
  y69 plateau and the first planner run refused a gully it could not
  see.
- 14:29 — the council proposed the ramp on its own (b058, 7 steps)
  and the validator **denied** it for the right reason:
  TestHumanH's coarse_dirt (5,67,2 / 4,66,2) inside the site. The
  deny drew two real flaws out of the plan: steps through the visitor
  keep-out, and the **chest's own column held as a step** — carved, it
  would have dug the depot chest out of its terrace. Fixed (keep-out
  skip in the planner, goal column never a candidate, a chest guard
  in the executor, site hugging the plan), tests 9/9 on the real
  visitor coordinates (c9d23fc).
- 14:38:41 — **b060 allowed**: 6 cobble steps SW of the chest
  ((-2,62,-4) … (-3,67,-6)), site r=4 — kind:known, scope:bounded,
  site:known, materials:gatherable. The builder owns it; the unattended
  stretch (projects done per hour is the headline) starts here.

- 15:00–16:00 — the ramp's executor earned its keep the hard way, one
  honest refusal at a time. The builder's quarry looped "quarried a
  stone" without ever holding one (a dig that reported success without
  checking its own outcome), then refused honestly ("too deep: the
  community mines no lower than y=48" — the nearest bare stone to the
  gully is a cave wall twenty blocks down), then found nothing at all
  (find_block's default window is ±2 of the builder's own feet; the
  pit's stone sits at y58–62 below them) — and the instrumented
  refusal named the real state: **the builder itself was at y38–40**,
  mined underground between project steps by its own library skills
  (the playable round's pit failure, alive in the bandit's repertoire;
  probe-find.js: 96 stone spots within 32 of the gully floor, so the
  world had stone all along). buildRamp now stands at the work BEFORE
  gathering for it — a search from the site finds the stone the site
  sits on — and the quarry is bounded `min_y: 49, any_level: true`.
  The drift watcher held Timber (soft, spend signal) over the wasteful
  stretch — the supervision doing exactly its job — and the hold lapses
  at its TTL.
- The seeds taught their own lesson: the batching worked (runs of
  90–115 s, the first seed of the day arrived), but by 15:40 the
  farm's own terrace was ground bare — "0 grass broken" every tick
  within 48, and nothing within 96 either. The seed economy of the
  spawn slope is spent. The owner's gate is back to one-seed (a seed
  in hand is a seed in the ground, and wheat pays its own seeds
  back), and the gatherer's forage reaches 160 for untouched patches.
  What the world still owes itself: a wheat cycle (plant-harvest-
  replant) so seeds compound instead of being mined out of the grass
  — that is next-seat work, recorded under risks.

- 16:10–17:40 — the pickaxe existed by 16:41 (bench-first: mineflayer's
  2x2 inventory craft times out on windowOpen, the table's window is
  the path that works — five attempts say so), the quarry still gave
  nothing, and the instrument closed it: **equip ok, cobble in hand 0**
  — pickaxe in hand, dig resolved, block to air, no drop entity, no
  item (probe-quarry.js reproduced it in isolation). This world's
  stone drops nothing, pickaxe or no; grass drops seeds, dirt drops
  dirt. Unverified why; an open question recorded for the next seat.
  The ramp is **dirt** now (96a6710): the scope names dirt steps, the
  bill is empty — the carve itself is dirt, and the steps pay for
  themselves out of the ground they are cut into. Operator debts of
  the day, honestly owed: one console tp (Timber, y40 → the ramp site,
  16:04 — the bandit's library skills mine the builder underground
  between steps, and from below the y=48 floor no dig up is legal) and
  two oak logs given for the pickaxe (16:40). b060 (cobblestone scope)
  carves real terrain until its stall clock abandons it (~19:00Z);
  the next proposal recomputes on the carved ground and builds the
  dirt steps on it.

- 18:05:46 — **b064 done**: the tester walked the dirt steps and
  passed them. Proposal to done in 24 minutes. The board: done 2
  (chest, ramp), active 1 (farm — waiting on wood for a hoe; a death
  in the pit cost the old one, inventories do not survive a
  respawn). The council's need line still names "ramp" — the planner
  measures the straight line from the pit past the visitor keep-out —
  but the board's own memory (a done ramp stays on it) keeps the
  proposal suppressed; the walk itself exists via the pit floor to
  the steps, which is what the tester's pass certified. TPS 20.0 in
  every sample of the day; MemAvailable min 34.4; grief 0; the day's
  doc section is docs/playtest-community-2026-11-02.md §6. The seat
  closes with the world running unattended: paper, bots, reflex, d1,
  drift-watch, community-watch, viewer — the same seven as day one.
## 2026-11-02, the gym round (desk brief: "agent-world-gym on the Thor")

- 06:54–07:03 — Read the desk brief and the Thor's own BRIEF.md, the
  autoplay-stack doc, and the crafter round-2 lab note (the rule that
  carries over: **record ALL of a teacher's frames**; a subset is a
  compute-saving shortcut, not a better choice — round 2's verdict was
  that the teaching-moment filter keeps 98.8 % of the decisive frames
  and teaches nothing beyond its own selection). Read the world's
  contract: the reflex's context (`bots/src/agent.js` `context()`), the
  option set (`agent_world_reflex.library` `eligible()`), the sealed
  prediction (`models.py`), the door (`door.py`), the ledger
  (`ledger.py`, builder-ide's `core.night.ledger` under the hood) and
  the bots' api + sandbox (`bots/src/api.js`).
  The gym branch was clean at b3cced0 (the community round's merge); no
  gym work had been started. Nothing of the community's was disturbed:
  the live world (25565), the bots, the reflex and d1 were left running
  exactly as they were.
- 07:03–07:14 — The environment, built under `gym/`:
  `agent_world_gym.AgentWorldEnv(reset/step)` over a bridge to one
  mineflayer bot. The observation is the reflex's own context, encoded
  once (`facts.py`) so the live env and the community's replay read the
  world the same way; the action is the library's live option set,
  discrete, with the ineligible options masked into
  `info["eligible_actions"]`. The bridge (`gym/bot/gym-bot.js`) reuses
  the world's own `Agent`, api, sandbox and measure, with a **null
  reflex** — it asks nothing and records nothing, so the gym writes
  nothing to the live world (checked afterwards: 0 plays by "Pupil" in
  the community's ledger).
- 07:05 — The private world, per the brief: the server copied from the
  community's `runtime/paper` with **every `world*` directory left
  behind**, its own seed (`agent-world-gym`), on **127.0.0.1:25630**
  (not 25565, not voyager-port's 25600, not world-snapshot's 25610),
  offline mode, under `thor-admit run --tier live --peak 3G --label
  agent-world-gym.mc` — lease #56, 1.4 GB resident against a 54 GB free
  box (load ~10.4, another seat's 40 GB lease alongside). It generated
  in **11.1 s** ("Done (11.122s)!"). The live world's world directory
  was never copied and never touched.
- 07:06–07:20 — The tests, five files, all passing: the facts encoder
  (one encoder, shared; a missing confidence is -1 and not 0; an
  unnamed block is "unknown" and never "air"), the env (a win is 1.0, a
  partial carries **no** reward and says so, an option that does not
  apply is refused by name, the eligible set is the world's own rule),
  the ledger (the fold, the episode split, and a write through the
  read-only connection **refused** by SQLite), the recorder (every
  frame kept, the community's own actions recorded, a partial stays a
  partial), the student (it learns what it is shown; the held-out split
  is by episode; the random policy stays legal).
- 07:20–07:36 — Two bugs of my own, both found by the live run:
  - **the episode split was wrong.** Splitting on the log's order made
    every handover between two of the four builders a new episode:
    **43,466 episodes of one or two plays** from 71,577. The rule is now
    per bot and then on the silence (600 s), and the same ledger folds
    into **20 episodes**. Regression test added.
  - **the episode boundary hung.** The bridge emptied the agent's bag
    with `bot.toss(type, null, count, callback)`; mineflayer's `toss`
    takes three arguments and returns a promise, and never calls a
    callback, so the reset waited for ever once the agent had a log in
    its bag. The bag is emptied with the promise API now, and every
    step of the boundary (toss, walk home, respawn) is capped.
  - Also fixed: the block grid read "unknown" everywhere, because
    `bot.blockAt` takes a position and the bridge passed three bare
    numbers (the world's own api reads it with `new Vec3(x, y, z)`).
- 07:36–07:52 — The run. The private world's dataset: 3 episodes, 18
  frames, under the cycle scripted policy. The community's dataset:
  **20 episodes, 72,388 frames**, read out of the world's ledger through
  a read-only SQLite connection. Every frame kept — nothing filtered.
  The action space is 41 options (the library's 13 live ones plus every
  option the community has ever chosen, retired versions and project
  steps included), so a student cloned from the community can be played
  in the private world with no translation table.
- 07:52 — The students. `bc-community`: 48,163 training frames,
  24,225 held out (whole episodes), held-out agreement **0.951**,
  training agreement 0.733. `bc-private`: 12 training frames — three
  episodes of a scripted policy is almost nothing, and the report says
  so. The rollouts (3 arms × 3 seeds × 2 episodes × 6 steps) are the
  long part: a skill in the world costs 36–85 s of real walking.
  The community's own rate, in the same units: **140.5 gathers and 0.6
  projects per episode** — but a community episode is a bot's whole run
  (3,598 plays on average) and a gym episode is 6 steps, so the two are
  not comparable per episode; that is said in the lab note.
- The lab note: `docs/lab/exp-agent-world-gym.md`. The package's own
  README (how to run, what it needs, how long it takes): `gym/README.md`.

## 2026-11-02, the gym round (desk brief: "agent-world-gym on the Thor")

- 06:54–07:03 — Read the desk brief and the Thor's own BRIEF.md, the
  autoplay-stack doc, and the crafter round-2 lab note (the rule that
  carries over: **record ALL of a teacher's frames**; a subset is a
  compute-saving shortcut, not a better choice — round 2's verdict was
  that the teaching-moment filter keeps 98.8 % of the decisive frames
  and teaches nothing beyond its own selection). Read the world's
  contract: the reflex's context (`bots/src/agent.js` `context()`), the
  option set (`agent_world_reflex.library` `eligible()`), the sealed
  prediction (`models.py`), the door (`door.py`), the ledger
  (`ledger.py`, builder-ide's `core.night.ledger` under the hood) and
  the bots' api + sandbox (`bots/src/api.js`).
  The gym branch was clean at b3cced0 (the community round's merge); no
  gym work had been started. Nothing of the community's was disturbed:
  the live world (25565), the bots, the reflex and d1 were left running
  exactly as they were.
- 07:03–07:14 — The environment, built under `gym/`:
  `agent_world_gym.AgentWorldEnv(reset/step)` over a bridge to one
  mineflayer bot. The observation is the reflex's own context, encoded
  once (`facts.py`) so the live env and the community's replay read the
  world the same way; the action is the library's live option set,
  discrete, with the ineligible options masked into
  `info["eligible_actions"]`. The bridge (`gym/bot/gym-bot.js`) reuses
  the world's own `Agent`, api, sandbox and measure, with a **null
  reflex** — it asks nothing and records nothing, so the gym writes
  nothing to the live world (checked afterwards: 0 plays by "Pupil" in
  the community's ledger).
- 07:05 — The private world, per the brief: the server copied from the
  community's `runtime/paper` with **every `world*` directory left
  behind**, its own seed (`agent-world-gym`), on **127.0.0.1:25630**
  (not 25565, not voyager-port's 25600, not world-snapshot's 25610),
  offline mode, under `thor-admit run --tier live --peak 3G --label
  agent-world-gym.mc` — lease #56, 1.4 GB resident against a 54 GB free
  box (load ~10.4, another seat's 40 GB lease alongside). It generated
  in **11.1 s** ("Done (11.122s)!"). The live world's world directory
  was never copied and never touched.
- 07:06–07:20 — The tests, five files, all passing: the facts encoder
  (one encoder, shared; a missing confidence is -1 and not 0; an
  unnamed block is "unknown" and never "air"), the env (a win is 1.0, a
  partial carries **no** reward and says so, an option that does not
  apply is refused by name, the eligible set is the world's own rule),
  the ledger (the fold, the episode split, and a write through the
  read-only connection **refused** by SQLite), the recorder (every
  frame kept, the community's own actions recorded, a partial stays a
  partial), the student (it learns what it is shown; the held-out split
  is by episode; the random policy stays legal).
- 07:20–07:36 — Two bugs of my own, both found by the live run:
  - **the episode split was wrong.** Splitting on the log's order made
    every handover between two of the four builders a new episode:
    **43,466 episodes of one or two plays** from 71,577. The rule is now
    per bot and then on the silence (600 s), and the same ledger folds
    into **20 episodes**. Regression test added.
  - **the episode boundary hung.** The bridge emptied the agent's bag
    with `bot.toss(type, null, count, callback)`; mineflayer's `toss`
    takes three arguments and returns a promise, and never calls a
    callback, so the reset waited for ever once the agent had a log in
    its bag. The bag is emptied with the promise API now, and every
    step of the boundary (toss, walk home, respawn) is capped.
  - Also fixed: the block grid read "unknown" everywhere, because
    `bot.blockAt` takes a position and the bridge passed three bare
    numbers (the world's own api reads it with `new Vec3(x, y, z)`).
- 07:36–07:52 — The run. The private world's dataset: 3 episodes, 18
  frames, under the cycle scripted policy. The community's dataset:
  **20 episodes, 72,388 frames**, read out of the world's ledger through
  a read-only SQLite connection. Every frame kept — nothing filtered.
  The action space is 41 options (the library's 13 live ones plus every
  option the community has ever chosen, retired versions and project
  steps included), so a student cloned from the community can be played
  in the private world with no translation table.
- 07:52 — The students. `bc-community`: 48,163 training frames,
  24,225 held out (whole episodes), held-out agreement **0.951**,
  training agreement 0.733. `bc-private`: 12 training frames — three
  episodes of a scripted policy is almost nothing, and the report says
  so. The rollouts (3 arms × 3 seeds × 2 episodes × 6 steps) are the
  long part: a skill in the world costs 36–85 s of real walking.
  The community's own rate, in the same units: **140.5 gathers and 0.6
  projects per episode** — but a community episode is a bot's whole run
  (3,598 plays on average) and a gym episode is 6 steps, so the two are
  not comparable per episode; that is said in the lab note.
- The lab note: `docs/lab/exp-agent-world-gym.md`. The package's own
  README (how to run, what it needs, how long it takes): `gym/README.md`.

- 18:28 -- **The run's numbers** (1 h 52 m wall: 16:36:09Z -> 18:28:35Z).
  The datasets: the community's **20 episodes / 72,388 frames** (every
  frame kept), the private world's 3 episodes / 18 frames. The action
  space: 41 options (13 live in the library + every option the community
  has ever chosen, so a student cloned from the community plays in the
  private world with no translation).
  The students: `bc-community` 48,163 training frames / 24,225 held out
  (whole episodes), held-out agreement **0.951**; `bc-private` 12 training
  frames -- three episodes of a scripted policy is almost nothing, and the
  report says so.
  The rollouts (gathers per 6-step episode, the world's own units):
  **bc-community 6.00** (seeds 6, 6, 6), **random 4.00** (seeds 3, 5,
  4), **bc-private 2.00** (seeds 0, 0, 6). Projects 0.00 for every arm:
  the gatherer never builds, so the other half of the
  achievements-equivalent needs the builder's role rolled out.
  The mechanism is in the world's own log: the community's gatherer spent
  the morning evolving its wood skill (g15 -- search 96 blocks at any
  level, walk on when it misses), and the student cloned from 72,388
  frames plays that skill every time; the random policy picks it about a
  third of the time and the surface-stone skill the rest, and stone is
  the one that misses. No interval is quoted: six rollouts of six steps
  is not a sample that carries one, so the per-seed rows are given.
  Box state beside it: MemAvailable 69 GB at the start, 45 GB at the
  end; load 11.6 -> 14.3; the private world's lease at 1.4 G resident
  against a 3.0 G peak; jax CPU-only with
  XLA_PYTHON_CLIENT_PREALLOCATE=false in every entry point. The
  community's world, bots, reflex and d1 ran throughout and were not
  touched: **0 plays by the gym's bot in the community's ledger**. A
  skill in the world costs 36-85 s of real walking, which is why the
  matrix is three seeds and not thirty.
- The lab note with the whole story: `docs/lab/exp-agent-world-gym.md`.

## Day three (2026-11-02, the 09:26 seat)

- 09:26 — the seat opens on the day-3 CONTINUE (stone drops, safe-keeping,
  the wheat cycle, the council's next projects). The seven detached
  processes all alive; TPS 20.0; 45 GB available, load 14.
- 09:29:46 — **the seat's own fault first**: I sent a Tab to the server
  console trying to tab-complete `gamerule `, and the completion's
  SuggestCommand component contained a literal tab — a disallowed chat
  character — and the serializer exception crashed the tick loop
  (crash-2026-11-02_09.29.46-server.txt; "Failed to encode Minecraft
  Component: ... Disallowed chat character: '\t'"). The server saved all
  chunks on the way down; restarted at 09:31:24 (Done 14.5s, joins work).
  Rule for every seat after this one: **the tmux console is a terminal —
  never send Tab; type plain queries only** (plain `gamerule
  minecraft:block_drops` is safe and answered in the log).
- 09:31 — after the restart Kite and Sprout rejoined but Pebble and Timber
  did not: Paper throttled their same-IP reconnects at 18:31:25Z
  ("Connection throttled!"), and the kick-during-login hung their
  reconnect loops forever — `connect()` only settled on 'spawn'/'error',
  so a login that ends with 'kicked'+'end' never settles the promise the
  loop is awaiting. Fixed in bots/src/agent.js (first of spawn/error/end
  settles it); ops/bots.sh restart brought all four back staggered
  (18:37:22–18:37:41Z). Also noted, not yet acted on: floodgate fails to
  enable on every boot (guice error, then "Disabling floodgate") and its
  dead netty injector throws "zip file closed" into the log on every
  join — Java joins are unaffected; the signed-in Bedrock door is
  untested today.
- 09:34:57 — the stone question, first instrument: NOT config.
  `minecraft:block_drops` (the rule's 26.1 name; doTileDrops is gone and
  level.dat no longer holds GameRules — they live per-dimension in
  world/dimensions/minecraft/overworld/data/minecraft/game_rules.dat) is
  **true**; plugins are Geyser/ViaVersion/floodgate (none touch drops);
  Pebble's playerGameType is 0. And `loot give Kite mine 0 20 0 air`
  **dropped 1 cobblestone** from minecraft:blocks/stone (Kite even made
  the Stone Age advancement) — the loot table itself yields without a
  tool. So the dig path, not the table, loses the drop. Next: inspect
  the pickaxe's components in a live inventory.
- 18:41–18:52 — **stone drops after all** (the day-3 question, closed):
  probe-stone-drop.js, three runs. A feet-adjacent pickaxe dig
  auto-picked 1 cobblestone (0→1); bare hand gave nothing (vanilla);
  the repeat run left a cobble entity lying at distance 1.0 for 3+ s
  while the bot stood still — the server's pickup radius is tighter
  than range-1 collection — and the console confirmed the entity
  server-side (execute → "COBBLE_ENTITY_THERE", 09:48:22 local).
  Day two's "stone drops nothing" was instrumentation blindness:
  digs at reach distance, drops on the ground, nobody walking onto
  them. collectAt now stands IN the dug cell (dcd3191); the doc
  carries the Superseded block (§6 and the new §7).
- 18:52 — the world still had what day two thought spent:
  probe-woodseed.js reads 40 logs and 40 short_grass within 96 of the
  depot (8s chunk warm-up first). Day two's forage read before the
  chunks loaded. No operator debt for the farm bootstrap.
- 18:56:38 — the crew restarted onto all of day three's code
  (0b16505): the wheat cycle (tendWheat — ripe-only harvest, replant
  the same cell, bank the surplus, seed guard on the last stem),
  safe-keeping (a dig below y=58 banks seeds and the hoe at the chest
  first; keepInventory untouched — proposed to Casey in the doc
  instead), and the council's shelter gate on the world's own trunk
  count. First tick: needs [ramp, farm, shelter]; **b069 "a shelter
  by the depot" proposed → allow → ratified** (site 6,67,11; 23
  blocks). All four bots back, staggered 18:56:19–18:56:37Z. Ramp
  tests 9/9, drift suite 71 passed. The unattended stretch (the
  headline measurement) starts here.
- 19:06–19:36 — the first unattended half-hour bought three more
  catches, each fixed and committed: **(1)** the seed forage was
  level-blind (find_block's default band is feet±2; Pebble in the pit
  at y64 read "no seed grass within reach" while forty stems stood at
  y71 — the wood hunt's own gully blindness, on the seed path;
  gatherSeeds passes any_level now), and an empty run backed off 45 s
  instead of re-issuing every tick (the seed spin, 30 instant plays a
  minute, 04f4da9). The first honest seed run: 5 grass broken over
  170 s, 0 of 14 seeds — the drop rate is about one seed in eight
  stems; the wheat cycle is what makes seeds compound, the grind is
  real. **(2)** my own range-0 collection stood the builder IN the
  cell it was about to fill, and the server silently refuses to place
  a block where a player stands — "Server did not answer the
  placement", four timeouts on one wall cell; api.place steps one
  cell aside now (b0bd934). **(3)** the deepest: b069's site was
  inside a dense spruce grove — surfaceAt skips leaves and logs, so
  the spot read standable while trunks stood in the wall cells and
  the canopy filled the roof band (probe-site.js). The walk into the
  canopy pocket hung the planner itself (probe-walk-shelter.js:
  GoalNear unresolved after 170 s). The shelter planner now requires
  three clear cells above the ground across the footprint and tries
  eight candidate rings; buildPlanned names "cannot reach" instead of
  firing a doomed placement; b069 rides its stall clock to abandon
  (~20:27Z) and the next proposal recomputes on clear ground
  (0287291). TPS 20.0 throughout; grief 0.
- 20:29–22:10 — the evening chain, fixed link by link, to the
  boundary: **(a)** the staged-wood credit outlived the despawned
  delivery (b044's log staged 11:26Z day two, gone by 11:31; a
  ten-minute wait re-bills one unit now — c6a21aa, fired 20:29:54Z);
  **(b)** the wait timer stored on a board-folded project object
  never aged past one tick (module map now — 363a7ba); **(c)** a dig
  that paid nothing reported itself a win — the bag is the truth now
  (e71e9de; Pebble mined five spruce logs for an empty bag
  20:32–20:44Z, drops falling where the collector cannot stand); **(d)**
  the first tick after spawn ran the reflex before the crew was wired
  and dumped the project's bag at the depot pile (idle until shared
  exists — c817647; this is where every given material kept going);
  **(e)** a hoe in hand needs 2 planks AND 2 sticks, not 4 planks
  first (b06df52); **(f)** api.craft opened a bench window from
  twelve blocks away — walk first (65b8079), inventory recipe first
  (aaca66e). And the boundary: **the use-on-block packet does not
  work for mineflayer clients here** — chest opens, table opens, and
  the hoe's till all time out or land nothing (probe-chest.js ×2,
  bare-handed; the till 2.4 s per attempt from ON the plot after an
  operator tp 22:03Z). No farmland has ever existed in this world;
  the depot chest has never held one item. Dig works, place works,
  use does not. A clean save-all restart (12:50 local) did not change
  it. Next-seat work: the use packet on 26.1 (client or server side).
- Operator debts, the day's full list: 1 seed 20:49Z (swept from the
  pile by the scout), 1 log + 1 seed 21:02Z (dumped by the startup
  reflex), 1 log + 1 seed 21:31Z (the planks never split), 1 hoe + 2
  seeds 21:54Z (the till never lands), 1 tp Sprout to the plot
  22:03Z. The farm was never hand-built; the number stays the
  community's.
- 22:10 — the seat's close-out numbers: TPS 751/752 samples >= 19.5
  (one 18.7 at the clean restart), grief 0 (six player builds
  protected), MemAvailable min 34.4 GB, board done 2 / active 2
  (farm blocked on the use packet; shelter riding its stall clock,
  the fixed planner re-proposes on clear ground after the abandon).
  Projects done per hour today: 0 — the day bought nine fixes with
  their numbers, and named the two blockers. The seven processes run
  on: paper, reflex, bots, viewer, d1, drift-watch, community-watch.
- 22:15 — d1 had exited at some point in the evening (its tmux window
  gone; the reflex ran on its local bandit all night — the crew kept
  deciding, which is the design's own fallback proving itself);
  restarted via ops/d1.sh, port 8094, health ok. The seven run again:
  paper, reflex, bots, viewer, d1, drift-watch, community-watch.
