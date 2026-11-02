"""Does the run op carry the program's completion value?

The facts scans read their answer through it. Until 2026-11-02 the
bridge's run op dropped the value, so every facts scan ever taken
came back empty — the planner was totally blind, not radius-blind
(found by round 2's run 1: 91 steps, every step's nearby {}, while
the same scan through run_code saw nineteen block types)."""

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
    time.sleep(15)  # the client holds no chunks at the moment of spawn
    for code in (
        "return await mc.scan(160)",
        "const r = await mc.scan(160); return r",
    ):
        try:
            result = adapter._call("run", timeout_s=45.0, code=code, timeout_ms=30000)
            print(f"code={code!r} -> {repr(result)[:400]}", flush=True)
        except Exception as exc:
            print(f"code={code!r} -> EXC {exc!r}"[:600], flush=True)
    try:
        result = adapter._call("run", timeout_s=45.0,
                               code="return await mc.scan_ore(32)", timeout_ms=30000)
        print(f"scan_ore -> {repr(result)[:200]}", flush=True)
    except Exception as exc:
        print(f"scan_ore -> EXC {exc!r}"[:400], flush=True)
    adapter.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
