# core-doors — what the MCP server found missing, and what this branch adds

The world-mcp server (`~/lm-wt/thor-world-repo`, its `docs/design.md`) is a
pure client of the core's HTTP doors. Building it found four gaps — its
§8 named them as open questions for Casey. This branch answers all four;
each landed as its own commit, tests first. Nothing here changes an
existing door's contract; everything is additive, and A1 (permissive by
default) holds throughout.

| world-mcp §8 | What this branch does | Commit |
|---|---|---|
| §8.5 concurrent reads | the store's reads take the one lock | `180ee04` |
| §8.1 agent identity | per-agent tokens: the `agent` claim on the ledger row | `481ff5d` |
| §8.2 recipe read door | `GET /v1/recipe/{version}` and `?against=` diff | `2494e18` |
| §8.4 plan intentions | the `plan.intention` kind on `/v1/tasks` | `b95c3ea` |

## 1. The store race (§8.5) — the lock, chosen by measurement

Every read door was served from one `sqlite3.Connection`
(`check_same_thread=False`) across the threadpool; pysqlite's statement
cache and cursor state collide, and the doors answered 500 —
`sqlite3.InterfaceError` in `count_events`, measured at 20–37 % of
concurrent GETs. The fix is the lock the writes already held, now covering
reads (`core.store._serialized`).

Why not per-thread connections (the textbook answer): measured slower at
every concurrency (85 vs 133 rps at 16 in flight, p95 350 vs 266 ms), and
they broke 5 API tests — callers read their own uncommitted writes inside
a batch (`NightsService.start` → `attach_slate_to_night` reads the night
row inside the open transaction), which a reader on its own connection
cannot see. A serialized read costs microseconds. The numbers and the
reproduction: `docs/lab/exp-store-race.md`,
`tests/test_store_race.py` (fails 10/10 unfixed).

## 2. Per-agent tokens (§8.1) — one actor, many agents

A token entry may carry an `agent` claim. It resolves onto the Principal
and rides every audit row the token writes —
`{kind, id, via, agent}` — so the log answers "which agent acted for
whom" from the row alone, and world-mcp can retire its own stamping.
Recorded, never gated: no door asks for the claim, a token without it
behaves exactly as before, and every class refusal (a kid's free text, an
adult-only door) refuses exactly as before. Two per-agent dev tokens
document the registry shape (`core/config.py`).

## 3. The recipe read door (§8.2) — `GET /v1/recipe/{version}`

The document, its `root_hash`, parent and edit — read from the
content-addressed blob and verified against the hash on read; a tampered
blob fails loud (§1.0, §5.2; tested). With `?against=<base>`: the
canonical op list that turns the base into the version (§1.1: the diff
*is* the op list), base→version so a night's edits read forward.
Read-only, to the classes that read branches already. The reads ride the
`RecipeStore` port (`version` / `document` / `diff`); an unwired core
answers 501 with the seam named, the `/v1/world/scene` precedent.

## 4. Plan intentions (§8.4) — the `plan.intention` kind

`POST /v1/tasks` gains a kind an agent files (its character-class token;
the agent claim from §2 rides the row): a proposal for the night's slate,
priced by the cost model like everything else. The band is the proposal's
own footprint — a slate row and the owner's decision on it (the model's
attention estimate, `basis: estimate`, marked `[e]`; zero GPU, zero
hosted cents). It prices the *proposal*, not the work it may seed: that
work is priced by its own kind when the night runs it, so a proposal
cannot fatten the slate with work it does not name. Admission takes it
like any task — slated, queued when the night starts.

## Testing

```bash
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/python -m pytest -q          # + pillow, and the usd extra for tests/usd
```

1378 passed, 3 skipped, 16 deselected (the opt-in real-engine run) at the
head of this branch. The four new test files:
`test_store_race.py`, `test_agent_identity.py`, `test_recipe_door.py`,
`test_plan_intentions.py`.
