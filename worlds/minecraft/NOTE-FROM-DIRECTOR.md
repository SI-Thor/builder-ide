# NOTE FROM THE DIRECTOR (2026-10-31 21:25): the lock design deadlocks; fixed in ops/run-paper.sh
`ops/run-paper.sh` held `~/lm-wt/heavy.lock` for the **whole life of the server**, while the bots take the same lock on **every decision tick**. Once the server held it, no bot (and no other heavy job on the Thor) could ever run. I stopped the waiting launch (the server had not started) and patched `run-paper.sh`: it now **checks ≥ 25 GB available and starts without the lock** (a 6 GB heap is under the ~8 GB heavy threshold).

Please also change the bots:
- **do not take heavy.lock per tick.** A decision tick is light;
- serve **one shared d1** under the lock **only while loading it** (or check free memory), then release, and batch all bots' questions per tick against it;
- the heavy lock is only for genuinely heavy, short steps.

Then start the world again with your ops script.
