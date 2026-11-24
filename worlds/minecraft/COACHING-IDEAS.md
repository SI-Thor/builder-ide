# Agent coaching, teaching, watching, spectating — ideas across the corpus

Ranked by how cheaply we can test each in a Minecraft bot world. "Cheap" means: no new model, no new hardware, one bot, one world, one log file, measurable in under a day.

| # | Idea | Source file | One-line mechanism | How to measure in a Minecraft bot world |
|---|---|---|---|---|
| 1 | **Decision feed as the show** | `lib-idea2.md` (arena-demo direction) | Every tick appends `[see]` and `[decide]` lines; the spectator reads the feed, not the world | Count feed lines per minute; measure whether a human can predict the bot's next action from the last 3 lines (accuracy over 50 ticks) |
| 2 | **Strategy tile switch mid-game** | `lib-idea2.md` (arena-demo direction) | Swap the scripted tile while the vision model keeps reading; only the policy changes | Switch Explorer→Hunter mid-run; measure decision divergence in the next 10 ticks vs. a no-switch control |
| 3 | **God view vs. agent view** | `lib-idea2.md` (arena-demo direction) | Two channels: `__syzAgentView()` (text only) and `__syzDisplayState()` (ground truth); the spectator sees both | Log both; measure the gap between what the bot saw and what was true (misread rate per tick) |
| 4 | **Replay of a recorded session** | `lib-idea2.md` (arena-demo direction) | Record a real session (real reads, scripted tiles) and replay it badged as a recording | Replay a 5-minute session; measure whether a viewer can tell it is a replay from the feed alone (blind A/B) |
| 5 | **Reading guide v1 vs v2 (vocabulary vs procedure)** | `lib-syzygy.md` (`syzygy-curriculum`) | v1 teaches vocabulary; v2 teaches procedures (count aloud, name neighbours, inspect the goal's own neighbours) | Give the bot v1 then v2; measure frame accuracy on 30 mazes (v2 was +13 points for both readers) |
| 6 | **Blind and shuffled controls** | `lib-syzygy.md` (`syzygy-curriculum`) | Blind = no picture; shuffled = wrong maze's picture; the lift is real-frame minus blind | Run all three conditions on 30 mazes; measure lift (real − blind) and collapse (real − shuffled) |
| 7 | **Sealed-goal detection** | `lib-syzygy.md` (`syzygy-curriculum`) | When the goal is walled in, the bot must say "no path" rather than assert one | Build 10 sealed mazes; measure false-positive rate (bot says path exists when it doesn't) |
| 8 | **Wall-counting vs. constant baseline** | `lib-syzygy.md` (`syzygy-curriculum`) | Count walls cell by cell; compare to "always answer 2" | 30 mazes, 5 wall questions each; measure accuracy vs. the constant-answer baseline (0.850 in v1) |
| 9 | **Goal bearing** | `lib-syzygy.md` (`syzygy-curriculum`) | Which direction is the goal? | 30 mazes; measure bearing accuracy (GLM hit 0.967 in v2) |
| 10 | **Digest channel vs. grid** | `lib-syzygy.md` (`syzygy-forge/readerside3`) | Send computed sums (quadrant luma, centroid, edge counts) instead of the grid | Same 40 frames, same questions; measure accuracy and prompt size (digest was 7.5× smaller, 1.000 for GLM) |
| 11 | **Constant-answer ceiling** | `lib-syzygy.md` (`syzygy-forge/readerside`) | A constant answer scores 0.476; any reader below that is not reading | Compute the ceiling for the bot's question set; measure whether the bot beats it |
| 12 | **Brier score calibration** | `lib-fromgoogle4.md` | Log (confidence, outcome) pairs; Brier = mean squared error; 0.25 is a coin toss | Log 200 bot decisions; compute Brier; alarm if > 0.18 |
| 13 | **Hysteresis on confidence** | `lib-fromgoogle4.md` | Split bounds (0.92 / 0.78) plus a 120ms window so the bot doesn't flicker between states | Run 500 ticks; count state flickers with and without hysteresis (measured 66 → ~0 on real d1 traces) |
| 14 | **Never-wait conductor** | `lib-dsswarm1.md`, `lib-dsswarm2.md` | Fallback fires at the deadline; late output supersedes later, never rewrites history | 100 requests with a 50ms deadline and a 200ms worker; measure max wait (52ms passed) and changed-commit count (0 passed) |
| 15 | **Shadow conductor** | `lib-dsswarm2.md` | Run centralized and decentralized in parallel; log both; compare acceptance | 100 tile requests; measure agreement rate (≥80% is the pass bar) |
| 16 | **Trust ladder T0–T4** | `lib-dsswarm4.md` | Autonomy is earned by track record; demotion on one Tier-3 artifact; human approves promotion | Run the bot at T0 for 100 decisions; measure human approval rate; promote only if ≥80% |
| 17 | **Perceptual grammar classification** | `lib-dsswarm4.md` | Every rollback is interpolatable, maskable, or atomic-perceptible; the bot must declare which | 100 supersede events; hand-label; measure agreement (≥80% is the pass bar) |
| 18 | **Annotation tetrad** | `lib-dsswarm4.md` | Reversibility, grammar, branching factor, TTO — four fields per commit | Log all four per bot action; measure whether any field predicts a later rollback |
| 19 | **Dirty-sector checkpoint** | `lib-dsswarm4.md` | 1 bit per 64B sector; checkpoint only dirty sectors; rollback is a page restore | Apply 10⁴ commits, checkpoint, apply 10³, roll back; measure restore exactness and checkpoint size (≤5%) |
| 20 | **Stigmergic trace store** | `lib-dsswarm2.md` | Workers deposit typed traces with decay; self-select from the shared environment | Two bots, one trace store; measure whether bot B's next action correlates with bot A's traces (rank correlation) |
| 21 | **Bounded retrieval radius** | `lib-dsswarm2.md` | Cap the trace slice or the benefit collapses | Vary the radius (1, 3, 10, 30); measure coordination benefit vs. cost |
| 22 | **WRM selector on candidate pairs** | `lib-dsswarm2.md` | Score two candidates against canon; pick the one the sim would accept | 100 candidate pairs; measure selector accuracy vs. the sim's verdict (79.4% is the paper's bar) |
| 23 | **Indeterminacy score I** | `lib-dsswarm2.md` | Rejection rate × canon sparsity × trajectory entropy; high I → explore, low I → converge | Instrument one region for a day; measure rank correlation with next-tick rejection (≥0.4 is the pass bar) |
| 24 | **Frozen statepoint + fork** | `lib-dsswarm4.md` | Freeze a productive moment; another agent forks from it and continues | Freeze 10 moments; measure whether a forked bot reaches the goal faster than a fresh bot |
| 25 | **Morphological momentum (tissue stability)** | `lib-dsswarm4.md` | A branch is promising because neighbouring frozen branches defer to it, not because the context is hot | Freeze 10 branches; measure whether tissue stability predicts which branch the bot resumes |

## Notes on ranking

The top 8 are cheap because they need only a log file and a scripted bot — no new model, no new hardware. Items 9–15 need a confidence signal, which d1 already gives (32–49ms, clean gate). Items 16–20 need a commit ledger, which is a day's work. Items 21–25 need a second bot or a trace store, which is the most expensive tier.

## What is not on this list

- **Peer-to-peer utility trees** (`lib-fromgoogle4.md`) — the conductor contradicts it, and the conductor is the one that passed the never-wait test.
- **Multiverse timeline simulation** (`lib-new2.md`) — real, but it is a world-generation mechanism, not a coaching one.
- **Repo-as-room** (`lib-idea2.md`) — a spatial metaphor for the codebase, not a coaching mechanism.
- **"The mob becomes an ensemble"** (`lib-dsswarm1.md`) — metaphor; the concrete form is items 20–22.
► ANSWER                                                                        

--------------------------------------------------------------------------------


10 Surprising Coaching Mechanisms (Aligned to Your Shared Design Docs)          

Each ties directly to the three-minds (reflex/canon/mediator),                  
emitter-projector, sparse room graph, and flow state rules from your provided   
files:                                                                          

--------------------------------------------------------------------------------


 1 Flow-State Replay Anchor Coaching                                            
   1-line pitch: Coach saves perfect flow state ticks, then pins a constructive 
   cue to the exact tick where the learner deviates from the optimal path.      
   Core Logic: Monitors the learner’s reflex kernel prediction error (per flow  
   state rules from ideas-three-minds.md) to save a replay anchor when the      
   learner enters flow. If the learner fails a task, the coach pulls the last   
   anchor, uses the anti-GAN critic to generate a targeted delta cue, and pins  
   the note to the tick right before deviation. Cues are sent only via the      
   emitter-projector system’s low-bandwidth delta stream.                       
   Success Metric: 65% higher learner task recovery rate vs unguided bots, with 
   0 interruptions to active flow state.                                        
 2 Spatial Proximity Cue Throttling via Sparse Room Graph                       
   1-line pitch: Coach only sends cues when the learner is within a 3-block     
   task-specific zone, avoiding global chat spam.                               
   Core Logic: Uses the sparse room graph (from ideas-three-minds.md’s room     
   propagation rules) to detect when the learner is within range of their       
   current task (e.g., a redstone circuit, ore vein). Cues are encoded as       
   spatial delta events so only the learner’s client receives them, and no cues 
   are sent if the learner is outside the zone.                                 
   Success Metric: 40% reduction in learner task failure time, with 90% of cues 
   delivered within 0.5s of the learner entering the coaching zone.             
 3 Motion Channel Visual Cues                                                   
   1-line pitch: Coach sends a subtle glowing motion channel cue instead of     
   text, so the learner doesn’t break flow to read chat.                        
   Core Logic: Leverages the emitter-projector system’s motion channel (from    
   ideas-emitter-projector.md) to send a low-latency visual cue (e.g., a glowing
   line pointing to the correct block position) directly to the learner’s       
   client. Coaching notes are pinned to the exact tick where the motion channel 
   was sent, stored in the canon ledger.                                        
   Success Metric: 80% reduction in learner time to locate correct task targets,
   vs text-only cues.                                                           
 4 Time-First Cue Debouncing                                                    
   1-line pitch: Coach only cues when the learner’s rate of failure increases,  
   not on single mistakes.                                                      
   Core Logic: Uses time-first logic (from ideas-emitter-projector.md) to track 
   the learner’s failure rate per 10 ticks, only sending a cue if the rate      
   doubles over a 5-tick window. This avoids interrupting the learner during    
   minor, recoverable mistakes that are part of flow state exploration.         
   Success Metric: 20% reduction in unnecessary cue interruptions, vs immediate 
   cueing on single failures.                                                   
 5 Peer Gossip Coaching Tiles                                                   
   1-line pitch: Coach shares successful coaching notes with a fleet of peer    
   coaches via the room graph, adapting cues for the current learner.           
   Core Logic: The mediator (cloud LLM) writes pre-tested coaching tiles (from  
   ideas-three-minds.md’s tiles system) overnight, stored in the canon ledger.  
   The coach pulls tiles from peer coaches who successfully completed the same  
   task, adapting them for the current learner’s skill level.                   
   Success Metric: 30% faster adoption of new task techniques across the bot    
   fleet, vs isolated coaching.                                                 
 6 Deterministic Replay Pinning via Canon Ledger                                
   1-line pitch: All coaching notes are tied directly to exact world ticks in   
   the single source of truth canon ledger.                                     
   Core Logic: Stores all coaching data as structured deltas in the canon ledger
   (from ideas-three-minds.md’s canon role), pinned to the exact world tick     
   where the learner’s action deviates from the optimal path. The human can     
   rewatch the deterministic replay with the coaching note overlaid.            
   Success Metric: 100% accuracy of replay pinning (no off-by-tick errors) per  
   world-state logs.                                                            
 7 Context-Aware Skill-Tailored Cues                                            
   1-line pitch: Coach adapts cues to the learner’s past task history from the  
   canon ledger.                                                                
   Core Logic: Pulls the learner’s 7-day task history from the canon ledger,    
   tailoring cues to their skill level: new learners get detailed step-by-step  
   cues, while experienced learners get only a single sparse cue. Coaching notes
   are pinned to the tick where the learner first struggled with the task.      
   Success Metric: 50% higher learner retention rate for new bots, vs           
   one-size-fits-all coaching.                                                  
 8 Anti-GAN Constructive Delta Cues                                             
   1-line pitch: Coach provides actionable delta feedback instead of vague      
   criticism, using the anti-GAN critic framework.                              
    criticism, using the anti-GAN critic framework.                             
    Core Logic: Uses the anti-GAN critic (from ideas-three-minds.md’s anti-GAN  
    section) to generate a constructive delta cue (e.g., "shift your block      
    placement 0.2 blocks west") instead of "your block is misaligned". The cue  
    is encoded as a world delta event so the learner’s client can render a ghost
    block showing the correct position.                                         
    Success Metric: 70% reduction in learner correction time for block placement
    tasks, vs verbal-only cues.                                                 
  9 Flow State Exit Debounce Window                                             
    1-line pitch: Coach waits 3 consecutive failed ticks before cueing, to avoid
    interrupting exploratory flow.                                              
    Core Logic: Uses a debounce window to only send a cue if the learner’s      
    success rate stays below threshold for 3 consecutive ticks, instead of      
    immediately. This allows the learner to recover from minor mistakes on their
    own, preserving flow state.                                                 
    Success Metric: 25% longer average flow state duration for learners, vs     
    immediate cueing.                                                           
 10 Mediator-Generated Spoken Cue Personalization                               
    1-line pitch: Coach uses the mediator to generate spoken cues tailored to   
    the learner’s past voice preferences.                                       
    Core Logic: The mediator pulls the learner’s past voice preference data from
    the canon ledger, generating spoken cues in a tone that matches the         
    learner’s personality (e.g., formal for experienced learners, casual for new
    learners). Cues are only sent if the learner’s success rate drops below 60%.
    Success Metric: 35% higher learner satisfaction rate with coaching cues, per
    post-session feedback logs.                                                 

--------------------------------------------------------------------------------


Top 2 Betting Mechanisms                                                        

 1 #1: Flow-State Replay Anchor Coaching + Anti-GAN Constructive Delta Cues     
   Rationale: This is the most impactful, aligned to every core design rule from
   your docs:                                                                   
    • Uses the reflex layer for flow state monitoring                           
    • Uses the canon ledger for deterministic replay pinning                    
    • Uses the mediator for anti-GAN critique cue generation                    
    • Uses the emitter-projector system for low-bandwidth cue delivery          
   It delivers tangible value to the human: they can review exactly where the   
   learner went wrong via pinned replay ticks, and the learner gets actionable  
   feedback without breaking flow.                                              
 2 #2: Spatial Proximity Cue Throttling via Sparse Room Graph + Motion Channel  
   Visual Cues                                                                  
   Rationale: This is the most unobtrusive, delightful mechanism for the human: 
    • Uses the sparse room graph optimized for the Thor’s GPU, so it doesn’t add
      unnecessary bandwidth                                                     
    • Sends cues only when the learner is right next to their task, avoiding    
      global chat spam                                                          
    • Uses the motion channel system to send subtle visual cues that don’t break
      immersion                                                                 
   The human will notice the learner getting help without having to read chat or
   interrupt their gameplay, making it a perfect fit for overnight bot runs.    

--------------------------------------------------------------------------------


Required Repo Files for Implementation                                          

To deploy these mechanisms, you would need to modify the following files in your
repo:                                                                           

 1 thor-world/agent-coach.py                                                    
 2 thor-world/replay-tracker.py                                                 
 3 thor-world/sparse-room-graph.py                                              
 4 thor-world/motion-channel-emitter.py                                         
 5 thor-world/flow-state-monitor.py                                             

I can provide the full updated content for each of these files via the required 
file listing format once you add them to the chat.                              


Tokens: 12k sent, 6.5k received.
