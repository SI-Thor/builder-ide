# BEAM prior art in our idea docs (DeepSeek library, 2026-11-01, capped at 15 rows)



Strongest ideas about large agent networks, actors, supervision, hot reload,    
distribution                                                                    

| # | Source file | Idea | BEAM or something else? |                            

|---|---|---|---|                                                               

| 1 | lib-beam-quilt.md (FOUNDATIONS.md) | "Per-process heaps with copied       
messages, selective-receive mailboxes (a patch's inbox is the natural           
seam-arbitration chokepoint), supervision trees with restart-intensity          
escalation, monitors/links, two-generation hot code swap" | For BEAM — the most 
concrete endorsement in the corpus |                                            

| 2 | lib-beam-quilt.md (FOUNDATIONS.md) | "Explicitly not pulled: distributed  
Erlang's full-mesh, cookie-trust, kill-the-loser name-resolution layer — it     
assumes the uniform-trust cluster edge hardware is not" | Against BEAM's        
distribution layer — only the process layer is pulled |                         

| 3 | lib-beam-quilt.md (README) | "Like processes on the BEAM virtual machine, 
patches share no state; influence is only ever a proposal sent across a seam,   
and the receiver's own transition decides" | For BEAM — process isolation as the
model for patch sovereignty |                                                   

| 4 | lib-beam-quilt.md (SPEC.md) | "P6 — Haltable. It can be stopped, and its  
station survives its absence; nothing downstream may require this specific      
instance" | For BEAM — haltability is a supervision property |                  

| 5 | lib-beam-quilt.md (SPEC.md) | "P4 — Active log (sovereign readings). It   
MUST NOT read or write another patch's log or state directly" | For BEAM —      
per-process state is BEAM's model |                                             

| 6 | lib-beam-quilt.md (PROGRAM-MAP.md) | "continuum-runtime (new repo) — the  
runtime. A Rust runtime over the chrono-tensor event stream" | Against BEAM —   
the runtime is Rust, not BEAM |                                                 

| 7 | lib-si-repos.md (plato-engine-block-elixir) | "BEAM supervision trees,    
fault tolerance, hot reload" — a shipped Elixir implementation of the PLATO room
| For BEAM — already in the fleet |                                             

| 8 | lib-dsswarm1.md | "The most important move is to not let models talk to   
each other directly... adopt a centralized conductor that owns the authoritative
'score'" | Against BEAM — a central scheduler, not peer-to-peer mailboxes |     

| 9 | lib-dsswarm2.md | "The Acephalous Fourmilière architecture does exactly   
this: LLM agents coordinate without any central orchestrator, through stigmergy"
| For BEAM — no central orchestrator is BEAM's model |                          

| 10 | lib-dsswarm2.md | "Let the Swarm Invent Its Own Roles Instead of         
Assigning Them" — 25,000-task experiment, 8 models, 4–256 agents, "5,006 unique 
roles from just 8 agents" | For BEAM — emergent roles are BEAM's                
supervision-tree shape |                                                        

| 11 | lib-dsswarm2.md | "Learn One Local Law Instead of Designing a Global     
Topology" — Waggle, 58.2% vs ~15% at 64 agents | For BEAM — a local law is      
BEAM's per-process behavior |                                                   

| 12 | lib-dsswarm3.md | "No agent writes code for a component it also          
verifies." — separation of powers | For BEAM — separation of powers is BEAM's   
supervision |                                                                   

| 13 | lib-dsswarm3.md | "Runbooks — What To Do When an Alarm Fires" — numbered 
steps, deviations logged | For BEAM — runbooks are supervision trees in prose | 

| 14 | lib-dsswarm4.md | "Team Topology — Ownership and Separation of Powers" | 
For BEAM — same shape |                                                         

| 15 | lib-new2.md | "The Reactive Cell Substrate: quilt-pincher/src/cell.rs" — 
ReactiveCell with RwLock<ReactiveLogic>, StableGraph, BFS cascade | Something   
else — Rust with parking_lot locks, not BEAM |                                  


The first experiment                                                            

Build a 4-bot Minecraft fleet in two runtimes — one Elixir/OTP supervision tree 
(one GenServer per bot, a Supervisor per squad, :pg for group messaging), one   
Rust tokio equivalent (one task per bot, a JoinHandle supervisor,               
tokio::sync::broadcast for group messaging) — and run the same scripted         
10-minute scenario on both: 4 bots, then 20, then 100, then 200, each bot       
issuing one action per second against a local Minecraft server. Measure three   
things: (a) crash recovery — kill one bot process mid-run and measure           
time-to-respawn and whether the other bots' action cadence is disturbed; (b) hot
reload — swap the bot's strategy module while the fleet is running and measure  
whether any bot drops a tick; (c) message fan-out cost — measure p99 latency of 
a broadcast to all bots at each fleet size. The BEAM case pays off if it wins on
(a) and (b) at 100+ bots without losing (c) — because those are the two         
properties the corpus keeps naming as load-bearing (haltability, hot swap) and  
the two that Rust's tokio makes you build by hand. If BEAM loses on (c) at 200  
bots, the experiment has told you the fleet is too small for the supervision win
to matter, and the Rust path is the right one.                                  


