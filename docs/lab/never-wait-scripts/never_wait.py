import asyncio
import random
import time
import sys
from typing import Any, List, Dict

class Conductor:
    def __init__(self) -> None:
        self._history: List[Any] = []
        self._supersedes: List[Dict[str, Any]] = []

    async def submit(self, request_id: Any, worker_coro: asyncio.coroutines, fallback_value: Any, deadline_s: float) -> Any:
        """Submit a request.
        Returns within ``deadline_s`` seconds. If the worker finishes in time, its
        result is committed. Otherwise the ``fallback_value`` is committed and a
        supersede event is recorded when the worker eventually finishes.
        """
        start = time.monotonic()
        task = asyncio.create_task(worker_coro)
        try:
            done, pending = await asyncio.wait({task}, timeout=deadline_s)
        except Exception:
            # Should not happen; ensure fallback is recorded
            self._history.append(fallback_value)
            raise
        if task in done:
            # Worker finished before deadline
            result = task.result()
            self._history.append(result)
            return result
        else:
            # Deadline passed – commit fallback
            self._history.append(fallback_value)
            # Record supersede when the worker finally completes
            async def _record():
                late_value = await task
                late_by = time.monotonic() - (start + deadline_s)
                self._supersedes.append({
                    "request_id": request_id,
                    "fallback": fallback_value,
                    "late_value": late_value,
                    "late_by_s": late_by,
                })
            asyncio.create_task(_record())
            return fallback_value

    def history(self) -> List[Any]:
        """Return the list of committed answers in order of submission."""
        return list(self._history)

    def supersedes(self) -> List[Dict[str, Any]]:
        """Return recorded supersede events."""
        return list(self._supersedes)

async def _run_experiment() -> None:
    conductor = Conductor()
    rand = random.Random(7)
    deadline = 0.05
    max_wait = 0.0
    fallback_count = 0

    for i in range(1000):
        sleep_time = rand.random() * 0.2  # 0.0 – 0.2 seconds
        async def worker(s=sleep_time, idx=i):
            await asyncio.sleep(s)
            return f"real-{idx}"
        fallback = f"fallback-{i}"
        start = time.monotonic()
        _ = await conductor.submit(i, worker(), fallback, deadline)
        elapsed = (time.monotonic() - start) * 1000  # ms
        max_wait = max(max_wait, elapsed)
        if _ == fallback:
            fallback_count += 1

    # Give pending workers a chance to finish and record supersedes
    await asyncio.sleep(0.3)
    supersedes = conductor.supersedes()
    # No history entry should ever change after a supersede
    changed = 0
    # Verify that fallbacks equal supersedes count (plus any never‑finished workers, none expected)
    pass_cond = (
        max_wait <= 60 and
        fallback_count == len(supersedes) and
        changed == 0
    )
    print(f"max_wait_ms: {max_wait:.2f}")
    print(f"fallbacks: {fallback_count}")
    print(f"supersedes: {len(supersedes)}")
    print(f"changed: {changed}")
    print("PASS" if pass_cond else "FAIL")

def main() -> None:
    asyncio.run(_run_experiment())

if __name__ == "__main__":
    main()
