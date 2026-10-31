"""The engine seat — `core.engine` behind one configuration line.

M1's render rungs and the merge gate's engine half used to be seat-local
stubs (`seats/stubs.py`'s `stub_render` and `StubGateEngine`). They now run
on the core's own engine seam, and the engine behind it is **the one line
that changes** (plan §3 week-1 item 3: *pointing at a real engine later is
configuration*):

* `SPEC` — the default configuration: the **fake engine** impersonating
  Fjellvik's own pin (the shipped document's `ENGINE_PIN`, so the recipe's
  pin and the engine's pin agree by construction — the seam's rule 2 would
  refuse a mismatch). The unit suite and the plain acceptance run use it.
* `BUILDER_ENGINE` (JSON, the deployment line `core.engine.engine_from_env`
  reads) — when set, it wins. The real-engine acceptance run (`-m engine`)
  sets it to `real_engine_spec(home)`: the **v2 venv on this box**
  (`~/lm-wt/v2-thor`, read-only), whose pin is interrogated from the venv
  itself — so the session then performs the **explicit pin edit** (X R9: a
  swap is an edit, never a silent reinterpretation) before any render runs.

The **generator resolution** is the box's own table below, and it is part
of every provenance row, never silent: the shipped Fjellvik document names
the fork's generators (`infinigen_thor.structures::crates` — ours to
write), which do not exist on upstream 2.0; on this box each name resolves
to the upstream generator of the same kind the v2 experiment probed
(renders and traces clean, seconds at preview rungs). The day the fork's
own generators land, the table changes — one configuration line, again.

What each piece is:

* `EngineSeat` — builds the engine (`BUILDER_ENGINE` → `real_engine_spec`
  → `SPEC`), hands the spine its gate adapter (`core.engine.gate.
  EngineGateEngine`, the §2.3 rungs over any engine), answers the labels
  the step table prints, and carries the licence row and provenance row a
  render's asset takes from the engine that produced it.
* `gate_recipe_at` — the gate's *what am I checking right now*: the recipe
  document and version hash at the branch head under test, read per call
  (the gate runs during the night, after commits).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from siblings import Seats

#: The engine behind this session by default — **the one configuration
#: line**. The pin is the shipped Fjellvik document's own, so the engine
#: serves exactly the recipe the session commits (a pin mismatch is the
#: seam's loudest refusal).
SPEC: dict = {"flavour": "fake", "pin": None}  # pin filled from the document at build

#: Where the v2 venv lives on this box (read-only; the brief's constraint).
#: Overridable with `BUILDER_V2_HOME` so another box can point elsewhere.
DEFAULT_V2_HOME = Path("~/lm-wt/v2-thor").expanduser()

#: The generator resolution for this box: our name → the v2 CLI's chain.
#: Chosen by probing upstream 2.0's manifest (each chain renders AND traces
#: at `RANDOM_CONTROL`, seconds at preview rungs — see
#: `docs/research/v2-thor-experiment.md`): a lidded wooden container for
#: the crates word (the v2 story is lids and handles), a wooden shelving
#: unit for the racks, and worn wood on `material_cube` — the way the CLI
#: renders a material alone.
V2_GENERATORS: dict[str, str] = {
    "crates": "storage_cabinet_with_door_rand",
    "racks": "storage_cell_shelf_rand",
    "weathering": "wood_scratched_rand material_cube",
}

#: The licence row the *fake* engine's artifacts carry — nothing was
#: generated, so the terms are the stand-in library's own.
FAKE_LICENCE: dict = {
    "spdx": "CC0-1.0",
    "dependency_terms": ["library crate: CC0 (Poly Haven)"],
    "commercial_ok": True,
    "checked_by": "core-licence-registry",
}


def real_engine_spec(home: Path, *, v2_home: Path | None = None) -> dict:
    """The v2 venv on this box as one configuration mapping — the SPEC the
    real-engine acceptance run puts into `BUILDER_ENGINE`."""
    root = v2_home or Path(
        os.environ.get("BUILDER_V2_HOME", str(DEFAULT_V2_HOME))).expanduser()
    return {
        "flavour": "infinigen-2-procfunc",
        "runtime": "venv",
        "python": str(root / ".venv" / "bin" / "python"),
        "repo": str(root / "src" / "infinigen-upstream"),
        "repo_name": "princeton-vl/infinigen",
        "generators": dict(V2_GENERATORS),
        "output_dir": str(Path(home) / "engine"),
    }


class EngineSeat:
    """The session's engine, built from one configuration line per run.

    The recipe seat is *bound* after construction (the spine opens before
    the recipe seam exists — the gate's recipe_at closure answers per call,
    so the late binding is exactly the "read it at gate time" rule).
    """

    def __init__(self, seats: Seats, spec: dict | None = None,
                 home: Path | None = None) -> None:
        from core.engine import open_engine
        from core.vocab import seed as vocab_seed

        raw = os.environ.get("BUILDER_ENGINE", "").strip()
        if raw:
            spec = json.loads(raw)
        else:
            spec = spec or SPEC
        pin = dict(vocab_seed.ENGINE_PIN)
        spec = {**spec, "pin": spec.get("pin") or pin}
        if spec.get("runtime") == "venv":
            spec.pop("pin")  # the venv is asked; a given pin would be verified
        self.spec = spec
        self.engine = open_engine(spec)
        self._recipe_seat = None
        self._home = home

    def bind(self, recipe_seat) -> None:
        self._recipe_seat = recipe_seat

    # -- what the session prints and records -----------------------------------

    @property
    def real(self) -> bool:
        """True when a real engine (not the fake) is behind the seam."""
        return self.engine.describe().flavour != "fake"

    def label(self, kind: str) -> str:
        """The step table's backend label — honest for both runs."""
        return ("real:" if self.real else "fake:") + f"engine({kind})"

    def licence_row(self) -> dict:
        """The complete licence row for artifacts this engine produced
        (§1.6). The venv reports its own terms; the fake says CC0."""
        if not self.real:
            return dict(FAKE_LICENCE)
        return self._venv_runtime().licence_row()

    def render_provenance(self, *, subject: str, prompt: str, seed: int,
                          rung: int) -> dict:
        """The provenance row a render's asset carries: the engine, the pin,
        the resolved generator chain (the name resolution is part of the
        record), the seed and the exact ask."""
        from core.engine.infinigen1 import RUNG_LADDER
        from core.engine.infinigen2 import generator_calls

        resolution, samples = RUNG_LADDER[rung]
        if not self.real:
            return {
                "source": "generated",
                "generator": {
                    "method": "fake-engine", "model_id": "fake-engine",
                    "prompt": prompt, "seed": seed,
                },
            }
        pin = self.engine.describe().pin
        calls = generator_calls(self._recipe_document())
        chain = self._venv_runtime().chain_for_subject(calls, subject)
        return {
            "source": "generated",
            "generator": {
                "method": "infinigen-2-procfunc (venv subprocess)",
                "model_id": f"infinigen@{pin.commit[:12]}",
                "engine_pin": pin.model_dump(mode="json"),
                "prompt": prompt,
                "seed": seed,
                "rung": rung,
                "resolution": resolution,
                "samples": samples,
                "resolved_generator": " ".join(chain),
            },
        }

    # -- the spine's ports -----------------------------------------------------

    def gate_engine(self):
        """§2.3's engine rungs over this engine — the gate checks whatever
        recipe the night branch is at, *when it runs*."""
        from core.engine.gate import EngineGateEngine

        seat = self
        return EngineGateEngine(
            self.engine,
            recipe_at=lambda: gate_recipe_at(seat._recipe_seat),
        )

    # -- internals -----------------------------------------------------------

    def _venv_runtime(self):
        runtime = getattr(self.engine, "_runtime", None)
        if runtime is None or getattr(runtime, "boundary", None) != "venv-subprocess":
            raise RuntimeError(
                "the engine behind this seat is not the venv runtime; the "
                "row asked for the venv's own terms"
            )
        return runtime

    def _recipe_document(self):
        head = self._recipe_seat.head("night")
        return self._recipe_seat.store.get_document(head)


def gate_recipe_at(recipe_seat):
    """(recipe document, version hash) at the night branch's head — the
    gate's snapshot, answered per call so a mid-night commit is seen."""
    head = recipe_seat.head("night")
    store = recipe_seat.store
    return store.get_document(head), store.get_version(head).root_hash
