# voyager-port lab scripts

The scripts that produced the numbers in
[`docs/lab/exp-voyager-port.md`](../../exp-voyager-port.md). They live beside
the report so that every number in it can be produced again.

**What they need.** The Thor, `~/lm-wt/voyager-port` checked out, the seat's
virtualenv (`.venv`), a private Paper sandbox in `mc-sandbox/` (see
`setup_mc_sandbox.sh`), and a DeepInfra key in `~/.config/last-mile/secrets.env`.
The probes that only read the world need the sandbox up; the measured run
needs it up as well.

**The order they are run in.**

| step | command | takes |
|---|---|---|
| make the sandbox | `bash setup_mc_sandbox.sh` | 2 min |
| start it | `bash start_mc_sandbox.sh --detach --exec` | 40 s |
| empty the bot's hands | `bash run_reset.sh` | 2 s (the server must be stopped) |
| measure | `VOYAGER_HOURS=0.5 bash run_measurement.sh` | the hours you ask for |
| read the numbers | `cat results/minecraft-run.json` | — |

`run_measurement.sh` detaches the run and writes
`results/minecraft-run.log`; the report payload is
`results/minecraft-run.json`, one line per turn is
`results/minecraft-steps.jsonl`, and the skill library and its ledger events
are `results/minecraft-ledger.sqlite3` and `results/bodies/`.

**The probes.** Each one answers one question about the stack that is
actually installed, and each is cheap.

| script | what it answers |
|---|---|
| `probe_models.py` | are the three model roles reachable, and what do they cost |
| `probe_diag.js` | where is the tree, and has the client got the chunks |
| `probe_diag2.js` | what protocol version, how many recipes, what packets |
| `probe_diag3.js` / `probe_diag4.js` | how the recipe book is keyed |
| `probe_scan_cost.py` | what a scan costs at each radius |
| `probe_tech_tree.py` | the wood → stone → iron chain, played by hand |
| `probe_trees.py` / `probe_surroundings.py` / `probe_minecraft.py` | what is around the spawn |
| `drive_bridge.py` | drive the bridge by hand, with its stderr in a file |
| `probe_planner_reply.py` | why the planner's reply sometimes has no JSON in it (the cap cut it) |
| `probe_verifier_reply.py` | what the verifier returns for the call the run actually makes |
| `probe_crafter_adapter.py` | the crafter adapter's whole port, for zero tokens |
| `dump_level.js` / `dump_player.js` | the world's and the bot's saved NBT |
| `move_bot.js` | put the bot at the tree |
| `reset_hands.js` | empty the bot's inventory before a measured run |
| `place_spawn.js` | move the world's spawn |

**The dead ends.** These are the things that do not work, so that nobody
spends an hour on them again: `rm -f` is refused by the seat's command gate;
`ops.json` and `place_spawn.js` cannot be written with a literal
`/setworldspawn` or `/tp` in the heredoc (write the command as `'/' + text`);
`bot.registry.itemsByName[name]` is an object, not a number; `prismarine-block`
and `prismarine-recipe` export a loader that needs `(bot.registry)`;
mineflayer-pathfinder 2.4.5 emits neither `path_complete` nor `path_blocked`
nor `path_timeout`; `findBlock`'s `maxDistance` is not a sphere radius; Paper
restores a missing `.dat` from the `.dat_old` beside it, so both have to be
moved aside; and the `write` tool is refused by the same gate, so the files
are staged in `/tmp` and copied over with `scp`.
