#!/usr/bin/env python3
"""What does Qwen3.8-Max actually return for a verifier prompt?

The pilot's step 23 executed cleanly (the log says "Held
wooden_pickaxe.", the world's own record says the goal was met) and
the verifier still answered nothing a parser could read —
"unreadable: no JSON object in the reply", completion 1017 tokens
against a 700 budget. This probe replays that verifier call a few
times and prints the whole answer shape: finish_reason, the content,
and the reasoning, so the difference between a readable and an
unreadable reply is a measured thing.

Usage: .venv/bin/python docs/lab/voyager-port-scripts/probe_verifier_reply.py [n]
Needs the DeepInfra key. Costs ~2k tokens per call, ~30 s each.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from core.voyager.llm import DeepInfraClient  # noqa: E402
from core.voyager.prompts import VERIFIER_SYSTEM, verifier_prompt  # noqa: E402
from core.voyager.prompts import parse_json_block  # noqa: E402

# step 23 of the pilot, as it happened
BEFORE = {
    "food": 20, "health": 20, "held": "",
    "inventory": {"oak_planks": 4, "stick": 6, "crafting_table": 1},
    "milestones": {"wood": False, "planks": True, "crafting_table": True,
                   "wooden_pickaxe": False, "stone": False, "furnace": False,
                   "iron": False, "iron_pickaxe": False, "stone_pickaxe": False},
    "nearby": {}, "ores": {},
    "position": {"x": -2.5, "y": 64, "z": 103.5},
    "time_of_day": 14920, "world": "minecraft",
}
AFTER = {
    "food": 20, "health": 20, "held": "wooden_pickaxe",
    "inventory": {"oak_planks": 1, "stick": 6, "wooden_pickaxe": 1},
    "milestones": {"wood": False, "planks": True, "crafting_table": True,
                   "wooden_pickaxe": True, "stone": False, "furnace": False,
                   "iron": False, "iron_pickaxe": False, "stone_pickaxe": False},
    "nearby": {}, "ores": {},
    "position": {"x": -2.5, "y": 64, "z": 103.5},
    "time_of_day": 14920, "world": "minecraft",
}
CODE = """async function main() {
  if (!mc.has('wooden_pickaxe')) {
    throw new Error('wooden_pickaxe is not in inventory.');
  }
  await mc.equip('wooden_pickaxe');
  console.log('Held wooden_pickaxe.');
}
main();"""


def main() -> int:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 4
    client = DeepInfraClient("verifier", "Qwen/Qwen3.8-Max")  # type: ignore[arg-type]
    user = verifier_prompt(
        goal="wooden_pickaxe",
        goal_description="hold a wooden pickaxe in hand",
        before=BEFORE,
        after=AFTER,
        log=["Held wooden_pickaxe."],
        self_verified=None,
        ground_truth=True,
        code=CODE,
    )
    for i in range(n):
        for label, budget in (("700 (the run's)", 700), ("2000 (room to answer)", 2000)):
            t0 = time.time()
            body = {
                "model": client.model,
                "max_tokens": budget,
                "temperature": 0.1,
                "messages": [
                    {"role": "system", "content": VERIFIER_SYSTEM},
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
            reasoning = message.get("reasoning_content") or ""
            try:
                parsed = parse_json_block(content)
                verdict = parsed.get("verdict")
            except ValueError as exc:
                verdict = f"UNREADABLE ({exc})"
            usage = data.get("usage") or {}
            details = (usage.get("completion_tokens_details") or {})
            print(
                f"[{i}] budget {label}: finish={choice.get('finish_reason')} "
                f"content_len={len(content)} reasoning_len={len(reasoning)} "
                f"completion={usage.get('completion_tokens')} "
                f"(reasoning_tokens={details.get('reasoning_tokens')}) "
                f"verdict={verdict} secs={time.time() - t0:.1f}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
