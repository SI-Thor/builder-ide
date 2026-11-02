#!/usr/bin/env python3
"""The gates: three watchers over the reconstructed change stream.

(a) level gate  - fixed thresholds: output older than 45 min, memory under
    25 GB, disk under 30 GB.
(b) rate gate   - time-first: memory falling faster than X GB/min, disk falling
    faster than Y GB/h, API error bursts, the queue growing while headroom is
    free.
(c) a+b         - both, as one gate.

A gate emits "speak now" events. Each condition latches: it speaks on the
rising edge and stays quiet until the condition clears, so one stall is one
speech, not one per second.

Usage: python3 scripts/gates.py [--out data/events.json]
"""
import argparse
import json
import os
import sys
from bisect import bisect_left, bisect_right

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import DATA, WINDOW_END, WINDOW_START, local, local_hm  # noqa: E402

GB = 1e9
MIN = 60

# ------------------------------------------------------------------ defaults
PARAMS = {
    # level gate (a) - the brief's fixed thresholds
    "out_age_s": 45 * MIN,          # a seat silent for 45 min
    "mem_low_gb": 25.0,             # box free memory under 25 GB
    "disk_low_gb": 30.0,            # box disk free under 30 GB
    # rate gate (b)
    "mem_rate_gb_min": 3.0,         # memory falling faster than 3 GB/min
    "mem_rate_window_s": 600,       # measured over a 10-minute trailing window
    "disk_rate_gb_h": 10.0,         # disk falling faster than 10 GB/h
    "disk_rate_window_s": 900,      # 15-minute trailing window
    "api_burst_n": 2,               # 2 provider failures ...
    "api_burst_window_s": 300,      # ... within 5 minutes
    "client_lost_n": 2,             # 2 admission clients lost ...
    "client_lost_window_s": 300,    # ... within 5 minutes
    "wifi_aborts_5min": 20,         # 20 driver aborts in 5 minutes
    "wifi_window_s": 300,
    "queue_growth": 3,              # queue grew by 3 ...
    "queue_window_s": 600,          # ... within 10 minutes ...
    "queue_headroom_gb": 50.0,      # ... while this much memory was free
    # every condition must hold this long before the gate speaks
    "telemetry_dark_s": 120,       # the box has not reported for 2 minutes
    "hold_s": 30,
}


