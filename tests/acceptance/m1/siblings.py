"""Load the seats — from the integrated core, one package tree.

Before the merge (INTEGRATION.md), this module materialized each seat from
its own branch with `git show` into a gitignored `.siblings/` scratch dir
and imported the pieces behind aliases (`sib_api` for core-api's `core/`,
`builder_recipe`, a PEP 420 namespace `core` for the rest). The brief for
this branch was to rewire the acceptance adapters to the integrated core,
so that mapping collapsed into this:

===============  =======================  ====================================
seat (was)       imported as              how
===============  =======================  ====================================
`core-api`       `core`                   the merged package at the repo root
`core-recipe`    `core.recipe`            (`Core.open` is `core.svc.Core.open`;
`vocab`          `core.vocab`              `create_app` is `core.api.create_app`)
`cold-start`     `core.coldstart`
`night-runner`   `core.night`
`why-kernel`     `core.why`,              no stub packages survive the merge —
                 `core.justification`     the real packages answer every import
===============  =======================  ====================================

`usd-backbone` is `builder_usd` on the same tree; it stays unmateralized
here as before — M1's render rungs run against the stub generator by
design (plan §2 M1 risks), and the USD compiler needs its wheels.

Nothing is materialized anymore: the repo root goes on `sys.path` (the
pytest run already has it; the headless drivers do not) and the merged
packages import under their own names. `heads` reports the one commit the
tree is at — the seats no longer move independently.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parents[2]


@dataclass
class Seats:
    """The loaded seat modules, by seat name — now `core`'s subpackages."""

    api: object          # core               (was core-api, as sib_api)
    recipe: object       # core.recipe        (was core-recipe, builder_recipe)
    vocab: object        # core.vocab         (branch vocab)
    coldstart: object    # core.coldstart     (branch cold-start)
    night: object        # core.night         (branch night-runner)
    why: object          # core.why           (branch why-kernel)
    justification: object  # core.justification (branch why-kernel)

    @property
    def heads(self) -> dict[str, str]:
        return dict(self._heads)  # type: ignore[attr-defined]


def _repo_head() -> str:
    out = subprocess.run(
        ["git", "-C", str(_REPO), "rev-parse", "HEAD"], check=True,
        capture_output=True, text=True,
    )
    return out.stdout.strip()


_LOADED: "Seats | None" = None


def load() -> Seats:
    """Import the integrated core's seat packages. Returns the seat modules.

    Idempotent per process: the seats are process-wide, so cache them.
    """
    global _LOADED
    if _LOADED is not None:
        return _LOADED

    root = str(_REPO)
    if root not in sys.path:
        sys.path.insert(0, root)

    import core
    import core.recipe
    import core.vocab
    import core.coldstart
    import core.night
    import core.why
    import core.justification

    seats = Seats(
        api=core, recipe=core.recipe, vocab=core.vocab, coldstart=core.coldstart,
        night=core.night, why=core.why, justification=core.justification,
    )
    seats._heads = {"core": _repo_head()}  # type: ignore[attr-defined]
    _LOADED = seats
    return seats
