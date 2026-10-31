"""The morning report (§3.2.8): a static page over the ledger, order fixed
by RV patch 2 — status line (computed), failures first, the cut named, the
night numbers (no single prediction score), filmstrip + branches with the
two standing options, parked questions triaged top-3 + count, the tally
with denominators, and the three-number morning line. Zero panel-side
state: regenerable from the log at any time (kill -9 test, §5.4)."""
from __future__ import annotations

from ..canon import canonical_bytes


class ReportBuilder:
    def __init__(self, core) -> None:
        self.core = core
        self.store = core.store

    def build(self, night_id: str) -> dict:
        from .nights import NightsService
        from .predictions import PredictionsService

        nights = NightsService(self.core, self.core.settings)
        night = nights.get(night_id)
        status = nights.compute_status(night_id)
        budget = self.store.get_row("budget", {"night": night_id}) or {"payload": {}}
        bdoc = budget["payload"]

        failures = self._failures(night)
        cut = self._cut(night_id)
        numbers = self._numbers(night_id, bdoc)
        filmstrip = [
            {"at": ev.at, "artifact": ev.artifact}
            for ev in self.store.events_since(0, types=["render.completed"])
            if ev.at >= night.started_at and (not night.stopped_at or ev.at <= night.stopped_at)
        ]
        branches = self._branches(night_id)
        questions = self._questions()
        landed = [
            w["payload"] for w in self.store.scan("work_orders")
            if w.get("state") == "landed"
        ]
        notices = [
            {"at": ev.at, **ev.payload}
            for ev in self.store.events_since(0, types=["model.change.noticed"])
        ]
        tally = PredictionsService(self.core).tally()
        three = self._three_number_line(night_id, bdoc)

        doc = {
            "night": night.model_dump(mode="json"),
            "status_line": status,
            "failure_line": self._failure_line(failures),
            "failures": failures,
            "cut": cut,
            "night_numbers": numbers,
            "filmstrip": filmstrip,
            "branches": branches,
            "parked_questions": questions,
            "landed_work_orders": landed,
            "model_change_notices": notices,
            "tally": tally["tally"],
            "three_number_line": three,
            "the_box": self._the_box(night),
        }
        return {
            "doc": doc,
            "json_bytes": canonical_bytes(doc),
            "text_bytes": self.render_text(doc).encode("utf-8"),
        }

    # ------------------------------------------------------------- sections

    def _failures(self, night) -> list[dict]:
        out = []
        for ev in self.store.events_since(0, types=["constraint.failed", "wo.failed",
                                                    "integrity.failure"]):
            if ev.at < night.started_at:
                continue
            out.append({"at": ev.at, "type": ev.type, "what": ev.payload})
        return out

    def _cut(self, night_id: str) -> dict:
        cut_tasks = [t["payload"] for t in self.store.scan("tasks")
                     if t.get("state") == "cut" and t["payload"].get("night") == night_id]
        ask_cut = {
            "gpu_minutes": sum(float(t.get("cost_estimate", {}).get("gpu_minutes", 0))
                               for t in cut_tasks),
            "wall_minutes": sum(float(t.get("cost_estimate", {}).get("wall_minutes", 0))
                                for t in cut_tasks),
        }
        if not cut_tasks:
            return {"line": "nothing was cut", "tasks": []}
        first = cut_tasks[0].get("intention", "")
        return {
            "line": f"{ask_cut['gpu_minutes'] / 60:.1f} GPU-h of the ask was cut at the bar; "
                    f"“{first[:48]}” is re-queued for tonight",
            "tasks": cut_tasks,
        }

    def _numbers(self, night_id: str, bdoc: dict) -> dict:
        events = self.store.events_since(0)
        edits = sum(1 for e in events if e.type == "version.committed")
        sealed = sum(1 for e in events if e.type == "prediction.sealed")
        critic_keeps = sum(1 for e in events if e.type == "critic.verdict"
                           and e.payload.get("verdict") == "keep")
        owner_keeps = sum(1 for e in events if e.type == "wo.kept")
        reverted = sum(1 for e in events if e.type == "branch.rejected") + \
            sum(1 for e in events if e.type == "critic.verdict"
                and e.payload.get("verdict") in ("fix", "revert"))
        parked = sum(1 for q in self.store.scan("questions") if q.get("open"))
        loads = bdoc.get("loads", {})
        load_budget = bdoc.get("load_budget", {})
        total_cap = sum(load_budget.get(m, 1) for m in loads) if loads else 0
        stage_hits = sum(1 for e in events if e.type == "job.done"
                         and e.payload.get("stage_cache") == "hit")
        stage_all = sum(1 for e in events if e.type == "job.done"
                        and e.payload.get("stage_cache") in ("hit", "miss", "partial"))
        return {
            "line": (
                f"{float(bdoc.get('wall_minutes', 0)) / 60:.1f} h wall · {edits} recipe edits · "
                f"{sealed} sealed bets · {critic_keeps + owner_keeps} kept "
                f"({critic_keeps} critic-keeps, {owner_keeps} owner-keeps) · "
                f"{reverted} reverted · {parked} parked · "
                f"{float(bdoc.get('gpu_minutes', 0)) / 60:.1f} of "
                f"{float((bdoc.get('rails') or {}).get('gpu_minutes', 0)) / 60:.1f} GPU-h · "
                f"{len(loads)} model loads (budget {total_cap or len(loads)}) · "
                f"stage-cache hits "
                f"{(100 * stage_hits // stage_all) if stage_all else 0}%"
            ),
            "recipe_edits": edits, "sealed_bets": sealed,
            "critic_keeps": critic_keeps, "owner_keeps": owner_keeps,
            "reverted": reverted, "parked": parked,
            "gpu_hours": round(float(bdoc.get("gpu_minutes", 0)) / 60, 2),
            "model_loads": loads, "model_load_budget": load_budget,
        }

    def _branches(self, night_id: str) -> dict:
        options = [b["payload"] for b in self.store.scan("branches")
                   if b.get("purpose") in ("morning-option", "night", "work-order")]
        standing = [
            {"name": "keep yesterday", "kind": "main-unchanged"},
            {"name": "back to the plan", "kind": "standing branch from the slate's base"},
        ]
        return {"options": options, "standing": standing}

    def _questions(self) -> dict:
        open_q = [q["payload"] for q in self.store.scan("questions") if q.get("open")]
        top3 = sorted(open_q, key=lambda q: q.get("id"))[:3]
        return {
            "top_3": top3,
            "count": len(open_q),
            "more_line": f"{len(open_q) - 3} more, none blocking" if len(open_q) > 3
            else "no further questions",
        }

    def _three_number_line(self, night_id: str, bdoc: dict) -> dict:
        gpu_h = round(float(bdoc.get("gpu_minutes", 0)) / 60, 1)
        hosted = f"${int(bdoc.get('hosted_cents', 0)) / 100:.2f} hosted (local)" \
            if not int(bdoc.get("hosted_cents", 0)) else \
            f"${int(bdoc.get('hosted_cents', 0)) / 100:.2f} hosted"
        decision_types = ["question.answered", "wo.kept", "wo.rejected"]
        decisions = sum(
            1 for e in self.store.events_since(0, types=decision_types)
            if e.actor.kind == "owner"
        )
        return {
            "line": f"{gpu_h} h of your Thor · {hosted} · "
                    f"{decisions} decisions of your attention (budget 10)",
            "gpu_hours": gpu_h, "hosted_cents": int(bdoc.get("hosted_cents", 0)),
            "attention_decisions": decisions, "attention_budget": 10,
        }

    def _the_box(self, night) -> list[dict]:
        """The machine's own growth beat: measured numbers replacing the
        slate's [e] fields (G §1)."""
        rows = []
        for ev in self.store.events_since(0):
            if ev.type == "critic.verdict" and ev.payload.get("timing"):
                rows.append({"what": "critic verdict", "timing": ev.payload["timing"]})
            if ev.type == "render.completed" and ev.payload.get("timing"):
                rows.append({"what": "render", "timing": ev.payload["timing"]})
        return rows

    def _failure_line(self, failures: list[dict]) -> str:
        if not failures:
            return "nothing failed"
        return f"{len(failures)} failure(s) — details below; failures lead the report"

    # ------------------------------------------------------------- text mode

    def render_text(self, doc: dict) -> str:
        """Text mode is the same ledger read (G §4.2)."""
        n = doc["night_numbers"]
        lines = [
            f"NIGHT {doc['night']['id']} — MORNING REPORT",
            "",
            f"1. STATUS: {doc['status_line']['line']}",
            f"2. FAILURES: {doc['failure_line']}",
            f"3. THE CUT: {doc['cut']['line']}",
            f"4. NUMBERS: {n['line']}",
            f"5. BRANCHES: {len(doc['branches']['options'])} options plus the standing "
            f"exits ({', '.join(s['name'] for s in doc['branches']['standing'])}); "
            f"parked questions: {doc['parked_questions']['count']} "
            f"({doc['parked_questions']['more_line']}); "
            f"landed work orders: {len(doc['landed_work_orders'])}",
            "6. TALLY (no single score — denominators or nothing):",
        ]
        for t in doc["tally"]:
            lines.append(f"   - {t['line']} · recency-weighted {t['recency_weighted']}")
        lines.append(f"7. {doc['three_number_line']['line']}")
        if doc["model_change_notices"]:
            lines.append("MODEL CHANGES (announced, never silent):")
            for notice in doc["model_change_notices"]:
                lines.append(f"   - {notice.get('at')}: {notice.get('line', notice)}")
        return "\n".join(lines) + "\n"

    def render_html(self, doc: dict) -> str:
        """Verdicts are words, never colour alone; stable reading order."""
        import html as h
        import json

        sections = [
            ("status", doc["status_line"]["line"]),
            ("failures", doc["failure_line"]),
            ("the cut", doc["cut"]["line"]),
            ("numbers", doc["night_numbers"]["line"]),
            ("three-number line", doc["three_number_line"]["line"]),
        ]
        body = "\n".join(
            f"<section><h2>{h.escape(title)}</h2><p>{h.escape(text)}</p></section>"
            for title, text in sections
        )
        tally_rows = "".join(
            f"<tr><td>{h.escape(t['builder'])}</td><td>{h.escape(t['claim_type'])}</td>"
            f"<td>{t['denominator']}</td><td>{t['hits']}</td>"
            f"<td>{t['recency_weighted'] if t['recency_weighted'] is not None else '—'}</td></tr>"
            for t in doc["tally"]
        )
        return (
            "<!doctype html><html><head><meta charset='utf-8'>"
            "<title>morning report</title>"
            "<style>body{font-family:system-ui;margin:2rem;max-width:46rem}"
            "section{margin:1rem 0;padding:.5rem 0;border-bottom:1px solid #ccc}"
            "td,th{padding:.2rem .6rem;text-align:left}</style></head><body>"
            f"<h1>Night {h.escape(doc['night']['id'])}</h1>{body}"
            "<section><h2>tally</h2><table>"
            "<tr><th>builder</th><th>claim type</th><th>denominator</th>"
            "<th>hits</th><th>recency-weighted</th></tr>"
            f"{tally_rows}</table>"
            f"<pre>{h.escape(json.dumps(doc, indent=1, sort_keys=True))}</pre>"
            "</section></body></html>"
        )