# --------------------------------------------------------------------- stream
class Stream:
    """The reconstructed change stream, read as change points."""

    def __init__(self, path):
        self.box = []       # (t, mem, gpu, q, lease)
        self.disk = []      # (t, gb)
        self.wifi = []      # (t, n)
        self.seats = {}     # seat -> {"write": t, "status": str, "host": str}
        self.commits = {}   # seat -> [t, ...]
        self.api = []       # (t, seat, class, n)
        self.client_lost = []   # t of an admission client that disappeared
        self._load(path)

    def _load(self, path):
        with open(path) as fh:
            for line in fh:
                r = json.loads(line)
                k = r["k"]
                if k == "box":
                    self.box.append((r["t"], r.get("mem"), r.get("gpu"), r.get("q"),
                                     r.get("lease")))
                elif k == "disk":
                    self.disk.append((r["t"], r["gb"]))
                elif k == "wifi":
                    self.wifi.append((r["t"], r["n"]))
                elif k == "seat":
                    self.seats.setdefault(r["s"], {"write": r["mw"], "status": r["st"],
                                                   "host": r["h"], "events": []})
                    self.seats[r["s"]]["events"].append((r["mw"], r["st"]))
                elif k == "commit":
                    self.commits.setdefault(r["s"], []).append(r["t"])
                elif k == "api":
                    self.api.append((r["t"], r["s"], r["c"], r.get("n", 1)))
                elif k == "client_lost":
                    self.client_lost.append(r["t"])
        self.box.sort()
        self.disk.sort()
        self.wifi.sort()
        self.api.sort()
        self.client_lost.sort()
        for s in self.seats.values():
            s["events"].sort()
        for s in self.commits.values():
            s.sort()
        self._box_t = [b[0] for b in self.box]
        self._disk_t = [d[0] for d in self.disk]
        self._wifi_t = [w[0] for w in self.wifi]

    def box_at(self, t):
        """Last box sample at or before t (zero-order hold)."""
        i = bisect_right(self._box_t, t) - 1
        return self.box[i] if i >= 0 else None

    def box_series(self, t0, t1):
        """Box samples in (t0, t1], with the sample just before t0 as the base."""
        lo = bisect_right(self._box_t, t0)
        return self.box[max(0, lo - 1):bisect_right(self._box_t, t1)]

    def disk_at(self, t):
        i = bisect_right(self._disk_t, t) - 1
        return self.disk[i] if i >= 0 else None

    def disk_series(self, t0, t1):
        lo = bisect_right(self._disk_t, t0)
        return self.disk[max(0, lo - 1):bisect_right(self._disk_t, t1)]

    def wifi_at(self, t):
        i = bisect_right(self._wifi_t, t) - 1
        return self.wifi[i] if i >= 0 else None

    def wifi_series(self, t0, t1):
        lo = bisect_right(self._wifi_t, t0)
        return self.wifi[max(0, lo - 1):bisect_right(self._wifi_t, t1)]

    def seat_out_age(self, seat, t):
        """Seconds since the seat last produced output.

        Exact from the seat's last write onwards. Before that write the seat is
        taken to have been producing output (age 0): the artefacts cannot show
        silence that ended before the last write.
        """
        s = self.seats.get(seat)
        if not s:
            return None
        last = s["write"]
        if t < last:
            return 0
        return t - last

    def seat_alive(self, seat, t):
        """Is the seat still running at t? (its .out has not reported an exit)"""
        s = self.seats.get(seat)
        if not s:
            return False
        if t < s["write"]:
            return True
        return s["status"] == "running"

    def seat_commit_age(self, seat, t):
        c = self.commits.get(seat)
        if not c:
            return None
        i = bisect_right(c, t) - 1
        if i < 0:
            return None
        return t - c[i]


# ---------------------------------------------------------------------- gates
class Latch:
    """One condition: speaks on the rising edge, re-arms when it clears.

    A condition must hold for `hold` seconds before it speaks. The box's
    MemAvailable reads bimodally (127 GB / 17 GB alternating) for minutes at a
    time after a restart, so without a hold every rate condition chatters.
    """

    def __init__(self, hold=0):
        self.hold = hold
        self.since = None
        self.firing = False

    def update(self, active, t):
        if active:
            if self.since is None:
                self.since = t
            if not self.firing and t - self.since >= self.hold:
                self.firing = True
                return True
        else:
            self.since = None
            self.firing = False
        return False


def mem_rate_gb_min(series, t, window):
    """Trailing-window slope of free memory, GB/min, over contiguous samples.

    The window must be contiguous: a rate across a gap (a daemon restart, the
    box going down) is meaningless, so the segment ends at the gap.
    """
    if len(series) < 2:
        return None
    newest_t, newest_m = series[-1][0], series[-1][1]
    oldest_t = oldest_m = None
    prev_t = newest_t
    for i in range(len(series) - 2, -1, -1):
        t_i, m_i = series[i][0], series[i][1]
        if prev_t - t_i > 30:              # a gap: older history is not comparable
            break
        if newest_t - t_i >= window:       # outside the window
            break
        oldest_t, oldest_m = t_i, m_i
        prev_t = t_i
    if oldest_t is None:
        return None
    span = newest_t - oldest_t
    if span < 60:
        return None
    return (newest_m - oldest_m) / GB / (span / 60.0)


def disk_rate_gb_h(series, t, window):
    """Trailing-window slope of free disk, GB/h."""
    if len(series) < 2:
        return None
    newest_t, newest_gb = series[-1][0], series[-1][1]
    oldest_t = oldest_gb = None
    prev_t = newest_t
    for i in range(len(series) - 2, -1, -1):
        t_i, gb = series[i][0], series[i][1]
        if prev_t - t_i > 120:
            break
        if newest_t - t_i >= window:
            break
        oldest_t, oldest_gb = t_i, gb
        prev_t = t_i
    if oldest_t is None:
        return None
    span = newest_t - oldest_t
    if span < 120:
        return None
    return (newest_gb - oldest_gb) / (span / 3600.0)


