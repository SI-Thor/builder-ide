"""What does mc.move_to_block actually do when the tree is ~87 blocks
out? The a2 run's wood programs all call it and finish in ~0.9 s with
ok=True, no log, no error — and the bot never moves (the facts' oak_log
distance pinned at 87.4 for nine straight steps). This drives the call
by hand and prints what comes back, how long it took, and where the
probe bot ended up. It joins the sandbox as a second bot; it does not
touch the measured run's bot (blocks are shared, positions are not).
"""

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
    time.sleep(15)  # chunks
    print("start position:", (adapter._call("observe") or {}).get("position"), flush=True)
    scan = adapter.run_code(
        "const r = await mc.scan(160);\nconsole.log('oak_log', JSON.stringify(r.nearby.oak_log));\n",
        timeout_s=60,
    )
    print("scan:", scan.log, scan.error, flush=True)

    started = time.time()
    walk = adapter.run_code(
        "const t0 = Date.now();\n"
        "const r = await mc.move_to_block('oak_log', 128, 60000);\n"
        "console.log('move took', Date.now() - t0, 'ms');\n"
        "console.log('returned', JSON.stringify(r));\n",
        timeout_s=90,
    )
    print(f"program wall {time.time() - started:.1f}s:", walk.log, walk.error, flush=True)
    print("end position:", (adapter._call("observe") or {}).get("position"), flush=True)
    adapter.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
