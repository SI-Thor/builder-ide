#!/usr/bin/env python3
"""Pull the tiles the real nights authored out of the real ledgers.

The tile seat's chooser has never played a tile in a real night, so there is
no real ``tile.played`` log to refit on. There *are* real tiles: the
``tile.authored`` rows the night runner wrote into its own ledger. This
script reads those ledgers and writes the tile bodies out, so the
experiment's option set is the one our nights actually produced rather than
something invented for the lab.

    python extract_real_tiles.py --out real_tiles.json

The ledgers are the night's own ``ledger.db`` (SQLite, one ``audit`` table);
the default paths are the three runs that wrote tiles.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

#: The real ledgers that carry ``tile.authored`` rows. The night runner
#: writes one ``ledger.db`` per run under its ``artifacts/<run>/``.
DEFAULT_LEDGERS = (
    Path.home() / "lm-wt/night-v3/artifacts/night-v3/ledger.db",
    Path.home() / "lm-wt/night-v3/artifacts/night-v3-c/ledger.db",
    Path.home() / "lm-wt/night-v3/artifacts/night-v3-d/ledger.db",
    Path.home() / "lm-wt/night-v4/artifacts/night-v4/ledger.db",
)


def extract(paths: list[Path]) -> list[dict]:
    """The distinct tile bodies, in the order the nights authored them."""
    out: list[dict] = []
    seen: set[str] = set()
    for path in paths:
        if not path.exists():
            continue
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            rows = conn.execute(
                "select at, payload from audit where type = 'tile.authored' "
                "order by seq"
            ).fetchall()
        finally:
            conn.close()
        for at, payload in rows:
            body = json.loads(payload)["body"]
            title = body["title"]
            if title in seen:
                continue
            seen.add(title)
            out.append(
                {
                    "title": title,
                    "body": body,
                    "authored_at": at,
                    "ledger": str(path),
                }
            )
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="real_tiles.json", help="where to write")
    parser.add_argument(
        "--ledger",
        action="append",
        default=[],
        help="a ledger.db to read (repeatable); the defaults are the real runs",
    )
    args = parser.parse_args()

    paths = [Path(p) for p in args.ledger] if args.ledger else list(DEFAULT_LEDGERS)
    tiles = extract(paths)
    payload = {
        "note": (
            "the tile bodies the real nights authored, read out of the night "
            "runners' own ledgers by extract_real_tiles.py"
        ),
        "ledgers": [str(p) for p in paths],
        "tiles": tiles,
    }
    Path(args.out).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(f"{len(tiles)} tiles -> {args.out}")
    for tile in tiles:
        print(f"  {tile['title']:28s} family={tile['body']['family']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
