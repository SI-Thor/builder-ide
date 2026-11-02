"""The cloud client — DeepInfra, three roles, every token counted.

The house rule is that the Thor hosts no language model: language comes
from the cloud, each call metered. This module is the one place that
rule is implemented, and it exists so that **every model call in the run
is counted**: the planner's, the coder's and the verifier's, with the
prompt and completion tokens the provider reports.

The key comes from ``~/.config/last-mile/secrets.env`` and is never
printed, never logged, and never written into a result. A client without
a key raises at construction, not at the first call, so a run cannot
half-start.

The wire format is DeepInfra's OpenAI-compatible one — the same shape
``~/lm-ops/di.py`` uses on the ProArt, so the two agree:

    POST https://api.deepinfra.com/v1/openai/chat/completions
    {"model": ..., "messages": [...], "max_tokens": ..., "temperature": ...}

and the answer carries ``usage.prompt_tokens`` and
``usage.completion_tokens``.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from .models import ModelReply, Role, TokenUsage

__all__ = [
    "CloudError",
    "DeepInfraClient",
    "ModelRouter",
    "CostBook",
    "load_secret",
    "DEEPINFRA_BASE_URL",
    "DEFAULT_MODELS",
]

#: DeepInfra's OpenAI-compatible root.
DEEPINFRA_BASE_URL = "https://api.deepinfra.com/v1/openai"

#: The three roles, with the models the brief names. The verifier is a
#: **different model** from the coder: a model that grades its own code
#: measures nothing, and the brief asks for the difference to be real.
DEFAULT_MODELS: dict[str, str] = {
    "planner": "XiaomiMiMo/MiMo-V2.6-Pro",
    "coder": "Qwen/Qwen3.8-27B",
    "verifier": "Qwen/Qwen3.8-Max",
}


class CloudError(RuntimeError):
    """A model call that did not come back with an answer."""

    def __init__(self, detail: str, *, status: int = 0) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status = status


def load_secret(name: str, *, path: str | None = None) -> str | None:
    """One value from the secrets file, or ``None``.

    The file is read here and nowhere else, and the value is never
    printed. A missing file is a missing key, not a crash: the caller
    decides what to do about it.
    """
    p = Path(path or os.path.expanduser("~/.config/last-mile/secrets.env"))
    if not p.exists():
        return None
    try:
        text = p.read_text()
    except OSError:
        return None
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key.strip() != name:
            continue
        value = value.strip().strip('"').strip("'")
        return value or None
    return None


class DeepInfraClient:
    """One model, addressed by role."""

    def __init__(
        self,
        role: Role,
        model: str,
        *,
        api_key: str | None = None,
        base_url: str = DEEPINFRA_BASE_URL,
        timeout: float = 300.0,
        max_retries: int = 2,
    ) -> None:
        self.role = role
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self._api_key = api_key or load_secret("DEEPINFRA_API_KEY") or load_secret(
            "OPENAI_API_KEY"
        )
        if not self._api_key:
            raise CloudError(
                "no DeepInfra key in ~/.config/last-mile/secrets.env "
                "(DEEPINFRA_API_KEY or OPENAI_API_KEY)"
            )

    def complete(
        self,
        system: str,
        user: str,
        *,
        max_tokens: int = 2000,
        temperature: float = 0.3,
    ) -> ModelReply:
        """Ask the model, and count what it cost."""
        body = {
            "model": self.model,
            "max_tokens": int(max_tokens),
            "temperature": float(temperature),
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        payload = json.dumps(body).encode()
        last: Exception | None = None
        for attempt in range(self.max_retries + 1):
            started = time.time()
            try:
                request = urllib.request.Request(
                    f"{self.base_url}/chat/completions",
                    data=payload,
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                )
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    data = json.load(response)
                break
            except urllib.error.HTTPError as exc:
                last = CloudError(
                    f"{self.model} returned HTTP {exc.code}", status=exc.code
                )
                if exc.code in (400, 401, 403, 404):
                    raise last
            except Exception as exc:  # network, timeout, bad JSON
                last = CloudError(f"{self.model} call failed: {exc}")
            if attempt < self.max_retries:
                time.sleep(2.0 * (attempt + 1))
        else:
            assert last is not None
            raise last

        try:
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise CloudError(f"{self.model} returned no message: {exc}") from exc
        usage = data.get("usage") or {}
        return ModelReply(
            text=text or "",
            usage=TokenUsage(
                role=self.role,
                model=self.model,
                prompt_tokens=int(usage.get("prompt_tokens") or 0),
                completion_tokens=int(usage.get("completion_tokens") or 0),
                seconds=time.time() - started,
            ),
        )


@dataclass
class CostBook:
    """Every token the run spent, by role and in total."""

    by_role: dict[str, int] = field(default_factory=dict)
    calls: dict[str, int] = field(default_factory=dict)
    seconds: float = 0.0

    def add(self, usage: TokenUsage) -> None:
        self.by_role[usage.role] = self.by_role.get(usage.role, 0) + usage.total_tokens
        self.calls[usage.role] = self.calls.get(usage.role, 0) + 1
        self.seconds += usage.seconds

    def total(self) -> int:
        return sum(self.by_role.values())

    def snapshot(self) -> dict[str, Any]:
        return {
            "by_role": dict(self.by_role),
            "calls": dict(self.calls),
            "total_tokens": self.total(),
            "model_seconds": round(self.seconds, 1),
        }


class ModelRouter:
    """The three roles, in one place.

    The loop asks for a role, not for a model, so the roles can be
    swapped without touching the loop — and so a test can put a scripted
    model in every seat.
    """

    def __init__(self, clients: Mapping[str, Any]) -> None:
        missing = {"planner", "coder", "verifier"} - set(clients)
        if missing:
            raise CloudError(f"the router is missing roles: {sorted(missing)}")
        self._clients = dict(clients)
        self.cost = CostBook()

    @classmethod
    def from_models(
        cls,
        models: Mapping[str, str] | None = None,
        *,
        api_key: str | None = None,
        base_url: str = DEEPINFRA_BASE_URL,
        timeout: float = 300.0,
    ) -> "ModelRouter":
        """The real clients, one per role."""
        chosen = dict(DEFAULT_MODELS)
        if models:
            chosen.update(models)
        clients = {
            role: DeepInfraClient(
                role,  # type: ignore[arg-type]
                model,
                api_key=api_key,
                base_url=base_url,
                timeout=timeout,
            )
            for role, model in chosen.items()
        }
        return cls(clients)

    def client(self, role: str) -> Any:
        try:
            return self._clients[role]
        except KeyError:
            raise CloudError(f"no client for the role {role!r}") from None

    def complete(
        self,
        role: str,
        system: str,
        user: str,
        *,
        max_tokens: int = 2000,
        temperature: float = 0.3,
    ) -> ModelReply:
        """Ask one role, and book what it cost."""
        reply = self.client(role).complete(
            system, user, max_tokens=max_tokens, temperature=temperature
        )
        self.cost.add(reply.usage)
        return reply
