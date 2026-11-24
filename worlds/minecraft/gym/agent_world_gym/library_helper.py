"""A small helper for writing skills: the library's own rules, applied.

The world's library is content addressed (``skill_<12 hex>`` over the
body) and its door is closed (:mod:`agent_world_reflex.door`). A helper
that writes a skill around those two rules keeps the tests honest: the
skills they use are skills the world would accept.

The id is given rather than computed, because a test needs to name the
skill it is about. Everything else — the vocabulary check, the shape of
the record — is the world's.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
if str(REPO / "reflex") not in sys.path:
    sys.path.insert(0, str(REPO / "reflex"))

from agent_world_reflex.door import check_body  # noqa: E402
from agent_world_reflex.models import canonical_bytes  # noqa: E402

__all__ = ["write_skill", "skill_record"]


def skill_record(
    skill_id: str,
    *,
    family: str,
    role: str,
    title: str,
    body: str,
    predict: dict[str, Any] | None = None,
    preconditions: list[dict[str, Any]] | None = None,
    version: int = 1,
    status: str = "active",
) -> dict[str, Any]:
    """The skill as the library writes it, with the door applied."""
    api = list(check_body(body))
    return {
        "id": skill_id,
        "family": family,
        "version": version,
        "kind": "behaviour",
        "role": role,
        "title": title,
        "body": body,
        "api": api,
        "preconditions": list(preconditions or []),
        "predict": dict(predict or {"kind": "none"}),
        "author": {
            "model": "seed",
            "provider": "seed",
            "prompt_hash": "seed",
            "cost_cents": 0,
            "temperature": None,
        },
        "provenance": {},
        "created_at": "2026-11-02T00:00:00Z",
        "status": status,
        "retired_at": None,
        "retire_reason": None,
    }


def write_skill(root: Path | str, **kwargs: Any) -> Path:
    """Write one skill into a library directory."""
    directory = Path(root)
    directory.mkdir(parents=True, exist_ok=True)
    record = skill_record(**kwargs)
    path = directory / f"{record['id']}.json"
    path.write_bytes(canonical_bytes(record))
    return path


def write_library(root: Path | str, skills: list[dict[str, Any]]) -> None:
    """Write several skills at once."""
    for skill in skills:
        write_skill(root, **skill)


def _read(path: Path) -> dict[str, Any]:  # pragma: no cover - a convenience
    return json.loads(Path(path).read_text(encoding="utf-8"))
