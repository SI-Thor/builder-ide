#!/usr/bin/env python3
"""seat-watch: the live watcher for the director's seats.

It watches the seats on this box and, over one ssh to the Thor, the seats
there.  It never touches a seat: it reads, and when something is wrong it
prints one line and exits 0.

    DONE <machine> <job>    a new EXIT line (watch-all.sh's rule)
    QUOTA <job>             "usage limit" / "Limit Exhausted" in an .out
    STALL <job> <reason>    a seat stopped making progress
    BOX <reason>            the Thor's or the ProArt's own state went wrong

**The two boxes.**  The Thor runs the seats' heavy work; the ProArt hosts the
seats and this watcher, in a 16 GB WSL VM.  They are watched separately -- one
channel per box -- because their memory and disk are hundreds of gigabytes
apart and one series for both would measure the difference between the boxes
rather than either box's own trend.  The brief's BOX clause is the Thor's
(MemAvailable falling at the lab's rate, disk under 20 GB); the ProArt has its
own memory conditions, which the desk's MEM signal asks for: MemAvailable
under 2 GB, or swap in use and rising.  Both print ``BOX proart-memory``.

**Where the numbers come from.**  The gate is the one the lab measured on
2026-11-01: `docs/lab/exp-seat-watcher.md` section 1.3 is its spec, and
`docs/lab/seat-watcher/scripts/gates.py` is its reference implementation.
Every threshold below is the lab's, except the two the brief changed, and
each one says which.  The trailing-window slope, the contiguity rule (a rate
is never computed across a gap), the latch (speak on the rising edge) and the
dwell (a condition must hold before it speaks) are the lab's mechanics, so
`replay.py` reproduces the lab's numbers from the lab's recorded fixtures.

**What is live and what is not.**  The live watcher runs the *box* half of
the lab's rate gate (memory rate, disk rate, the box's own floors, and the
telemetry-dark condition of the lab's (b+) variant), the *text* channels
watch-all.sh and board.sh already read (EXIT lines, quota markers), and a
per-seat progress gate that is new: the lab's method applied to a seat's own
signals.  The lab's queue, client-lost and Wi-Fi-abort conditions are
implemented in the engine (the replay needs them to reproduce the lab's
numbers) but the live watcher does not feed them, because the brief's BOX
clause names memory and disk only.  `docs/lab/exp-seat-watch-live.md` says
what that leaves uncovered.

Standard library only.  Python 3.8+.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from bisect import bisect_left, bisect_right, insort
from collections import deque


def _insert(times, records, t, rec):
    """Keep a time list and its records aligned, in time order.

    The lab's Stream loads the whole series and bisects it; a live watcher
    gets its samples one at a time, so the series is kept sorted as it grows.
    """
    pos = bisect_right(times, t)
    times.insert(pos, t)
    records.insert(pos, rec)

# ---------------------------------------------------------------------------
# every threshold, and where it comes from
# ---------------------------------------------------------------------------
# The lab's defaults (docs/lab/exp-seat-watcher.md sections 1.3 and 2.6),
# except the two the brief changed and the three the brief added.
DEFAULTS = {
    # -- the lab's rate gate (section 1.3) ---------------------------------
    "mem_rate_gb_min": 3.0,        # memory falling faster than 3 GB/min
    "mem_rate_window_s": 600,      #   over a 10-minute trailing window
    "disk_rate_gb_h": 10.0,        # disk falling faster than 10 GB/h
    "disk_rate_window_s": 900,     #   over a 15-minute trailing window
    "api_burst_n": 2,              # 2 provider failures ...
    "api_burst_window_s": 300,     #   ... within 5 minutes
    "client_lost_n": 2,            # 2 admission clients lost ...
    "client_lost_window_s": 300,   #   ... within 5 minutes
    "wifi_aborts_5min": 20,        # 20 Wi-Fi driver aborts in 5 minutes
    "wifi_window_s": 300,
    "queue_growth": 3,             # the queue grew by 3 ...
    "queue_window_s": 600,         #   ... within 10 minutes ...
    "queue_headroom_gb": 50.0,     #   ... while this much memory was free
    # every condition must hold this long before the gate speaks (section 1.3)
    "hold_s": 30,
    # the box has not reported for 2 minutes (section 1.3, and 2.5)
    "telemetry_dark_s": 120,
    # -- the lab's level gate (section 1.3) --------------------------------
    "mem_low_gb": 25.0,
    "disk_low_gb": 20.0,           # the brief says 20 GB; the lab used 30
    # -- the brief's seat-level conditions --------------------------------
    "stall_window_s": 600,         # no progress for a window
    "ssh_child_s": 1800,           # an ssh child alive > 30 min with no output
    "loop_window_s": 3600,         # a watcher loop with nothing running, 1 h
    "out_age_s": 45 * 60,          # the lab's level gate's seat clause
    # -- the ProArt's own memory (the desk's MEM signal) --------------------
    # The ProArt hosts the seats and the watcher itself: 14 seats in a 16 GB
    # WSL VM, and it was memory that killed the previous seat on 2026-11-01.
    # So the ProArt's memory is watched too, with the brief's own thresholds
    # (MemAvailable under 2 GB) and a leading indicator (swap in use rising).
    "proart_mem_low_gb": 2.0,      # MemAvailable under 2 GB
    "proart_swap_rate_gb_min": 0.5,  # swap used rising faster than 0.5 GB/min
    "proart_swap_window_s": 300,   #   over a 5-minute trailing window
    # -- the poll -----------------------------------------------------------
    "poll_s": 15,
}

# The two contiguity constants are not in the lab's PARAMS: they are hard
# constants in the lab's two slope functions, so they stay hard here.
MEM_GAP_S = 30        # mem_rate_gb_min: the walk stops at a gap over 30 s
MEM_MIN_SPAN_S = 60   # mem_rate_gb_min: a window shorter than 60 s has no rate
DISK_GAP_S = 120      # disk_rate_gb_h: the walk stops at a gap over 120 s
DISK_MIN_SPAN_S = 120  # disk_rate_gb_h: a window shorter than 120 s has no rate

GB = 1e9
MIN = 60

# The exit reasons the watcher can print, and the lab condition behind each.
BOX_REASONS = {
    "memory_falling_fast": "memory_falling",
    "disk_falling_fast": "disk_falling",
    "box_disk_low": "disk_low",
    "telemetry_dark": "telemetry_dark",
    # the ProArt's own memory -- not the lab's gate, the desk's MEM signal
    "proart_memory_low": "proart-memory",
    "proart_swap_rising": "proart-memory",
}
STALL_REASONS = ("no_progress", "ssh_child_idle", "watcher_loop")

# The conditions the engine knows.  The replay turns all of them on (it has
# to reproduce the lab's six gates); the live watcher turns on the box half.
ALL_CONDITIONS = (
    "box_memory_low",
    "box_disk_low",
    "seat_output_stale",
    "memory_falling_fast",
    "disk_falling_fast",
    "api_error_burst",
    "client_lost_burst",
    "network_error_burst",
    "queue_growing_headroom",
    "telemetry_dark",
    "proart_memory_low",
    "proart_swap_rising",
)

# The two boxes the watcher reads.  A record with no machine tag is the
# Thor's: the lab's recorded stream is the Thor's own series, and the replay
# has to reproduce the lab's numbers from it.
THOR = "thor"
PROART = "proart"


def now():
    return time.time()


def local_str(ts):
    """epoch seconds -> '2026-11-01 13:07:09', Alaska time if the tz is there.

    The boxes run America/Anchorage.  zoneinfo needs a tz database, which a
    bare WSL install may not have, so UTC is the fallback and the label says
    which one it is.
    """
    tz = _tz()
    if tz is None:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(ts)) + " UTC"
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))


_TZ = "unset"


def _tz():
    global _TZ
    if _TZ == "unset":
        _TZ = None
        try:
            from zoneinfo import ZoneInfo
            _TZ = ZoneInfo("America/Anchorage")
            time.tzset()
        except Exception:
            _TZ = None
    return _TZ


# ---------------------------------------------------------------------------
# the gate's mechanics (the lab's, section 1.3)
# ---------------------------------------------------------------------------
class Latch:
    """One condition: it speaks on the rising edge and re-arms when it clears.

    A condition must hold for ``hold`` seconds before it speaks.  The box's
    MemAvailable reads bimodally (127 GB / 17 GB alternating) for minutes at a
    time after a restart, so without the dwell every rate condition chatters:
    the lab measured 645 speeches a day instead of 71.
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


