# EXP — "never wait": a deadline, a fallback, and a supersede that never rewrites history

**Idea (idea5, kept as gold):** every request has a deadline. When it passes, a fallback answers and is **committed**. If the real answer arrives later, it is recorded as a **supersede** event beside the committed one, and committed history is never rewritten. This is a correctness property: a swarm of slow models can never block the first mile, and the ledger can never be quietly altered after the fact.

**Mechanism.** `Conductor.submit()` starts the worker as a task and waits on it with `asyncio.wait(..., timeout=deadline)`. On timeout it appends the fallback to the history and returns at once. A follower task awaits the worker and appends `{request_id, fallback, late_value, late_by_s}` to the supersede log, without touching the history.

**Measured** (ProArt, Python 3, standard library only): 1,000 requests, deadline 50 ms, workers sleeping 0–200 ms (seeded).

| quantity | value |
|---|---|
| longest wait | **52.25 ms** (bar ≤ 60) |
| fallbacks committed | 723 |
| supersedes recorded | 723 (every late answer accounted for) |
| committed answers changed | **0** |
| verdict | PASS |

**Where it lands:**
- **The first mile:** a cached or reflex answer at the deadline, the real one as a supersede.
- **core/judge's escalation ladder:** the local d1 answer commits, a late cloud answer supersedes.
- **The ledger:** a `*.superseded` event kind beside the original, never an edit.

**Reproduce:** `python docs/lab/never-wait-scripts/never_wait.py`; tests in `tests/test_never_wait.py`.

*Written by the pi seat (gpt-oss-120b on Groq: the script; the tests were finished by the director after a tool-call failure).*
