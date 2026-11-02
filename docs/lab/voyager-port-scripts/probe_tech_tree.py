"""Can the primitives play the tech tree? A hand-run of the whole chain.

This is the bridge's acceptance test, written as the steps a player
would take: walk to the tree, cut it, turn the logs into planks, make a
table, put it down, make a wooden pickaxe, and mine the stone.

It uses no model. If these steps work, the vocabulary a skill is written
against is a vocabulary that does something.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from core.voyager.adapters.minecraft import MinecraftAdapter

STEPS: list[tuple[str, str]] = [
    ("look around",
     "const r = await mc.scan(96);\n"
     "console.log('nearby ' + JSON.stringify(r.nearby));"),
    ("walk to the tree",
     "const r = await mc.move_to_block('oak_log', 96, 60000);\n"
     "console.log('at ' + JSON.stringify(r.at));"),
    ("cut the tree",
     "const r = await mc.collect('oak_log', 4, 16);\n"
     "console.log('collected ' + r.collected + ' have ' + r.have);"),
    ("make planks",
     "const r = await mc.craft('oak_planks', 8);\n"
     "console.log('planks ' + JSON.stringify(r.inventory));"),
    ("make a crafting table",
     "const r = await mc.craft('crafting_table', 1);\n"
     "console.log('table ' + JSON.stringify(r.inventory));"),
    ("put the table down",
     "const r = await mc.place_adjacent('crafting_table');\n"
     "console.log('placed at ' + JSON.stringify(r.at));"),
    ("make a wooden pickaxe",
     "const r = await mc.craft('wooden_pickaxe', 1);\n"
     "console.log('pickaxe ' + JSON.stringify(r.inventory));"),
    ("mine the stone",
     "const r = await mc.mine_block('stone', 32, 3);\n"
     "console.log('mined ' + r.mined + ' ' + JSON.stringify(r.inventory));"),
]


def main() -> int:
    adapter = MinecraftAdapter(log=lambda m: print("adapter:", m, flush=True))
    adapter.open()
    time.sleep(10)
    for label, code in STEPS:
        started = time.time()
        result = adapter.run_code(code, timeout_s=180)
        print(f"--- {label}: {time.time() - started:.1f}s ok={result.ok}", flush=True)
        for line in result.log:
            print("   ", line, flush=True)
        if result.error:
            print("    ERROR:", result.error, flush=True)
    progress = adapter.progress()
    print("progress:", json.dumps(progress.as_dict(), sort_keys=True), flush=True)
    print("milestones:", json.dumps(adapter.observe().get("milestones"), sort_keys=True),
          flush=True)
    adapter.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