class TrailingSlope:
    """The trailing-window slope of a series, with the lab's three rules.

    1. The series for a query is the lab's: **the sample just before the
       window as a base, plus the samples inside the window**.  The samples
       older than the base are not in it, so they cannot be walked into.
    2. The walk back stops at a gap larger than ``gap_s``, so a rate is never
       computed across a daemon restart or across the box going down.
    3. The window must **span** at least ``min_span_s``, or there is no rate.

    The base matters more than it looks.  When the newest sample is older
    than the query time -- the box has gone quiet -- the base can still be
    inside the window measured from the newest sample, and then it is the
    base that the slope is measured over.

    The lab's version is a function over a slice of the whole series; this is
    the same computation over a series that arrives one sample at a time,
    which is what a live watcher has.  `replay.py` proves they agree.
    """

    def __init__(self, window_s, gap_s, min_span_s, scale=1.0, unit_s=60.0):
        self.window_s = window_s
        self.gap_s = gap_s
        self.min_span_s = min_span_s
        self.scale = scale      # bytes -> GB for the memory channel
        self.unit_s = unit_s    # 60 for GB/min, 3600 for GB/h
        self._times = []        # the samples' times, oldest first
        self._values = []

    def add(self, t, value):
        if value is None:
            return
        pos = bisect_right(self._times, t)
        self._times.insert(pos, t)
        self._values.insert(pos, value)

    def slope(self, t):
        """The slope over the trailing window at ``t``, or None."""
        times = self._times
        values = self._values
        n = len(times)
        if n < 2:
            return None
        # the lab's series: the base (the last sample at or before the window)
        # and the samples inside the window
        lo = bisect_right(times, t - self.window_s)
        hi = bisect_right(times, t)
        if hi - max(0, lo - 1) < 2:
            return None
        base = lo - 1
        newest_i = hi - 1
        if newest_i < 0:
            return None
        # the walk covers the base and the samples inside the window; with no
        # base it covers the samples inside the window from the oldest one.
        # (The lower bound must never be -1: that would wrap to the newest.)
        stop = base if base >= 0 else 0
        newest_t = times[newest_i]
        newest_v = values[newest_i]
        oldest_t = oldest_v = None
        prev_t = newest_t
        for i in range(newest_i - 1, stop - 1, -1):
            t_i = times[i]
            if prev_t - t_i > self.gap_s:
                break                       # a gap: older history is not comparable
            if newest_t - t_i >= self.window_s:
                break                       # outside the window
            oldest_t, oldest_v = t_i, values[i]
            prev_t = t_i
        if oldest_t is None:
            return None
        span = newest_t - oldest_t
        if span < self.min_span_s:
            return None
        return (newest_v - oldest_v) / self.scale / (span / self.unit_s)


class BoxChannel:
    """One box's own channel: its memory, its swap and its disk series.

    The watcher reads two boxes, and they are not the same box: the Thor runs
    the seats' heavy work (122 GB of memory, 85 GB of disk free), the ProArt
    hosts the seats and the watcher itself (16 GB of memory, 804 GB of disk
    free).  Their series are kept apart, because feeding both into one series
    makes the slope read the *difference between the boxes* instead of either
    box's own trend.

    That is not a theoretical worry: with both boxes in one series the live
    watcher's disk slope read **-21,504 GB/h** on a Thor with 85 GB free,
    because the series alternated 804 GB and 85 GB every poll.  The condition
    would have fired about two minutes after every start.  One channel per box
    is the fix, and the lab's recorded stream is one box, so the lab's numbers
    are untouched.
    """

    def __init__(self, params):
        self.mem = TrailingSlope(params["mem_rate_window_s"], MEM_GAP_S,
                                  MEM_MIN_SPAN_S, scale=GB)
        self.swap = TrailingSlope(params["proart_swap_window_s"], MEM_GAP_S,
                                  MEM_MIN_SPAN_S, scale=GB)
        self.disk = TrailingSlope(params["disk_rate_window_s"], DISK_GAP_S,
                                  DISK_MIN_SPAN_S, unit_s=3600.0)
        self.box = []              # {"t", "mem", "swap_used", "gpu", "q", "lease"}
        self.disk_recs = []        # {"t", "gb"}
        self._box_t = []           # the times of the above, for bisect
        self._disk_t = []

    def add_box(self, t, mem, swap_used=None, gpu=None, q=None, lease=None):
        _insert(self._box_t, self.box, t,
                {"t": t, "mem": mem, "swap_used": swap_used, "gpu": gpu,
                 "q": q, "lease": lease})
        self.mem.add(t, mem)
        self.swap.add(t, swap_used)

    def add_disk(self, t, gb):
        _insert(self._disk_t, self.disk_recs, t, {"t": t, "gb": gb})
        self.disk.add(t, gb)

    def box_at(self, t):
        """The last box sample at or before t (zero-order hold)."""
        i = bisect_right(self._box_t, t) - 1
        return self.box[i] if i >= 0 else None

    def disk_at(self, t):
        i = bisect_right(self._disk_t, t) - 1
        return self.disk_recs[i] if i >= 0 else None

    def box_series(self, t0, t1):
        """Box samples in (t0, t1], with the sample just before t0 as base."""
        lo = bisect_right(self._box_t, t0)
        hi = bisect_right(self._box_t, t1)
        base = self.box[lo - 1] if lo > 0 else None
        return ([base] if base is not None else []) + self.box[lo:hi]

    def disk_series(self, t0, t1):
        lo = bisect_right(self._disk_t, t0)
        hi = bisect_right(self._disk_t, t1)
        base = self.disk_recs[lo - 1] if lo > 0 else None
        return ([base] if base is not None else []) + self.disk_recs[lo:hi]


