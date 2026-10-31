"""Budget mechanics (§5.5): rails (gpu_minutes, hosted_cents,
wall_minutes) plus the fourth rail — a per-model load cap enforced at
batch admission, because weight-swap thrash is the binding constraint and
no spend unit can count loads. Enforcement is BEFORE spend."""
from __future__ import annotations

from ..errors import NotFound, Refused
from ..events import Actor, core_actor
from ..models import Rail
from ..night.cost.model import get_model

THRESHOLDS = (80, 95, 100)
DEFAULT_LOADS_PER_NIGHT = 1


class BudgetService:
    def __init__(self, core) -> None:
        self.core = core
        self.store = core.store

    def snapshot(self, night: str | None = None) -> dict:
        if night is None:
            running = [n for n in self.store.scan("nights") if n.get("state") == "running"]
            if not running:
                nights = self.store.scan("nights")
                if not nights:
                    # no night has run: the bar is the model's own default —
                    # the spec's 360 GPU-min / 560 wall-min, from one place.
                    return {"night": None, "rails": get_model().default_night_rails().model_dump(),
                            "spend": {}, "remaining": {}, "bar": "no night", "loads": {},
                            "load_budget": {}, "thresholds": {}}
                night = sorted(nights, key=lambda n: n["payload"].get("started_at", ""))[-1]["id"]
            else:
                night = running[0]["id"]
        row = self.store.get_row("nights", {"id": night})
        if row is None:
            raise NotFound(f"night {night} not found", entity=night)
        budget = self.store.get_row("budget", {"night": night}) or {"payload": {}}
        doc = budget["payload"]
        rails = Rail(**(row["payload"].get("rails") or {}))
        spend = {k: doc.get(k, 0) for k in ("gpu_minutes", "hosted_cents", "wall_minutes")}
        remaining = {
            "gpu_minutes": round(rails.gpu_minutes - float(spend["gpu_minutes"]), 2),
            "hosted_cents": rails.hosted_cents - int(spend["hosted_cents"]),
            "wall_minutes": round(rails.wall_minutes - float(spend["wall_minutes"]), 2),
        }
        pct = (100 * float(spend["gpu_minutes"]) / rails.gpu_minutes) if rails.gpu_minutes else 0
        state = "ok" if pct < 80 else "drain (80%: stop opening batches)" if pct < 95 \
            else "stop (95%: close out in-flight)" if pct < 100 else "bar reached (100%)"
        load_budget = row["payload"].get("load_budget") or {}
        loads = doc.get("loads", {})
        load_state = {
            model: {"loads": n, "cap": load_budget.get(model, DEFAULT_LOADS_PER_NIGHT),
                    "at_cap": n >= load_budget.get(model, DEFAULT_LOADS_PER_NIGHT)}
            for model, n in loads.items()
        }
        return {
            "night": night,
            "rails": rails.model_dump(mode="json"),
            "spend": spend,
            "remaining": remaining,
            "bar": {"gpu_pct": round(pct, 1), "state": state},
            "loads": loads,
            "load_budget": load_budget,
            "load_state": load_state,
        }

    def check_thresholds(self, night: str) -> list[int]:
        """Graduated throttling (§5.5): 80 → stop opening batches, 95 → stop
        new work, 100 → commit branches and write the report. Each level is
        announced once per night as budget.threshold."""
        snap = self.snapshot(night)
        pct = snap["bar"]["gpu_pct"]
        already = {
            ev.payload.get("level")
            for ev in self.store.events_for("night", night, ["budget.threshold"])
        }
        fired: list[int] = []
        for level in THRESHOLDS:
            if pct >= level and level not in already:
                ev = self.store.new_event(
                    "budget.threshold", core_actor(),
                    {"entity_kind": "night", "entity_id": night},
                    {"level": level, "gpu_pct": pct, "cut": level >= 80,
                     "action": {80: "stop opening batches and branches; drain what runs",
                                95: "stop new work; close out in-flight branches",
                                100: "commit branches; write the report now"}[level]},
                )
                self.store.append(ev)
                fired.append(level)
        return fired

    def record_spend(self, night: str, spend: dict, *, job: str | None = None,
                     wo: str | None = None) -> None:
        ev = self.store.new_event(
            "budget.spend", core_actor(),
            {"entity_kind": "night", "entity_id": night},
            {"night": night, "spend": spend, "job": job, "wo": wo},
        )
        self.store.append(ev)
        self.check_thresholds(night)

    def model_load(self, night: str, model: str, actor: Actor | None = None) -> dict:
        """Admission for a model load: enforced BEFORE the load, never
        started-and-killed (§5.5)."""
        row = self.store.get_row("nights", {"id": night})
        if row is None:
            raise NotFound(f"night {night} not found", entity=night)
        budget = self.store.get_row("budget", {"night": night}) or {"payload": {"loads": {}}}
        loads = (budget["payload"].get("loads") or {})
        cap = row["payload"].get("load_budget", {}).get(model, DEFAULT_LOADS_PER_NIGHT)
        if loads.get(model, 0) + 1 > cap:
            raise Refused(
                f"model {model} is at its load cap ({cap}) tonight — the batch waits for "
                "the drain, it is not started and killed (§5.5)", night=night, model=model)
        ev = self.store.new_event(
            "sched.model.load", actor or core_actor(),
            {"entity_kind": "night", "entity_id": night},
            {"night": night, "model": model},
        )
        self.store.append(ev)
        return {"model": model, "loads": loads.get(model, 0) + 1, "cap": cap}
