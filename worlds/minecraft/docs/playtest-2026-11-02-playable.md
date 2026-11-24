# The playable round, measured (2026-11-02)

Casey's bar (13:40, 2026-11-01): *"I want the minecraft to be playable
with the agents live."* This note is the proof and the honest limits.
Every number below was produced by a committed script; the box state
accompanies each. The scripts: `bots/probe-human.js` (the join),
`bots/probe-commands.js` (the service), `bots/probe-grief.js` (the
no-grief rule), `ops/steady.sh` + `ops/tps-window.sh` (the steady half
hour).

- **The world**: Paper 26.1.2-74 (`26.1.2-74-ver/26.1.2@e4e17fc`,
  protocol "26.1"), LAN-only at `192.168.0.78:25565` (Java) and
  `:19132/udp` (Bedrock through Geyser), heap capped 6 GB, `nice 10`,
  whitelist **off for playtest** (`AW_PLAYTEST=1`; a restart used to
  re-arm it from the template — the 15:10 battery was refused at the
  door until the knob existed).
- **The crew**: Pebble (gatherer), Timber (builder), Kite (scout),
  Sprout (farmer); one shared d1-2B (port 8094) behind the reflex
  (loopback 8110); tick 2 s. Play.md is the one page for players.

## 1. Joining, proved by a client

TestHuman9 (bots/probe-human.js, 00:52 UTC window; box: load 11,
86 GB free, crew + watcher + d1 live):

| step | result |
|---|---|
| join to spawn | **0.4 s** |
| greeting (Kite, once per person per 10 min) | **1062 ms** |
| moved (walk+jump, 2.5 s) | **9.0 blocks** |
| chat | one marked free-text line |
| broke a block | `coarse_dirt` — verified gone, not just dug-at |
| placed one back | **yes**, into its own hole |

**Privacy, checked not assumed**: 0 occurrences of the marked
free-text (or any human chat) in `runtime/logs/bots.jsonl` across all
joins; the only records naming a TestHuman are the crew's own `say`
lines. The probes taught two lessons the world's api already knew: a
dig is a packet, not a promise (look first, verify after), and a drop
takes seconds to land in a hand.

## 2. The commands, each timed

From the batteries (the last full run 04:26 UTC; earlier runs named
where they differ). Each time is send-line → world-answer:

