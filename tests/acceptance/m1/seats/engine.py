"""The engine seat — `core.engine` behind one configuration line.

M1's render rungs and the merge gate's engine half used to be seat-local
stubs (`seats/stubs.py`'s `stub_render` and `StubGateEngine`). They now run
on the core's own engine seam, with the **fake engine** behind it — so the
day a real engine stands there, this file's `SPEC` is the line that changes
and nothing else in either acceptance suite does (plan §3 week-1 item 3:
*pointing at a real engine later is configuration*).

What each piece is:

* `SPEC` — the one configuration line. Today the fake engine impersonating
  Fjellvik's own pin (the shipped document's `ENGINE_PIN`, so the recipe's
  pin and the engine's pin agree by construction — the seam's rule 2 would
  refuse a mismatch). Tomorrow, the same shape with `"flavour":
  "infinigen-2-procfunc"` (or `-1x`) plus the checkout's paths.
* `EngineSeat` — builds the engine via `open_engine`, hands the spine its
  gate adapter (`core.engine.gate.EngineGateEngine`, the §2.3 rungs over
  any engine), and answers the preview asks the door makes.
* `gate_recipe_at` — the gate's *what am I checking right now*: the recipe
  document and version hash at the branch head under test, read per call
  (the gate runs during the night, after commits).
"""

from __future__ import annotations

from siblings import Seats

#: The engine behind this session — **the one configuration line**. The pin
#: is the shipped Fjellvik document's own, so the engine serves exactly the
#: recipe the session commits (a pin mismatch is the seam's loudest refusal).
SPEC: dict = {"flavour": "fake", "pin": None}  # pin filled from the document at build


class EngineSeat:
    """The session's engine, built from `SPEC` once per run.

    The recipe seat is *bound* after construction (the spine opens before
    the recipe seam exists — the gate's recipe_at closure answers per call,
    so the late binding is exactly the "read it at gate time" rule).
    """

    def __init__(self, seats: Seats, spec: dict | None = None) -> None:
        from core.engine import open_engine
        from core.vocab import seed as vocab_seed

        pin = dict(vocab_seed.ENGINE_PIN)
        spec = {**(spec or SPEC), "pin": (spec or SPEC).get("pin") or pin}
        self.spec = spec
        self.engine = open_engine(spec)
        self._recipe_seat = None

    def bind(self, recipe_seat) -> None:
        self._recipe_seat = recipe_seat

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


def gate_recipe_at(recipe_seat):
    """(recipe document, version hash) at the night branch's head — the
    gate's snapshot, answered per call so a mid-night commit is seen."""
    head = recipe_seat.head("night")
    store = recipe_seat.store
    return store.get_document(head), store.get_version(head).root_hash
