"""The cloud LLM client the E4 improver uses.

Casey's rule (builder-ide CLAUDE.md): "No LLMs on the Thor. Language
comes from cloud subscriptions (z.ai, MiniMax, Claude, others), each a
parameter priced per call." The Thor never hosts one.

Two credential paths, tried in order:
  1. an explicit key in ~/.config/last-mile/secrets.env (ZAI_API_KEY etc.);
  2. this seat's own MiniMax credential (the local mcode auth store),
     which is what the runtime itself uses.

No key is ever printed.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


def _secret_from_secrets_env(name: str) -> str | None:
    p = Path(os.path.expanduser("~/.config/last-mile/secrets.env"))
    if not p.exists():
        return None
    for line in p.read_text().splitlines():
        line = line.strip()
        if line.startswith(f"{name}="):
            v = line.split("=", 1)[1].strip().strip('"').strip("'")
            return v or None
    return None


def _minimax_seat_token() -> str | None:
    """This seat's own MiniMax access token from the local auth store."""
    p = Path.home() / ".minimax/auth/prod/en/mcode-public/auth.json"
    if not p.exists():
        return None
    try:
        d = json.loads(p.read_text())
    except Exception:
        return None
    for rec in (d.get("records") or {}).values():
        tok = rec.get("accessToken")
        if tok:
            return str(tok)
    return None


class CloudLLM:
    """One cloud LLM, addressed by provider and model."""

    def __init__(self, provider: str = "minimax", model: str = "MiniMax-M3.1-Flash",
                 base_url: str | None = None, api_key: str | None = None,
                 timeout: float = 180.0):
        self.provider = provider
        self.model = model
        self.base_url = base_url or "https://agent.minimax.io/mavis/api/v1/llm/v1"
        self.timeout = timeout
        self._key = api_key
        self.credential_source: str | None = None

    def _resolve_key(self) -> str | None:
        if self._key:
            # already resolved; keep the source recorded the first time
            return self._key
        if self.provider == "minimax":
            k = _secret_from_secrets_env("MINIMAX_API_KEY") or _minimax_seat_token()
            if k:
                self.credential_source = ("~/.config/last-mile/secrets.env"
                                          if _secret_from_secrets_env("MINIMAX_API_KEY")
                                          else "local mcode auth store")
                self._key = k
                return k
        if self.provider in ("zai", "z.ai"):
            k = _secret_from_secrets_env("ZAI_API_KEY") or _secret_from_secrets_env("Z_AI_API_KEY")
            if k:
                self.credential_source = "~/.config/last-mile/secrets.env"
                self._key = k
                return k
        return None

    def available(self) -> bool:
        return self._resolve_key() is not None

    def call(self, prompt: str, system: str | None = None,
             max_tokens: int = 2000, temperature: float = 0.2,
             retries: int = 2) -> dict[str, Any]:
        key = self._resolve_key()
        if not key:
            raise RuntimeError(f"no credential for provider {self.provider}")
        body: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            body["system"] = system
        if temperature is not None:
            body["temperature"] = temperature
        # The provider is configured with the anthropic protocol, which
        # normally wants `x-api-key`; this seat's own credential is an
        # OAuth access token, which the gateway accepts as a Bearer.
        # Try both, in order, and report which one worked.
        header_sets = [
            {"Authorization": f"Bearer {key}", "anthropic-version": "2023-06-01",
             "Content-Type": "application/json"},
            {"x-api-key": key, "anthropic-version": "2023-06-01",
             "Content-Type": "application/json"},
        ]
        last: str = ""
        raw_first: Any = None
        for attempt in range(max(1, retries)):
            for headers in header_sets:
                req = urllib.request.Request(
                    f"{self.base_url.rstrip('/')}/messages",
                    data=json.dumps(body).encode(), method="POST", headers=headers)
                t0 = time.perf_counter()
                try:
                    with urllib.request.urlopen(req, timeout=self.timeout) as r:
                        data = json.loads(r.read())
                except urllib.error.HTTPError as e:
                    last = f"HTTP {e.code}: {e.read().decode(errors='replace')[:300]}"
                    continue
                except Exception as e:  # noqa: BLE001
                    raise RuntimeError(f"{type(e).__name__}: {e}")
                ms = (time.perf_counter() - t0) * 1000.0
                if raw_first is None:
                    raw_first = data
                text = ""
                for block in (data.get("content") or []):
                    if block.get("type") == "text":
                        text += block.get("text", "")
                if not text.strip() and attempt + 1 < max(1, retries):
                    # an empty answer: the model spent the budget on a
                    # thinking block, or the gateway dropped it. Try again.
                    last = "empty response"
                    continue
                return {"text": text, "ms": ms, "usage": data.get("usage"),
                        "model": data.get("model", self.model),
                        "credential_source": self.credential_source,
                        "stop_reason": data.get("stop_reason"),
                        "raw_keys": sorted((data or {}).keys()),
                        "n_content_blocks": len(data.get("content") or [])}
        return {"text": "", "ms": 0.0, "usage": None, "model": self.model,
                "credential_source": self.credential_source,
                "stop_reason": None, "raw_keys": sorted((raw_first or {}).keys()),
                "n_content_blocks": 0, "error": last}


def call_cloud(prompt: str, system: str | None = None,
               max_tokens: int = 2000, temperature: float = 0.2,
               provider: str = "minimax", model: str = "MiniMax-M3.1-Flash",
               ) -> dict[str, Any]:
    return CloudLLM(provider=provider, model=model).call(
        prompt, system=system, max_tokens=max_tokens, temperature=temperature)
