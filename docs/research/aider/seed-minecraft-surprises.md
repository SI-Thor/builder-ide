# Seed-2.0-mini: what the Minecraft bots can learn that a builder-ide night cannot (2026-11-01, /ask)

► ANSWER                                                                        

6 Non-Obvious, One-Day Testable Lessons for LAN Minecraft Bots (Unlearnable by  
Infinigen Builder-IDE)                                                          

All tie to real-time shared physical world dynamics, vs Infinigen’s static,     
scripted overnight recipe runs:                                                 

 1 Physical signaling heuristics: Bots learn to communicate via world-state     
   pulses (2 quick cobblestone breaks = "need more materials") instead of cloud 
   chat or pre-written prompts—impossible in Infinigen’s isolated, cached       
   scenes. Test: 1-day wall-building task, count redundant chat eliminated via  
   block signals.                                                               
 2 Unscripted fault recovery: Unlike Infinigen’s pre-planned rollbacks, bots    
   adapt to real-time glitches (lava spawns, stuck pathing) via their d1 fast   
   model: e.g., a builder swaps to a water bucket to free a trapped miner. Test:
   1-day run with 5 random unscripted faults, measure recovery time vs cloud    
   scripts.                                                                     
 3 Dynamic resource zoning: Bots reallocate labor mid-task as the shared world  
   shifts—e.g., shifting miners to newly exposed diamond veins mid-castle build,
   no cloud recipe recompile needed. Test: 1-day castle build with hidden       
   mid-task ore spawns.                                                         
 4 Epistemic pause triggers: Bots wait for a cloud skill only when stuck (e.g., 
   unable to build a floating arch) instead of running on fixed Infinigen-style 
   schedules, avoiding wasted block attempts. Test: 1-day floating bridge task, 
   count wasted blocks vs scheduled cloud calls.                                
 5 Peer priority alignment: Bots use d1 to track peer progress and reallocate   
   idle work—e.g., a builder helps a lagging miner instead of sticking to their 
   original task, something Infinigen’s linear scripted bots cannot do. Test:   
   1-day uneven resource load task.                                             
 6 Dynamic state filtering: Bots learn to ignore irrelevant world changes       
   (chickens, leaf decay) and only sync task-critical state, cutting LAN        
   bandwidth far more than Infinigen’s fixed delta streams. Test: 1-day 8-bot   
   run, measure bandwidth usage with vs without filtering.                      