class Engine:
    """The lab's gate, as a state machine over a record stream.

    Records are the lab's own kinds, so the same engine serves the replay and
    the live watcher:

        {"k": "box",  "t": ..., "mem": bytes, "q": int, "lease": int}
        {"k": "disk", "t": ..., "gb": float}
        {"k": "wifi", "t": ..., "n": int}
        {"k": "api",  "t": ..., "s": seat, "c": class}
        {"k": "client_lost", "t": ...}
        {"k": "seat", "t": ..., "s": seat, "mw": mtime, "st": status, "h": host}
        {"k": "commit", "t": ..., "s": seat}

    A box or disk record may carry ``"m": "proart"`` or ``"m": "thor"``.  A
    record with no ``m`` is the Thor's, which is what the lab's recorded
    stream is.
    """

    def __init__(self, params=None, conditions=None, seats=None):
        self.p = dict(DEFAULTS)
        if params:
            self.p.update(params)
        self.conditions = set(ALL_CONDITIONS if conditions is None else conditions)
        self.latches = {}
        self.boxes = {}            # machine -> BoxChannel
        self.wifi = []             # (t, n)
        self.api = []              # (t, seat, class)
        self.client_lost = []      # t
        self._wifi_t = []
        self._api_t = []
        self.seats = {}            # seat -> {"write", "status", "host"}
        self.commits = {}          # seat -> [t, ...]
        self.seat_names = list(seats) if seats is not None else None

    def channel(self, machine):
        """One box's channel, created on first use."""
        ch = self.boxes.get(machine)
        if ch is None:
            ch = self.boxes[machine] = BoxChannel(self.p)
        return ch

    # -- feeding -------------------------------------------------------------

    def feed(self, rec):
        k = rec.get("k")
        machine = rec.get("m") or THOR
        if k == "box":
            ch = self.channel(machine)
            ch.add_box(rec["t"], rec.get("mem"), rec.get("swap_used"),
                       rec.get("gpu"), rec.get("q"), rec.get("lease"))
        elif k == "disk":
            self.channel(machine).add_disk(rec["t"], rec.get("gb"))
        elif k == "wifi":
            _insert(self._wifi_t, self.wifi, rec["t"], (rec["t"], rec.get("n")))
        elif k == "api":
            _insert(self._api_t, self.api, rec["t"],
                    (rec["t"], rec.get("s"), rec.get("c")))
        elif k == "client_lost":
            insort(self.client_lost, rec["t"])
        elif k == "seat":
            # NOTE: the lab's gates.py uses setdefault here, so a seat's
            # "write" is its FIRST captured write, not its last.  That is
            # reproduced deliberately: the replay has to reproduce the lab's
            # numbers.  It matters for one seat of the day (183 of 184 seats
            # were captured exactly once, so first and last coincide).
            slot = self.seats.setdefault(rec["s"], {"write": rec["mw"],
                                                    "status": rec["st"],
                                                    "host": rec.get("h")})
            slot.setdefault("events", []).append((rec["mw"], rec["st"]))
        elif k == "commit":
            self.commits.setdefault(rec["s"], []).append(rec["t"])

    # -- the reads the lab's Stream offers ----------------------------------
    # These are the Thor's: the lab's stream is the Thor's series.

    def box_at(self, t):
        """The last box sample at or before t (zero-order hold)."""
        return self.channel(THOR).box_at(t)

    def box_series(self, t0, t1):
        """Box samples in (t0, t1], with the sample just before t0 as base."""
        return self.channel(THOR).box_series(t0, t1)

    def disk_at(self, t):
        return self.channel(THOR).disk_at(t)

    def disk_series(self, t0, t1):
        return self.channel(THOR).disk_series(t0, t1)

    def wifi_series(self, t0, t1):
        lo = bisect_right(self._wifi_t, t0)
        hi = bisect_right(self._wifi_t, t1)
        base = self.wifi[lo - 1] if lo > 0 else None
        return ([base] if base is not None else []) + self.wifi[lo:hi]

    def seat_out_age(self, seat, t):
        """Seconds since the seat's captured write (the lab's semantics)."""
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

    # -- the gate ------------------------------------------------------------

    def latch(self, name):
        if name not in self.latches:
            self.latches[name] = Latch(self.p.get("hold_s", 30))
        return self.latches[name]

    def gate_conditions(self, which):
        """Which conditions a gate is made of.

        The first five are the lab's six gates (its gates.py section "The
        gates, and the variants"); "live" is the subset the live watcher
        runs, and it is the only gate that is not in the lab.
        """
        a = ("box_memory_low", "box_disk_low", "seat_output_stale")
        b = ("memory_falling_fast", "disk_falling_fast", "api_error_burst",
             "client_lost_burst", "network_error_burst", "queue_growing_headroom")
        if which == "a":
            return a
        if which == "b":
            return b
        if which == "ab":
            return a + b
        if which == "bplus":
            return b + ("telemetry_dark",)
        if which == "abplus":
            return a + b + ("telemetry_dark",)
        if which == "live":
            return ("proart_memory_low", "proart_swap_rising",
                    "memory_falling_fast", "disk_falling_fast", "box_disk_low",
                    "telemetry_dark")
        return ()

    def step(self, t, which="b", seat_filter=None):
        """Evaluate the conditions at time t; return the speeches.

        ``which`` picks the gate the way the lab's gates.py does: "a" is the
        level gate, "b" the rate gate, "ab" both, "bplus" the rate gate plus
        the telemetry-dark condition.
        """
        p = self.p
        events = []
        seats = seat_filter if seat_filter is not None else (
            list(self.seats) if self.seat_names is None else self.seat_names)
        conds = set(self.gate_conditions(which)) & self.conditions
        thor = self.channel(THOR)

        # ---- the ProArt's own memory (the desk's MEM signal) ----------------
        # The ProArt is the seat host: 14 seats in a 16 GB WSL VM, and it is
        # memory that killed the previous seat.  Two conditions, one reason:
        # the floor the desk names (MemAvailable under 2 GB) and a leading
        # indicator (swap in use, rising).  The swap condition is the one that
        # can speak before the box is already in trouble.
        if conds & {"proart_memory_low", "proart_swap_rising"}:
            pa = self.channel(PROART)
            last = pa.box_at(t)
            if last:
                mem = last.get("mem")
                if mem is not None and "proart_memory_low" in conds:
                    free = mem / GB
                    active = free < p["proart_mem_low_gb"]
                    if self.latch("proart_mem_low").update(active, t):
                        events.append({"t": t, "gate": which, "cond": "proart_memory_low",
                                       "seat": None, "value": round(free, 2),
                                       "say": "the ProArt has %.2f GB of memory free "
                                              "(under the %.0f GB floor)"
                                              % (free, p["proart_mem_low_gb"])})
                used = last.get("swap_used")
                if used is not None and "proart_swap_rising" in conds:
                    sr = pa.swap.slope(t)
                    active = (sr is not None and used > 0
                              and sr > p["proart_swap_rate_gb_min"])
                    if self.latch("proart_swap").update(active, t):
                        events.append({"t": t, "gate": which, "cond": "proart_swap_rising",
                                       "seat": None,
                                       "value": round(sr, 3) if sr is not None else None,
                                       "swap_gb": round(used / GB, 2),
                                       "say": "the ProArt's swap is in use and rising "
                                              "at %.2f GB/min (%.1f GB used)"
                                              % (sr if sr is not None else 0.0,
                                                 used / GB)})

        # ---- level gate ----------------------------------------------------
        if conds & {"box_memory_low", "box_disk_low", "seat_output_stale"}:
            b = self.box_at(t)
            if b and b["mem"] is not None and "box_memory_low" in conds:
                free = b["mem"] / GB
                if self.latch("mem_low").update(free < p["mem_low_gb"], t):
                    events.append({"t": t, "gate": which, "cond": "box_memory_low",
                                   "seat": None, "value": round(free, 2),
                                   "say": "the Thor has %.1f GB of memory free "
                                          "(under the %.0f GB floor)"
                                          % (free, p["mem_low_gb"])})
            d = self.disk_at(t)
            if d and "box_disk_low" in conds:
                if self.latch("disk_low").update(d["gb"] < p["disk_low_gb"], t):
                    events.append({"t": t, "gate": which, "cond": "box_disk_low",
                                   "seat": None, "value": d["gb"],
                                   "say": "the Thor's disk has %.0f GB free "
                                          "(under the %.0f GB floor)"
                                          % (d["gb"], p["disk_low_gb"])})
            if "seat_output_stale" in conds:
                for seat in seats:
                    age = self.seat_out_age(seat, t)
                    if age is None:
                        continue
                    alive = self.seat_alive(seat, t)
                    if which == "a":
                        active = age > p["out_age_s"]
                    else:
                        active = alive and age > p["out_age_s"]
                    if self.latch("seat:" + seat).update(active, t):
                        events.append({"t": t, "gate": which, "cond": "seat_output_stale",
                                       "seat": seat, "value": round(age / MIN, 1),
                                       "alive": alive,
                                       "say": "seat %s has produced no output for "
                                              "%.0f min" % (seat, age / MIN)})

        # ---- rate gate -----------------------------------------------------
        if conds & {"memory_falling_fast", "disk_falling_fast", "api_error_burst",
                    "client_lost_burst", "network_error_burst",
                    "queue_growing_headroom", "telemetry_dark"}:
            mr = thor.mem.slope(t)
            if mr is not None and "memory_falling_fast" in conds \
                    and self.latch("mem_rate").update(
                        mr < -p["mem_rate_gb_min"], t):
                events.append({"t": t, "gate": which, "cond": "memory_falling_fast",
                               "seat": None, "value": round(mr, 2),
                               "say": "the Thor's free memory is falling at %.1f GB/min "
                                      "(over %d min)" % (mr, p["mem_rate_window_s"] // MIN)})
            dr = thor.disk.slope(t)
            if dr is not None and "disk_falling_fast" in conds \
                    and self.latch("disk_rate").update(
                        dr < -p["disk_rate_gb_h"], t):
                events.append({"t": t, "gate": which, "cond": "disk_falling_fast",
                               "seat": None, "value": round(dr, 1),
                               "say": "the Thor's free disk is falling at %.0f GB/h" % dr})
            # api error burst: provider failures inside the window
            n = self._count(self._api_t, t, p["api_burst_window_s"])
            if "api_error_burst" in conds and self.latch("api_burst").update(
                    n >= p["api_burst_n"], t):
                kinds = sorted({a[2] for a in self.api
                                if t - p["api_burst_window_s"] <= a[0] <= t})
                events.append({"t": t, "gate": which, "cond": "api_error_burst",
                               "seat": None, "value": n,
                               "say": "%d provider failures in the last %d min (%s)"
                                      % (n, p["api_burst_window_s"] // MIN,
                                         ", ".join(kinds))})
            # admission clients lost: the box's view of an API call that died
            nl = self._count(self.client_lost, t, p["client_lost_window_s"])
            if "client_lost_burst" in conds and self.latch("client_lost_burst").update(
                    nl >= p["client_lost_n"], t):
                events.append({"t": t, "gate": which, "cond": "client_lost_burst",
                               "seat": None, "value": nl,
                               "say": "%d API clients vanished from the admission "
                                      "daemon in the last %d min"
                                      % (nl, p["client_lost_window_s"] // MIN)})
            # network error rate: Wi-Fi driver aborts in the window
            ws = self.wifi_series(t - p["wifi_window_s"], t)
            wn = sum(w[1] for w in ws if w[0] > t - p["wifi_window_s"])
            if "network_error_burst" in conds and self.latch("wifi_burst").update(
                    wn >= p["wifi_aborts_5min"], t):
                events.append({"t": t, "gate": which, "cond": "network_error_burst",
                               "seat": None, "value": wn,
                               "say": "%d network driver aborts in the last %d min"
                                      % (wn, p["wifi_window_s"] // MIN)})
            # the box stopped reporting: the rate of change went to zero
            # because there is nothing left to change
            if "telemetry_dark" in conds:
                last = self.box_at(t)
                dark = (t - last["t"]) if last else None
                if dark is not None and self.latch("telemetry_dark").update(
                        dark > p["telemetry_dark_s"], t):
                    events.append({"t": t, "gate": which, "cond": "telemetry_dark",
                                   "seat": None, "value": int(dark),
                                   "say": "the Thor has not reported for %d min"
                                          % (dark // 60)})
            # the queue grows while there is headroom to spare
            b = self.box_at(t)
            qb = self.box_series(t - p["queue_window_s"], t)
            if b and b["q"] is not None and len(qb) >= 2 \
                    and "queue_growing_headroom" in conds:
                q_old = qb[0]["q"] or 0
                grew = (b["q"] or 0) - q_old
                headroom = (b["mem"] or 0) / GB
                active = grew >= p["queue_growth"] and headroom > p["queue_headroom_gb"]
                if self.latch("queue_grow").update(active, t):
                    events.append({"t": t, "gate": which, "cond": "queue_growing_headroom",
                                   "seat": None, "value": grew,
                                   "say": "the admission queue grew by %d to %s while "
                                          "%.0f GB of memory stayed free"
                                          % (grew, b["q"], headroom)})
        return events

    @staticmethod
    def _count(times, t, window):
        """How many of ``times`` fall in [t-window, t].

        The lab counts with bisect_left on the lower bound, so an event
        exactly at the window's edge counts.  Same here.
        """
        i = bisect_left(times, t - window)
        return bisect_right(times, t) - i


# ---------------------------------------------------------------------------
# the collector: it runs on both boxes and prints JSON lines
# ---------------------------------------------------------------------------
# It is a string so that one copy of this file is the whole watcher: the
# ProArt runs it locally, and the Thor runs the same bytes over one ssh.
COLLECTOR_SRC = r'''
import json, os, re, subprocess, sys, time

MACHINE = sys.argv[1] if len(sys.argv) > 1 else "proart"
OPS = os.environ.get("LM_OPS", os.path.expanduser("~/lm-ops"))
WT = os.path.expanduser("~/lm-wt")

EXIT_RE = re.compile(rb"^EXIT [0-9]+$")
QUOTA_RE = re.compile(rb"usage limit|limit exhausted", re.I)
COUNTER_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)=(\d+)\b")
TAIL_KEEP = 65536


def sh(cmd, timeout=25):
    try:
        p = subprocess.run(cmd, shell=True, capture_output=True, timeout=timeout)
        return p.stdout.decode("utf-8", "replace")
    except Exception:
        return ""


def scan_out(path):
    """The .out's facts: EXIT lines, quota markers, its last counter line."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    exits = 0
    quota = False
    tail = b""
    try:
        with open(path, "rb") as fh:
            carry = b""
            while True:
                chunk = fh.read(1 << 20)
                if not chunk:
                    break
                buf = carry + chunk
                lines = buf.split(b"\n")
                carry = lines.pop()
                for ln in lines:
                    if EXIT_RE.match(ln):
                        exits += 1
                    if QUOTA_RE.search(ln):
                        quota = True
                tail = (tail + chunk)[-TAIL_KEEP:]
            if carry:
                if EXIT_RE.match(carry):
                    exits += 1
                if QUOTA_RE.search(carry):
                    quota = True
    except OSError:
        return None
    counter = None
    for ln in reversed(tail.split(b"\n")):
        s = ln.decode("utf-8", "replace")
        vals = COUNTER_RE.findall(s)
        if len(vals) >= 2:
            counter = {"text": s.strip()[:160],
                       "all_zero": all(int(v) == 0 for _, v in vals),
                       "fields": len(vals)}
            break
    return {"size": st.st_size, "mtime": st.st_mtime, "exits": exits,
            "quota": quota, "counter": counter}


def proc_map():
    """pid -> ppid, from one ps call."""
    out = sh("ps -eo pid=,ppid= 2>/dev/null")
    m = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        try:
            m[int(parts[0])] = int(parts[1])
        except ValueError:
            continue
    return m


def stat_of(pid):
    """(ppid, cpu_seconds, start_epoch, comm) from /proc/<pid>/stat."""
    try:
        with open("/proc/%d/stat" % pid, "r", errors="replace") as fh:
            raw = fh.read()
    except OSError:
        return None
    rp = raw.rfind(")")
    if rp < 0:
        return None
    comm = raw[raw.find("(") + 1:rp]
    f = raw[rp + 2:].split()
    try:
        hz = os.sysconf("SC_CLK_TCK")
        boot = float(sh("awk '/^btime/{print $2}' /proc/stat").strip() or 0)
        return (int(f[1]), (int(f[11]) + int(f[12])) / float(hz),
                boot + int(f[19]) / float(hz), comm)
    except (IndexError, ValueError, OSError):
        return None


def tree_of(root, pmap):
    kids = {}
    for pid, ppid in pmap.items():
        kids.setdefault(ppid, []).append(pid)
    seen = set()
    stack = [root]
    while stack:
        p = stack.pop()
        if p <= 0 or p in seen:
            continue
        seen.add(p)
        stack.extend(kids.get(p, []))
    return seen


def net_bytes():
    """pid -> bytes sent+received on its sockets, from ss(8)."""
    out = sh("ss -tnip 2>/dev/null")
    per = {}
    pids = []
    for line in out.splitlines():
        if line[:1] in (" ", "\t"):
            if not pids:
                continue
            ms = re.search(r"bytes_sent:(\d+)", line)
            mr = re.search(r"bytes_received:(\d+)", line)
            if ms or mr:
                b = int(ms.group(1) if ms else 0) + int(mr.group(1) if mr else 0)
                for pid in pids:
                    per[pid] = per.get(pid, 0) + b
        else:
            pids = [int(x) for x in re.findall(r"pid=(\d+)", line)]
    return per


def tmux_panes():
    out = sh("tmux list-panes -a -F '#{session_name}\t#{window_name}\t#{pane_pid}' 2>/dev/null")
    panes = {}
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) == 3:
            panes[parts[1]] = int(parts[2] or 0)
    return panes


def git_head(path):
    """(sha, committer_epoch) for a worktree, without spawning git if we can."""
    gd = None
    try:
        with open(os.path.join(path, ".git"), "r", errors="replace") as fh:
            txt = fh.read().strip()
        if txt.startswith("gitdir:"):
            gd = txt.split(":", 1)[1].strip()
        elif os.path.isdir(os.path.join(path, ".git")):
            gd = os.path.join(path, ".git")
    except OSError:
        return None, None
    if not gd:
        return None, None
    sha = None
    try:
        with open(os.path.join(gd, "HEAD"), "r", errors="replace") as fh:
            head = fh.read().strip()
        if head.startswith("ref:"):
            ref = head.split(None, 1)[1].strip()
            refp = os.path.join(gd, ref)
            with open(refp, "r", errors="replace") as fh:
                sha = fh.read().strip()
        else:
            sha = head
    except OSError:
        pass
    ct = None
    try:
        with open(os.path.join(gd, "logs", "HEAD"), "r", errors="replace") as fh:
            last = None
            for line in fh:
                if line.strip():
                    last = line
        if last:
            parts = last.split()
            if len(parts) >= 5:
                ct = int(parts[4])
    except (OSError, ValueError):
        pass
    if ct is None:
        try:
            ct = int(os.stat(os.path.join(gd, "HEAD")).st_mtime)
        except OSError:
            ct = None
    return sha, ct


def notes_of(path):
    try:
        st = os.stat(os.path.join(path, "NOTES.md"))
        return {"size": st.st_size, "mtime": st.st_mtime}
    except OSError:
        return None


def main():
    t = time.time()
    out = []
    # ---- the box ---------------------------------------------------------
    mem = None
    swap_total = None
    swap_free = None
    try:
        with open("/proc/meminfo") as fh:
            for line in fh:
                if line.startswith("MemAvailable:"):
                    mem = int(line.split()[1]) * 1024
                elif line.startswith("SwapTotal:"):
                    swap_total = int(line.split()[1]) * 1024
                elif line.startswith("SwapFree:"):
                    swap_free = int(line.split()[1]) * 1024
                if mem is not None and swap_total is not None and swap_free is not None:
                    break
    except OSError:
        pass
    swap_used = None
    if swap_total is not None and swap_free is not None:
        swap_used = max(0, swap_total - swap_free)
    disk = None
    df = sh("df -Pk / 2>/dev/null")
    if df:
        lines = df.strip().splitlines()
        if len(lines) >= 2:
            f = lines[-1].split()
            if len(f) >= 4:
                try:
                    disk = int(f[3]) / (1024.0 * 1024.0)
                except ValueError:
                    disk = None
    out.append({"kind": "box", "machine": MACHINE, "t": t, "mem": mem,
                "swap_used": swap_used, "disk_gb": disk})

    # ---- the jobs --------------------------------------------------------
    if MACHINE == "thor":
        outdir = WT
    else:
        outdir = os.path.join(OPS, "wt")
    try:
        names = sorted(f for f in os.listdir(outdir) if f.endswith(".out"))
    except OSError:
        names = []
    panes = tmux_panes()
    pmap = proc_map()
    net = net_bytes()
    for fname in names:
        job = fname[:-4]
        path = os.path.join(outdir, fname)
        info = scan_out(path)
        if info is None:
            continue
        workdir = os.path.join(WT, job)
        # the seat's tmux pane: window names are "<agent>-<job>"
        pane = 0
        for w, pid in panes.items():
            if w.endswith("-" + job):
                pane = pid
                break
        cpu = 0.0
        ssh_children = []
        pids = tree_of(pane, pmap) if pane else set()
        for pid in pids:
            st = stat_of(pid)
            if not st:
                continue
            cpu += st[1]
            if st[3] == "ssh":
                ssh_children.append({"pid": pid, "age_s": max(0.0, t - st[2]),
                                     "start": st[2]})
        netb = sum(net.get(pid, 0) for pid in pids)
        sha, ct = git_head(workdir)
        out.append({"kind": "job", "machine": MACHINE, "t": t, "name": job,
                    "out": info, "notes": notes_of(workdir),
                    "git": {"sha": sha, "ct": ct}, "pane": pane,
                    "cpu": round(cpu, 2), "net": netb, "ssh": ssh_children,
                    "live": bool(pane)})
    for line in out:
        print(json.dumps(line))
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''


def collect(machine, cfg):
    """Run the collector on one box; return its records.

    The Thor is read over one ssh; the ProArt is read locally.  The same
    collector source runs in both places.
    """
    env = dict(os.environ)
    env["LM_OPS"] = cfg["ops"]
    if machine == "thor":
        cmd = ["ssh", "-o", "ConnectTimeout=8", "-o", "BatchMode=yes",
               "-o", "ServerAliveInterval=5", "-o", "ServerAliveCountMax=2",
               cfg["ssh"], "python3 - " + machine]
        proc = subprocess.run(cmd, input=COLLECTOR_SRC, capture_output=True,
                              text=True, timeout=cfg["ssh_timeout"], env=env)
    else:
        cmd = [sys.executable, "-", machine]
        proc = subprocess.run(cmd, input=COLLECTOR_SRC, capture_output=True,
                              text=True, timeout=cfg["ssh_timeout"], env=env)
    if proc.returncode != 0:
        return [], "collector on %s failed (rc=%d): %s" % (
            machine, proc.returncode, (proc.stderr or "").strip()[:200])
    recs = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            recs.append(json.loads(line))
        except ValueError:
            continue
    if not recs:
        return [], "collector on %s returned nothing" % machine
    return recs, None


# ---------------------------------------------------------------------------
# the seat-level gate: has this job made any progress?
# ---------------------------------------------------------------------------
class SeatState:
    """What the watcher remembers about one job between polls."""

    def __init__(self, job):
        self.job = job
        self.machine = None
        self.last_seen = None
        self.baseline = None          # the progress signals at the first poll
        self.last_progress = None     # when a progress signal last moved
        self.evidence_gap = False     # a poll could not read this job
        self.counter_seen = None      # (text, first seen) for the loop shape
        self.counter_all_zero_since = None
        self.fired = None             # the reason already reported

    def signals(self, rec):
        """The progress signals of one poll: a dict of comparable values."""
        out = rec.get("out") or {}
        notes = rec.get("notes") or {}
        git = rec.get("git") or {}
        return {
            "git": git.get("sha"),
            "notes": notes.get("size"),
            "out": out.get("size"),
            "cpu": rec.get("cpu"),
            "net": rec.get("net"),
        }

    def update(self, rec, t):
        """Fold one poll into the state; return True if progress happened."""
        moved = False
        if self.baseline is None:
            # the first poll only establishes the baseline
            self.baseline = self.signals(rec)
            self.last_progress = t
            self.evidence_gap = False
            moved = True
        else:
            sig = self.signals(rec)
            for key, val in sig.items():
                old = self.baseline.get(key)
                if val is None or old is None:
                    continue
                if key == "git":
                    if val != old:
                        self.baseline[key] = val
                        moved = True
                elif val > old:
                    self.baseline[key] = val
                    moved = True
            if moved:
                self.last_progress = t
                self.evidence_gap = False
                self.fired = None
            else:
                self.evidence_gap = False
        # the watcher-loop shape: the last counter line shows nothing running
        out = rec.get("out") or {}
        counter = out.get("counter")
        if counter and counter.get("all_zero"):
            if self.counter_seen is None or self.counter_seen[0] != counter.get("text"):
                self.counter_seen = (counter.get("text"), t)
                self.counter_all_zero_since = t
        else:
            self.counter_seen = None
            self.counter_all_zero_since = None
        return moved

    def mark_gap(self):
        """A poll could not read this job: the evidence is missing, not flat.

        The lab's rule: a rate is never computed across a gap, and a gap in
        the evidence is not evidence of persistence.  So the stall window
        restarts instead of carrying the gap.
        """
        self.evidence_gap = True
        self.last_progress = None
        self.baseline = None

    def stall_reason(self, t, cfg):
        """The stall shape this job is in, or None."""
        p = cfg["params"]
        key = (self.machine, self.job)
        out_age = cfg["out_ages"].get(key)
        # The two failure shapes the brief names.  They are checked before the
        # generic gate, and a shape that is *developing* holds the generic
        # gate back: otherwise the generic gate (10 min) would always win over
        # the shapes (30 min and 1 h), and the reason would never say which
        # shape it was.
        ssh = cfg["ssh_children"].get(key) or []
        for s in ssh:
            if s["age_s"] > p["ssh_child_s"] and out_age is not None \
                    and out_age > p["ssh_child_s"]:
                return "ssh_child_idle", "an ssh child has been alive %.0f min " \
                                         "with no output for %.0f min" \
                                         % (s["age_s"] / 60.0, out_age / 60.0)
        if self.counter_all_zero_since is not None \
                and t - self.counter_all_zero_since >= p["loop_window_s"]:
            return "watcher_loop", "the log has shown nothing running for %d min " \
                                   "(%s)" % ((t - self.counter_all_zero_since) // 60,
                                             self.counter_seen[0])
        # a shape that is developing holds the generic gate back
        if out_age is not None and out_age > p["stall_window_s"]:
            for s in ssh:
                if s["age_s"] > p["stall_window_s"]:
                    return None, None
            if self.counter_all_zero_since is not None:
                return None, None
        if self.last_progress is None:
            return None, None
        if t - self.last_progress >= p["stall_window_s"]:
            return "no_progress", "no progress for %d min" % ((t - self.last_progress) // 60)
        return None, None


# ---------------------------------------------------------------------------
# the watcher
# ---------------------------------------------------------------------------
class Watcher:
    def __init__(self, cfg):
        self.cfg = cfg
        self.params = cfg["params"]
        self.seats = {}            # (machine, job) -> SeatState
        self.exit_baseline = {}    # (machine, job) -> EXIT count at the start
        self.quota_baseline = {}   # (machine, job) -> its mtime and marker state
        self.started = None
        self.engine = Engine(self.params, conditions=(
            "memory_falling_fast", "disk_falling_fast", "box_disk_low",
            "telemetry_dark", "proart_memory_low", "proart_swap_rising"))
        self.logfile = None

    # -- the log ------------------------------------------------------------

    def log(self, msg):
        line = "%s  %s" % (local_str(now()), msg)
        try:
            if self.logfile is None:
                self.logfile = open(self.cfg["log"], "a")
            self.logfile.write(line + "\n")
            self.logfile.flush()
        except OSError:
            pass
        sys.stderr.write(line + "\n")
        sys.stderr.flush()

    # -- one poll -----------------------------------------------------------

    def poll(self):
        """Read both boxes; return (records, per-job facts, errors).

        Each box's box and disk records carry the machine they came from, so
        the engine keeps one series per box.  The two boxes' memory and disk
        are hundreds of gigabytes apart, and one series for both of them would
        measure the difference between the boxes rather than either box's own
        trend.
        """
        recs = []
        jobs = {}
        errors = []
        for machine in (PROART, THOR):
            got, err = collect(machine, self.cfg)
            if err:
                errors.append(err)
                continue
            for r in got:
                if r.get("kind") == "box":
                    recs.append({"k": "box", "t": r["t"], "mem": r.get("mem"),
                                 "swap_used": r.get("swap_used"), "m": machine,
                                 "q": None, "lease": None})
                    if r.get("disk_gb") is not None:
                        recs.append({"k": "disk", "t": r["t"],
                                     "gb": r["disk_gb"], "m": machine})
                elif r.get("kind") == "job":
                    key = (machine, r["name"])
                    jobs[key] = r
        return recs, jobs, errors

    # -- the baseline -------------------------------------------------------

    def baseline(self, jobs):
        """watch-all.sh's rule: the EXIT markers present at the start do not count."""
        self.started = now()
        for (machine, job), r in jobs.items():
            out = r.get("out") or {}
            self.exit_baseline[(machine, job)] = out.get("exits", 0)
            self.quota_baseline[(machine, job)] = {
                "mtime": out.get("mtime") or 0,
                "quota": bool(out.get("quota")),
            }

    # -- the checks ---------------------------------------------------------

    def check_done(self, jobs):
        """A new EXIT line: the same rule as watch-all.sh."""
        for (machine, job), r in sorted(jobs.items()):
            out = r.get("out") or {}
            base = self.exit_baseline.get((machine, job), 0)
            if out.get("exits", 0) > base:
                return "DONE %s %s" % (machine, job)
        return None

    def check_quota(self, jobs):
        """A quota marker in an .out, in a file this watch has seen written.

        Old .out files keep their quota markers for ever: six on the Thor and
        one on the ProArt still carry them from 2026-11-01.  So the marker has
        to be *new* -- the file was written during this watch, or it did not
        carry the marker when the watch started -- otherwise the watcher
        cries quota on every start.
        """
        for (machine, job), r in sorted(jobs.items()):
            out = r.get("out") or {}
            if not out.get("quota"):
                continue
            base = self.quota_baseline.get((machine, job),
                                           {"mtime": 0, "quota": False})
            new_marker = not base["quota"]
            written_since = (out.get("mtime") or 0) > base["mtime"]
            if new_marker or written_since:
                return "QUOTA %s" % job
        return None

    def check_stall(self, jobs, t):
        """A seat stopped making progress."""
        cfg = self.cfg
        out_ages = {}
        ssh_children = {}
        for key, r in jobs.items():
            out = r.get("out") or {}
            out_ages[key] = t - (out.get("mtime") or t)
            ssh_children[key] = r.get("ssh") or []
        cfg["out_ages"] = out_ages
        cfg["ssh_children"] = ssh_children

        # a job we could not read this poll: the evidence is missing, not flat
        for key, st in self.seats.items():
            if key not in jobs:
                st.mark_gap()

        for (machine, job), r in sorted(jobs.items()):
            if not r.get("live"):
                continue          # a seat with no window is not a stalled seat
            key = (machine, job)
            st = self.seats.get(key)
            if st is None:
                st = SeatState(job)
                st.machine = machine
                self.seats[key] = st
            st.update(r, t)
            if st.fired:
                continue
            reason, detail = st.stall_reason(t, cfg)
            if reason:
                st.fired = reason
                self.log("STALL %s %s (%s) machine=%s" % (job, reason, detail, machine))
                return "STALL %s %s" % (job, reason)
        return None

    def check_box(self, t):
        """The Thor's own state."""
        events = self.engine.step(t, which="live")
        for e in events:
            reason = BOX_REASONS.get(e["cond"])
            if reason:
                self.log("BOX %s (%s) value=%s" % (reason, e["say"], e.get("value")))
                return "BOX %s" % reason
        return None

    # -- the loop -----------------------------------------------------------

    def run(self):
        cfg = self.cfg
        # the first poll establishes the baselines
        recs, jobs, errors = self.poll()
        for e in errors:
            self.log("poll error: %s" % e)
        self.baseline(jobs)
        for r in recs:
            self.engine.feed(r)
        self.log("watching %d jobs (proart %d, thor %d); poll %ds; window %ds"
                 % (len(jobs),
                    sum(1 for k in jobs if k[0] == "proart"),
                    sum(1 for k in jobs if k[0] == "thor"),
                    cfg["params"]["poll_s"], cfg["params"]["stall_window_s"]))
        deadline = cfg["started_at"] + cfg["timeout"] if cfg["timeout"] else None
        while True:
            t = now()
            recs, jobs, errors = self.poll()
            for e in errors:
                self.log("poll error: %s" % e)
            for r in recs:
                self.engine.feed(r)
            for line in (self.check_done(jobs), self.check_quota(jobs),
                         self.check_stall(jobs, t), self.check_box(t)):
                if line:
                    self.log("speaking: %s" % line)
                    print(line)
                    sys.stdout.flush()
                    return 0
            if deadline and now() >= deadline:
                print("TIMEOUT")
                sys.stdout.flush()
                return 0
            sleep_for = cfg["params"]["poll_s"] - (now() - t)
            if sleep_for > 0:
                time.sleep(sleep_for)


def build_parser():
    ap = argparse.ArgumentParser(
        description="the live watcher for the director's seats")
    ap.add_argument("--poll", type=float, default=DEFAULTS["poll_s"],
                    help="seconds between polls (default 15; the lab's "
                         "memory-rate rule needs samples under 30 s apart)")
    ap.add_argument("--timeout", type=float, default=36000.0,
                    help="seconds before giving up (default 36000; 0 = never)")
    ap.add_argument("--ssh", default="thor-lan", help="the Thor's ssh host")
    ap.add_argument("--ssh-timeout", type=float, default=30.0,
                    help="seconds to wait for a collector to answer")
    ap.add_argument("--ops", default=os.environ.get("LM_OPS",
                                                    os.path.expanduser("~/lm-ops")),
                    help="the ops directory (default $LM_OPS or ~/lm-ops)")
    ap.add_argument("--log", default=None,
                    help="the log file (default $LM_OPS/seat-watch.log)")
    ap.add_argument("--window", type=float, default=DEFAULTS["stall_window_s"],
                    help="seconds without progress before a seat is stalled")
    ap.add_argument("--ssh-child", type=float, default=DEFAULTS["ssh_child_s"],
                    help="seconds an ssh child may live with no output")
    ap.add_argument("--loop-window", type=float, default=DEFAULTS["loop_window_s"],
                    help="seconds of a log showing nothing running")
    ap.add_argument("--proart-mem-low", type=float,
                    default=DEFAULTS["proart_mem_low_gb"],
                    help="GB of memory below which the ProArt is reported "
                         "(default 2.0)")
    ap.add_argument("--proart-swap-rate", type=float,
                    default=DEFAULTS["proart_swap_rate_gb_min"],
                    help="GB/min of swap in use, rising, that reports the "
                         "ProArt (default 0.5)")
    ap.add_argument("--once", action="store_true",
                    help="one poll, then print what it saw and exit")
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    params = dict(DEFAULTS)
    params["poll_s"] = args.poll
    params["stall_window_s"] = args.window
    params["ssh_child_s"] = args.ssh_child
    params["loop_window_s"] = args.loop_window
    params["proart_mem_low_gb"] = args.proart_mem_low
    params["proart_swap_rate_gb_min"] = args.proart_swap_rate
    cfg = {
        "params": params,
        "ssh": args.ssh,
        "ssh_timeout": args.ssh_timeout,
        "ops": args.ops,
        "log": args.log or os.path.join(args.ops, "seat-watch.log"),
        "timeout": args.timeout,
        "started_at": now(),
    }
    w = Watcher(cfg)

    if args.once:
        recs, jobs, errors = w.poll()
        for e in errors:
            print("error:", e)
        w.baseline(jobs)
        print("box records: %d, jobs: %d" % (len(recs), len(jobs)))
        for r in recs:
            if r.get("k") == "box":
                mem = r.get("mem")
                swap = r.get("swap_used")
                print("  box %-7s mem_available=%s swap_used=%s"
                      % (r.get("m"),
                         ("%.2f GB" % (mem / 1e9)) if mem is not None else "?",
                         ("%.2f GB" % (swap / 1e9)) if swap is not None else "?"))
        for (machine, job), r in sorted(jobs.items()):
            out = r.get("out") or {}
            print("  %-7s %-28s live=%-5s exits=%-3s out_age=%4.0fs size=%-8s "
                  "cpu=%-7s net=%-9s quota=%s"
                  % (machine, job, r.get("live"), out.get("exits"),
                     (now() - out.get("mtime", now())), out.get("size"),
                     r.get("cpu"), r.get("net"), out.get("quota")))
        return 0

    try:
        return w.run()
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
