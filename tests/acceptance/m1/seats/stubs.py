"""The stubs the plan expects M1 to run on (plan §2, M1 risks): no engine,
no bpy wheel, no critic model yet.

* `StubTelemetry` — a lane that is free (load 0.3), the pre-flight's honest
  "lane free" branch. core-api's `BlindTelemetry` is the other honest
  branch ("status will be `did not run — unknown`") and is exercised by its
  own seat's tests.
* `StubGateEngine` — core-api's `MergeGateEngine` seam (§2.3 steps 1–6) over
  the stub generator: the analytic checks and render rungs pass
  deterministically, and every critic-shaped verdict wears
  `verdict@scripted` on its face (RV patch 15 — no critic model has been
  chosen, so no verdict may pretend otherwise).
* `stub_render(seed, rung, what)` — the deterministic "render" bytes. Same
  seed, same bytes; that is the property the stage cache and the sealed-bet
  replays lean on (§1.9, §5.3), and the stub keeps it honest.
"""

from __future__ import annotations

import hashlib


class StubTelemetry:
    """§3.2.2: the lane is free and telemetry can see it."""

    def __init__(self, load: float = 0.3) -> None:
        self._load = load

    def lane_load(self) -> float | None:
        return self._load


class StubGateEngine:
    """§2.3's engine rungs over the stub generator — always labelled."""

    def deterministic_rebuild(self, edit_id: str | None) -> dict:
        return {
            "ok": True,
            "check": "deterministic_rebuild",
            "engine": "stub-generator",
            "byte_identical": True,
        }

    def render_rung(self, rung: int, seed: int) -> dict:
        return {
            "verdict": "keep",
            "label": "verdict@scripted",
            "degraded": True,
            "rung": rung,
            "seed": seed,
            "summary": (
                f"rung-{rung} · stub generator · deterministic in seed {seed} · "
                "verdict@scripted"
            ),
        }

    def run_checks(self, checks: list[dict]) -> list[dict]:
        out = []
        for check in checks:
            kind = check.get("kind", "?")
            out.append({
                "check": f"{kind}:{check.get('spec', {})}",
                "ok": True,
                "engine": "stub-generator",
                "method": "scripted analytic computation (no physics engine — §7.14)",
                "label": "verdict@scripted",
            })
        return out


def stub_render(seed: int, rung: int, what: str = "harbor") -> bytes:
    """Deterministic render bytes: the stub generator's one promise.

    A real rung would be a PNG from Cycles on the Thor; until the bpy wheel
    lands, the stub keeps the property every consumer depends on — the same
    (seed, rung, subject) always produces the same bytes — and says what it
    is inside the bytes it produces.
    """
    body = (
        f"stub-render v1 · {what} · rung {rung} · seed {seed} · "
        "generator: stub (engine pending, plan M1 risks)"
    ).encode("utf-8")
    digest = hashlib.sha256(body).hexdigest()[:16]
    return f"{body} · sha:{digest}".encode("utf-8")
