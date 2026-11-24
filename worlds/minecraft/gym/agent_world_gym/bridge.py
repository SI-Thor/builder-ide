"""The bridge: the HTTP client for the gym's own bot.

The gym's agent is a mineflayer bot, and mineflayer is Node's. So the bot
runs in Node — ``gym/bot/gym-bot.js``, which reuses the world's own Agent,
its api, its sandbox and its measure — and the Python env drives it over
loopback HTTP.

The bridge carries **no policy**: the env asks for an observation and asks
for a skill to be run, and nothing else crosses the door. It also writes
nothing to the live world: the world's reflex is replaced by a null one, so
the gym's plays are never recorded in the community's ledger.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

__all__ = ["GymBridge", "BridgeError"]


class BridgeError(RuntimeError):
    """The bridge could not answer, or answered with a refusal."""


class GymBridge:
    """A client for the gym's bot bridge."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 25640,
        timeout: float = 180.0,
    ) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout

    # -- the wire ---------------------------------------------------------------

    def _url(self, path: str) -> str:
        return f"http://{self.host}:{self.port}{path}"

    def _request(self, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        data = None
        headers = {}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(  # noqa: S310 - loopback, port is an int
            self._url(path), data=data, headers=headers
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as reply:
                body = reply.read().decode("utf-8")
        except urllib.error.HTTPError as err:
            raise BridgeError(f"the bridge answered {err.code}: {err.reason}") from err
        except (OSError, urllib.error.URLError) as err:
            raise BridgeError(f"the bridge is not answering: {err}") from err
        try:
            return json.loads(body)
        except ValueError as err:
            raise BridgeError(f"the bridge said something that is not JSON: {body[:200]}") from err

    # -- the doors --------------------------------------------------------------

    def health(self) -> dict[str, Any]:
        return self._request("/health")

    def skills(self) -> list[dict[str, Any]]:
        """The library the bridge holds: every skill it can run."""
        answer = self._request("/skills")
        return list(answer.get("skills") or [])

    def observation(self, grid: int = 0) -> dict[str, Any]:
        """The world's state facts, and the optional local block grid."""
        suffix = f"?grid={int(grid)}" if grid else ""
        return self._request(f"/observation{suffix}")

    def reset(self) -> dict[str, Any]:
        """Start a new episode: the agent's bag and counters are cleared."""
        return self._request("/reset", {})

    def step(self, skill_id: str) -> dict[str, Any]:
        """Run one skill and measure what it did."""
        answer = self._request("/step", {"skill_id": str(skill_id)})
        if not answer.get("ok", False):
            raise BridgeError(str(answer.get("error", "the bridge refused the step")))
        return answer
