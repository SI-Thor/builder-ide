
► ANSWER                                                                        

 1 Code changes needed? No.                                                     
 2 Explanation: You asked for a comparison of the read-only design docs and     
   explicitly said “No file changes.” This is a gap analysis, not a change      
   request, so no files need to be edited and no file listings are output.      
 3 Changes needed? No — therefore no file listings are provided.                

Presence                                                                        

 • GPU pre-emption is SIGSTOP, not stream priorities. Three-minds: “live work   
   pre-empts it at once (memory leases, stream priorities)”. Thor-admit         
   §8.2/§11.7 uses SIGSTOP (whole process group) and cannot set CUDA stream     
   priority inside an arbitrary job. Smallest change: correct three-minds to    
   “SIGSTOP (giving up the GPU’s streams)” and keep stream priority as §11.7    
   open work; or add an optional stream_priority field to presence_add the job  
   honors (daemon only passes it).                                              
 • “Soaks every gap” assumes work exists. The presence queue is a file, empty by
   default (§11.6); the daemon runs only registered jobs and cannot know what   
   should run. Smallest change: ship a default presence.json with the four      
   recurring jobs (or have the night runner register them); the ledger’s        
   no_work_registered already measures the unsoaked gap.                        
 • Ledger does not show each player’s groove. Three-minds: “a d1 per character, 
   the critic… each in its own groove”. The ledger books by tier only (§8.4);   
   labels are known to leases/history but not broken out. Smallest change: add a
   by_label map (or labels inside each tier) to the ledger so each player’s     
   running/preempted seconds are visible.                                       

Band                                                                            

 • No autopilot window / keyframe trigger. Three-minds: keyframes timed to “high
   confidence and a low rate of change”. Thor-admit only knows                  
   memory/GPU/leases; it cannot know reflex confidence or rate of change.       
   Smallest change: have the reflex publish confidence + rate_of_change to      
   flow.json; add a keyframe trigger that admits a preparation/practice job when
   confidence > τ and rate < ε. If no signal, this stays a night-runner/mediator
   concern (scope out of thor-admit).                                           
 • “Glance gathers other players’ state (peers, the human)” is not a daemon     
   function. Thor-admit has no room graph, peers, or human state. Smallest      
   change: the scheduler only grants the gap; the mediator fills it. Update     
   three-minds to say the scheduler provides the window, the mediator decides   
   what to look at (no daemon change).                                          
 • No cue primitive. Three-minds: “Cues, not scores… sparse, high-gain signals  
   on their own channel in the room graph”. Thor-admit protocol has no cue op   
   and no room graph. Smallest change: add a presence_cue op (label + payload)  
   that writes to a per-job cue FIFO/file; the critic/night runner sends “take  
   another chorus”; the daemon just delivers.                                   
 • “Grant that loop another chorus (more iterations)” is not expressible.       
   Presence jobs are fixed commands with a peak; the daemon cannot know         
   improvement rate or reallocate iterations. Smallest change: add              
   presence_update (or allow editing presence.json) so the critic/night runner  
   can change a job’s command/iterations; the daemon runs the updated job. The  
   decision stays with the critic.                                              
 • No human-feedback input. Three-minds: “What Casey keeps, undoes or looks at  
   is the dancers’ feedback”. Thor-admit has no human-feedback channel. Smallest
   change: add a feedback.jsonl (or ledger annotation) the human/morning reader 
   writes; the night runner reads it to adjust presence jobs. Thor-admit records
   it if given a feedback op; otherwise scope to night runner.                  

Flow                                                                            

 • No “knower’s sign” (JEPA prediction error + confidence). Thor-admit measures 
   CPU/GPU/memory, not latent prediction error or model confidence. Smallest    
   change: the reflex/mediator publishes prediction_error and confidence to     
   flow.json; thor-admit reads it and logs flow.sign (steady/faded) in the      
   ledger. The daemon does not compute it.                                      
 • No mediator-call or outcome measurement. Three-minds: “Measure it: mediator  
   calls in flow vs out of it, and whether intervening during flow ever improves
   the outcome.” The ledger has no mediator-call counter and cannot see LLM     
   calls (not leases). Smallest change: add a mediator event stream (timestamp, 
   in_flow, call, outcome_improved) written by the mediator/night runner; the   
   ledger folds it into a mediator section (calls_in_flow, calls_out_of_flow,   
   intervened_improved). Improvement must be reported by the night runner.      
 • Re-entry triggers are external. Three-minds: steps back in when “the sign    
   fades… or someone needs bringing into the moment (a new agent, or the human  
   arriving)”. Thor-admit has no rate gate or new-agent/human-arrival detection.
   Smallest change: the mediator publishes sign_faded / new_agent /             
   human_arrived; the night runner sends a live presence_add for the mediator   
   job. Thor-admit’s existing live pre-emption lets it start at once.           


Tokens: 45k sent, 12k received. Cost: $0.06 message, $0.59 session.
