"""The Prop-maker's generative batch, on the command line.

Run a night of props:

    python -m core.genbatch --requests examples/mini_night_requests.json \\
        --out artifacts/mini-night

The night's work is written into a SQLite ledger, the morning comes back as
JSON, as text and as the core's own HTML report, and every prop that was
made is recorded as an asset with its provenance and its licence row.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from core.night.ledger import SQLiteLedger
from core.night.report import render_html, render_text

from core.genbatch.comfy import ComfyClient
from core.genbatch.executor import Templates
from core.genbatch.models import PropRequest
from core.genbatch.night import run_prop_night
from core.genbatch.workflow import load_template

__all__ = ["main"]

DEFAULT_TRELLIS_ROOT = Path.home() / "lm-wt" / "trellis"


def _templates(root: Path) -> Templates:
    """The two workflow templates, read from the TRELLIS.2 environment."""
    workflows = root / "workflows"
    return Templates(
        image=load_template(workflows / "text2image.api.json"),
        trellis=load_template(workflows / "trellis2_512.api.json"),
    )


def _requests(path: Path) -> list[PropRequest]:
    body = json.loads(path.read_text())
    if not isinstance(body, list):
        raise SystemExit(f"{path}: the requests file must hold a list")
    return [PropRequest.model_validate(row) for row in body]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m core.genbatch",
        description="Run a night of generated props through TRELLIS.2.",
    )
    parser.add_argument(
        "--requests", required=True, type=Path, help="a JSON file of prop requests"
    )
    parser.add_argument(
        "--out", required=True, type=Path, help="where the night leaves its report"
    )
    parser.add_argument("--night-id", default="night-genbatch")
    parser.add_argument(
        "--comfy-url", default="http://127.0.0.1:8188", help="the ComfyUI service"
    )
    parser.add_argument(
        "--trellis-root",
        type=Path,
        default=DEFAULT_TRELLIS_ROOT,
        help="the TRELLIS.2 environment (read, never modified)",
    )
    args = parser.parse_args(argv)

    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    requests = _requests(args.requests)
    client = ComfyClient(
        args.comfy_url, output_root=args.trellis_root / "out"
    )
    ledger = SQLiteLedger(out / "ledger.db")
    try:
        report = run_prop_night(
            requests=requests,
            client=client,
            templates=_templates(args.trellis_root),
            ledger=ledger,
            night_id=args.night_id,
        )
    finally:
        ledger.close()

    (out / "report.json").write_text(report.model_dump_json(indent=2))
    (out / "report.txt").write_text(report.render_text() + "\n")
    (out / "report.html").write_text(render_html(report.night))
    (out / "core-report.txt").write_text(render_text(report.night) + "\n")
    (out / "assets.json").write_text(
        json.dumps([asset.model_dump() for asset in report.assets], indent=2)
    )
    print(report.render_text())
    print(f"\nthe night left its report in {out}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
