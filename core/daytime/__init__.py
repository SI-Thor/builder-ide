"""The always-on daytime world: one room, one clock, and nothing else.

The world advances between sessions under the same recipe. The ledger is its
only state — every change is an audit event, and the world is what you get
when you fold the log. Nothing is written to a side file.
"""

from __future__ import annotations

__all__ = ["DAYTIME_EVENT_TYPES", "CHANGE_KINDS", "ENTRY_BEHAVIOURS"]

from .events import CHANGE_KINDS, DAYTIME_EVENT_TYPES, ENTRY_BEHAVIOURS
