"""Minimal YYYY-MM-DD date arithmetic.

Fixed-width ISO dates compare correctly as plain strings, so expiry checks
stay string comparisons (deterministic and portable — no locale, no tz).
Only grace-period arithmetic needs real date math, and Python's stdlib
``datetime`` is exactly the boring, correct tool for that.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone


def is_valid_date(s: str) -> bool:
    """True iff ``s`` is a strict YYYY-MM-DD calendar date."""
    if len(s) != 10 or s[4] != "-" or s[7] != "-":
        return False
    if not (s[0:4].isdigit() and s[5:7].isdigit() and s[8:10].isdigit()):
        return False
    try:
        date(int(s[0:4]), int(s[5:7]), int(s[8:10]))
    except ValueError:
        return False
    return True


def add_days(day: str, n: int) -> str | None:
    """Add ``n`` days to a YYYY-MM-DD string; None for invalid input."""
    if not is_valid_date(day):
        return None
    return (date.fromisoformat(day) + timedelta(days=n)).isoformat()


def today() -> str:
    """Today as YYYY-MM-DD from the system clock (UTC)."""
    return datetime.now(timezone.utc).date().isoformat()
