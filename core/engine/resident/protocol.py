"""The wire between the core and the resident scene process.

**Deliberately standalone.** This module imports nothing but the standard
library, uses no ``core`` package, and stays inside Python 3.9 syntax, because
the resident process may run under the *engine's* interpreter: bpy pins
Python 3.11 (``bpy==4.2.0``), while this core is 3.12. The two sides therefore
share this file as **data**, not as an import — the core imports it as
``core.engine.resident.protocol``, the resident loads it as a top-level
``protocol`` module from its own directory.

The frames are newline-delimited canonical JSON: one request per line, one
response per line, ids matched in order. The resident answers on the channel
it was given and keeps its diagnostics on stderr, because the spike measured
what happens when a resident fills a pipe nobody reads (WS §5.5: the render
progress fills 64 KB after a dozen renders and the process waits forever on a
write that never completes).

The op applier at the bottom is the one piece of logic that exists on both
sides: the core applies a recipe's ops with :func:`core.recipe.edits.apply_ops`
and the resident applies them with :func:`apply_ops` here. The two are kept
honest by a digest check on every sync — the parent compares the document the
resident arrived at against the one it computed, and refuses if they differ —
so a drift between the two implementations is loud, not silent.
"""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any

__all__ = [
    "PROTOCOL_VERSION",
    "METHODS",
    "EditRejected",
    "ProtocolError",
    "apply_ops",
    "canonical_bytes",
    "content_hash",
    "decode",
    "encode",
    "error_frame",
    "ok_frame",
    "touched_entries",
]

#: Bumped when the frame shape changes; the parent refuses a resident that
#: answers with a different version.
PROTOCOL_VERSION = 1

#: The methods a resident answers. A closed list: an unknown method is a
#: refusal, never a guess.
METHODS = (
    "ping",
    "describe",
    "sync",
    "stage",
    "preview",
    "export",
    "state",
    "stats",
    "shutdown",
)


class ProtocolError(Exception):
    """A frame the peer could not parse, or a method it does not have."""


class EditRejected(Exception):
    """An op the resident could not apply — the mirror of the core's
    ``EditRejected``, with the same wording."""


# --------------------------------------------------------------------------- frames


def canonical_bytes(obj: Any) -> bytes:
    """Canonical JSON: sorted keys, no whitespace — the same shape the core's
    ``core.canon`` produces, so a digest computed here matches one computed
    there for the same document."""
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def content_hash(obj: Any) -> str:
    """``sha256:…`` over the canonical JSON — the same shape as
    ``core.canon.content_hash``."""
    return "sha256:" + hashlib.sha256(canonical_bytes(obj)).hexdigest()


def encode(frame: dict) -> bytes:
    """One frame on the wire: canonical JSON and a newline."""
    return canonical_bytes(frame) + b"\n"


