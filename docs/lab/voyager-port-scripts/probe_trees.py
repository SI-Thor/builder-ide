"""How far is the nearest tree? The world's own answer to "is this a place a
player could start from".

The scan reaches 160 blocks, which is the loaded area of the server at
view-distance 8. If there is no log inside it, the spawn is a place where
a player would have to walk a long way before the tech tree starts, and
that is a fact about the measurement, not a bug to be hidden.
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
    time.sleep(15)
    for radius in (48, 96, 160):
        code = "const r = await mc.scan(%d);\nconsole.log(JSON.stringify(r.nearby));\n" % radius
        result = adapter.run_code(code, timeout_s=180)
        try:
            found = json.loads(result.log[0]) if result.log else {}
        except Exception:
            found = {}
        logs = {k: v for k, v in found.items() if k.endswith("_log")}
        print(f"scan {radius}: logs={json.dumps(logs)} error={result.error}", flush=True)
    adapter.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
