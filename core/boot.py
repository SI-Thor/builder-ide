"""Boot sequence (§5.2): core.boot → recover → core.recovered.

1. Open DB; projections dirty → catch up / rebuild by folding audit
   (projection.rebuilt when a rebuild was needed).
2. Verify artifact hashes referenced by landed work orders and reports; a
   broken reference fails loud (integrity.failure).
3. Recovery over jobs: expired lease with no heartbeat → job.requeued.
4. Attempts: no seat runner exists in this half — attempts stay as
   recorded; the adapter half resumes or restarts as attempt n+1.
5. Nights: if running, rails unexhausted and the wall window open → the
   queue is durable and resumes; else stop cleanly with the status line and
   lost_minutes computed from heartbeat gaps — never hidden.
"""
from __future__ import annotations

from datetime import datetime, timezone

from .canon import now_utc
from .errors import IntegrityFailure
from .events import core_actor
from .models import Rail


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc)


class Boot:
    def __init__(self, store, settings) -> None:
        self.store = store
        self.settings = settings

    def run(self) -> dict:
        report: dict = {"projections": {}, "integrity": "ok", "jobs_requeued": [],
                        "nights_stopped": [], "resumed_night": None}
        report["projections"] = self.store.boot()
        if report["projections"].get("rebuilt"):
            self.store.append(self.store.new_event(
                "projection.rebuilt", core_actor(),
                {"entity_kind": "core", "entity_id": "core"},
                {"reason": report["projections"].get("diffs", "fold_seq ahead of audit")},
            ))
        self.store.append(self.store.new_event(
            "core.boot", core_actor(), {"entity_kind": "core", "entity_id": "core"},
            {"at": now_utc(), "projections": report["projections"]},
        ))
        broken = self.integrity_check()
        if broken:
            self.store.append(self.store.new_event(
                "integrity.failure", core_actor(),
                {"entity_kind": "core", "entity_id": "core"},
                {"broken": broken},
            ))
            raise IntegrityFailure(
                "artifact integrity failures at boot (§5.2 step 2)", broken=broken)
        report["jobs_requeued"] = self.recover_jobs()
        stopped, resumed = self.recover_nights()
        report["nights_stopped"] = stopped
        report["resumed_night"] = resumed
        self.store.append(self.store.new_event(
            "core.recovered", core_actor(), {"entity_kind": "core", "entity_id": "core"},
            {"at": now_utc(), **{k: v for k, v in report.items() if k != "projections"}},
        ))
        return report

    # ------------------------------------------------------------- integrity

    def integrity_check(self) -> list[dict]:
        broken: list[dict] = []
        for row in self.store.scan("work_orders"):
            if row.get("state") not in ("landed", "kept"):
                continue
            doc = row["payload"]
            refs: list[tuple[str, str]] = []
            preview = doc.get("preview") or {}
            if preview.get("sha256"):
                refs.append(("preview", preview["sha256"]))
            for ev in doc.get("evidence", []):
                if ev.get("sha256", "").startswith("sha256:"):
                    refs.append((f"evidence:{ev.get('kind')}", ev["sha256"]))
            for what, sha in refs:
                if not self.store.artifacts.verify(sha):
                    broken.append({"entity": "work_order", "id": row["id"], "what": what, "sha256": sha})
        for row in self.store.scan("nights"):
            rep = (row["payload"] or {}).get("report") or {}
            if rep.get("sha256") and not self.store.artifacts.verify(rep["sha256"]):
                broken.append({"entity": "night", "id": row["id"], "what": "report", "sha256": rep["sha256"]})
        return broken

    # ------------------------------------------------------------- jobs

    def recover_jobs(self) -> list[str]:
        requeued: list[str] = []
        now = now_utc()
        for row in self.store.scan("jobs"):
            if row.get("state") not in ("running", "queued"):
                continue
            doc = row["payload"]
            lease_until = doc.get("lease_until")
            heartbeat = doc.get("heartbeat_at")
            if row.get("state") == "running" and lease_until and lease_until > now:
                continue  # lease still live; the runner owns it
            if row.get("state") == "running" and heartbeat and lease_until is None:
                continue
            ev = self.store.new_event(
                "job.requeued", core_actor(),
                {"entity_kind": "job", "entity_id": row["id"]},
                {"from_state": row["state"], "reason": "expired lease at boot (§5.2 step 3)",
                 "id": row["id"], "state": "requeued"},
            )
            try:
                self.store.append(ev)
                requeued.append(row["id"])
            except Exception:
                continue
        return requeued

    # ------------------------------------------------------------- nights

    def recover_nights(self) -> tuple[list[dict], str | None]:
        from .svc.nights import NightsService  # late import: report builder needed

        svc = NightsService(self.store, self.settings)
        stopped: list[dict] = []
        resumed: str | None = None
        now = _parse(now_utc())
        for row in self.store.scan("nights"):
            if row.get("state") != "running":
                continue
            night = row["payload"]
            started = _parse(night.get("started_at", now_utc()))
            rails = Rail(**{k: v for k, v in (night.get("rails") or {}).items()
                            if k in ("gpu_minutes", "hosted_cents", "wall_minutes")})
            budget = self.store.get_row("budget", {"night": row["id"]})
            spend = (budget or {}).get("payload", {})
            gpu_used = float(spend.get("gpu_minutes", 0))
            wall_used = (now - started).total_seconds() / 60
            rails_left = rails.gpu_minutes - gpu_used > 0 and rails.wall_minutes - wall_used > 0
            if rails_left:
                resumed = row["id"]  # durable queue resumes from the last sealed step
                continue
            svc.stop(row["id"], core_actor(), reason="boot recovery: rails exhausted or window closed")
            stopped.append({"id": row["id"], "status": "stopped at boot"})
        return stopped, resumed
