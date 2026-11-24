"""The door: what a skill may say, and the words it may use.

This world has one vocabulary and it is closed. A skill is a small
JavaScript function, and it may only use the words below — the
observations it may read and the actions it may take. Anything else is
**refused**, not repaired and not clamped: a skill that reaches for a word
the world does not have is not a skill with a bad word in it, it is not a
skill.

The door has three checks:

1. **No escapes.** The names that would let a skill out of the world
   (``require``, ``process``, ``fetch``, ``eval``, ...) are refused by
   name. This is a static check on the source.
2. **No unknown words.** Every function the skill calls is either a word
   of the world's vocabulary or a name the skill itself declared. This is
   a static check on the source.
3. **It parses.** The body is compiled by Node's own parser. A body that
   does not parse is refused with the parser's message.

At run time the sandbox is a third door: the skill runs in a context that
contains the vocabulary and nothing else, so even a check that missed
something cannot reach outside.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .models import SkillRefusal

__all__ = ["VOCABULARY", "OBSERVE", "ACT", "BANNED", "check_body", "vocabulary_text"]

#: The world's vocabulary: the words a skill may use.
#:
#: Each entry is the word's name and what it means. The cloud author is
#: given this same list, so the door and the author never disagree about
#: what exists.
VOCABULARY: dict[str, str] = {
    # --- what the bot can see -------------------------------------------------
    "position": "the bot's block position as {x, y, z}",
    "health": "the bot's health, 0..20",
    "food": "the bot's food, 0..20",
    "time_of_day": "0..1 through the Minecraft day (0 = dawn, 0.5 = noon, 0.75 = dusk)",
    "light": "the light level where the bot stands, 0..15",
    "inventory": "[{name, count}] of everything the bot carries",
    "inventory_count": "how many of one item name the bot carries",
    "block_at": "the name of the block at x, y, z, or null",
    "find_block": "the nearest matching block as {x, y, z, name}, or null. Takes {name} and {max_distance}",
    "nearby_players": "[{name, distance}] of the players near the bot",
    "look_at": "turn the bot's head toward x, y, z",
    "find_chest": "the nearest chest as {x, y, z}, or null",
    # --- what the bot may do --------------------------------------------------
    "dig": "mine the block at x, y, z",
    "place": "place a block of the given name at x, y, z",
    "move_to": "walk to x, y, z",
    "equip": "hold the item of the given name",
    "craft": "craft the given item, this many times",
    "attack": "attack the entity of the given name",
    "wait": "wait the given number of ticks",
    "open_chest": "open the nearest chest, so things can be put in it or taken out",
    "deposit": "put this many of an item into the open chest",
    "withdraw": "take this many of an item out of the open chest",
    "depot": "the community's depot as {x, y, z}: the spot where the builders leave things for each other",
    "leave_at_depot": "walk to the depot and leave things there: a name and a count leaves that many, no arguments leaves everything the bot carries",
    "take_from_depot": "walk to the depot and take what is there; returns how many the bot now has",
}

OBSERVE: tuple[str, ...] = tuple(
    name for name in VOCABULARY if name in {
        "position", "health", "food", "time_of_day", "light", "inventory",
        "inventory_count", "block_at", "find_block", "nearby_players", "look_at",
        "find_chest",
    }
)
ACT: tuple[str, ...] = tuple(name for name in VOCABULARY if name not in OBSERVE)

#: The escapes. Refused by name, before anything else is looked at.
BANNED: frozenset[str] = frozenset({
    "require", "process", "globalThis", "eval", "Function", "constructor",
    "__proto__", "prototype", "fetch", "XMLHttpRequest", "WebSocket",
    "import", "Buffer", "setTimeout", "setInterval", "queueMicrotask",
    "child_process", "fs", "os", "net", "http", "https", "dns", "crypto",
    "worker_threads", "vm", "module", "exports", "__dirname", "__filename",
    "Atomics", "SharedArrayBuffer", "WebAssembly",
})

#: A skill body may not be bigger than this. The skills are small on
#: purpose: a small script is a script a person can read in the morning.
MAX_BODY_BYTES = 8192

_DECLARED_PATTERNS = (
    re.compile(r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)"),
    re.compile(r"\bfunction\s+([A-Za-z_$][\w$]*)"),
    re.compile(r"\b([A-Za-z_$][\w$]*)\s*=(?!=)"),
    re.compile(r"\b([A-Za-z_$][\w$]*)\s*:(?![:])"),
    re.compile(r"\b([A-Za-z_$][\w$]*)\s*\)"),
)

_CALL = re.compile(r"(?<![.\w$])([A-Za-z_$][\w$]*)\s*\(")

#: Words that are not calls to anything of ours.
_JS_KEYWORDS = frozenset({
    "if", "for", "while", "switch", "catch", "return", "typeof", "function",
    "await", "async", "of", "in", "new", "do", "else", "try", "finally",
    "throw", "delete", "void", "case", "default", "yield", "instanceof",
})


def vocabulary_text() -> str:
    """The vocabulary, as the cloud author is given it."""
    lines = []
    for name in sorted(VOCABULARY):
        lines.append(f"- {name}(...): {VOCABULARY[name]}")
    return "\n".join(lines)


def _strip_noise(source: str) -> str:
    """Remove comments and string literals, so the scans see code only."""
    out: list[str] = []
    i = 0
    n = len(source)
    while i < n:
        ch = source[i]
        nxt = source[i + 1] if i + 1 < n else ""
        if ch == "/" and nxt == "/":
            while i < n and source[i] != "\n":
                i += 1
            continue
        if ch == "/" and nxt == "*":
            i += 2
            while i + 1 < n and not (source[i] == "*" and source[i + 1] == "/"):
                i += 1
            i += 2
            continue
        if ch in "\"'`":
            quote = ch
            i += 1
            while i < n and source[i] != quote:
                if source[i] == "\\":
                    i += 1
                i += 1
            i += 1
            out.append('""')
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _declared_names(code: str) -> set[str]:
    names: set[str] = set()
    for pattern in _DECLARED_PATTERNS:
        for match in pattern.findall(code):
            for part in str(match).split(","):
                name = part.strip().split(":")[0].split("=")[0].strip()
                if re.fullmatch(r"[A-Za-z_$][\w$]*", name or ""):
                    names.add(name)
    return names


def check_body(source: str, *, node: str | None = None) -> tuple[str, ...]:
    """Check a skill body against the door.

    Returns the words the skill uses, in the order they appear. Raises
    :class:`SkillRefusal` with a closed reason code when the body is not
    admitted.
    """
    if not source or not source.strip():
        raise SkillRefusal("empty_body", "a skill with no source is not a skill")
    if len(source.encode("utf-8")) > MAX_BODY_BYTES:
        raise SkillRefusal(
            "body_too_large",
            f"a skill body is at most {MAX_BODY_BYTES} bytes, this one is "
            f"{len(source.encode('utf-8'))}",
        )

    code = _strip_noise(source)

    # 1. no escapes
    for name in sorted(BANNED):
        if re.search(rf"(?<![.\w$]){re.escape(name)}(?![\w$])", code):
            raise SkillRefusal("banned_identifier", f"'{name}' is not a word of this world")

    # 2. no unknown words
    declared = _declared_names(code)
    used: list[str] = []
    for name in _CALL.findall(code):
        if name in _JS_KEYWORDS or name in declared or name in VOCABULARY:
            continue
        raise SkillRefusal(
            "unknown_word",
            f"'{name}' is not a word of this world; the words are: "
            + ", ".join(sorted(VOCABULARY)),
        )
    for name in VOCABULARY:
        if re.search(rf"(?<![.\w$]){re.escape(name)}\s*\(", code):
            used.append(name)

    # 3. it parses
    _check_parses(source, node=node)
    return tuple(dict.fromkeys(used))


def _check_parses(source: str, *, node: str | None) -> None:
    """Compile the body with Node's own parser.

    A body that does not parse is refused with the parser's message, so
    the cloud author is told what is wrong rather than finding out at
    play time.

    The body is checked as the body of an async function, because that is
    what it is: a skill awaits its actions, and ``await`` is only legal
    inside a function.
    """
    node = node or shutil.which("node")
    if not node:
        # No parser available: the run-time sandbox is still a door.
        return
    wrapped = "(async () => {\n" + source + "\n})"
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "skill.js"
        path.write_text(wrapped, encoding="utf-8")
        result = subprocess.run(
            [node, "--check", str(path)],
            capture_output=True,
            text=True,
            timeout=20,
        )
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "").strip().splitlines()
        detail = " / ".join(line.strip() for line in message[:3] if line.strip())
        raise SkillRefusal("does_not_parse", detail or "the parser refused the body")
