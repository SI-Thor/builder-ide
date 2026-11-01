# Research waiting list

Repos and models Casey flagged to study later. Each line has the date, the link, the licence, and why it might matter. Move an entry to its own note under docs/research/ when it is studied.

- **2026-10-31 · OpenEBFM** (https://github.com/datamllab/OpenEBFM, MIT; full code released 2026-10-07, technical report 2026-10-23): training and scaling **energy-based foundation models**, a language model that scores the compatibility of a (context, continuation) pair with one scalar energy.
  - **Why it might matter:** an energy is a natural *verifier and confidence*. That makes it a candidate for the judge's calibration problem (judge-calibration found d1's confidence *anti-correlated* when the prompt names the decoy first), the critic's continuation scoring, and the flow "knower" (low energy = "yes, keep going").
  - **To study:** the report's scaling laws, the checkpoint sizes (Thor fit), whether energies are order-invariant (the decoy test), and the cost of scoring vs generating.
