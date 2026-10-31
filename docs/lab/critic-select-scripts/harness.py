"""The shared harness: score the set with a candidate, and fold the table.

One place, so every candidate is measured the same way: the same members,
the same counting rule, the same per-verdict timing, and the same result
file shape. A candidate that is measured differently from the others is not
being compared, it is being told a different story.
"""

from __future__ import annotations

import json
import resource
import sys
import time
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.critic.critic import CriticRunner  # noqa: E402
from core.critic.grow import ensure_derived  # noqa: E402
from core.critic.set import read_bases, read_manifest  # noqa: E402

MANIFEST = ROOT / "core" / "critic" / "reference-set.json"
CACHE = ROOT / "core" / "critic" / ".cache"
RESULTS = ROOT / "docs" / "lab" / "critic-select-scripts" / "results"

__all__ = ["MANIFEST", "CACHE", "RESULTS", "load_set", "run_candidate", "write_result"]


def load_set(
    manifest_path: str | Path = MANIFEST,
    cache_dir: str | Path = CACHE,
) -> tuple[list[Any], list[Any]]:
    """The reference set: its members (with their images re-derived) and its bases."""
    manifest = Path(manifest_path)
    members = read_manifest(manifest)
    bases = read_bases(manifest)
    members = ensure_derived(members, bases, cache_dir)
    return members, bases


def run_candidate(
    critic: Any,
    members: Sequence[Any],
    bases: Sequence[Any],
    *,
    cache_dir: str | Path = CACHE,
    night: str | None = None,
    verbose: bool = True,
) -> dict[str, Any]:
    """Score every member the critic can see, and fold the table."""
    runner = CriticRunner(bases=bases, critic=critic, cache_dir=cache_dir)

    per_member = []
    for member in members:
        if member.layer not in critic.layers:
            # A pixel critic cannot judge a defect that lives in the
            # geometry, and the reference set never re-renders a mesh
            # defect. The member is left out of the fold entirely — it is
            # neither a miss nor a clean control.
            continue
        started = time.perf_counter()
        cpu_before = resource.getrusage(resource.RUSAGE_SELF)
        verdict = runner.score(member)
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        cpu_after = resource.getrusage(resource.RUSAGE_SELF)
        cpu_ms = (
            (cpu_after.ru_utime - cpu_before.ru_utime)
            + (cpu_after.ru_stime - cpu_before.ru_stime)
        ) * 1000.0
        per_member.append(
            {
                "member_id": verdict.member_id,
                "base_id": verdict.base_id,
                "defect": verdict.defect,
                "layer": verdict.layer,
                "label": verdict.label,
                "degraded": verdict.degraded,
                "latency_ms": round(elapsed_ms, 3),
                "cpu_ms": round(cpu_ms, 3),
                "checks": [
                    {
                        "check": c.check,
                        "fired": c.fired,
                        "detail": c.detail,
                        "measured": c.measured,
                        "applicable": c.applicable,
                    }
                    for c in verdict.checks
                ],
            }
        )
        if verbose:
            print(
                f"  {verdict.member_id} {verdict.defect or 'clean':18s} "
                f"{elapsed_ms:9.1f} ms  "
                f"fired={[c.check for c in verdict.checks if c.fired]}",
                flush=True,
            )

    table = runner.table(night=night)
    return {
        "candidate": getattr(critic, "name", "critic"),
        "critic": getattr(critic, "name", "critic"),
        "layers": list(critic.layers),
        "members": per_member,
        "table": table.as_dict(),
    }


def write_result(payload: dict[str, Any], name: str) -> Path:
    """Write one candidate's result and print its table."""
    RESULTS.mkdir(parents=True, exist_ok=True)
    out = RESULTS / f"{name}.json"
    out.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    table = payload["table"]
    print(f"\n{payload['candidate']}: in_band={table['in_band']} "
          f"totals={table['totals']}")
    for row in table["rows"]:
        if row["members"]:
            print(
                f"  {row['defect']:18s} tp={row['tp']} fp={row['fp']} "
                f"fn={row['fn']} tn={row['tn']}"
            )
    print(f"wrote {out}")
    return out
