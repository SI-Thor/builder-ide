#!/usr/bin/env python3
"""Reward audit: the reward distribution of every skill, per window.

The playtest of 2026-11-01 found one skill whose reward was exactly 0.5
on every one of its plays. A constant reward carries no signal, so the
chooser cannot learn from it — and a constant *high* reward (0.5 is
higher than any working gatherer's true rate) holds a role while
teaching nothing. This script prints, per skill and per window, the
shape of the reward: plays, wins, losses, partials, the distinct reward
values, and a flag on the degenerate patterns:

- ``CONSTANT``  — every play in the window scored the same value;
- ``NEVER-WIN`` — no play in the window scored above 0;
- ``NEVER-ZERO``— no play in the window scored 0.

Usage (on the Thor, from the repo root):

    python3 ops/reward-audit.py [--ledger runtime/world-ledger.sqlite3]
                                [--windows 0.5,2,all]

``--windows`` is a comma list of window lengths in hours, plus ``all``
for the whole ledger. The default is ``0.5,6,all``. Takes about a
second on the full ledger (34k events, Nov 2026).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sqlite3
from collections import defaultdict
from pathlib import Path

RESULT_REWARD = {"win": 1.0, "partial": None, "lose": 0.0}


def reward_of(play: dict):
    """The same arithmetic PlayRecord.reward uses (models.py).

    A partial play carries no reward: it cannot be scored, so the
    chooser does not learn from it. Before 2026-11-01 it scored 0.5 —
    the fabricated constant behind the playtest finding.
    """
    outcome = play.get("outcome") or {}
    score = outcome.get("score")
    if score is not None:
        return float(score)
    return RESULT_REWARD.get(outcome.get("result"), 0.0)


def load_plays(path: Path) -> list[dict]:
    conn = sqlite3.connect(str(path))
    plays = []
    for (payload,) in conn.execute(
        "SELECT payload FROM audit WHERE type = 'tile.played' ORDER BY seq"
    ):
        plays.append(json.loads(payload))
    conn.close()
    return plays


def load_families(skills_dir: Path) -> dict[str, str]:
    """skill_id → family, from the library on disk (one file per skill)."""
    families: dict[str, str] = {}
    if not skills_dir.is_dir():
        return families
    for path in skills_dir.glob("skill_*.json"):
        try:
            skill = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        families[skill.get("id", "")] = skill.get("family", "?")
    return families


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ledger", default="runtime/world-ledger.sqlite3")
    ap.add_argument("--skills-dir", default="runtime/skills")
    ap.add_argument("--windows", default="0.5,6,all")
    args = ap.parse_args()

    plays = load_plays(Path(args.ledger))
    families = load_families(Path(args.skills_dir))
    if not plays:
        print("no plays in", args.ledger)
        return

    newest = dt.datetime.fromisoformat(plays[-1]["at"].replace("Z", "+00:00"))
    print(f"ledger: {args.ledger}")
    print(f"plays: {len(plays)}  newest: {plays[-1]['at']}")

    windows: list[tuple[str, list[dict]]] = []
    for spec in args.windows.split(","):
        if spec == "all":
            windows.append(("whole ledger", plays))
        else:
            lo = newest - dt.timedelta(hours=float(spec))
            cut = lo.isoformat().replace("+00:00", "Z")
            sel = [p for p in plays if p["at"] >= cut]
            windows.append((f"last {spec}h", sel))

    for label, selected in windows:
        by_skill: dict[str, list[dict]] = defaultdict(list)
        for play in selected:
            by_skill[play["skill_id"]].append(play)
        print(f"\n=== {label}: {len(selected)} plays, {len(by_skill)} skills ===")
        header = f"{'skill':20} {'fam':>14} {'n':>6} {'win':>6} {'lose':>6} {'part':>6} {'mean':>7}  distinct rewards"
        print(header)
        rows = sorted(by_skill.items(), key=lambda kv: -len(kv[1]))
        for skill_id, group in rows:
            scored = [reward_of(p) for p in group if reward_of(p) is not None]
            rewards = [reward_of(p) for p in group]
            results = [(p.get("outcome") or {}).get("result") or "?" for p in group]
            distinct = sorted(set(scored))
            shown = str([round(v, 3) for v in distinct[:8]])
            if len(distinct) > 8:
                shown += f" … ({len(distinct)} values)"
            flags = []
            if scored and len(distinct) == 1:
                flags.append("CONSTANT")
            if scored and max(scored) == 0:
                flags.append("NEVER-WIN")
            if scored and min(scored) > 0:
                flags.append("NEVER-ZERO")
            unscored = len(rewards) - len(scored)
            family = families.get(skill_id, "?")
            extra = f"  [{unscored} unscored]" if unscored else ""
            print(
                f"{skill_id:20} {family:>14} {len(group):6} "
                f"{results.count('win'):6} {results.count('lose'):6} "
                f"{results.count('partial'):6} {(sum(scored) / len(scored) if scored else 0):7.4f}  "
                f"{shown}{extra}{'  <== ' + ','.join(flags) if flags else ''}"
            )


if __name__ == "__main__":
    main()
