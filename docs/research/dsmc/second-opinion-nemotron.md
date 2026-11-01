**1. Ranking mistakes**  
- **#1 Biographer letters** and **#2 Five‑beat return arc** are *presentation* layers. They cannot be exercised until the Canon can emit a stable, queryable state (gaps, precedents, board manifest) and agents have bounded perception. Putting them first inflates “value” while the underlying data model is still missing.  
- **#7 The wager**, **#8 Sleep‑cycle gossip**, **#11 The dependent**, **#12 Puzzle box** are narrative flourishes that depend on a working commitment/ledger and gap‑resolution pipeline. Their “M/L” effort scores hide the prerequisite work (gap objects, validator, board manifest).  
- **#6 Sensory limits** is correctly low‑effort but is ranked after the return‑arc; perception gating is needed before any agent can meaningfully *write* a letter or *close* a gap.  

**2. Three things to do first (with concrete pass‑bars)**  

| Order | Task | Why it unlocks the rest | One‑day test & pass bar |
|------|------|------------------------|--------------------------|
| 1 | **Gaps as first‑class Canon objects** (rank 3) | Provides the atomic unit the DM, biographer, and commitments all reference. | Insert a typed gap, run 3 DM rounds, verify state machine `open → proposed → adjudicated → closed` with a receipted ruling and a scar. Pass: all four transitions recorded and replayable. |
| 2 | **Precedent store + deterministic validator** (rank 4) | Turns DM rulings into reusable, conflict‑free law; needed before commitments or wagers can be judged. | Load 100 synthetic rulings, query 10 k random look‑ups. Pass: p99 latency < 10 ms **and** zero validator‑rejected inconsistencies. |
| 3 | **BoardManifest (Canon→Board projection)** (rank 5) | Gives the spectator/Director a stable, versioned view; the biographer reads this, not raw events. | Generate manifest at receipt k, hand to a colleague who must describe the board in one sentence without follow‑up. Pass: single‑sentence description, no clarification needed. |

**3. Missed risk**  
The ranking assumes the **shared Liquid d1‑2B decision model** will stay a neutral “policy engine.” In practice the batched inference path creates a *single latent policy* that all four bots query, causing behavioral homogenisation and making per‑agent sensory limits or commitment‑driven divergence impossible to express. If the model drifts, every agent drifts together, and the validator cannot catch semantic collisions because they never appear as divergent proposals. A spike to add per‑agent heads (or a lightweight world‑model shim) should be scheduled before any narrative layer ships.
