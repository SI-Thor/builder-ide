# PLAY — joining the agents

One page. The world is **Minecraft Java 26.1** on the Thor, LAN-only,
open to anyone on the house network (the whitelist is off while we
playtest). Four agents live there: **Pebble** (gatherer — chops wood,
mines stone), **Timber** (builder — raises the wall), **Kite** (scout —
walks the boundary, notices arrivals), **Sprout** (farmer — breaks new
ground, plants). They keep working whether you are there or not.

## Joining

| | |
|---|---|
| **Java (the laptop)** | Minecraft Java **26.1** (the current release) → Multiplayer → Direct Connection → `192.168.0.78:25565` |
| **Bedrock (tablets, phones)** | Minecraft Bedrock → Play → Servers → Add Server → address `192.168.0.78`, port `19132` (UDP). **The device must be signed into its Xbox/Microsoft account** — Bedrock itself requires that for online play, and our bridge honours it; a free account is enough, and no Java copy is needed |
| **Watch instead** | `http://192.168.0.78:8080/` — the 3D view from any browser; `http://192.168.0.78:8080/ascii` is the same world in text; `http://192.168.0.78:8080/voices` speaks the agents' lines |

No Java account is needed for our LAN door (the server is offline-mode).
Bedrock joins arrive through Geyser + Floodgate; the name gets a small
mark in front of it (`.` or `*`). One honest limit, measured on
2026-11-02: an *anonymous* Bedrock client (no Xbox sign-in) is refused
with "Please log into Xbox to join this server" — Geyser 2.12.1 takes
no unauthenticated Bedrock sessions whatever the config says. Real
signed-in devices are the supported path. If a recent Bedrock client is
rejected over its *version*, ViaVersion is already installed to bridge
(Geyser 2.12.1 targets Minecraft 26.3; the world runs 26.1.2) — tell us
the version number on the title screen.

## Talking to the agents

Say a line in normal chat (T). They answer in chat — and out loud on
the voices page. You can name one to pick who answers ("Pebble, come
here"), otherwise the nearest one takes it.

| say | what happens |
|---|---|
| `follow me` | the nearest one follows you around |
| `stop` | everyone stops what they were doing for you |
| `come here` | the nearest one walks to you |
| `gather wood` / `gather stone` | Pebble chops or mines it and brings it to **you** (a few minutes — it is really doing it) |
| `help me build` | Timber comes to you; place two blocks in a line and he carries the line on, or hands you materials |
| `what are you doing?` | the nearest one says what it is up to |
| `what are you building?` | the community's own answer: the projects on the board, with their progress |
| `build a farm` · `plant trees` · `build a chest` · `build a shelter` | your request becomes a project on the community's board, checked by the same rules as theirs — if the ground allows it, the crew takes it up |
| `go home` | the nearest one walks back to the depot |
| `help` | the short version of this table |

## What to expect, and the limits

- Kite greets you when you arrive (once every ten minutes, not every
  reconnect) — and the greeting tells you what the community is
  building and how to lend a hand.
- **The community keeps working whether you are there or not.** A
  council picks the next project from what the world needs (a chest at
  the depot so goods stop landing in a pile, the forest replanted, a
  farm, a path, a shelter); the gatherer supplies, the builders build
  to the plan, and Kite walks the finished work and files what is
  missing. Every project and every block it places is checked against
  the world's rules first — including yours: a plan that would build
  over your blocks is refused before it starts.
- **They never touch your stuff.** Blocks you place are yours: they
  won't mine them, they won't build within a few blocks of them, they
  won't open a chest you placed, and they never attack a player. Say
  `help me build` to invite Timber to build beside you.
- Your chat is never recorded anywhere — only the agents' own words and
  decisions are logged.
- The world runs at low priority on the Thor; if the box gets busy the
  agents pause politely and resume.
- Known limits: Pebble delivers at your feet — stand still for it;
  "gather" can fail honestly ("nothing came of it") when the forest or
  stone is far; Timber carries a line only in a straight run of your
  last two blocks.
