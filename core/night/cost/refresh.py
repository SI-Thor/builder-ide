"""Refresh the cost model's data from the recordings it is built on.

Two things move under the model:

* the **sweep** — Infinigen's scenes and stages, measured on this box; and
* a **night** — the lane splits the box recorded while it worked.

When either records new timings the model's data should follow, or the model
is a snapshot of a moment that has already passed. But a number nobody can
trace back to a file is a number somebody typed, so the refresh **re-pins
the snapshot**: it copies the recording into the model's own data directory,
records the file's md5 and row count in the index, and writes down what it
did and when.

    ~/lm-wt/integrate-core/.venv/bin/python -m core.night.cost.refresh --sweep
    ~/lm-wt/integrate-core/.venv/bin/python -m core.night.cost.refresh \\
        --ledger ~/lm-wt/propmaker-batch/artifacts/mini-night/ledger.db
    ~/lm-wt/integrate-core/.venv/bin/python -m core.night.cost.refresh --check

``--check`` asks the quieter question: is the pinned snapshot still the file
the model was built from, or has the recording moved on since? That is the
question to ask before a night's plan is built on the model's numbers.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from core.night.cost.extract_mini_night import extract
from core.night.cost.records import DATA_DIR

__all__ = [
    "check",
    "refresh_night",
    "refresh_sweep",
]

#: The recording the sweep snapshot is taken from, when nothing else is said.
DEFAULT_SWEEP = Path("~/src/infinigen-thor/outputs/sweep/sweep.tsv")


def _md5(path: Path) -> str:
    """The file's md5 — the fingerprint that pins a snapshot."""
    digest = hashlib.md5()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 16), b""):
            digest.update(block)
    return digest.hexdigest()


def _rows(path: Path) -> int:
    """The number of data rows in a TSV (the header is not a row)."""
    with path.open("r", encoding="utf-8") as handle:
        return max(sum(1 for _ in handle) - 1, 0)


def _read_index(data_dir: Path) -> dict[str, Any]:
    return json.loads((data_dir / "recorded.json").read_text(encoding="utf-8"))


def _block_span(lines: list[str], name: str, lo: int, hi: int) -> tuple[int, int]:
    """The lines of the block called ``name``: the line it opens on, and the
    line that closes it."""
    begin = None
    for index in range(lo, hi):
        if lines[index].strip().startswith(f'"{name}":'):
            begin = index
            break
    if begin is None:
        raise KeyError(name)
    indent = len(lines[begin]) - len(lines[begin].lstrip())
    for index in range(begin + 1, hi):
        line = lines[index]
        if line.strip() in ("},", "}") and (len(line) - len(line.lstrip())) == indent:
            return begin, index
    raise KeyError(name)


def _patch(text: str, path: list[str], changes: dict[str, Any]) -> str:
    """Change some values inside a block of the index, and leave the rest of
    the file exactly as it was.

    The index is read by people as often as by the model, so a refresh should
    be a changed number, not a reformatted file.
    """
    lines = text.splitlines()
    if path:
        lo, hi = 0, len(lines)
        for name in path:
            begin, close = _block_span(lines, name, lo, hi)
            lo, hi = begin + 1, close
    else:
        lo, hi = 1, len(lines) - 1
    indent = 2 if not path else len(lines[hi]) - len(lines[hi].lstrip()) + 2
    for key, value in changes.items():
        rendered = json.dumps(value, ensure_ascii=False)
        for index in range(lo, hi):
            if lines[index].strip().startswith(f'"{key}":'):
                # the last key of a block carries no comma: keep it that way
                comma = "," if lines[index].rstrip().endswith(",") else ""
                lines[index] = f'{" " * indent}"{key}": {rendered}{comma}'
                break
        else:
            others = [i for i in range(lo, hi) if lines[i].strip().startswith('"')]
            comma = "," if others else ""
            lines.insert(lo, f'{" " * indent}"{key}": {rendered}{comma}')
            hi += 1
    return "\n".join(lines) + "\n"


def _now() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")


def refresh_sweep(source: Path | None = None, *, data_dir: Path = DATA_DIR) -> dict[str, Any]:
    """Re-pin the sweep snapshot, and record what was pinned.

    The snapshot is a copy: the model reads a file that does not change under
    it, and the index says which file it came from and what it weighed.
    """
    source = Path(source or DEFAULT_SWEEP).expanduser()
    if not source.exists():
        raise FileNotFoundError(f"no sweep at {source}")
    index = _read_index(data_dir)
    recorded = index.get("sources", {}).get("sweep", {})
    target = data_dir / recorded.get("file", "infinigen_sweep.tsv")

    before = recorded.get("md5")
    rows_before = recorded.get("rows")
    shutil.copyfile(source, target)
    rows = _rows(target)
    md5 = _md5(target)

    index_path = data_dir / "recorded.json"
    text = index_path.read_text(encoding="utf-8")
    text = _patch(text, ["sources", "sweep"], {
        "file": target.name,
        "origin": str(source),
        "rows": rows,
        "md5": md5,
        "note": (
            f"snapshot of the sweep recording ({_now()}); {rows} rows, pinned "
            f"by md5 so the model reads a file that does not move under it — "
            f"run --check to see whether the recording has moved on since"
        ),
    })
    text = _patch(text, [], {"recorded_at": datetime.now().astimezone().strftime("%Y-%m-%d")})
    index_path.write_text(text, encoding="utf-8")
    return {
        "source": str(source),
        "file": str(target),
        "rows": rows,
        "md5": md5,
        "changed": md5 != before or rows != rows_before,
        "was": {"md5": before, "rows": rows_before},
    }


