# The warm scene server — a resident process behind the engine seam

Plan item 15 (draft 2, week 3): *the measured numbers say the win is
builder wait and crash recovery, not edit→preview latency — so the
server's job is defined as **holding the scene and surviving a kill**.*
This package is that job, as a fourth engine flavour on the seam
(`open_engine({"flavour": "resident", ...})`).

The research behind every decision here is the spike
(`docs/research/warm-scene.md`, cited as WS below) and the v2 experiment
(`docs/research/v2-thor-experiment.md`, E): the tax a warm server removes
is the *launch* — ~0.25 s of `import bpy` (WS §4.2), ~2.4 s of process
start-up per scene on the v2 build (E §5) — paid once instead of per
request. The render itself is 80–90 % of a real interaction and is
**not** claimed (WS §4.1).

```
the adapter (this core)                     the resident (the engine's own
────────────────────────────                interpreter, maybe 3.11 + bpy)
ResidentEngine  ── journal first, then apply ──►  worker.py (one thread)
SceneJournal    ◄── the durable recipe ──        protocol.py (the mirror)
ResidentPolicy                                     fake_backend | blender_backend
ResidentProcess (the RPC; stdout is the wire)      the scene, held
```

## The job, measured (this box, load ≈ 12–15, 2026-10-31)

`python -m core.engine.resident.bench` (add `--backend blender --python
~/lm-wt/warm-scene/.venv/bin/python` for the real engine):

| | batch p50 | warm p50 | starts | kill −9 → next result |
|---|---|---|---|---|
| fake backend | 38.9 ms | **1.6 ms** (24×) | 20 → 1 | 45 ms, bytes + digest identical |
| blender (bpy 4.2.0) | 339.6 ms | **71.6 ms** (4.7×) | 20 → 1 | 1214 ms, bytes + digest identical |

The blender batch column is the spike's launch tax measured through the
seam — ~0.27 s of interpreter + `import bpy` per edit, paid once when
warm. Recovery replays the journal onto a fresh resident and *proves*
it landed: the core computes the document with its own op applier and
refuses a resident that arrived anywhere else.

## The modules

| module | what it is |
|---|---|
| `engine.py` | `ResidentEngine`, the `Engine` implementation: sync by typed diff (journal first, then apply), recovery by replay + digest check |
| `transport.py` | the subprocess and the one-request-one-response RPC; the child's stdout is the protocol, its stderr is a log **file** |
| `journal.py` | `journal.jsonl` (the truth, fsynced per op, torn lines tolerated) + `recipe.json` (a snapshot at checkpoints — the whole-file-per-edit rewrite is gone, WS §5.3) + `checkpoint.json` (document, journal position, scene digest) |
| `policy.py` | the four dials: health checks, restart budget + backoff, checkpoint cadence, memory-growth guard |
| `protocol.py` | the wire format and the mirror of the core's op applier — standalone (stdlib, 3.9 syntax) because the resident may run under the engine's interpreter |
| `backend.py` / `fake_backend.py` | the scene half of the seam, and the deterministic fake the tests and benchmark run on |
| `blender_backend.py` | the real engine's scene (opt-in: needs `bpy`, hence its own interpreter) |
| `worker.py` | the resident process: one thread (`bpy` is not thread-safe, WS §5.1), stdout redirected to the log before anything that chats can import (WS §5.5) |
| `bench.py` | the benchmark above |

## Running it

```bash
# the tests (fake backend, real subprocesses, real SIGKILLs)
python -m pytest tests/engine/test_resident.py -v

# the opt-in real-engine test (bpy 4.2.0 lives in the spike's venv here)
BUILDER_RESIDENT_BLENDER=~/lm-wt/warm-scene/.venv/bin/python \
  python -m pytest tests/engine/test_resident_real.py -v

# the benchmark
python -m core.engine.resident.bench
python -m core.engine.resident.bench --backend blender \
  --python ~/lm-wt/warm-scene/.venv/bin/python
```

As a service, the engine is one configuration line (the same shape
`BUILDER_ENGINE` carries):

```python
open_engine({
    "flavour": "resident", "pin": {...},
    "root": "$BUILDER_HOME/resident",     # where the journal lives
    "backend": "blender",
    "python": ".../.venv/bin/python",     # the engine's own interpreter
    "policy": {"max_restarts": 3, "checkpoint_every_ops": 25},
})
```

## What is stubbed, and the named missing pieces

- **`blender_backend.stage()` is not an Infinigen stage.** It evaluates
  the resident scene into a deterministic description (entry digests +
  scene digest), which proves the stage read the scene the recipe
  describes. The fork's `infinigen_thor.stage_runner` is the same named
  missing piece the v1/v2 adapters carry; it replaces that method's
  body, not its contract.
- **Single-tenant and serial, on purpose.** One request at a time on the
  resident's main thread (`bpy` is not thread-safe, WS §5.1). A render
  blocks a ping; acceptable for one workshop, stated here.
- **The scheduler's residency half is not wired.** core-spec §1.9 wants
  `scene.loaded`/`scene.evicted` audit events, a per-branch peak-RSS
  bound and LRU eviction; this package reports the numbers
  (`stats()`: RSS, peak, guard recycles) and leaves the policy to the
  scheduler when it exists.
- **`requests` is an in-memory list** of every request's wall time —
  fine for a session and the benchmark, not a month.

## Honest limits

- The fake backend's numbers measure the seam's own machinery (process
  start, RPC, journal fsync); the blender numbers are the real tax but
  on a small scene — WS §4.1's caveat (the render dominates real
  interactions) is unchanged and unrepeated here.
- The digest is taken at checkpoints, not per edit (O(scene size);
  WS §5.4) — an edit pays one journal append (O(1)), never a scene walk.
- The resident never writes the journal: the **adapter** owns it, which
  keeps the spec's hard rule intact — the warm scene server is a derived
  cache, never a writer (core-spec §1.9, decision 17).
