"""$BUILDER_HOME layout and service settings (core-spec §1.0).

    $BUILDER_HOME (default ~/builder-ide)
      core.db                 # SQLite WAL: audit + projections
      artifacts/ab/ab1234…    # content-addressed, write-once
      stages/                 # stage cache (owned by the engine half)
      recipes/                # recipe documents per version (mirror)
      sandboxes/              # engineer worktrees + seats, deletable
      usd-cache/              # compiled scene layers
      reports/                # prebuilt static morning reports
      tokens.json             # token registry (dev defaults; see auth.py)
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Settings:
    home: Path
    db_path: Path
    artifacts_dir: Path
    stages_dir: Path
    recipes_dir: Path
    sandboxes_dir: Path
    usd_cache_dir: Path
    reports_dir: Path
    tokens_file: Path
    # Dev tokens used when no tokens.json exists. Real per-actor issuance is a
    # later milestone; these are documented, LAN-only development credentials.
    default_tokens: dict = field(
        default_factory=lambda: {
            "dev-token-casey": {"class": "owner", "actor": "casey"},
            "dev-token-magnus": {"class": "owner", "actor": "magnus", "kid": True},
            "dev-token-panel": {"class": "panel", "actor": "panel"},
            "dev-token-propmaker": {"class": "character", "actor": "prop-maker"},
            "dev-token-companion": {"class": "character", "actor": "companion"},
        }
    )
    # Actors who may not submit free text, by class, in code (§4.1).
    kid_actors: frozenset = frozenset({"magnus"})
    # The SSE heartbeat (§4.3). Short enough to keep proxies from closing a
    # quiet connection, long enough not to fill the feed with noise.
    sse_heartbeat_seconds: float = 15.0
    sse_poll_seconds: float = 0.25
    # A stream's ceiling. A client that never disconnects must not hold a
    # connection forever.
    sse_max_seconds: float = 3600.0
    # The always-on daytime world (plan item 19, B3). Casey has not decided
    # B3, so the daytime is off unless this one setting says otherwise.
    daytime_enabled: bool = False

    @classmethod
    def for_home(cls, home: str | Path) -> "Settings":
        home = Path(home).expanduser().resolve()
        s = cls(
            home=home,
            db_path=home / "core.db",
            artifacts_dir=home / "artifacts",
            stages_dir=home / "stages",
            recipes_dir=home / "recipes",
            sandboxes_dir=home / "sandboxes",
            usd_cache_dir=home / "usd-cache",
            reports_dir=home / "reports",
            tokens_file=home / "tokens.json",
        )
        for d in (
            s.artifacts_dir,
            s.stages_dir,
            s.recipes_dir,
            s.sandboxes_dir,
            s.usd_cache_dir,
            s.reports_dir,
        ):
            d.mkdir(parents=True, exist_ok=True)
        return s

    def ensure_tokens_file(self) -> None:
        if not self.tokens_file.exists():
            self.tokens_file.write_text(
                json.dumps({"tokens": self.default_tokens}, indent=2) + "\n",
                encoding="utf-8",
            )

    def load_tokens(self) -> dict[str, dict]:
        if self.tokens_file.exists():
            data = json.loads(self.tokens_file.read_text(encoding="utf-8"))
            return data.get("tokens", {})
        if os.environ.get("BUILDER_TOKENS"):
            return json.loads(os.environ["BUILDER_TOKENS"]).get("tokens", {}) or json.loads(
                os.environ["BUILDER_TOKENS"]
            )
        return self.default_tokens


def default_settings() -> Settings:
    return Settings.for_home(os.environ.get("BUILDER_HOME", "~/builder-ide"))
