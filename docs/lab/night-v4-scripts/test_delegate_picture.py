#!/usr/bin/env python3
"""The delegate on the night's own picture — the path the ledger got wrong.

**What the night's ledger says.** All eighteen of the run's delegate calls
failed with the same error::

    {"stage": "image", "task_id": "img:crate", "variant_id": "img:crate_r1_v1",
     "error": "FileNotFoundError: [Errno 2] No such file or directory: 'crate_s102_00004_.png'"}

The executor records the **name** ComfyUI gave a picture; ComfyUI keeps the
file in its own input directory, and the delegate was handed the name
alone, so it opened a path that does not exist.

**What this script shows.** The same picture, named the same way, resolved
the way the runner now resolves it, answered by the same delegate: the
d1-2B with its projector, asked the six fixed class questions.

Run on the Thor, from the night-v4 worktree::

    cd ~/lm-wt/night-v4 && PYTHONPATH=. \
        ~/lm-wt/propmaker-batch/.venv/bin/python \
        docs/lab/night-v4-scripts/test_delegate_picture.py

It starts the delegate's own server under a lease, and stops it after.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

RUNNER = Path(__file__).with_name("run_night.py")

spec = importlib.util.spec_from_file_location("night_runner", RUNNER)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
sys.path.insert(0, str(runner.THOR_ADMIT_PKG))

from core.critic.candidates.d1 import ask_d1  # noqa: E402
from core.critic.candidates.questions import CLASS_QUESTIONS  # noqa: E402

#: A picture from the night's own run: the name the executor recorded and
#: the file ComfyUI keeps.
NAME = "crate_s102_00004_.png"


def main() -> int:
    heavy = runner.Heavy(ledger=None)
    handle = runner.serve_delegate(heavy, Path("/tmp"))
    try:
        picture = Path(NAME)
        if not picture.is_absolute():
            picture = runner.TRELLIS_INPUT / picture
        print(f"the picture, as the store records it: {NAME!r}")
        print(f"the picture, as the runner resolves it: {picture}")
        print(f"it is there: {picture.exists()}")
        probabilities, wall_s, usage = ask_d1(
            f"http://127.0.0.1:{runner.PORT_DELEGATE}", picture,
            {name: CLASS_QUESTIONS[name] for name in runner.IMAGE_CLASSES},
        )
        fired = {name: value for name, value in probabilities.items()
                 if value >= runner.DELEGATE_GATE}
        print(json.dumps({"probabilities": probabilities, "fired": fired,
                          "gate": runner.DELEGATE_GATE,
                          "wall_s": round(wall_s, 3)}, indent=2))
    finally:
        runner.stop_d1(handle)
    return 0


if __name__ == "__main__":
    sys.exit(main())
