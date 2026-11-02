"""What is around the bot? A wider look, with the chunks given time to load."""

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
    time.sleep(12)  # let the chunks around the spawn load
    for radius in (16, 32, 48):
        code = (
            "const r = await mc.scan(%d);\n"
            "console.log(JSON.stringify(r.nearby));\n" % radius
        )
        result = adapter.run_code(code, timeout_s=120)
        print(f"scan {radius}:", result.log, result.error, flush=True)
    code = (
        "const o = await mc.scan_ore(32);\n"
        "console.log(JSON.stringify(o.ores));\n"
    )
    result = adapter.run_code(code, timeout_s=120)
    print("ores:", result.log, result.error, flush=True)
    print("facts:", json.dumps(adapter.observe(), sort_keys=True)[:600], flush=True)
    adapter.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
