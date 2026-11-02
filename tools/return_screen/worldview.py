"""worldview.py — the world's ledger folded into what a returning human needs.

Everything here reads the world's SQLite ledger **read-only** (a `mode=ro`
URI) plus the two files beside it that carry human presence: the player
build log (named humans placing blocks) and the screen's own visit log.
Nothing in this module writes to the world.

The fold is cached with a TTL because the page asks for it on every load
and the ledger holds ~93k rows; the world keeps writing while we read
(short-lived read-only connections, WAL readers never block the writer).
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_DB = "/home/caseydigennaro/lm-wt/agent-world/runtime/world-ledger.sqlite3"
DEFAULT_PLAYER_LOG = "/home/caseydigennaro/lm-wt/agent-world/runtime/logs/player-builds.jsonl"

CHARACTERS = ["Kite", "Sprout", "Pebble", "Timber"]


def _connect(db: str) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{db}?mode=ro", uri=True)


def _iso(epoch: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch))


def parse_at(value: str) -> float:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    import datetime as _dt
    parsed = _dt.datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_dt.timezone.utc)
    return parsed.timestamp()


def _merge_intervals(points: list[tuple[float, float]], gap: float) -> list[tuple[float, float]]:
    """Consecutive (at, ...) points merged into intervals when within `gap` s."""
    if not points:
        return []
    intervals: list[list[float]] = [[points[0][0], points[0][0]]]
    for at, _ in points[1:]:
        if at - intervals[-1][1] <= gap:
            intervals[-1][1] = at
        else:
            intervals.append([at, at])
    return [(a, b) for a, b in intervals]


@dataclass
class _Cache:
    value: Any = None
    at: float = 0.0


class WorldView:
    """Cached, read-only folds of the world's ledger for the return screen."""

    def __init__(self, db: str = DEFAULT_DB, player_log: str = DEFAULT_PLAYER_LOG,
                 state_dir: str | Path = "state", ttl: float = 60.0) -> None:
        self.db = db
        self.player_log = Path(player_log)
        self.state_dir = Path(state_dir)
        self.ttl = ttl
        self._rows_cache = _Cache()
        self._drift_cache = _Cache()

    # ------------------------------------------------------------- raw rows

    def rows(self) -> list[dict]:
        """Every audit row, compact: seq, at (epoch), kind, actor, verdict,
        outcome, humans present, cost. Parsed once, cached."""
        now = time.time()
        c = self._rows_cache
        if c.value is not None and now - c.at < self.ttl:
            return c.value
        conn = _connect(self.db)
        out: list[dict] = []
        try:
            for seq, at, actor_json, kind, payload_json in conn.execute(
                    "SELECT seq, at, actor, type, payload FROM audit ORDER BY seq"):
                actor = json.loads(actor_json).get("id", "?")
                payload = json.loads(payload_json)
                row: dict[str, Any] = {
                    "seq": seq, "at": parse_at(at), "at_iso": at, "kind": kind,
                    "actor": actor, "payload": payload,
                }
                if kind == "tile.played":
                    outcome = payload.get("outcome", {})
                    row["verdict"] = outcome.get("result", "")
                    ctx = payload.get("context", {})
                    row["humans"] = int(ctx.get("humans") or 0)
                    row["agent"] = ctx.get("bot")
                    row["skill"] = payload.get("skill_id")
                elif kind == "judge.verdict":
                    cost = payload.get("cost", {}) or {}
                    row["refused"] = bool(payload.get("refused"))
                    row["tokens"] = int(cost.get("input_tokens") or 0)
                    row["gpu_minutes"] = float(cost.get("gpu_minutes") or 0.0)
                    row["hosted_cents"] = float(cost.get("hosted_cents") or 0.0)
                    row["verdict"] = "refused" if row["refused"] else "ruled"
                else:
                    row["verdict"] = ""
                out.append(row)
        finally:
            conn.close()
        c.value, c.at = out, now
        return out

    # ------------------------------------------------------------- sources

    def player_events(self) -> list[dict]:
        if not self.player_log.exists():
            return []
        events = []
        with self.player_log.open() as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                d["_at"] = parse_at(d.get("at", "1970-01-01T00:00:00Z"))
                events.append(d)
        return sorted(events, key=lambda d: d["_at"])

    def visit_events(self) -> list[dict]:
        path = self.state_dir / "visits.jsonl"
        if not path.exists():
            return []
        out = []
        with path.open() as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                d["_at"] = parse_at(d.get("at", "1970-01-01T00:00:00Z"))
                out.append(d)
        return out

    # ------------------------------------------------------------ the fold

    def humans(self) -> list[dict]:
        """Named humans the two logs know about, with their last-seen time."""
        last: dict[str, dict] = {}
        for e in self.player_events():
            who = e.get("by") or "?"
            last.setdefault(who, {"name": who, "last_seen": e["_at"], "source": "in the world"})
            if e["_at"] > last[who]["last_seen"]:
                last[who].update(last_seen=e["_at"], source="in the world")
        for v in self.visit_events():
            who = v.get("human") or "?"
            last.setdefault(who, {"name": who, "last_seen": v["_at"], "source": "on this screen"})
            if v["_at"] > last[who]["last_seen"]:
                last[who].update(last_seen=v["_at"], source="on this screen")
        return sorted(last.values(), key=lambda h: -h["last_seen"])

    def last_seen(self, human: str) -> float | None:
        for h in self.humans():
            if h["name"] == human:
                return h["last_seen"]
        return None

    def refusal_segments(self, rows: list[dict], since: float | None = None) -> list[dict]:
        """Episodes of judge refusal, merged at 10-minute gaps.

        Each segment carries its overlap with the window `since` → now:
        `verdicts_in` / `refused_in` count only the verdict rows inside the
        overlap, so a window that starts mid-episode (or after recovery)
        rates the episode by what the human actually missed, not by the
        whole ledger's history.
        """
        points = [(r["at"], r) for r in rows
                  if r["kind"] == "judge.verdict" and r.get("refused")]
        verdicts = [(r["at"], r) for r in rows if r["kind"] == "judge.verdict"]
        now = rows[-1]["at"] if rows else time.time()
        out = []
        for start, end in _merge_intervals(points, gap=600.0):
            n = sum(1 for at, _ in points if start - 1e-9 <= at <= end + 1e-9)
            overlap_start = max(start, since) if since is not None else start
            overlap_end = min(end, now)
            verdicts_in = refused_in = 0
            if overlap_end >= overlap_start:
                for at, r in verdicts:
                    if overlap_start <= at <= overlap_end:
                        verdicts_in += 1
                        refused_in += int(bool(r.get("refused")))
            out.append({"start": _iso(start), "end": _iso(end), "start_epoch": start,
                        "end_epoch": end, "refusals": n,
                        "overlap_start": _iso(overlap_start),
                        "verdicts_in": verdicts_in, "refused_in": refused_in,
                        "still_running": end >= now - 600.0})
        return out

    def presence_windows(self, rows: list[dict]) -> list[dict]:
        points = [(r["at"], r) for r in rows
                  if r["kind"] == "tile.played" and r.get("humans", 0)]
        out = []
        for start, end in _merge_intervals(points, gap=900.0):
            plays = [r for at, r in points if start - 1e-9 <= at <= end + 1e-9]
            out.append({
                "start": _iso(start), "end": _iso(end), "start_epoch": start,
                "end_epoch": end, "plays_during": len(plays),
                "max_humans": max((p.get("humans", 0) for p in plays), default=0),
            })
        return out

    def drift(self) -> dict:
        now = time.time()
        c = self._drift_cache
        if c.value is not None and now - c.at < max(self.ttl, 60.0):
            return c.value
        try:
            from core.drift import DriftConfig, DriftDetector, build_series
            series = build_series(self.db)
            detection = DriftDetector(DriftConfig()).run(series)
            alarms = [{
                "at": _iso(a.at), "at_epoch": a.at, "level": a.level,
                "agent": a.agent or "the world", "reason": a.reason,
            } for a in detection.alarms]
            value = {"available": True, "alarms": alarms,
                     "levels": {lvl: sum(1 for a in alarms if a["level"] == lvl)
                                for lvl in ("hard", "tier", "soft")}}
        except Exception as exc:  # the screen must survive a drift import failure
            value = {"available": False, "error": f"{type(exc).__name__}: {exc}",
                     "alarms": [], "levels": {}}
        c.value, c.at = value, now
        return value

    def lanes(self, rows: list[dict], since: float | None) -> list[dict]:
        horizon = rows[-1]["at"] if rows else time.time()
        span_start = since if since is not None else (rows[0]["at"] if rows else horizon)
        hours = max((horizon - span_start) / 3600.0, 1e-9)
        lanes: dict[str, dict] = {}
        for name in CHARACTERS:
            lanes[name] = {"actor": name, "role": "character", "plays": 0, "win": 0,
                           "lose": 0, "partial": 0, "tokens": 0, "hosted_cents": 0.0,
                           "gpu_minutes": 0.0, "last_at": None}
        lanes["judge@d1:d1-2B"] = {"actor": "judge@d1:d1-2B", "role": "judge",
                                   "verdicts": 0, "refused": 0, "tokens": 0,
                                   "hosted_cents": 0.0, "gpu_minutes": 0.0, "last_at": None}
        lanes["seed"] = {"actor": "seed", "role": "engineer", "authored": 0, "last_at": None}
        lanes["mediator"] = {"actor": "mediator", "role": "core", "retired": 0, "last_at": None}
        for r in rows:
            if since is not None and r["at"] < since:
                continue
            lane = lanes.get(r["actor"])
            if lane is None:
                continue
            lane["last_at"] = r["at_iso"]
            if r["kind"] == "tile.played":
                lane["plays"] += 1
                lane[r["verdict"]] = lane.get(r["verdict"], 0) + 1
            elif r["kind"] == "judge.verdict":
                lane["verdicts"] += 1
                lane["refused"] += int(bool(r.get("refused")))
                lane["tokens"] += r.get("tokens", 0)
                lane["gpu_minutes"] += r.get("gpu_minutes", 0.0)
                lane["hosted_cents"] += r.get("hosted_cents", 0.0)
            elif r["kind"] == "tile.authored":
                lane["authored"] += 1
            elif r["kind"] == "tile.retired":
                lane["retired"] += 1
        out = list(lanes.values())
        for lane in out:
            if "plays" in lane and lane["plays"]:
                lane["plays_per_hour"] = round(lane["plays"] / hours, 1)
                lane["win_rate"] = round(lane["win"] / lane["plays"], 3)
            if "verdicts" in lane and lane["verdicts"]:
                lane["refusal_rate"] = round(lane["refused"] / lane["verdicts"], 3)
        return out

    def marks(self, rows: list[dict], since: float | None) -> list[dict]:
        """The decision points the scrubber marks, since `since`."""
        out: list[dict] = []
        for r in rows:
            if since is not None and r["at"] < since:
                continue
            if r["kind"] == "tile.authored":
                p = r["payload"]
                out.append({"at": r["at_iso"], "at_epoch": r["at"], "seq": r["seq"],
                            "kind": "skill.admitted", "actor": r["actor"],
                            "title": p.get("title"), "family": p.get("family"),
                            "skill": p.get("skill")})
            elif r["kind"] == "tile.retired":
                p = r["payload"]
                out.append({"at": r["at_iso"], "at_epoch": r["at"], "seq": r["seq"],
                            "kind": "skill.retired", "actor": r["actor"],
                            "family": p.get("family"), "reason": p.get("reason")})
        for a in self.drift()["alarms"]:
            if since is None or a["at_epoch"] >= since:
                out.append({"at": a["at"], "at_epoch": a["at_epoch"], "seq": None,
                            "kind": f"drift.{a['level']}", "actor": a["agent"],
                            "reason": a["reason"]})
        for seg in self.refusal_segments(rows):
            if since is None or seg["end_epoch"] >= since:
                out.append({"at": seg["start"], "at_epoch": seg["start_epoch"], "seq": None,
                            "kind": "judge.refusing", "actor": "judge@d1:d1-2B",
                            "reason": f"the judge began refusing — {seg['refusals']} refusals "
                                      f"through {seg['end']}"})
        for w in self.presence_windows(rows):
            if since is None or w["end_epoch"] >= since:
                out.append({"at": w["start"], "at_epoch": w["start_epoch"], "seq": None,
                            "kind": "human.present", "actor": "a human",
                            "reason": f"a human was in the world ({w['plays_during']} plays "
                                      f"around them) until {w['end']}"})
        for v in self.visit_events():
            if since is None or v["_at"] >= since:
                out.append({"at": v.get("at"), "at_epoch": v["_at"], "seq": None,
                            "kind": "visit.opened", "actor": v.get("human"),
                            "reason": "the return screen was opened"})
        out.sort(key=lambda m: m["at_epoch"])
        return out

    def hourly(self, rows: list[dict], since: float | None) -> list[dict]:
        buckets: dict[int, dict] = {}
        for r in rows:
            if r["kind"] != "tile.played":
                continue
            if since is not None and r["at"] < since:
                continue
            hour = int(r["at"] // 3600) * 3600
            b = buckets.setdefault(hour, {"hour": _iso(hour), "hour_epoch": hour,
                                          "plays": 0, "win": 0, "by_agent": {}})
            b["plays"] += 1
            b["win"] += int(r["verdict"] == "win")
            if r.get("agent"):
                b["by_agent"][r["agent"]] = b["by_agent"].get(r["agent"], 0) + 1
        return [buckets[k] for k in sorted(buckets)]

    def threshold(self, rows: list[dict], since: float | None) -> dict:
        n = {"plays": 0, "verdicts": 0, "refused": 0, "authored": 0, "retired": 0,
             "plays_while_human_present": 0, "first_at": None, "last_at": None}
        for r in rows:
            if since is not None and r["at"] < since:
                continue
            if n["first_at"] is None:
                n["first_at"] = r["at_iso"]
            n["last_at"] = r["at_iso"]
            if r["kind"] == "tile.played":
                n["plays"] += 1
                n["plays_while_human_present"] += int(bool(r.get("humans")))
            elif r["kind"] == "judge.verdict":
                n["verdicts"] += 1
                n["refused"] += int(bool(r.get("refused")))
            elif r["kind"] == "tile.authored":
                n["authored"] += 1
            elif r["kind"] == "tile.retired":
                n["retired"] += 1
        alarms = self.drift()["alarms"]
        n["drift_alarms"] = sum(1 for a in alarms
                                if since is None or a["at_epoch"] >= since)
        return n

    def authored_recent(self, rows: list[dict], since: float | None, limit: int = 12) -> list[dict]:
        out = []
        for r in rows:
            if r["kind"] != "tile.authored":
                continue
            if since is not None and r["at"] < since:
                continue
            p = r["payload"]
            out.append({"at": r["at_iso"], "family": p.get("family"),
                        "title": p.get("title"), "skill": p.get("skill"),
                        "version": p.get("version")})
        return out[-limit:]

    def retired_recent(self, rows: list[dict], since: float | None, limit: int = 12) -> list[dict]:
        out = []
        for r in rows:
            if r["kind"] != "tile.retired":
                continue
            if since is not None and r["at"] < since:
                continue
            p = r["payload"]
            out.append({"at": r["at_iso"], "family": p.get("family"),
                        "reason": p.get("reason"), "plays": p.get("plays"),
                        "wins": p.get("wins")})
        return out[-limit:]

    def span(self, rows: list[dict]) -> dict:
        if not rows:
            return {"rows": 0}
        first, last = rows[0], rows[-1]
        return {"rows": len(rows), "first_at": first["at_iso"], "last_at": last["at_iso"],
                "hours": round((last["at"] - first["at"]) / 3600.0, 1)}

    # ----------------------------------------------------------- the one call

    def snapshot(self, human: str | None = None) -> dict:
        rows = self.rows()
        known = self.humans()
        who = human or (known[0]["name"] if known else "Casey")
        since = self.last_seen(who)
        return {
            "generated_at": _iso(time.time()),
            "human": who,
            "humans": [{"name": h["name"], "last_seen": _iso(h["last_seen"]),
                        "source": h["source"]} for h in known],
            "since": _iso(since) if since is not None else rows[0]["at_iso"] if rows else None,
            "since_epoch": since if since is not None else (rows[0]["at"] if rows else 0.0),
            "span": self.span(rows),
            "threshold": self.threshold(rows, since),
            "lanes": self.lanes(rows, since),
            "marks": self.marks(rows, since),
            "hourly": self.hourly(rows, since),
            "drift": self.drift(),
            "refusals": self.refusal_segments(rows, since),
            "authored_recent": self.authored_recent(rows, since),
            "retired_recent": self.retired_recent(rows, since),
        }
