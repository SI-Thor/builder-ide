"""Probe the Minecraft adapter: connect the bot, print the facts, run one skill.

This is the smoke test for the bridge — it does not use a model.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from core.voyager.adapters.minecraft import MinecraftAdapter


def main() -> int:
    adapter = MinecraftAdapter(log=lambda m: print("adapter:", m, flush=True))
    adapter.open()
    print("connected", flush=True)
    facts = adapter.observe()
    print(json.dumps(facts, indent=2, sort_keys=True)[:3000], flush=True)

    code = (
        "console.log('hello from the sandbox');\n"
        "const near = await mc.scan(24);\n"
        "console.log('nearby: ' + JSON.stringify(near.nearby));\n"
        "const count = await mc.count('oak_log');\n"
        "console.log('oak_log count: ' + count.count);\n"
    )
    result = adapter.run_code(code, timeout_s=60)
    print("run ok:", result.ok, "seconds:", round(result.seconds, 2), flush=True)
    print("log:", result.log, flush=True)
    print("error:", result.error, flush=True)

    check = adapter.evaluate("const c = await mc.count('oak_log'); return c.count >= 0;", timeout_s=30)
    print("evaluate:", check, flush=True)

    print("progress:", json.dumps(adapter.progress().as_dict(), sort_keys=True), flush=True)
    adapter.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
