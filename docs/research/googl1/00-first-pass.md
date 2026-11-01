# googl1.md: a bare-metal Thor brainstorm, checked against our measurements (2026-11-01)

The source is Casey's `googl1.md`: a 25,000-word Google-chat brainstorm about running the Jetson AGX Thor "bare-metal", with EL3 boot, a flattened MMU, NIC DMA rings polled by a dedicated core, raw SASS injection and hardware-directed GPU loops. Most of it is a vision of removing the software stack. A handful of it is testable on stock JetPack 7 tonight.

## How it was read
1. **Triage, Groq gpt-oss-120b** (`$0.008`). It listed 20 claims. Its own errors (it assumed JetPack 5.x and Cortex-A78 cores, and suggested writing a made-up GPU doorbell address through `/dev/mem`) mean its verdicts are a list, not findings.
2. **The real pass, the DeepSeek library** (`$0.10`). It has our measured lab notes in its cached context, so each claim is checked against what we measured. Its answer follows.

**The rule for this document:** nothing here writes to `/dev/mem`, firmware or the boot configuration. Those ideas are listed in §3 for Casey, and they stay ideas.

## The most useful lead: Green Contexts
The doc names **CUDA 13.2 Green Contexts** (`cuDevSmResourceSplitByCount`): SM partitions *inside a process*, made with a driver API call.
- MIG on this box partitions compute only, and creating slices is blocked while the desktop holds the GPU (`docs/lab/exp-mig.md`).
- Green Contexts could give live work (the first mile, d1, previews) a guaranteed SM share **with the desktop up and no reboot**.

This is **seed 164**, added to xp-batch as a seventh spec. It is the next thing to measure before Casey decides on running headless.

## The library's tables
1. Hardware claims in lib-googl1.md vs. our measurements                        

| # | Claim (quoted) | Verdict |                                                

|---|---|---|                                                                   

| 1 | "the 14-core ARM Neoverse V3AE cluster" | Confirmed (14 cores) |          

| 2 | "128GB LPDDR5X RAM" | Contradicted — we measure 122 GB usable |           

| 3 | "273 GB/s" memory bandwidth | Untested — we have not run a bandwidth      
benchmark |                                                                     

| 4 | "2,560 CUDA cores" | Untested — we have not queried SM count |            

| 5 | "Compute Capability 11.0" / "sm_110" | Confirmed (sm_110) |               

| 6 | "no NVDLA co-processor and no Optical Flow Accelerator (OFA)" | Confirmed 
(matches our hardware survey) |                                                 

| 7 | "no RT cores" | Confirmed |                                               

| 8 | "the CPU and GPU are on the exact same die" | Confirmed (unified memory   
works) |                                                                        

| 9 | "traditional memory copy latency across a slow PCIe bus drop to absolute  
zero" | Confirmed (zero-copy works) |                                           

| 10 | "CUDA 13.2 Green Contexts" / "cuDevSmResourceSplitByCount" | Untested —  
we have not called the API |                                                    

| 11 | "MIG hardware partitioning" | Contradicted — MIG is compute-only and     
blocked by the desktop on our box |                                             

| 12 | "Tensor Memory Accelerator (TMA)" | Untested — we have not used TMA |    

| 13 | "mbarrier" hardware barriers | Untested |                                

| 14 | "Persistent Management Warp (Warp 0)" | Untested |                       

| 15 | "Hardware Doorbell Register (0x40001000)" | Untested — address not       
confirmed on T5000 |                                                            

| 16 | "NVCP_DOORBELL_REGISTER_OFFSET = 0x1000" | Untested |                    

| 17 | "THOR_BLACKWELL_HOST_BASE_ADDR = 0x40000000" | Untested |                

| 18 | "EL3 BootROM" / "Exception Level 3" | Untested — we have not inspected   
boot |                                                                          

| 19 | "AMBA CHI" coherent fabric | Untested — coherence works, protocol name   
unverified |                                                                    

| 20 | "NVLink-C2C" | Contradicted — the doc itself later says "there is no     
physical NVLink-C2C bridge inside a single chip" |                              


2. Ten ideas testable on stock JetPack 7 (no /dev/mem, no firmware, no boot     
config)                                                                         

| # | Idea | Existing spec | One-day test |                                     

|---|---|---|---|                                                               

| 1 | L2 persistence window (cudaStreamSetAttribute + cudaAccessPropertyPersist)
| xp-batch: l2-persist | Pin the gate's bounds array; measure throughput at 10⁴ 
and 10⁶ candidates with/without. Pass: ≥15% at 10⁶, no regression at 10⁴. |     

| 2 | Stream priority preemption (cudaStreamCreateWithPriority) | xp-batch:     
stream-priority | Long background kernel on −1, short UX kernel on 0. Pass: UX  
p99 ≤ 1.2× idle baseline. |                                                     

| 3 | Persistent kernel polling a lock-free queue | xp-batch: persistent-queue |
Compare launch-per-batch vs. persistent poll at batch sizes 1/10/100. Pass:     
persistent wins at batch ≤ 10. |                                                

| 4 | CUDA Graph capture of the gate | xp-batch: gc-probe | Capture the         
invariant check as a graph; measure launch overhead. Pass: ≤ 5 µs per launch    
(matches our 4.7 µs measurement). |                                             

| 5 | Green Contexts SM split (cuDevSmResourceSplitByCount) | — | Create two SM 
partitions, run a dummy kernel in each. Pass: both complete with correct        
results. Fail: API returns unsupported. |                                       

| 6 | __launch_bounds__(32, 16) register pinning | — | Compile with the         
directive, check ptxas -v reports 32 registers. Pass: exactly 32, no spill. |   

| 7 | membar.gl / membar.sys fence ordering | — | Write payload, fence, ring    
doorbell; reader checks payload before acting. Pass: zero torn reads over 10⁶   
iterations. |                                                                   

| 8 | cp.async global→shared bypass | — | Compare a copy loop with and without  
cp.async. Pass: ≥ 1.3× throughput. |                                            

| 9 | Warp-shuffle argmax reduction (__shfl_xor_sync) | — | Replace a           
shared-memory reduction with warp shuffle. Pass: ≥ 2× faster on 32-lane         
reduction. |                                                                    

| 10 | cudaMemAdvise preferred-location on the gate's buffers | — | Set         
SetPreferredLocation on GPU for the command queue; measure dispatch latency.    
Pass: p99 ≤ 1.5× the no-advise baseline. |                                      


3. Five ideas that need an OS or firmware change (for Casey)                    

| # | Idea | What it needs |                                                    

|---|---|---|                                                                   

| 1 | EL3 BootROM / Secure Monitor setup | Custom bootloader; not reachable from
JetPack userspace |                                                             

| 2 | Flattened MMU / 1-to-1 physical-to-virtual map | Kernel or hypervisor     
change; not a userspace API |                                                   

| 3 | Raw SASS injection into I-Cache | Driver-level; sys_icache_invalidate is  
not exposed to userspace |                                                      

| 4 | MMIO doorbell at 0x40001000 / 0x50004000 | /dev/mem access + confirmed    
address; needs root and a hardware map we do not have |                         

| 5 | NIC DMA ring buffer polling | Kernel driver change; the NIC is not exposed
as a raw ring to userspace |                                                    


