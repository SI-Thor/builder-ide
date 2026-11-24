# Luanti: what a later re-engineering phase would have to rebuild

The brief chose **both** engines, and then ordered them: Minecraft
Java (Paper) first and fully, Luanti in a later re-engineering phase.
Nothing was built for Luanti. This note says what would have to be
rebuilt, so that the choice is a plan and not a shrug.

Luanti (formerly Minetest) is the open lab: LGPL, and the engine is
ours to change. The reason to want it is not that it is another voxel
game — it is that **the engine can be changed**, so the things this
project keeps wanting (a text projection that is part of the world
rather than a viewer bolted onto it; a perception channel the mediator
authors; a server that knows what each builder can see) can be built
into the engine instead of around it.

Minecraft is the *host* for the proof of concept: it is what the
family already plays, so the proof of concept can be judged by the
people it is for.

---

## What carries over unchanged

Most of the system's value is not in the game.

| part | where it lives | does it change? |
|---|---|---|
| the **reflex** | d1-2B through builder-ide's judge (`core/judge`) | **no.** The decision model, the pack, the confidence gate and the attempt log are engine-agnostic. |
| the **chooser** | the contextual bandit over (context bucket, skill) | **no.** The same arms, the same propensity arithmetic. |
| the **mediator** | the cloud author and the feedback packets | **no.** "Write a better one; here is why it lost" does not care what world the skill runs in. |
| the **canon** | the SQLite ledger and the tile events | **no.** The same log, the same folds. |
| the **presence rule** | the memory floor and the yielding | **no.** |
| the **privacy rule** | no chat and no audio stored | **no.** |

So the re-engineering is **not** a rewrite of the system. It is a
second *host* for the same system, and the interesting question is what
the engine's openness buys.

## What has to be rebuilt

### 1. The agent's way into the world

mineflayer speaks the Minecraft Java protocol. There is no equivalent
for Luanti that is both mature and in Node, and building one is not the
point. The brief already allows the alternative: **a Lua-mod agent**.

A mod runs inside the server process, with the world's own API
(`get_node`, `set_node`, `find_nodes_near`, `get_player_by_name`,
`player:set_pos`, the item and inventory APIs). That is more power than
mineflayer has, which cuts both ways: the mod needs its own door.

**The rebuild:** a Lua mod that
- exposes the world's vocabulary to agent code (the same closed set the
  Node sandbox exposes: observe / act, nothing else);
- sandboxes the agent code, so an agent cannot reach `os`, `io`, the
  filesystem or the server's internals. Lua 5.1's `setfenv` gives a
  per-function environment; a proxy table refuses unknown words, the
  same way the Python door refuses unknown words;
- reports every action to the world, so the play record is complete
  without trusting the agent's own account of itself;
- exposes the **perception** the way the current builders do: the
  mediator's perception spec (§7 of `three-minds.md`) would become a
  data file the mod reads, so what a builder can see is authored by the
  mediator rather than fixed in the mod's code.

### 2. The seam between the world and the reflex

Today the reflex is a Python service on loopback and the builders are
HTTP clients. A Lua mod cannot speak that HTTP client easily (Luanti's
Lua has no general HTTP client in a mod; `request_http_api` is a
server-side helper, not a client).

**The rebuild:** a small bridge in the same shape as the current one.
The cheapest honest version is a **file-backed queue**: the mod writes
its state and its actions to a file in the world's runtime directory
(the world already has a ledger, a skill library and a log directory),
and the Python reflex reads it and writes back the choice. It is the
same seam with a different transport, and it keeps the reflex, the
chooser and the mediator in one language.

A richer version is a **mod channel**: Luanti's `mod_channel` is the
engine's own event bus, and the world's deltas could ride it — which
would make the *text world* a first-class view of the engine rather
than something a viewer computes (see §4).

### 3. The content

Minecraft's content is the trees, the wheat and the cobblestone; the
skills are written against those names (`oak_log`, `wheat_seeds`,
`cobblestone`). Luanti's default game has its own node names
(`default:tree`, `default:cobble`), and VoxeLibre/MineClone2 is the
Minecraft-shaped alternative.

**The rebuild:** either a content mod that provides the handful of
nodes the community's skills need, or a mapping layer between the
vocabulary and the engine's names. The second is better: the
vocabulary is the world's interface, and it should not be tied to one
game's item names. The seed skills would be re-written against the
vocabulary, and the *same* skill would then be able to run in both
worlds.

### 4. The views

**The 3D view** does not port: prismarine-viewer is mineflayer's
world model. For Luanti the options are the desktop client (a person
joins and sees the builders — which is the actual requirement), a
server-side screenshot service (`minetest.render_scene` can render
frames headlessly), or a web client (a large project of its own).

**The text view ports directly, and ports *better*.** The ASCII kernel
is integer arithmetic over a block grid, and Luanti's world *is* a
block grid — no chunk protocol, no entity packets, no ray marching
through a block registry. It would run inside the server, as a view
rather than as a viewer, which is exactly the direction the design
wants: "a text world that innately gives each agent their own
perspective without much compute" (`three-minds.md`).

This is the strongest argument for the later phase: **in Luanti the
text view can be part of the engine**, and the projector stops being
something that reads the world and becomes something the world is.

### 5. The measurement

Every number in the Minecraft proof of concept has to be re-measured:
the tick cost of a Lua agent against the Thor's cores, the memory of
the server with N agents in it, the decision model's latency through a
different transport, and the win rates of the same skills in a world
with different content. The *mechanisms* carry over; the numbers do
not.

## The order, if the phase comes

1. the Lua mod with the door and the vocabulary (no agents yet);
2. the file-backed bridge to the existing reflex — the same d1, the
   same chooser, the same ledger, the same skill library;
3. one role (the gatherer) ported as a skill, to measure the round
   trip;
4. the text view inside the engine;
5. the rest of the roles, and the perception spec.

Step 2 is the one that matters: if the reflex can be reused unchanged,
the second engine is a host, not a rewrite — and the experiment
becomes "does the same mind work in a different world", which is the
question the whole three-minds design is pointed at.
