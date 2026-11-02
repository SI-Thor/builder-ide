# open-game-agent (colinlevine), triage 2026-11-01

Casey: "another to be studied for our projects". Director's read of the repo metadata and README (no code run).

- **What it is:** a Microsoft intern-hackathon project (5 stars, last push 2025-06-27). An MCP server exposing
  PyAutoGUI tools (click at screen-percentage coordinates, keypress, screen info) to an LLM, plus a memory of past
  actions and outcomes: a vector store in Azure AI Search, or a "legacy" one kept as markdown files. Demos: 2048
  (stable) and Wordle (work in progress).
- **Licence: none.** With no licence file the code is all-rights-reserved: we may learn from the ideas, not copy code.
- **What it adds beside ramenvr/autopilot (docs/research/autopilot.md, in progress):** nothing new in mechanism.
  Autopilot already has the stronger version of both ideas: harnesses written per task for a decision model, and a
  per-project memory that improves run over run. Open-game-agent's pixel-level click and keypress is the weakest
  way to drive a game; our worlds expose state directly (mineflayer, the ledger), so the agent should act on state,
  not pixels.
- **The one idea worth keeping:** memory as **human-readable markdown the human can edit**. That matches design for
  absence: a person returning can read, and correct, what the agent believes it learned. Our precedent store
  (dsmc gaps -> precedents) should stay readable the same way.
- **Verdict:** methods-only; no lane. Revisit only if it gains a licence and a state-level (not pixel) interface.