def refresh_night(
    ledger: Path,
    *,
    source: str = "mini_night",
    data_dir: Path = DATA_DIR,
) -> dict[str, Any]:
    """Re-extract a night's lane splits into the model's data.

    The ledger is the night runner's own audit log: the GPU lane and the CPU
    lane measured separately, one sample per job.

    ``source`` names the night in the index — "mini_night" or
    "mini_night_2" — so each night's extract lands in its own file and its
    own entry in the index.
    """
    ledger = Path(ledger).expanduser()
    if not ledger.exists():
        raise FileNotFoundError(f"no ledger at {ledger}")
    index = _read_index(data_dir)
    recorded = index.get("sources", {}).get(source, {})
    target = data_dir / recorded.get("file", f"{source}.json")
    doc = str(recorded.get("doc", "docs/lab/mini-night.md"))

    document = extract(ledger, night=source, doc=doc)
    before = target.read_text(encoding="utf-8") if target.exists() else ""
    target.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n",
                      encoding="utf-8")
    index_path = data_dir / "recorded.json"
    text = index_path.read_text(encoding="utf-8")
    text = _patch(text, ["sources", source], {
        "file": target.name,
        "origin": str(ledger),
        "jobs": document["jobs"],
        "note": (
            f"the night's own ledger, re-extracted {_now()}: "
            f"{document['jobs']} jobs with both lanes measured"
        ),
    })
    text = _patch(text, [], {"recorded_at": datetime.now().astimezone().strftime("%Y-%m-%d")})
    index_path.write_text(text, encoding="utf-8")
    return {
        "source": str(ledger),
        "file": str(target),
        "jobs": document["jobs"],
        "changed": before != target.read_text(encoding="utf-8"),
    }


def check(*, data_dir: Path = DATA_DIR) -> dict[str, Any]:
    """Has the recording moved on since the model was pinned?

    The pinned snapshot and its md5 are the model's own; the origin is the
    recording they were taken from. When the two disagree, the model is still
    true of the snapshot and no longer true of the box.
    """
    index = _read_index(data_dir)
    sweep = index.get("sources", {}).get("sweep", {})
    snapshot = data_dir / sweep.get("file", "infinigen_sweep.tsv")
    result: dict[str, Any] = {
        "recorded_at": index.get("recorded_at"),
        "snapshot": str(snapshot),
        "md5": sweep.get("md5"),
        "rows": sweep.get("rows"),
    }
    if not snapshot.exists():
        result["stale"] = True
        result["why"] = f"the pinned snapshot {snapshot.name} is missing"
        return result
    result["snapshot_md5"] = _md5(snapshot)
    result["snapshot_rows"] = _rows(snapshot)
    result["pinned"] = result["snapshot_md5"] == sweep.get("md5")
    origin = Path(str(sweep.get("origin", ""))).expanduser()
    if origin.exists():
        result["origin"] = str(origin)
        result["origin_md5"] = _md5(origin)
        result["origin_rows"] = _rows(origin)
        result["moved_on"] = result["origin_md5"] != sweep.get("md5")
        result["stale"] = bool(result["moved_on"])
    else:
        result["origin"] = str(origin)
        result["origin_missing"] = True
        result["stale"] = not result["pinned"]
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sweep", nargs="?", const=str(DEFAULT_SWEEP), default=None,
                        type=Path, help="the sweep to re-pin (default: the recorded origin)")
    parser.add_argument("--ledger", type=Path, default=None,
                        help="a night's ledger to re-extract")
    parser.add_argument("--night", default="mini_night",
                        help="which night the ledger is: the source key it is "
                        "recorded under (mini_night, mini_night_2, ...)")
    parser.add_argument("--check", action="store_true",
                        help="report whether the recording has moved on")
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR,
                        help="the model's data directory")
    args = parser.parse_args()

    said = False
    if args.sweep is not None:
        print(json.dumps(refresh_sweep(args.sweep, data_dir=args.data_dir), indent=2))
        said = True
    if args.ledger is not None:
        print(json.dumps(
            refresh_night(args.ledger, source=args.night, data_dir=args.data_dir),
            indent=2))
        said = True
    if args.check or not said:
        print(json.dumps(check(data_dir=args.data_dir), indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover - a refresh script
    raise SystemExit(main())
