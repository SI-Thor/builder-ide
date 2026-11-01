# Seed-2.0-mini: parametric prop families as night variety (2026-11-01, aider:ideas, /ask)

> -written CAD script per prop type with named parameters (width, plank_count, w
> ear); the night samples parameters, a critic scores, and winners are kept. How
>  should we choose which parameters to sample (active learning, novelty, the bu
> ilders' use), and how should Casey's keep/undo feed back? Give 8 mechanisms, e
> ach with one metric, then your two best bets. Under 600 words.                

--------------------------------------------------------------------------------

► THINKING                                                                      

Got it, let's tackle this. First, need 8 mechanisms each with a metric, then top
2, keep under 600 words, prose only, tie to the given docs (like the three      
minds, emitter-projector, builder-ide from the reference files).                

First, list each mechanism with a clear metric:                                 

 1 Low-confidence parameter sampling: Metric = % of sampled props that fail     
   critic pass threshold (target <20% failure rate)                             
 2 Novelty-driven sampling: Metric = Unique parameter combination count per     
   night (target +15% new combos vs prior week)                                 
 3 Builder usage hotspots: Metric = Number of builder calls for that prop type  
   (target align sampling to top 3 used props)                                  
 4 Edge case boundary sampling: Metric = % of samples within 5% of parameter    
   min/max bounds (target 10% of batch)                                         
 5 Temporal drift sampling: Metric = Rate of parameter shift from prior night's 
   winners (target 20% drift to avoid stagnation)                               
 6 Human context sampling: Metric = % of samples matching recent human in-world 
   requests (target match 80% of logged user prompts)                           
 7 Failure replay sampling: Metric = % of samples reusing parameters from prior 
   failed props (target 30% of batch to fix gaps)                               
 8 Random baseline sampling: Metric = Kullback-Leibler divergence from winner   
   distribution (target match baseline to avoid bias)                           

Then top 2: First, Builder Usage Hotspots + Failure Replay Sampling combined?   
Wait no, wait the user wants two best bets. Wait, first: Builder Usage Hotspots 
paired with Low-Confidence Sampling – because it aligns with what builders      
actually need, and targets weak spots. Metric tied together? Wait no, each      
mechanism has its own metric. Wait no, the user said 8 mechanisms each with one 
metric, then two best bets.                                                     

Wait also tie back to Casey's keep/undo feed: each mechanism uses the keep/undo 
log as training data for the parameter distribution, right? Like the taste      
ledger from builder-ide.md.                                                     

Wait keep it tight, under 600 words. Let's structure:                           

First, 8 targeted sampling mechanisms, each with a clear success metric:        

 1 Low-confidence parameter sampling: % of samples failing critic pass          
   thresholds (target <20% failure)                                             
 2 Novelty-driven sampling: Unique parameter combo count per night (target +15% 
   vs prior week)                                                               
 3 Builder usage hotspot sampling: Monthly builder prop request volume (target  
   align batch to top 3 used prop types)                                        
 4 Edge boundary sampling: % of samples within 5% of parameter min/max bounds   
   (target 10% of batch)                                                        
 5 Temporal drift sampling: KL divergence from prior night’s winning parameters 
   (target 20% drift to avoid stagnation)                                       
 6 Human context sampling: % of samples matching recent in-world user requests  
   (target match 80% of logged prompts)                                         
 7 Failure replay sampling: % of samples reusing parameters from prior failed   
   props (target 30% of batch to close gaps)                                    
 8 Random baseline sampling: KL divergence from unfiltered random sampling      
   (target avoid biased winner distributions)                                   

Then top two bets:                                                              

 1 Builder Usage Hotspots + Failure Replay Sampling: This aligns batch work to  
   what builders actively need (tying to the project’s core utility) and fixes  
   unaddressed failure modes from past runs, directly using Casey’s keep/undo   
   log as failure source. Success metric: 3x higher adoption of generated props 
   by builders vs baseline.                                                     
 2 Low-Confidence + Temporal Drift Sampling: This targets weak, underperforming 
   parameter sets while avoiding stagnation, using the critic’s failure scores  
   and taste ledger from builder-ide’s preference tracking. Success metric: 25% 
   reduction in post-night human edits to generated props.                      

Wait also tie in the keep/undo feedback: every keep/undo action updates the     
parameter distribution model for each mechanism, so the sampling shifts over    
time to match what the team (human + builders) actually values.                 

Wait make sure it's prose, no code, under 600 words. Let's refine to be concise,
tie to the reference docs (like the taste ledger, critic scores, builder work   
orders from the supplied TEAM.md and ideas-vision.md).                          

Wait let's draft properly:                                                      

8 Sampling Mechanisms (Each with Metric)                                        

 1 Low-confidence parameter sampling: % of sampled props failing critic pass    
   thresholds (target <20% failure rate)                                        
 2 Novelty-driven sampling: Unique parameter combination count per night (target
   +15% new combos vs prior 7 days)                                             
 3 Builder usage hotspot sampling: Monthly builder prop request volume (target  
   batch top 3 requested prop types)                                            
 4 Edge boundary sampling: % of samples within 5% of parameter min/max bounds   
   (target 10% of total batch)                                                  
 5 Temporal drift sampling: KL divergence from prior night’s winning parameters 
   (target 20% drift to avoid stagnation)                                       
 6 Human context sampling: % of samples matching recent in-world user requests  
   (target align 80% to logged user prompts)                                    
 7 Failure replay sampling: % of samples reusing parameters from prior failed   
   props (target 30% of batch to close gaps)                                    
 8 Random baseline sampling: KL divergence from unfiltered random sampling      
   (target avoid biased winner distributions)                                   

Top Two Bets                                                                    

 1 Builder Usage Hotspots + Failure Replay Sampling: This aligns overnight      
   generation to the props builders actively request (tying to core project     
   utility) and repurposes Casey’s keep/undo log to fix unaddressed failure     
   modes. It directly uses the project’s taste ledger and critic failure data to
   prioritize high-value, high-risk batches. Success metric: 3x higher adoption 
   of generated props by builders vs baseline random sampling.                  
 2 Low-Confidence + Temporal Drift Sampling: This targets underperforming       
   parameter sets while avoiding creative stagnation, using critic failure      
   scores and the builder-ide preference tracking system. It shifts sampling to 
   fill gaps in the current winning parameter distribution without drifting too 
   far from what the team already values. Success metric: 25% reduction in      
   post-night human edits to auto-generated props.                              

Wait also mention that all mechanisms feed back into Casey's keep/undo log:     
every kept prop updates the sampling distribution for its type, while undone    
props flag parameters to avoid or replay. That ties to the reference docs' taste
ledger and keep/undo feedback loops.                                            

Wait let's make it flow better, keep under 600 words. Let's trim:               

--------------------------------------------------------------------------------

8 Sampling Mechanisms (Each with Clear Success Metric)                          

 1 Low-confidence parameter sampling: % of sampled props failing critic pass    
   thresholds (target <20% failure rate)                                        
 2 Novelty-driven sampling: Unique parameter combination count per night (target
   +15% new combos vs prior 7 days)                                             
 3 Builder usage hotspot sampling: Monthly builder prop request volume (target  
   batch top 3 requested prop types)                                            
 4 Edge boundary sampling: % of samples within 5% of parameter min/max bounds   
   (target 10% of total batch)                                                  
 5 Temporal drift sampling: KL divergence from prior night’s winning parameters 
   (target 20% drift to avoid stagnation)                                       
 6 Human context sampling: % of samples matching recent in-world user requests  
   (target align 80% to logged user prompts)                                    
 7 Failure replay sampling: % of samples reusing parameters from prior failed   
   props (target 30% of batch to close gaps)                                    
 8 Random baseline sampling: KL divergence from unfiltered random sampling      
   (target avoid biased winner distributions)                                   

Top Two Recommended Bets                                                        

 1 Builder Usage Hotspots + Failure Replay Sampling: This aligns overnight      
   generation to the props builders actively request (tying to the project’s    
   core utility) and repurposes Casey’s keep/undo log to fix unaddressed failure
   modes. It uses the project’s taste ledger and critic failure data to         
   prioritize high-value, high-risk batches. Success metric: 3x higher adoption 
   of generated props by builders vs baseline random sampling.                  
 2 Low-Confidence + Temporal Drift Sampling: This targets underperforming       
   parameter sets while avoiding creative stagnation, using critic failure      
   scores and the builder-ide preference tracking system. It shifts sampling to 
   fill gaps in the current winning parameter distribution without drifting too 
   far from what the team already values. Success metric: 25% reduction in      
   post-night human edits to auto-generated props.                              

All mechanisms feed back into Casey’s keep/undo log: every kept prop updates the
sampling distribution for its type, while undone props flag parameters to avoid 
or rework, closing the feedback loop outlined in the builder-ide vision.        

Wait that's around 350 words, under 600, prose only, ties to the reference docs,
8 mechanisms each with metric, two best bets, covers the keep/undo feedback.    
Perfect. Let's check: yes, each mechanism has a metric, top two are clear, ties 
to the user's question about parametric prop families, night sampling, critic   
scoring, keep/undo. Yeah that's exactly what they asked for.                    

--------------------------------------------------------------------------------

► ANSWER                                                                        

8 Sampling Mechanisms (Each with Clear Success Metric)                          

 1 Low-confidence parameter sampling: % of sampled props failing critic pass    
   thresholds (target <20% failure rate)                                        
 2 Novelty-driven sampling: Unique parameter combination count per night (target
   +15% new combos vs prior 7 days)                                             
 3 Builder usage hotspot sampling: Monthly builder prop request volume (target  
   batch top 3 requested prop types)                                            
 4 Edge boundary sampling: % of samples within 5% of parameter min/max bounds   
   (target 10% of total batch)                                                  
 5 Temporal drift sampling: KL divergence from prior night’s winning parameters 
   (target 20% drift to avoid stagnation)                                       
 6 Human context sampling: % of samples matching recent in-world user requests  
   (target align 80% to logged user prompts)                                    
 7 Failure replay sampling: % of samples reusing parameters from prior failed   
   props (target 30% of batch to close gaps)                                    
 8 Random baseline sampling: KL divergence from unfiltered random sampling      
   (target avoid biased winner distributions)                                   

Top Two Recommended Bets                                                        

 1 Builder Usage Hotspots + Failure Replay Sampling: This aligns overnight      
   generation to the props builders actively request (tying to the project’s    
   core utility) and repurposes Casey’s keep/undo log to fix unaddressed failure
   modes. It uses the project’s taste ledger and critic failure data to         
   prioritize high-value, high-risk batches. Success metric: 3x higher adoption 
   of generated props by builders vs baseline random sampling.                  
 2 Low-Confidence + Temporal Drift Sampling: This targets underperforming       
   parameter sets while avoiding creative stagnation, using critic failure      
   scores and the builder-ide preference tracking system. It shifts sampling to 
   fill gaps in the current winning parameter distribution without drifting too 
   far from what the team already values. Success metric: 25% reduction in      
   post-night human edits to auto-generated props.                              

All mechanisms feed back into Casey’s keep/undo log: every kept prop updates the
sampling distribution for its type, while undone props flag parameters to avoid 
or rework, closing the feedback loop outlined in the core builder-ide vision.   


