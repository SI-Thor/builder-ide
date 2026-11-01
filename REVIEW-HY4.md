► ANSWER                                                                        

No file changes are proposed; docs/design/thor-admit.md is read-only and this is
a review.                                                                       

 1 SIGSTOP holding memory (GPU pre-emption). Failure: GPU pre-emption SIGSTOPs  
   the presence job, but a stopped process keeps all its unified-memory pages   
   (no swap), so its reserved is still charged and MemAvailable does not rise.  
   Symptom: presence.preempted (GPU) is logged, yet a live lease waiting for    
   memory is still not admitted; MemAvailable stays flat; the ledger books      
   preempted_for_live_work while the box is still short. Fix: never use SIGSTOP 
   for memory pressure — memory pre-emption must be SIGTERM (already) and the   
   reservation is removed only after the process is reaped; for GPU pre-emption 
   use CUDA stream priority / MPS to yield the GPU without stopping the process,
   or treat a SIGSTOP'd job as still holding memory and expect no headroom gain.
 2 Learned peaks too low (--peak auto). Failure: auto reserves the p95 of       
   peaks.jsonl; a label whose true peak exceeds p95 (or a shifted workload)     
   reserves too little, and with no swap the box blows through the 8 GiB        
   emergency floor before the watchdog acts. Symptom: lease granted with peak 40
   GiB but peak_rss_bytes 55 GiB in the history; MemAvailable crashes; the      
   watchdog stops the largest lease or the kernel OOM-kills a service; no       
   lease.underreserved is logged. Fix: reserve max(p95, last_peak, requested) or
   p99 × 1.2; refuse auto for labels with too few runs; on any over-run, write  
   the measured peak immediately and log lease.underreserved with reserved vs   
   peak_rss.                                                                    
 3 Pinned CUDA / device memory not swappable. Failure: MemAvailable is the      
   kernel's estimate for reclaimable memory; CUDA cudaMalloc/pinned host and the
   GPU carveout are not reclaimable, so a lease is admitted when MemAvailable is
   high but the non-swappable pool is full. Symptom: MemAvailable 30 GiB, but   
   cudaMalloc fails or tegrastats shows lfb (largest free block) tiny;          
   nvidia-smi memory used is high; the workload OOMs while the daemon says there
   was room. Fix: track device/pinned memory via cudaMemGetInfo and the         
   per-lease peak_gpu_bytes; subtract GPU/pinned from headroom and add a        
   --gpu-floor (e.g., 2 GiB device) so projected accounts for non-swappable     
   memory, not just MemAvailable.                                               
 4 Clients that never release (stuck lock holder). Failure: the lease is held by
   an flock; if the client hangs (or a wrapper keeps the fd) and never sends    
   release and never dies, the lock is never dropped, so the reservation is     
   charged forever. Symptom: lease.granted with no lease.released; status shows 
   the lease held, current low but reserved still charged; new leases queue     
   forever; projected never recovers. Fix: add a heartbeat — the client must    
   send held then periodic heartbeat; if no heartbeat for N samples, or the     
   target pgid is gone while the lock is still held, the daemon SIGTERMs the    
   target and force-releases the lease after a grace period; verify liveness via
   /proc/<pgid>, not just the lock.                                             
 5 Ledger books phantom running time for granted-but-never-held leases. Failure:
   the ledger books a lease as running from granted, but if the client dies or  
   is refused before held, the lease is released without the command ever       
   running; the ledger still counts running_s for that tier. Symptom: ledger    
   shows live.running_s > 0 with runs: 0 and peak_rss_bytes: null;              
   idle.unattributed is 0 but the box did no work; the log has lease.granted →  
   lease.released with no held. Fix: start the running timer at held (or        
   confirmed pgid); if released without held, emit lease.granted_not_run and    
   book the grant→release interval as a new attributed cause granted_not_run    
   (not running, not unattributed), keeping the classifier total and            
   unattributed at 0.                                                           


Tokens: 29k sent, 8.9k received. Cost: $0.04 message, $0.35 session.