| command | answered by | result | time |
|---|---|---|---|
| `what are you doing?` | nearest | says the live job | ~1.4–4 s |
| `Pebble, what are you doing?` | Pebble | its own job | ~1–4 s |
| `follow me` | nearest | follows; catches up when you stop | closed 3 blocks instantly; from 37 blocks it closes but can lose the thread in rough country |
| `stop` | all | stops, one ack, visibly still 5 s | ack **400 ms** |
| `come here` | nearest | arrives within reach | from ≤8 blocks, seconds; from 35+ blocks over rough ground it can fail its 150 s |
| `gather wood` | Pebble | works the whole job honestly | ack **400 ms**; outcome below |
| `gather stone` | Pebble | mines stone, delivers | ack 400 ms; delivery races the shared depot pile |
| `help me build` | Timber | comes, stands by, carries your line on | arrives when near; the carry-on went unproven tonight (the test's own placements failed at its spots) |
| `go home` | nearest | walks to the depot | duty holds a 5-minute clock; not run to completion tonight |

**gather wood's honest story** (worth reading): the ack is instant;
the work is real — the gatherer searches, walks out, retries from new
ground (three looks, each said aloud: "nothing there, TestHuman —
trying farther out"), and reports "nothing came of it" when the world
gives nothing. The spawn forest is gone (a night of chopping; trunks
stand again only within a few blocks of the depot), and for most of
the night Pebble was stranded at **bedrock** (y=0, 72 below the depot)
— the whole crew had mined itself into a pit. v13 of gatherer.wood now
goes home for the forest first; the pit-stranding and the
plant-nothing economy are the mediator's jobs, written down for it.

**No model on the path**: a fixed table parses the phrase
(humanity.js), routing is deterministic (named / role-owner / nearest),
duties are walked by mineflayer's planners; only `gather` asks the
reflex for a family skill, through the same chooser and play record as
any other play (the `/decide` grew a `family=` filter for this). A
follow now walks with its own movements (no digging, parkour allowed —
the work movements stall a few blocks from a moving target forever)
and un-wedges itself when it stops making progress, the same nudge the
walks have always used.

## 3. Never grief

Rules (through the api every skill uses, and the pathfinder's
`safeToBreak`): never mine a placed block or within 4 blocks of one;
never build within 8 unless the person said `help me build` (a
10-minute invite); never open a person's chest; never attack a player.
Ledger: a block that appears while a person is within 6 blocks is
theirs, persisted to `runtime/logs/player-builds.jsonl`. 14 offline
tests pin the rules (`bots/test/no-grief.test.js`).

Live proof (probe-grief, 06:01 UTC): TestHumanH dug and placed two
`coarse_dirt` by hand; **Timber was working 4 blocks away** (Kite 20,
Sprout 19); both placements were recorded by the ledger the moment
they landed; after the watch, **still standing: 2 of 2**. An earlier
run (05:30 UTC, crew 13–35 blocks) also held 2 of 2.

Said plainly: for most of the night the ledger was silently dead — the
crew's humansNear read `player.position`, a field mineflayer never
sets, so every observation threw inside its own catch. The blocks
survived those runs by luck of geography, not by rule; the one-line
fix (read the entity) went in at 06:00 and the proof above is the
first under the rule. `bots/probe-observe.js` is the two-client
replica that isolated it.

## 4. Steady with a person on, 31 minutes

`ops/steady.sh 31` holds TestHuman (wanders every 30 s, digs and
places every 2 min, asks the crew a question every 5 min) and samples
every 30 s. 20:26–20:57 local (05:21–05:57 UTC), box also carrying the
grief and gather probes (load 13–28):

| measure | bar | result |
|---|---|---|
| TPS (1m) | ≥ 19.5 | **63/63 samples ≥ 19.5; min 19.9, median 20.0** (ops/tps-window.sh over the same window — the console's answers, ANSI and all, are timestamped in paper.log) |
| MemAvailable | ≥ 30 GB | **min 78.9 GB**, median 95 GB |
| d1 latency | unchanged | running mean 3.7 ms before → **6.0 ms** during (still single-digit milliseconds under a person plus probes; the night's CPU-only judge ran ~58 ms) |
| the pack (all bots, one call) | — | 7.0 ms mean |

## 5. The Bedrock door, measured

- RakNet answers on UDP 19132 (Geyser shipped with `transport:
  nethernet` — WebRTC only — so no LAN Bedrock client could even ping
  it; now `both`).
- ViaVersion 5.12.3 installed: Geyser 2.12.1 targets Minecraft 26.3,
  the world runs 26.1.2, and Geyser itself said so at every boot.
- An **anonymous** Bedrock client (bedrock-protocol 3.59.0,
  `bots/probe-bedrock.js`) is refused: "Please log into Xbox to join
  this server" — across auth-type online/offline/floodgate, a reload
  and two restarts. What a person must do: sign the device into its
  Xbox/Microsoft account (Bedrock requires it for online play; free),
  then add server `192.168.0.78:19132`. **Untested here — no Bedrock
  device on this seat; the signed-in path is the one thing not
  proved.**
- Java clients: 26.1.x joins directly at `192.168.0.78:25565` (proved
  by every probe above, all of them Java-protocol clients).

## The night's incidents, for the record

- **The Thor lost power ~01:05 UTC** (second reboot in two days; it
  was load ~11 with 86 GB free). Everything restarted from the ops
  scripts; the world saved cleanly.
- The cut left one audit row with an empty id inside builder-ide's
  ledger (the box died between the placeholder INSERT and its UPDATE);
  every play then collided with it ("UNIQUE constraint failed:
  audit.id") until one UPDATE healed the row. The JSONL log of record
  refolded unchanged (41,357 plays). The dead DB is parked at
  `runtime/ledger-broken-20261102/`.
- tmux panes shuffled across the restarts, and the steady run's "tps"
  went to a bystander bash for a while; the console pane is now found
  (the pane whose terminal java was born on), not assumed.

## What is left, and the risks

- The **carry-on** of `help me build` and `go home` to completion were
  not witnessed tonight — the test's own footing kept failing. The
  pieces (arrival, invite, line detection, placement through the
  guarded api) are each exercised; the whole path wants one clean run.
- The **depot is a pile on the ground**: a delivery can lose its goods
  to whichever builder (or the Watcher, who stands there) sweeps it.
  The gather retries blunt it; the real fix (a chest with an inventory,
  or delivering straight from the dig) is mediator territory.
- The crew mines itself into pits (Pebble spent hours at bedrock) and
  the spawn forest is gone — both are skill-library work (depth-minding,
  tree-planting), exactly what the mediator is for.
- follow/come from 35+ blocks over rough ground can still fail their
  clocks: the walks unwedge and retry, but a 72-block climb out of a
  quarry is beyond tonight's movements.
