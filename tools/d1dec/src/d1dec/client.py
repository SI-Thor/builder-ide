"""A small client for the decision servers.

The same client talks to llama.cpp's server and to ours, so the
benchmark measures the servers and not the client.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any


@dataclass
class PackResult:
    """The outcome of one pack."""

    tick: int
    char_id: str
    latency_s: float
    answers: dict[str, Any]
    input_tokens: int = 0
    error: str | None = None


class DecisionClient:
    def __init__(self, base_url: str, timeout: float = 600.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def ask_pack(self, body: dict[str, Any]) -> tuple[dict[str, Any], float, int]:
        """One pack, one request. Returns the answers, the latency and the
        number of input tokens the server counted."""
        payload = json.dumps(body).encode()
        req = urllib.request.Request(
            f"{self.base_url}/v1/systemone",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        t0 = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            body_text = exc.read().decode(errors="replace")
            raise RuntimeError(f"HTTP {exc.code}: {body_text[:400]}") from exc
        dt = time.perf_counter() - t0
        out = json.loads(raw)
        return out.get("answers", {}), dt, int(out.get("usage", {}).get("input_tokens", 0))

    def ask_packs_concurrently(
        self, packs: list[dict[str, Any]], workers: int | None = None
    ) -> list[PackResult]:
        """A tick: every pack is sent at once, the way a game tick lands.

        One thread per pack, so the server sees the whole burst at the
        same time.
        """
        workers = workers or max(1, len(packs))
        results: list[PackResult | None] = [None] * len(packs)
        lock = threading.Lock()

        def one(i: int) -> None:
            pack = packs[i]
            body = {"state": pack["state"], "questions": pack["questions"]}
            try:
                answers, dt, ntok = self.ask_pack(body)
                err = None
            except Exception as exc:
                answers, dt, ntok = {}, 0.0, 0
                err = f"{type(exc).__name__}: {exc}"
            with lock:
                results[i] = PackResult(
                    tick=pack.get("tick", 0),
                    char_id=pack.get("char_id", str(i)),
                    latency_s=dt,
                    answers=answers,
                    input_tokens=ntok,
                    error=err,
                )

        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(one, range(len(packs))))
        return [r for r in results if r is not None]

    def health(self) -> bool:
        try:
            with urllib.request.urlopen(f"{self.base_url}/health", timeout=5) as resp:
                return resp.status == 200
        except Exception:
            return False
