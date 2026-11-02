#!/usr/bin/env python3
"""What does MiMo-V2.6-Pro actually return for a planner prompt?

The pilot run lost 6 of 23 steps to "planner_unreadable: no JSON
object in the reply", every one with the same ~1732 tokens — the
prompt's size and near nothing else. The suspicion: the model is a
reasoning model, the 1200-token completion budget is spent on
reasoning, and `message.content` comes back empty with
finish_reason "length". This probe asks the same role the same
shape of question a few times and prints the whole answer shape.

Usage: .venv/bin/python docs/lab/voyager-port-scripts/probe_planner_reply.py [n]
Needs the DeepInfra key in ~/.config/last-mile/secrets.env. Costs about
2k tokens per call. Takes ~30 s per call.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from core.voyager.llm import DeepInfraClient  # noqa: E402
from core.voyager.prompts import PLANNER_SYSTEM, planner_prompt  # noqa: E402

FACTS = {
    "inventory": {"oak_planks": 12, "stick": 8, "crafting_table": 1},
    "nearby": {"oak_log": 3},
    "position": [0, 64, 0],
}
LAST = "the previous program failed: Error: no recipe for wooden_pickaxe"


def main() -> int:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 4
    client = DeepInfraClient("planner", "XiaomiMiMo/MiMo-V2.6-Pro")  # type: ignore[arg-type]
    user = planner_prompt(
        goal="wooden_pickaxe",
        goal_description="craft a wooden pickaxe from planks and sticks",
        facts=FACTS,
        library=[
            {
                "id": "crafting_table",
                "title": "put a crafting table down",
                "description": "place the table from the inventory and open it",
            }
        ],
        last_outcome=LAST,
    )
    print(f"prompt tokens (rough): {len(user) // 4}")
    for i in range(n):
        for label, budget in (("1200 (the run's)", 1200), ("4000 (room to think)", 4000)):
            t0 = time.time()
            # one raw call, so the whole answer shape is visible
            body = {
                "model": client.model,
                "max_tokens": budget,
                "temperature": 0.3,
                "messages": [
                    {"role": "system", "content": PLANNER_SYSTEM},
                    {"role": "user", "content": user},
                ],
            }
            import urllib.request

            request = urllib.request.Request(
                f"{client.base_url}/chat/completions",
                data=json.dumps(body).encode(),
                headers={
                    "Authorization": f"Bearer {client._api_key}",
                    "Content-Type": "application/json",
                },
            )
            with urllib.request.urlopen(request, timeout=client.timeout) as response:
                data = json.load(response)
            choice = (data.get("choices") or [{}])[0]
            message = choice.get("message") or {}
            content = message.get("content") or ""
            print(
                f"[{i}] budget {label}: finish={choice.get('finish_reason')} "
                f"content_len={len(content)} "
                f"message_keys={sorted(message.keys())} "
                f"usage={data.get('usage')} "
                f"secs={time.time() - t0:.1f}"
            )
            if not content:
                rc = message.get("reasoning_content") or ""
                print(f"    reasoning_content_len={len(rc)} tail={rc[-200:]!r}")
            else:
                print(f"    content head={content[:160]!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
