#!/usr/bin/env python3
"""The delegate bake-off: score the reference set with one candidate.

One candidate per run, because the candidates are very different beasts: the
scripted checks are analytic and take milliseconds, the local decision model
wants a resident server, and the cloud one wants a Worker with the AI
binding. The harness runs one, measures it, and writes
``results/<name>.json``.

    python docs/lab/critic-delegate-scripts/score_set.py --candidate scripted
    python docs/lab/critic-delegate-scripts/score_set.py --candidate d1
    python docs/lab/critic-delegate-scripts/score_set.py --candidate clef
    python docs/lab/critic-delegate-scripts/score_set.py --candidate hybrid \
        --set delegate=d1

The members, the counting rule and the per-verdict timing are the ones the
first bake-off used (``docs/lab/critic-select-scripts/harness.py``), so the
rows here are comparable with the rows there by construction: the same
members, the same fold (:func:`core.critic.critic.calibration_table`), the
same clock.

The mesh half needs an interpreter with ``bpy`` — the Infinigen checkout's
virtualenv on the Thor:

    export CRITIC_BLENDER_PYTHON=~/src/infinigen-thor/.venv/bin/python
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SELECT = HERE.parent / "critic-select-scripts"
for path in (str(HERE), str(SELECT)):
    if path not in sys.path:
        sys.path.insert(0, path)

from harness import CACHE, MANIFEST, load_set, run_candidate  # noqa: E402

from core.critic.select import resolve_critic  # noqa: E402

RESULTS = HERE / "results"


def _parse_value(raw: str):
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", default="scripted")
    parser.add_argument("--name", default=None, help="the result file's name")
    parser.add_argument("--manifest", default=str(MANIFEST))
    parser.add_argument("--night", default=None)
    parser.add_argument(
        "--set",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="a keyword argument for the candidate (repeatable)",
    )
    args = parser.parse_args()

    kwargs = {}
    for item in args.set:
        key, _, raw = item.partition("=")
        kwargs[key] = _parse_value(raw)

    members, bases = load_set(args.manifest, CACHE)

    critic, reason = resolve_critic(args.candidate, **kwargs)
    if reason:
        print(f"! {reason} — falling back to the scripted critic")

    payload = run_candidate(critic, members, bases, night=args.night)
    payload["fallback_reason"] = reason
    payload["kwargs"] = {k: v for k, v in kwargs.items()}
    payload["box"] = _box_state()
    name = args.name or args.candidate
    RESULTS.mkdir(parents=True, exist_ok=True)
    out = RESULTS / f"{name}.json"
    out.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    table = payload["table"]
    print(
        f"\n{name}: in_band={table['in_band']} "
        f"tp={table['totals']['tp']} fp={table['totals']['fp']} "
        f"fn={table['totals']['fn']} tn={table['totals']['tn']}"
    )
    print(f"wrote {out}")
    return 0


def _box_state() -> dict:
    """The box's state, beside the numbers."""
    import platform
    import re
    import subprocess

    def _read(path: str, pattern: str) -> float | None:
        try:
            text = Path(path).read_text()
        except OSError:
            return None
        match = re.search(pattern, text)
        return float(match.group(1)) if match else None

    mem = _read("/proc/meminfo", r"MemAvailable:\s+(\d+) kB")
    model = None
    try:
        model = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=20,
        ).stdout.strip()
    except Exception:  # noqa: BLE001 - the box state is best effort
        model = None
    return {
        "kernel": platform.release(),
        "arch": platform.machine(),
        "mem_available_gib": round(mem / 1048576.0, 2) if mem else None,
        "gpu": model,
    }


if __name__ == "__main__":
    raise SystemExit(main())
