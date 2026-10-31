"""The critic seat's command line.

    python -m core.critic --grow --publish

grows the reference set from the sweep, re-scores it, and publishes the
FP/FN table. The night runner calls the same function
(:func:`core.critic.grow.grow`) from inside the night; this is the version a
human runs by hand, and the two share every line of the logic.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .grow import NightBudget, grow
from .select import CRITIC_DEFAULT, candidate_names, resolve_critic

__all__ = ["main"]


def _default_paths() -> tuple[Path, Path, Path]:
    root = Path(__file__).resolve().parent
    return (
        root / "reference-set.json",
        root / ".cache",
        root / "CALIBRATION.md",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="core.critic",
        description="The critic's calibration set: grow it, score it, publish it.",
    )
    parser.add_argument(
        "--grow",
        action="store_true",
        help="harvest the sweep, add the new renders, re-score the whole set",
    )
    parser.add_argument(
        "--publish",
        action="store_true",
        help="write the FP/FN table to CALIBRATION.md",
    )
    parser.add_argument(
        "--sweep-root",
        default=None,
        help="where the sweep's renders are (default: the Thor's)",
    )
    parser.add_argument("--manifest", default=None, help="the set's manifest")
    parser.add_argument("--cache", default=None, help="where derived images go")
    parser.add_argument("--table", default=None, help="where the table is written")
    parser.add_argument("--night", default=None, help="the night this is for")
    parser.add_argument(
        "--wall-minutes",
        type=float,
        default=30.0,
        help="the night's unused lane — the growth is sized to it",
    )
    parser.add_argument(
        "--target",
        type=int,
        default=30,
        help="how many members the set aims for (§1.9's ~30)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="print the result as JSON",
    )
    parser.add_argument(
        "--critic",
        default=None,
        help=(
            "which critic scores the set (default: the scripted one; "
            "BUILDER_CRITIC overrides it). Choices: "
            + ", ".join(candidate_names())
        ),
    )
    args = parser.parse_args(argv)

    manifest_path, cache_dir, table_path = _default_paths()
    if args.manifest:
        manifest_path = Path(args.manifest)
    if args.cache:
        cache_dir = Path(args.cache)
    if args.table:
        table_path = Path(args.table)

    if not args.grow and not args.publish:
        parser.print_help()
        return 2

    # The critic is a parameter with a default: the scripted checks, which
    # are also the fallback. A critic that cannot be built on this box
    # falls back to them and says why.
    wanted = args.critic or os.environ.get("BUILDER_CRITIC") or CRITIC_DEFAULT
    critic, reason = resolve_critic(wanted)
    if reason:
        print(f"! {reason} — the scripted critic answers instead")

    result = grow(
        sweep_root=args.sweep_root,
        manifest_path=manifest_path,
        cache_dir=cache_dir,
        table_path=table_path,
        night=args.night,
        budget=NightBudget(wall_minutes=args.wall_minutes),
        target=args.target,
        publish=args.publish,
        critic=critic,
    )

    if args.json:
        print(json.dumps(result.as_dict(), indent=1, sort_keys=True))
        return 0

    table = result.table
    print(f"critic:        {wanted} ({result.critic})")
    print(f"bases seen:    {result.bases_seen}")
    print(f"members added: {result.added_count}")
    print(f"members total: {len(result.added) + result.already_known}")
    if table is not None:
        print(f"in band:       {table.in_band}")
        for row in table.rows:
            if row.members == 0:
                continue
            print(
                f"  {row.defect:18s} tp={row.counts.tp:3d} fp={row.counts.fp:3d} "
                f"fn={row.counts.fn:3d} tn={row.counts.tn:3d}"
            )
    if result.table_path:
        print(f"published:     {result.table_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
