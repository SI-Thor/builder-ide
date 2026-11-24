#!/usr/bin/env python3
"""The decision model's port: join the box's one d1, whatever port it is on.

After the Thor's 2026-11-01 reboot, another seat's serve held the d1-2B
lease (on port 8142) while the world asked its configured 8094 and got
nothing — the reflex ran without its judge, logging failures. These
tests pin the discovery: the configured port when it answers, the
lease's port when only it answers, the configured port when nothing
does.

    runtime/venv/bin/python tests/test_d1_port.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "reflex"))

import agent_world_reflex.decision as decision  # noqa: E402

results: list[str] = []


def check(name: str, got, want) -> None:
    ok = got == want
    results.append(f"{'ok  ' if ok else 'FAIL'} {name}: got {got!r}, want {want!r}")
    if not ok:
        results.append("FAILED: " + name)


def main() -> None:
    real_answers = decision._answers
    real_leases = decision.lease_ports_for
    real_speaks = decision._speaks_systemone
    try:
        decision._answers = lambda port, timeout=2.0: port == 8094  # noqa: E731
        decision._speaks_systemone = lambda port, timeout=4.0: True  # noqa: E731
        decision.lease_ports_for = lambda model: [("serve.d1-2B", 8142)]  # noqa: E731
        check("configured port answers → use it", decision.discover_d1_port(configured=8094), (8094, "configured"))

        decision._answers = lambda port, timeout=2.0: port == 8142  # noqa: E731
        check(
            "only the lease's port answers → join it",
            decision.discover_d1_port(configured=8094),
            (8142, "lease serve.d1-2B"),
        )

        # A green health door is not enough: the playtest of 2026-11-01
        # found a lease whose server answered /health and not the API,
        # and the reflex failed 480 of 486 asks against it.
        decision._speaks_systemone = lambda port, timeout=4.0: port == 8094  # noqa: E731
        check(
            "a lease that does not speak the API is skipped",
            decision.discover_d1_port(configured=8094),
            (8094, "none"),
        )

        decision._answers = lambda port, timeout=2.0: False  # noqa: E731
        decision._speaks_systemone = lambda port, timeout=4.0: False  # noqa: E731
        check(
            "nothing answers → configured port, and say so",
            decision.discover_d1_port(configured=8094),
            (8094, "none"),
        )

        decision.lease_ports_for = lambda model: []  # noqa: E731
        decision._answers = lambda port, timeout=2.0: port == 8142  # noqa: E731
        decision._speaks_systemone = lambda port, timeout=4.0: True  # noqa: E731
        check(
            "no lease for this model → configured port",
            decision.discover_d1_port(configured=8094),
            (8094, "none"),
        )
    finally:
        decision._answers = real_answers
        decision.lease_ports_for = real_leases
        decision._speaks_systemone = real_speaks

    print("\n".join(results))
    if any(r.startswith("FAIL") for r in results):
        sys.exit(1)
    print(f"all {sum(1 for r in results if r.startswith('ok'))} checks pass")


if __name__ == "__main__":
    main()
