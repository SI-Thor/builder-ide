"""Shared helpers: the boxes' clock, and the episode window.

Both boxes run America/Anchorage. Alaska fell back from AKDT (UTC-8) to AKST
(UTC-9) at 2026-11-01 02:00 local, so the local hour 01:00-02:00 happens
twice that day. Every conversion goes through zoneinfo so the fold is handled
by the tz database rather than by a fixed offset.
"""
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Anchorage")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "raw")
DATA = os.path.join(ROOT, "data")

# The day under test, in local time.
DAY = "2026-11-01"
WINDOW_START = datetime(2026, 11, 1, 0, 0, tzinfo=TZ).timestamp()
WINDOW_END = datetime(2026, 11, 1, 16, 5, tzinfo=TZ).timestamp()


def local(ts):
    """epoch seconds -> local '2026-11-01 13:07:09' string."""
    return datetime.fromtimestamp(ts, TZ).strftime("%Y-%m-%d %H:%M:%S")


def local_hm(ts):
    return datetime.fromtimestamp(ts, TZ).strftime("%H:%M:%S")


def epoch_local(s, fmt="%Y-%m-%d %H:%M:%S"):
    """local string -> epoch seconds (zoneinfo handles the fold)."""
    return datetime.strptime(s, fmt).replace(tzinfo=TZ).timestamp()


def epoch_utc(s):
    """'2026-11-01T13:07:09Z' -> epoch seconds."""
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()


def parse_journal_ts(s):
    """journalctl -o short-iso '2026-11-01T10:46:47-09:00' -> epoch seconds."""
    return datetime.fromisoformat(s).timestamp()


def parse_daemon_ts(s):
    """'2026-11-01T19:28:50Z' -> epoch seconds (the daemon logs UTC)."""
    return epoch_utc(s)


def read_jsonl(path):
    rows = []
    if not os.path.exists(path):
        return rows
    with open(path, "r", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(__import__("json").loads(line))
            except ValueError:
                continue
    return rows
