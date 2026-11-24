"""The action space: the reflex's options, as indices.

The gym's action space is discrete over the world's own option set — the
skills the reflex may choose — and the index is stable, because the list is
sorted. The same list serves the live env and the replay of the community's
plays, so a student cloned from the community's ledger can be evaluated in
the live env with no translation table between them.

Two kinds of option appear in the world's log: the library's skills
(``skill_<12 hex>``) and the community's project steps (``project.<kind>``).
A project step is not a skill — the private world runs no project board —
so the env refuses one by name, and the refusal is recorded rather than
silently ignored.
"""

from __future__ import annotations

from typing import Iterable, Sequence

__all__ = [
    "PROJECT_PREFIX",
    "action_list",
    "is_project_id",
    "index_of",
]

#: The community's project steps are named like this.
PROJECT_PREFIX = "project."


def is_project_id(skill_id: str) -> bool:
    """Is this a project step rather than a skill?"""
    return str(skill_id).startswith(PROJECT_PREFIX)


def action_list(
    skill_ids: Iterable[str],
    extra_ids: Iterable[str] = (),
) -> list[str]:
    """The sorted union of every option the student may choose."""
    return sorted({str(x) for x in skill_ids} | {str(x) for x in extra_ids})


def index_of(action_ids: Sequence[str], skill_id: str) -> int:
    """The index of a skill in the action list, or ``-1`` if it is not one.

    ``-1`` rather than an exception: the community's log holds skills that
    the current library does not (an old version, a retired one), and a
    replay must be able to say "that option is gone" instead of dying on
    it.
    """
    try:
        return list(action_ids).index(str(skill_id))
    except ValueError:
        return -1
