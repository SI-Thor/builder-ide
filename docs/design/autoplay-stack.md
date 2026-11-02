# The auto-play stack: where each common tool fits our system (2026-11-01)

Casey shared another agent's lists of systems used for auto-playing and asked how ours can synergise with them, and to build out the repos. **The principle:** adopt the *standards* (APIs, dataset formats, benchmarks), so the whole ecosystem plugs into our world. Keep our own architecture (three minds, tiles, the canon, thor-admit), where it is already measured.

| Tool | Licence | Verdict | How it fits |
|---|---|---|---|
| **Gymnasium** (Farama) | MIT | **Adopt** | Wrap agent-world (and Crafter, and later night tasks) as Gymnasium environments: obs = the integer text view or state; actions = skills/tiles or primitives. Every RL tool then plugs in |
| **Minari** (Farama) | Apache-2.0 | **Adopt** | The format for **every watched demonstration**: teacher episodes, bot sessions, opt-in human play (state only). Offline RL and behaviour cloning read it |
| **Stable Baselines3** | MIT | **Adopt (baselines)** | PPO/DQN/SAC students on Gymnasium envs: the honest baseline for "does watching a teacher beat learning alone?" |
| **Crafter** | MIT | **Adopt (the fast lab)** | A 2D Minecraft-like survival world: thousands of episodes an hour on the Thor's CPUs, presence-tier. Every teacher–student experiment runs here first, then in the real world |
| **World Models** (Ha & Schmidhuber) | reference code | **Learn from** | The "imagination gate": check a skill in a learned model before admitting it (dsmc). Rebuild the idea on our stack rather than vendoring |
| **TextWorld** (Microsoft) | MIT | **Evaluate** | The text-world half of three-minds: train and test the mediator where the world *is* text |
| **MineRL** | code MIT; **data has its own terms** | **Evaluate (data)** | Large human Minecraft demonstrations as a teacher; check the dataset licence and Minecraft EULA terms before use |
| **Voyager** | MIT | **Already ours in spirit** | Skills-as-code is our tiles; agent-world built on that lineage (CraftMind) |
| **GVGAI** | — | **Watch** | A cross-game generality benchmark, for later |
| **Unity ML-Agents** | Apache-2.0 | **Skip** | Not our engine; its idea (side channels, curriculum) is noted |
| **JARVIS/GAIA, PyAutoGUI** | MIT/BSD | **Watch only; act carefully** | The screen watcher's *actuator* side. Watching, yes. Acting on Casey's real desktop needs his explicit OK per use |
| **LangChain, AutoGen** | MIT | **Skip** | We have our own orchestration (the seats, the canon, thor-admit), measured |
| **llama.cpp, Ollama** | MIT | **Already used** | llama.cpp serves d1 and the local coder; Ollama is off on the Thor (disk) |

## Build-out (queued)
1. **`agent-world-gym`:** a Gymnasium environment over the live agent-world, plus a **Minari recorder** for every session (bots, teacher, opt-in human state). On a branch of SuperInstance/agent-world.
2. **`crafter-lab`:** Crafter + SB3 on the Thor's CPUs (presence tier). The first watching-teachers experiment:
   - a student that learns only from surprise-filtered teaching moments of a teacher (scripted first, then an LLM agent);
   - against learning from all of the teacher's frames, against PPO alone.
   - Measure agreement, success, and teacher calls per hour.
3. **`thor-watcher`** (later, a SuperInstance repo): the screen-watcher engine, packaged (the change-stream gate, intents in the canon, the teaching-moment filter), once the seat-watcher and crafter-lab experiments say what works.
