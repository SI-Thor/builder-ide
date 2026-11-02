"""How long does a scan take? The facts have to be cheap enough to be read
on every step of the loop."""

from __future__ import annotations

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
    for radius in (16, 48, 96):
        started = time.time()
        code = "const r = await mc.scan(%d);\nconsole.log('n=' + Object.keys(r.nearby).length);\n" % radius
        result = adapter.run_code(code, timeout_s=180)
        print(f"scan {radius}: {time.time() - started:.2f}s log={result.log} err={result.error}",
              flush=True)
    started = time.time()
    code = "const r = await mc.scan_ore(32);\nconsole.log('n=' + Object.keys(r.ores).length);\n"
    result = adapter.run_code(code, timeout_s=180)
    print(f"scan_ore 32: {time.time() - started:.2f}s log={result.log} err={result.error}",
          flush=True)
    adapter.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