def decode(line: bytes) -> dict:
    """One frame off the wire."""
    try:
        frame = json.loads(line.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError(f"unreadable frame: {exc}") from exc
    if not isinstance(frame, dict):
        raise ProtocolError("a frame is a JSON object")
    return frame


def ok_frame(request_id: int, result: dict) -> dict:
    return {"id": request_id, "ok": True, "result": result}


def error_frame(request_id: int, code: str, message: str, **detail: Any) -> dict:
    return {
        "id": request_id,
        "ok": False,
        "error": {"code": code, "message": message, "detail": detail},
    }


# --------------------------------------------------------------------------- ops
# A mirror of ``core.recipe.edits`` — the path grammar and the three verbs.
# The core's own applier is the reference; this one exists because the
# resident may run under a different interpreter, and the digest check on
# every sync is what keeps the two from drifting apart.


DOCUMENT_KEYS = frozenset(
    {"id", "name", "schema_version", "engine_pin", "seeds", "entries", "constraints"}
)
MAX_ENTRY_SEGMENTS = 3


def _split(path: str) -> list:
    segments = path.split(".")
    if not path or any(not segment for segment in segments):
        raise EditRejected("malformed op path: %r" % (path,))
    return segments


def _looks_like_entry_path(segments: list) -> bool:
    return 1 <= len(segments) <= MAX_ENTRY_SEGMENTS


def _entry_prefix(entries: dict, segments: list):
    for size in range(len(segments), 0, -1):
        candidate = ".".join(segments[:size])
        if candidate in entries:
            return candidate, segments[size:]
    return None, segments


def _descend(container: Any, segments: list, path: str):
    current = container
    for segment in segments[:-1]:
        if isinstance(current, list):
            if not segment.isdigit():
                raise EditRejected("no such path: %r" % (path,))
            position = int(segment)
            if position >= len(current):
                raise EditRejected("no such path: %r" % (path,))
            current = current[position]
            continue
        if not isinstance(current, dict):
            raise EditRejected("no such path: %r" % (path,))
        if segment not in current:
            raise EditRejected("no such path: %r" % (path,))
        current = current[segment]
    last = segments[-1]
    if isinstance(current, list):
        if not last.isdigit():
            raise EditRejected("no such path: %r" % (path,))
        position = int(last)
        if position >= len(current):
            raise EditRejected("no such path: %r" % (path,))
        return current, position
    if not isinstance(current, dict):
        raise EditRejected("no such path: %r" % (path,))
    return current, last


def _locate(document: dict, path: str, creating: bool = False):
    segments = _split(path)
    entries = document.get("entries", {})

    if segments[0] == "entries":
        rest = segments[1:]
        if not rest:
            raise EditRejected("malformed op path: %r" % (path,))
        entry_path, remainder = _entry_prefix(entries, rest)
        if entry_path is None:
            if not creating or not _looks_like_entry_path(rest):
                raise EditRejected("no such entry: %r" % (".".join(rest),))
            return entries, ".".join(rest)
        if not remainder:
            return entries, entry_path
        return _descend(entries[entry_path], remainder, path)

    if segments[0] in DOCUMENT_KEYS:
        if len(segments) == 1:
            return document, segments[0]
        return _descend(document, segments, path)

    entry_path, remainder = _entry_prefix(entries, segments)
    if entry_path is None:
        if not creating or not _looks_like_entry_path(segments):
            raise EditRejected("no such entry: %r" % (segments[0],))
        return entries, ".".join(segments)
    if not remainder:
        return entries, entry_path
    return _descend(entries[entry_path], remainder, path)


def _apply_one(document: dict, op: dict) -> None:
    verb = op.get("op")
    path = op.get("path")
    value = op.get("value")

    if verb == "add":
        container, key = _locate(document, path, creating=True)
        if isinstance(container, dict):
            if key not in container:
                container[key] = deepcopy(value)
                return
            existing = container[key]
            if isinstance(existing, list):
                existing.append(deepcopy(value))
                return
            raise EditRejected("cannot add %r: it is not a list" % (path,))
        raise EditRejected("cannot add %r" % (path,))

    container, key = _locate(document, path)

    if verb == "set":
        if isinstance(container, list):
            container[key] = deepcopy(value)
            return
        if not isinstance(container, dict):
            raise EditRejected("no such path: %r" % (path,))
        container[key] = deepcopy(value)
        return

    if verb == "remove":
        if isinstance(container, list):
            del container[key]
            return
        if not isinstance(container, dict):
            raise EditRejected("no such path: %r" % (path,))
        if key not in container:
            raise EditRejected("cannot remove %r: it does not exist" % (path,))
        del container[key]
        return

    raise EditRejected("unknown op: %r" % (verb,))


def apply_ops(document: dict, ops: list) -> dict:
    """Apply a list of typed ops to a copy of a recipe document.

    The base is never mutated. This is the resident's half of the core's
    :func:`core.recipe.edits.apply_ops`; the parent checks the two agree by
    comparing the digests of the documents they arrive at.
    """
    out = deepcopy(document)
    for op in ops:
        _apply_one(out, op)
    return out


def touched_entries(document: dict, ops: list) -> list:
    """The entries a list of ops reaches — the resident's dirty set."""
    entries = document.get("entries", {})
    touched = []
    for op in ops:
        path = op.get("path") or ""
        segments = _split(path)
        if segments[0] == "entries":
            rest = segments[1:]
            entry_path, _ = _entry_prefix(entries, rest)
        elif segments[0] in DOCUMENT_KEYS:
            entry_path = None
        else:
            entry_path, _ = _entry_prefix(entries, segments)
        if entry_path and entry_path not in touched:
            touched.append(entry_path)
    return sorted(touched)