def run_gate(stream, which, params, t0, t1, seats_watch=None):
    """Walk the stream one second at a time and collect speak-now events."""
    events = []
    latches = {}

    hold = params.get("hold_s", 30)

    def latch(name):
        if name not in latches:
            latches[name] = Latch(hold)
        return latches[name]

    seats = seats_watch if seats_watch is not None else list(stream.seats)
    api_times = [a[0] for a in stream.api]
    lost_times = stream.client_lost

    t = t0
    while t <= t1:
        # ---- level gate ------------------------------------------------
        if which in ("a", "ab"):
            b = stream.box_at(t)
            if b and b[1] is not None:
                free = b[1] / GB
                if latch("mem_low").update(free < params["mem_low_gb"], t):
                    events.append({"t": t, "gate": which, "cond": "box_memory_low",
                                   "seat": None, "value": round(free, 2),
                                   "say": f"the Thor has {free:.1f} GB of memory free "
                                          f"(under the {params['mem_low_gb']:.0f} GB floor)"})
            d = stream.disk_at(t)
            if d:
                if latch("disk_low").update(d[1] < params["disk_low_gb"], t):
                    events.append({"t": t, "gate": which, "cond": "box_disk_low",
                                   "seat": None, "value": d[1],
                                   "say": f"the Thor's disk has {d[1]:.0f} GB free "
                                          f"(under the {params['disk_low_gb']:.0f} GB floor)"})
            for seat in seats:
                age = stream.seat_out_age(seat, t)
                if age is None:
                    continue
                alive = stream.seat_alive(seat, t)
                if which == "a":
                    # literal reading of the brief: every seat's output age counts
                    active = age > params["out_age_s"]
                else:
                    # only a seat that is still alive can be "hung"
                    active = alive and age > params["out_age_s"]
                if latch("seat:" + seat).update(active, t):
                    events.append({"t": t, "gate": which, "cond": "seat_output_stale",
                                   "seat": seat, "value": round(age / MIN, 1),
                                   "alive": alive,
                                   "say": f"seat {seat} has produced no output for "
                                          f"{age / MIN:.0f} min"})

        # ---- rate gate --------------------------------------------------
        if which in ("b", "ab", "bplus", "abplus"):
            bs = stream.box_series(t - params["mem_rate_window_s"], t)
            mr = mem_rate_gb_min(bs, t, params["mem_rate_window_s"])
            if mr is not None and latch("mem_rate").update(mr < -params["mem_rate_gb_min"], t):
                events.append({"t": t, "gate": which, "cond": "memory_falling_fast",
                               "seat": None, "value": round(mr, 2),
                               "say": f"the Thor's free memory is falling at {mr:.1f} GB/min "
                                      f"(over {params['mem_rate_window_s'] // MIN} min)"})
            ds = stream.disk_series(t - params["disk_rate_window_s"], t)
            dr = disk_rate_gb_h(ds, t, params["disk_rate_window_s"])
            if dr is not None and latch("disk_rate").update(dr < -params["disk_rate_gb_h"], t):
                events.append({"t": t, "gate": which, "cond": "disk_falling_fast",
                               "seat": None, "value": round(dr, 1),
                               "say": f"the Thor's free disk is falling at {dr:.0f} GB/h"})
            # api error burst: provider failures inside the window
            i = bisect_left(api_times, t - params["api_burst_window_s"])
            n = bisect_right(api_times, t) - i
            if latch("api_burst").update(n >= params["api_burst_n"], t):
                kinds = sorted({a[2] for a in stream.api[i:bisect_right(api_times, t)]})
                events.append({"t": t, "gate": which, "cond": "api_error_burst",
                               "seat": None, "value": n,
                               "say": f"{n} provider failures in the last "
                                      f"{params['api_burst_window_s'] // MIN} min ({', '.join(kinds)})"})
            # admission clients lost: the box's view of an API call that died
            i = bisect_left(lost_times, t - params["client_lost_window_s"])
            nl = bisect_right(lost_times, t) - i
            if latch("client_lost_burst").update(nl >= params["client_lost_n"], t):
                events.append({"t": t, "gate": which, "cond": "client_lost_burst",
                               "seat": None, "value": nl,
                               "say": f"{nl} API clients vanished from the admission "
                                      f"daemon in the last "
                                      f"{params['client_lost_window_s'] // MIN} min"})
            # network error rate: Wi-Fi driver aborts in the window
            ws = stream.wifi_series(t - params["wifi_window_s"], t)
            wn = sum(w[1] for w in ws if w[0] > t - params["wifi_window_s"])
            if latch("wifi_burst").update(wn >= params["wifi_aborts_5min"], t):
                events.append({"t": t, "gate": which, "cond": "network_error_burst",
                               "seat": None, "value": wn,
                               "say": f"{wn} network driver aborts in the last "
                                      f"{params['wifi_window_s'] // MIN} min"})
            # the box stopped reporting: the rate of change went to zero
            # because there is nothing left to change
            if which in ("bplus", "abplus"):
                last = stream.box_at(t)
                dark = (t - last[0]) if last else None
                if dark is not None and latch("telemetry_dark").update(
                        dark > params["telemetry_dark_s"], t):
                    events.append({"t": t, "gate": which, "cond": "telemetry_dark",
                                   "seat": None, "value": int(dark),
                                   "say": f"the Thor has not reported for {dark // 60} min"})
            # the queue grows while there is headroom to spare
            b = stream.box_at(t)
            qb = stream.box_series(t - params["queue_window_s"], t)
            if b and b[3] is not None and len(qb) >= 2:
                q_old = qb[0][3] or 0
                grew = (b[3] or 0) - q_old
                headroom = (b[1] or 0) / GB
                active = grew >= params["queue_growth"] and headroom > params["queue_headroom_gb"]
                if latch("queue_grow").update(active, t):
                    events.append({"t": t, "gate": which, "cond": "queue_growing_headroom",
                                   "seat": None, "value": grew,
                                   "say": f"the admission queue grew by {grew} to "
                                          f"{b[3]} while {headroom:.0f} GB of memory stayed free"})

        t += 1

    for e in events:
        e["time"] = local(e["t"])
    return events


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stream", default=os.path.join(DATA, "stream.jsonl"))
    ap.add_argument("--out", default=os.path.join(DATA, "events.json"))
    ap.add_argument("--params", default=None, help="JSON file of parameter overrides")
    args = ap.parse_args()

    params = dict(PARAMS)
    if args.params:
        params.update(json.load(open(args.params)))

    stream = Stream(args.stream)
    out = {"params": params, "window": {"start": local(WINDOW_START), "end": local(WINDOW_END)},
           "gates": {}}
    for which, label in (("a", "level"), ("b", "rate"), ("ab", "level+rate"),
                         ("bplus", "rate + telemetry-dark"), ("abplus", "level + rate + telemetry-dark")):
        ev = run_gate(stream, which, params, WINDOW_START, WINDOW_END)
        out["gates"][which] = {"label": label, "events": ev}
        print(f"gate {which:3s} ({label:10s}): {len(ev):4d} speak-now events")
    # variant: the level gate restricted to seats that are still alive
    ev = run_gate(stream, "a", params, WINDOW_START, WINDOW_END)
    out["gates"]["a_live"] = {
        "label": "level (seats alive only)",
        "note": "identical to gate a except the seat clause is applied only to seats "
                "that have not reported an exit; without this the gate alarms on every "
                "finished seat",
        "events": [e for e in ev if e["cond"] != "seat_output_stale" or e.get("alive")],
    }
    print(f"gate a_live (level, live seats only): {len(out['gates']['a_live']['events']):4d} "
          f"speak-now events")

    os.makedirs(DATA, exist_ok=True)
    with open(args.out, "w") as fh:
        json.dump(out, fh, indent=1)
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
