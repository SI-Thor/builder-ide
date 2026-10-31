"""The stubs the plan still expects M1 to run on — fewer than before.

The engine-side stubs moved to the seam: the render rungs, the gate's
engine half and the preview bytes now run on `core.engine` with the **fake
engine** behind it (`seats/engine.py`, one configuration line). What stays
here is the piece that was never engine work:

* `StubTelemetry` — a lane that is free (load 0.3), the pre-flight's honest
  "lane free" branch. core-api's `BlindTelemetry` is the other honest
  branch ("status will be `did not run — unknown`") and is exercised by its
  own seat's tests.

Still stubs, each named with its missing piece (the README's tally):
`stub:critic` (no chosen, calibrated critic model — every verdict wears
`verdict@scripted`, RV patch 15) and `stub:engineer(aider-local)` (the
engineer adapter behind the attempt loop — the bake-off's pick). The
engine's bytes are the fake's — deterministic in the whole request, and
they say `fake-engine` inside themselves.
"""

from __future__ import annotations


class StubTelemetry:
    """§3.2.2: the lane is free and telemetry can see it."""

    def __init__(self, load: float = 0.3) -> None:
        self._load = load

    def lane_load(self) -> float | None:
        return self._load
